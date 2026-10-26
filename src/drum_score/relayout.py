"""Bounded, disposable PDF relayout process; only its JSON delivery survives."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .jobs import JobError

MAX_DELIVERY = 32 * 1024**2
MAX_TEMP = 128 * 1024**2


@contextmanager
def slot(jobs):
    # flock is independent of SQLite byte-range locking. No schema or sidecar.
    descriptor = os.open(jobs.database, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JobError('service_busy', '正在生成另一份排版，请稍后再试。', 503) from None
        yield descriptor
    finally:
        os.close(descriptor)


def delivery(jobs, task, capability, paper, rows):
    jobs.view(task, capability)
    with slot(jobs) as lease:
        with jobs.transaction() as db:
            row = jobs.authorize(db, task, capability)
            jobs.check_live(row)
            if row['state'] != 'complete':
                raise JobError('not_ready', '结果尚未就绪。')
            identifier = jobs.records.start(db, 'layout', task=task,
                source=json.loads(row['source']).get('url'), settings={'paper': paper, 'rows': rows})
            record = db.execute('SELECT * FROM processing_records WHERE id=?', (identifier,)).fetchone()
            jobs.records.update(db, record, attempt=row['attempt'])
        try:
            data = _delivery(jobs, task, capability, paper, rows, lease)
            output = json.loads(data)
            def reference(value):
                binary = base64.b64decode(value, validate=True)
                return {'bytes': len(binary), 'sha256': hashlib.sha256(binary).hexdigest()}
            summary = {key: output.get(key) for key in ('page_count', 'paper', 'target_rows', 'actual_rows')}
            summary.update(pdf=reference(output['pdf']), pages=[reference(page) for page in output['pages']])
            with jobs.transaction() as db:
                record = db.execute('SELECT * FROM processing_records WHERE id=?', (identifier,)).fetchone()
                jobs.finish_record(db, record, 'complete', output=summary)
            return data
        except Exception as error:
            code = error.code if isinstance(error, JobError) else 'layout_failed'
            with jobs.transaction() as db:
                record = db.execute('SELECT * FROM processing_records WHERE id=?', (identifier,)).fetchone()
                jobs.finish_record(db, record, 'failed', code=code)
            if isinstance(error, JobError):
                error.recorded = True
                raise
            failure = JobError('layout_failed', '无法完成临时排版，默认 PDF 仍可下载。')
            failure.recorded = True
            raise failure from None


def _delivery(jobs, task, capability, paper, rows, lease):
    jobs.view(task, capability)
    with jobs.transaction() as db:
        row = jobs.authorize(db, task, capability)
        jobs.check_live(row)
        if row['state'] != 'complete':
            raise JobError('not_ready', '结果尚未就绪。')
        row = dict(row)
    jobs.recover_staging(row, print_locked=True)
    source, size = jobs.open_artifact(task, capability)
    root = None
    process = guardian = None
    writer = None
    safe_cleanup = True
    try:
        with os.fdopen(source, 'rb') as stream:
            if size > MAX_DELIVERY:
                raise JobError('resource_limit', '谱面超出临时排版限制。')
            # Admission, disk allocation and worker reservations share the
            # SQLite write barrier. The reserved file is counted by capacity.
            with jobs.transaction() as db:
                jobs.capacity(reserve=True, db=db)
                if shutil.disk_usage(jobs.root).free < jobs.min_free_bytes + 2 * MAX_TEMP:
                    raise JobError('storage_full', '临时排版空间不足。', 503)
                root = Path(tempfile.mkdtemp(prefix='.drum-score-job-',
                    dir=jobs.attempt_root(row['id'], row['attempt'])))
            jobs.remember_staging(row, root, print_layout=True)
            with jobs.transaction() as db:
                jobs.capacity(reserve=True, db=db)
                with (root / 'reservation').open('xb') as reservation:
                    os.posix_fallocate(reservation.fileno(), 0, MAX_TEMP)
                jobs.capacity(reserve=True, db=db)
            with (root / 'input.pdf').open('xb') as target:
                shutil.copyfileobj(stream, target)
        command = [sys.executable, '-m', 'drum_score.relayout', str(root), paper, str(rows or 0)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parent.parent),
                 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
        safe_cleanup = False
        from .supervision import _identity
        identity = _identity(process.pid)
        reader, writer = os.pipe()
        metadata = root.stat()
        try:
            guardian = subprocess.Popen([sys.executable, '-m', 'drum_score.guardian', str(reader),
                str(process.pid), str(root), str(metadata.st_dev), str(metadata.st_ino), identity or '', 'lease'],
                pass_fds=(reader, lease), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, start_new_session=True)
        finally:
            os.close(reader)
        if not select.select([guardian.stdout], [], [], 5)[0] or guardian.stdout.read(1) != b'R':
            raise JobError('layout_failed', '无法建立排版清理保护。')
        guardian.stdout.close()
        (root / 'ready').touch()
        deadline = time.monotonic() + 90
        while process.poll() is None:
            if time.monotonic() > deadline:
                raise JobError('layout_timeout', '排版超时，默认 PDF 仍可下载。')
            used = sum(path.stat().st_size for path in root.iterdir()
                       if path.is_file() and path.name != 'reservation')
            if used > min(MAX_TEMP, jobs.job_temp_bytes):
                raise JobError('resource_limit', '临时排版超出存储限制。')
            jobs.capacity()
            jobs.view(task, capability)
            time.sleep(.1)
        result = root / 'delivery.json'
        if process.returncode or not result.is_file() or result.stat().st_size > MAX_DELIVERY:
            raise JobError('layout_failed', '无法安全完成排版，默认 PDF 仍可下载。')
        data = result.read_bytes()
        jobs.view(task, capability)
        return data
    except OSError:
        raise JobError('layout_failed', '无法完成临时排版，默认 PDF 仍可下载。') from None
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        if writer is not None:
            os.close(writer)
        if guardian is not None:
            # Never remove materials while a descendant could still write.
            # The guardian also retains the slot until every writer stops.
            try:
                safe_cleanup = guardian.wait(timeout=10) == 0
            except subprocess.TimeoutExpired:
                safe_cleanup = False
        elif process is not None:
            # Child never received ready, so no external writers started.
            safe_cleanup = True
        if root is not None and safe_cleanup:
            jobs.recover_staging(row, print_locked=True)

def main():
    import resource
    root, paper, count = sys.argv[1:4]
    root = Path(root)
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TEMP, MAX_TEMP))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    deadline = time.monotonic() + 10
    while not (root / 'ready').exists():
        if time.monotonic() > deadline:
            return 2
        time.sleep(.02)
    try:
        from .print_layout import extract, render
        with extract(root / 'input.pdf', root) as image:
            result = render(image, root, paper=paper, rows=int(count) or None)
        files = [root / 'score.pdf', *sorted(root.glob('page-*.png'))]
        if sum(path.stat().st_size for path in files) > 23 * 1024**2:
            return 2
        result['pdf'] = base64.b64encode(files[0].read_bytes()).decode('ascii')
        result['pages'] = [base64.b64encode(path.read_bytes()).decode('ascii') for path in files[1:]]
        (root / 'delivery.json').write_text(json.dumps(result), encoding='utf-8')
        return 0
    except Exception:
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
