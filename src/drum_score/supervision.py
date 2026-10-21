"""Single task owner; sampled resource limits are not cgroup hard limits."""
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
import json
import multiprocessing
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .core import ConversionError, ResourceBudget, _convert, _publish


_guardian_lock = ContextVar('guardian_lock', default=None)
_service_attempt = ContextVar("service_attempt", default=None)


@contextmanager
def service_attempt(jobs, row):
    token = _service_attempt.set((jobs, row))
    try:
        yield
    finally:
        _service_attempt.reset(token)


@contextmanager
def guardian_lease(descriptor):
    """Keep a service worker's OS lease alive until orphan writers stop."""
    token = _guardian_lock.set(descriptor)
    try:
        yield
    finally:
        _guardian_lock.reset(token)


def _worker(source, output, limits, connection, temporary, parent_pid, ready):
    if hasattr(os, 'setsid'):
        os.setsid()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if os.name == 'posix' and Path('/proc').is_dir():
        import ctypes
        ctypes.CDLL(None).prctl(1, signal.SIGKILL)
        if os.getppid() != parent_pid:
            os.kill(os.getpid(), signal.SIGKILL)
    os.environ.update(TMPDIR=temporary, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                      MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = temporary
    try:
        ready.wait()
        import cv2
        cv2.setNumThreads(1)
        result = _convert(source, output, limits=limits, progress=lambda stage:
                          connection.send(('stage', stage)) if stage != 'complete' else None)
        connection.send(('result', result))
    except ConversionError as error:
        connection.send(('error', (error.code, str(error))))
    except BaseException:
        connection.send(('error', ('conversion_failed', '转换进程异常退出，未发布结果。')))
    finally:
        connection.close()


def _identity(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def _processes(root_pid, root_identity=None):
    """Read only process identity and RSS, never command lines or environments."""
    records = {}
    for entry in Path('/proc').glob('[0-9]*'):
        try:
            fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
            records[int(entry.name)] = (int(fields[1]), int(fields[21]) * os.sysconf('SC_PAGE_SIZE'), fields[19], int(fields[3]))
        except (OSError, ValueError, IndexError):
            continue
    if root_identity is not None and records.get(root_pid, (None, None, None))[2] != root_identity:
        return {}, 0
    descendants = {root_pid} | {pid for pid, record in records.items() if record[3] == root_pid}
    changed = True
    while changed:
        before = len(descendants)
        descendants.update(pid for pid, (parent, _, _, _) in records.items() if parent in descendants)
        changed = before != len(descendants)
    return {pid: records[pid][2] for pid in descendants if pid in records}, sum(
        records.get(pid, (0, 0, '', 0))[1] for pid in descendants)


def _stop(process, tracked, *, root_identity=None, wait_until_stopped=False):
    same_root = root_identity is None or _identity(process.pid) == root_identity
    if same_root and process.is_alive() and hasattr(os, 'killpg') and process.pid:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for pid, start_time in tracked.items():
        try:
            stat = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
            if stat[19] != start_time:
                continue
        except (OSError, ValueError, IndexError):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if same_root and process.is_alive():
        process.kill()
    process.join(timeout=5)
    deadline = time.monotonic() + 2
    while wait_until_stopped or time.monotonic() < deadline:
        active = False
        for pid, start_time in tracked.items():
            try:
                fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
                if fields[19] == start_time and fields[0] != 'Z':
                    active = True
                    os.kill(pid, signal.SIGKILL)
            except (OSError, ValueError, IndexError):
                pass
        if not active:
            break
        time.sleep(.01)


def run(source, output, *, progress=None, limits=None, cancel=None):
    # Directory setup and context-manager cleanup are filesystem operations too.
    # Keep them inside the same public error boundary as the worker lifecycle.
    try:
        return _run(source, output, progress=progress, limits=limits, cancel=cancel)
    except KeyboardInterrupt:
        raise ConversionError('cancelled', '转换已取消，未发布结果。') from None
    except ConversionError:
        raise
    except Exception:
        raise ConversionError('conversion_failed', '转换进程异常退出，未发布结果。') from None


def _run(source, output, *, progress=None, limits=None, cancel=None):
    started = time.monotonic()
    budget = ResourceBudget(limits, cancel)
    lease = _guardian_lock.get()
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ConversionError('output_exists', '结果路径已存在，请选择新的目录。')
    output.parent.mkdir(parents=True, exist_ok=True)
    methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context('spawn' if 'spawn' in methods else methods[0])
    peak_rss = peak_disk = 0
    tracked = {}
    result = None
    temporary_directory = tempfile.TemporaryDirectory(prefix='.drum-score-job-', dir=output.parent)
    published = False
    try:
        temporary = temporary_directory.name
        root = Path(temporary)
        owner = _service_attempt.get()
        if owner is not None:
            owner[0].remember_staging(owner[1], root)
        budget.root = root
        parent, child = context.Pipe(duplex=False)
        ready = context.Event()
        process = context.Process(target=_worker, args=(source, root / 'complete', budget.limits, child, temporary, os.getpid(), ready))
        guardian = None
        guardian_write = None
        previous_term = None
        root_identity = None
        if threading.current_thread() is threading.main_thread():
            previous_term = signal.getsignal(signal.SIGTERM)
            def interrupted(signum, frame):
                if lease is not None and callable(previous_term):
                    previous_term(signum, frame)
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupted)
        try:
            budget.check()
            process.start()
            if Path('/proc').is_dir():
                root_identity = _identity(process.pid)
                if root_identity is None:
                    raise ConversionError('conversion_failed', '转换进程身份不可用。')
                tracked[process.pid] = root_identity
            child.close()
            if Path('/proc').is_dir():
                guardian_read, guardian_write = os.pipe()
                identity = root.stat()
                try:
                    guardian = subprocess.Popen([sys.executable, '-m', 'drum_score.guardian',
                        str(guardian_read), str(process.pid), str(root), str(identity.st_dev), str(identity.st_ino), root_identity,
                        *(['lease'] if lease is not None else [])],
                        pass_fds=(guardian_read,) + ((lease,) if lease is not None else ()), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, start_new_session=True)
                finally:
                    os.close(guardian_read)
                if not select.select([guardian.stdout], [], [], 5)[0] or guardian.stdout.read(1) != b'R':
                    raise ConversionError('conversion_failed', '无法建立任务清理保护，未开始转换。')
                guardian.stdout.close()
            ready.set()
            while True:
                budget.check()
                peak_disk = max(peak_disk, budget._peak_temp)
                if Path('/proc').is_dir():
                    descendants, rss = _processes(process.pid, root_identity)
                    for pid, identity_value in descendants.items():
                        tracked.setdefault(pid, identity_value)
                    peak_rss = max(peak_rss, rss)
                    if rss > budget.limits['rss_bytes']:
                        raise ConversionError('resource_limit', '转换进程树超过采样内存预算，未发布结果。')
                if parent.poll(.02):
                    try:
                        kind, payload = parent.recv()
                    except EOFError:
                        break
                    if kind == 'stage':
                        if progress:
                            progress(payload)
                    elif kind == 'error':
                        raise ConversionError(*payload)
                    elif kind == 'result':
                        result = payload
                        break
                elif not process.is_alive():
                    break
            process.join(timeout=1)
            if result is None or process.is_alive() or process.exitcode != 0:
                raise ConversionError('conversion_failed', '转换进程异常退出，未发布结果。')
            budget.check(force_disk=True)
            result['resources'] = {'limits': budget.limits, 'peak_sampled_tree_rss_bytes': peak_rss or None,
                'peak_observed_temp_bytes': max(peak_disk, budget._peak_temp),
                'memory_enforcement': 'sampled_process_tree', 'sample_interval_seconds': .02,
                'disk_sample_interval_seconds': .2,
                'opencv_threads': 1, 'numeric_thread_environment': 1}
            result['elapsed_seconds'] = time.monotonic() - started
            (root / 'complete' / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            budget.check(force_disk=True)
            _publish(root / 'complete', output)
            published = True
        except KeyboardInterrupt:
            raise ConversionError('cancelled', '转换已取消，未发布结果。') from None
        except ConversionError:
            raise
        except Exception:
            raise ConversionError('conversion_failed', '转换进程异常退出，未发布结果。') from None
        finally:
            if previous_term is not None:
                signal.signal(signal.SIGTERM, previous_term)
            parent.close()
            child.close()
            if process.pid is not None:
                _stop(process, tracked, root_identity=root_identity, wait_until_stopped=lease is not None)
            if guardian_write is not None:
                try:
                    os.write(guardian_write, b'1')
                except BrokenPipeError:
                    pass
                os.close(guardian_write)
            if guardian is not None:
                try:
                    guardian.wait(timeout=None if lease is not None else 5)
                except subprocess.TimeoutExpired:
                    guardian.kill()
                    guardian.wait()
    finally:
        handling_error = sys.exc_info()[0] is not None
        try:
            temporary_directory.cleanup()
        except Exception:
            # Keep an existing specific error, or the committed complete result.
            # Cleanup must never expose filesystem paths through the boundary.
            if not handling_error and not published:
                raise
    if progress:
        try:
            progress('complete')
        except Exception:
            pass  # Publication is the commit point; observers cannot retract it.
    return result
