"""One durable conversion worker, independent of HTTP server lifetime."""
from .arguments import PublicParser
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import signal
import stat
import time

from .core import ConversionError, convert
from .jobs import JobError, Jobs


def validate_result(jobs, row):
    root = jobs.attempt_root(row['id'], row['attempt']) / 'result'
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Incomplete result')
    manifest = root / 'manifest.json'
    if manifest.is_symlink() or manifest.stat().st_size > 16 * 1024**2:
        raise ValueError('Invalid manifest')
    result = json.loads(manifest.read_text(encoding='utf-8'))
    if result['status'] != 'complete' or result['reliable'] is not False or not result['pages']:
        raise ValueError('Incomplete result')
    for reference in (result['pdf'], *result['pages']):
        name = reference['path']
        if not isinstance(name, str) or '/' in name or '\\' in name or name in ('.', '..'):
            raise ValueError('Invalid artifact')
        path = root / name
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != reference['bytes']:
            raise ValueError('Invalid artifact')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != reference['sha256']:
                raise ValueError('Changed artifact')
    return {'status': 'complete', 'reliable': False, 'warnings': result['warnings'], 'page_count': len(result['pages']),
        'pdf': result['pdf'], 'pages': result['pages'], 'source': result['source'],
        'program': result['program'], 'resources': result['resources'],
        'retention': result.get('retention')}


def retain_delivery(jobs, row):
    root = jobs.attempt_root(row['id'], row['attempt']) / 'result'
    result = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    jobs.remember_result(row, result)
    with jobs.transaction() as db:
        managed = dict(db.execute('SELECT * FROM managed_attempts WHERE task=? AND attempt=?',
            (row['id'], row['attempt'])).fetchone())
    entries = json.loads(managed['files'])
    intermediates = [entry for entry in entries if entry[0].startswith('result/samples/') or entry[0] == 'result/longshot.png']
    jobs.remove_files(managed, intermediates)
    for reference in [*result.get('samples', []), *([result['longshot']] if 'longshot' in result else [])]:
        reference['original_path'] = reference.pop('path')
        reference['retained'] = False
    result['retention'] = {'profile': 'web_delivery', 'native_samples_retained': False,
        'longshot_retained': False, 'can_reconstruct_from_retained_sources': False,
        'note': '保留来源指纹、实际 PTS 与处理记录；原生帧和长图已清理，不能仅凭此目录重建。'}
    (root / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    jobs.remember_result(row, result)
    return validate_result(jobs, row)


@contextmanager
def worker_lock(jobs):
    descriptor = os.open(jobs.root / 'worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JobError('worker_busy', '已有 worker 或清理保护正在运行。') from None
        yield descriptor
    finally:
        # Closing our reference preserves an inherited guardian lease after SIGKILL.
        os.close(descriptor)


def recover(jobs):
    with jobs.transaction() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM tasks WHERE state IN ('running','cancelling','finishing')")]
    for row in rows:
        if row['state'] == 'finishing':
            try:
                summary = validate_result(jobs, row)
                if summary != json.loads(row['summary']):
                    raise ValueError('Changed publishing decision')
                jobs.settle(row, 'complete')
                continue
            except (OSError, ValueError, KeyError, TypeError):
                pass
        # A crash can fall between the core's atomic publication and inventory
        # registration. Recover only the hashed complete artifact set inside an
        # already registered attempt; never take ownership of unknown entries.
        with jobs.transaction() as db:
            managed = db.execute('SELECT files FROM managed_attempts WHERE task=? AND attempt=?',
                (row['id'], row['attempt'])).fetchone()
        if managed and json.loads(managed['files']) == []:
            try:
                validate_result(jobs, row)
                manifest = jobs.attempt_root(row['id'], row['attempt']) / 'result' / 'manifest.json'
                jobs.remember_result(row, json.loads(manifest.read_text(encoding='utf-8')))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        jobs.discard(row)
        jobs.settle(row, 'interrupted', 'interrupted', '处理进程已中断，可显式重试。')


def run(jobs, *, once=False, poll_interval=.25, limits=None):
    from .supervision import guardian_lease
    stopping = False
    def stop(*args):
        nonlocal stopping
        stopping = True
    previous = {signum: signal.signal(signum, stop) for signum in (signal.SIGTERM, signal.SIGINT)}
    try:
        with worker_lock(jobs) as descriptor, guardian_lease(descriptor):
            recover(jobs)
            while not stopping:
                jobs.cleanup()
                row = jobs.claim()
                if row is None:
                    if once:
                        return 0
                    time.sleep(poll_interval)
                    continue
                try:
                    attempt = jobs.register_attempt(row)
                    next_capacity = 0
                    def cancelled():
                        nonlocal next_capacity
                        if time.monotonic() >= next_capacity:
                            next_capacity = time.monotonic() + .2
                            try:
                                jobs.capacity()
                            except JobError as error:
                                raise ConversionError(error.code, error.message) from None
                        return stopping or jobs.cancelled(row)
                    convert(json.loads(row['source'])['url'], attempt / 'result',
                        progress=lambda stage: jobs.stage(row, stage) if stage != 'complete' else None,
                        cancel=cancelled, limits={**(limits or {}), 'temp_bytes': jobs.job_temp_bytes})
                    validate_result(jobs, row)
                    summary = retain_delivery(jobs, row)
                    jobs.capacity()
                    if jobs.finishing(row, summary):
                        jobs.settle(row, 'complete')
                    else:
                        jobs.discard(row)
                        jobs.settle(row, 'cancelled')
                except ConversionError as error:
                    cancelled = jobs.cancelled(row)
                    jobs.discard(row)
                    if cancelled:
                        jobs.settle(row, 'cancelled')
                    elif error.code == 'cancelled':
                        jobs.settle(row, 'interrupted', 'interrupted', '处理进程已中断，可显式重试。')
                        stopping = True
                    else:
                        message = str(error).replace('请提供清晰的本地视频。', '请检查公开视频是否可匿名访问，或更换清晰、完整的纵向滚谱。')
                        jobs.settle(row, 'failed', error.code, message)
                except Exception:
                    # Never expose paths, network output, database or OS exception text.
                    # A lost commit acknowledgement may already have made finishing durable.
                    if jobs.publishing(row):
                        raise JobError('publication_pending', '发布决定已保存，重启后恢复。') from None
                    jobs.discard(row)
                    jobs.settle(row, 'failed', 'conversion_failed', '转换失败，可检查来源后重试。')
                jobs.cleanup()
                if once:
                    return 0
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0


def main(argv=None):
    parser = PublicParser(prog='drum-score-worker', description='串行处理匿名网站持久队列。')
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--once', action='store_true', help='处理至多一个任务后退出')
    parser.add_argument('--poll-interval', type=float, default=.25)
    from .service_limits import add_storage_arguments, storage_options, add_conversion_arguments, conversion_options
    add_storage_arguments(parser)
    add_conversion_arguments(parser)
    args = parser.parse_args(argv)
    if not .01 <= args.poll_interval <= 60:
        parser.error('poll-interval 必须在 0.01 至 60 秒之间')
    try:
        return run(Jobs(args.data_root, **storage_options(args)), once=args.once, poll_interval=args.poll_interval, limits=conversion_options(args))
    except (JobError, OSError, ValueError, ConversionError):
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
