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


def _worker(source, output, limits, connection, temporary, parent_pid, ready, options=None, prepared=None, operation="convert", inspection=None, register=None, website=False):
    if hasattr(os, 'setsid'):
        os.setsid()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    parent_death = None
    if os.name == 'posix' and Path('/proc').is_dir():
        import ctypes
        parent_death = ctypes.CDLL(None)
        parent_death.prctl(1, signal.SIGKILL)
        if os.getppid() != parent_pid:
            os.kill(os.getpid(), signal.SIGKILL)
    os.environ.update(TMPDIR=temporary, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                      MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    tempfile.tempdir = temporary
    source_descriptor = None
    try:
        from .description_policy import enabled, last_details
        enabled.set(website)
        last_details.set({'url': prepared['origin']['url'], 'description_policy': prepared['origin'].get('description_policy')} if prepared and 'origin' in prepared else None)
        ready.wait()
        if parent_death is not None:
            # The guardian handshake precedes ready. Keep this exact session
            # leader stopped on caller death until the guardian can discover
            # and stop its descendants, including children not sampled yet.
            if parent_death.prctl(1, signal.SIGSTOP) != 0:
                raise ConversionError('conversion_failed', '无法建立任务清理保护，未开始转换。')
            if os.getppid() != parent_pid:
                os.kill(os.getpid(), signal.SIGSTOP)
        if prepared is not None and '_fd' in prepared:
            source_descriptor = prepared['_fd'].detach()
            prepared['path'] = f'/proc/{os.getpid()}/fd/{source_descriptor}'
        import cv2
        cv2.setNumThreads(1)
        if operation != 'convert':
            from .source_preparation import prepare
            result = prepare(operation, source, output, limits, inspection)
        else:
            result = _convert(source, output, options=options, limits=limits, prepared=prepared,
                              expert_fallback=website, progress=lambda stage:
                              connection.send(('stage', stage)) if stage != 'complete' else None)
        connection.send(('result', result))
    except ConversionError as error:
        details = dict(last_details.get() or {})
        if getattr(error, 'conversion_details', None):
            details['conversion_failure'] = error.conversion_details
        connection.send(('error', (error.code, str(error), details or None)))
    except BaseException:
        connection.send(('error', ('conversion_failed', '转换进程异常退出，未发布结果。')))
    finally:
        if source_descriptor is not None:
            os.close(source_descriptor)
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


def _stat(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
    except (OSError, ValueError, IndexError):
        return None


def _freeze_tree(tracked):
    """Stop known writers before rescanning, so they cannot fork past cleanup."""
    deadline = time.monotonic() + 1
    while True:
        pending = False
        discovered = {}
        for pid, start_time in list(tracked.items()):
            fields = _stat(pid)
            if not fields or fields[19] != start_time or fields[0] == 'Z':
                continue
            if fields[0] not in {'T', 't'}:
                try:
                    os.kill(pid, signal.SIGSTOP)
                except ProcessLookupError:
                    continue
                pending = True
            descendants, _ = _processes(pid, start_time)
            for child, identity in descendants.items():
                if child not in tracked:
                    discovered.setdefault(child, identity)
        tracked.update(discovered)
        # Uninterruptible I/O may defer SIGSTOP. Still reach SIGKILL and let
        # the caller's existing writer-wait policy control final cleanup.
        if (not pending and not discovered) or time.monotonic() >= deadline:
            return
        time.sleep(.01)


def _kill_groups(tracked):
    """SIGKILL each tracked group leader's whole group and track its members.

    A leader killed on its own cannot run its group cleanup, which would
    orphan members it started itself, such as a downloader's child process.
    """
    _freeze_tree(tracked)
    groups = {}
    for pid, start_time in list(tracked.items()):
        fields = _stat(pid)
        if fields and fields[19] == start_time and fields[2] == str(pid):
            groups[pid] = start_time
    if not groups:
        return
    members = {}
    for entry in Path('/proc').glob('[0-9]*'):
        fields = _stat(entry.name)
        if fields and int(fields[2]) in groups:
            members[int(entry.name)] = (int(fields[2]), fields[19])
    for group, start_time in groups.items():
        fields = _stat(group)
        if not fields or fields[19] != start_time or fields[2] != str(group):
            continue
        for pid, (member_group, identity) in members.items():
            if member_group == group:
                tracked.setdefault(pid, identity)
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _stop(process, tracked, *, root_identity=None, wait_until_stopped=False):
    same_root = root_identity is None or _identity(process.pid) == root_identity
    if same_root and process.pid and Path('/proc').is_dir():
        # The sampling loop may not have seen processes started just before
        # cancellation. Record the live tree before the root stops existing.
        descendants, _ = _processes(process.pid, root_identity)
        for pid, identity_value in descendants.items():
            tracked.setdefault(pid, identity_value)
        _kill_groups(tracked)
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


def run(source, output, *, options=None, progress=None, limits=None, cancel=None, prepared=None, operation="convert", inspection=None, register=None):
    # Directory setup and context-manager cleanup are filesystem operations too.
    # Keep them inside the same public error boundary as the worker lifecycle.
    try:
        return _run(source, output, options=options, progress=progress, limits=limits, cancel=cancel, prepared=prepared, operation=operation, inspection=inspection, register=register)
    except KeyboardInterrupt:
        raise ConversionError('cancelled', '转换已取消，未发布结果。') from None
    except ConversionError:
        raise
    except Exception:
        raise ConversionError('conversion_failed', '转换进程异常退出，未发布结果。') from None


def _run(source, output, *, options=None, progress=None, limits=None, cancel=None, prepared=None, operation="convert", inspection=None, register=None):
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
        if prepared is not None and '_descriptor' in prepared:
            from multiprocessing.reduction import DupFd
            prepared = dict(prepared)
            prepared['_fd'] = DupFd(prepared.pop('_descriptor'))
        process = context.Process(target=_worker, args=(source, root / 'complete', budget.limits, child, temporary, os.getpid(), ready, options, prepared, operation, inspection), kwargs={'website': owner is not None})
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
                        error = ConversionError(*payload[:2])
                        error.source_details = payload[2] if len(payload) > 2 else None
                        raise error
                    elif kind == 'result':
                        result = payload
                        break
                elif not process.is_alive():
                    break
            process.join(timeout=1)
            if result is None or process.is_alive() or process.exitcode != 0:
                raise ConversionError('conversion_failed', '转换进程异常退出，未发布结果。')
            budget.check(force_disk=True)
            if operation == 'inspect':
                return result  # Private URLs stay in the pipe, never a manifest.
            result['resources'] = {'limits': budget.limits,
                'phase_seconds': result['metrics'].get('phase_seconds', {}), 'peak_sampled_tree_rss_bytes': peak_rss or None,
                'peak_observed_temp_bytes': max(peak_disk, budget._peak_temp),
                'memory_enforcement': 'sampled_process_tree', 'sample_interval_seconds': .02,
                'disk_sample_interval_seconds': .2,
                'opencv_threads': 1, 'numeric_thread_environment': 1}
            result['elapsed_seconds'] = time.monotonic() - started
            if prepared and prepared.get('_preparation'):
                result['resources']['source_preparation'] = prepared['_preparation']
                result['elapsed_seconds'] += prepared['_preparation']['elapsed_seconds']
            (root / 'complete' / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            budget.check(force_disk=True)
            if register is not None:
                register(root / 'complete')
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
