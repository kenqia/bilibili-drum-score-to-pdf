"""Real process trees: stopping a task must not orphan members of nested groups."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.supervision import _freeze_tree, _identity, _kill_groups, _processes, _stat, _stop

# A group leader (like the downloader worker, which calls setsid) with one child
# in its own group. The child is started last, so a sampler may not see it yet.
LEADER = '''import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])
identity = Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]
open(sys.argv[1], 'w').write(f'{child.pid} {identity}')
time.sleep(3600)
'''
ROOT = '''import os, subprocess, sys, time
from pathlib import Path
os.setsid()
leader = subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[3]], start_new_session=True)
identity = Path(f'/proc/{leader.pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]
open(sys.argv[1], 'w').write(f'{leader.pid} {identity}')
time.sleep(3600)
'''


class Process:
    """The multiprocessing.Process surface that _stop uses, over a Popen."""
    def __init__(self, popen):
        self.popen, self.pid = popen, popen.pid

    def is_alive(self):
        return self.popen.poll() is None

    def kill(self):
        self.popen.kill()

    def join(self, timeout=None):
        try:
            self.popen.wait(timeout)
        except subprocess.TimeoutExpired:
            pass


def alive(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def read_pid(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return int(path.read_text().split()[0])
        time.sleep(.02)
    raise AssertionError('fixture process did not start')


@unittest.skipUnless(Path('/proc').is_dir(), 'Linux process tree contract')
class StopProcessTree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.started = []

    def tearDown(self):
        # Independent of the cleanup under test. Freeze each fixture tree before
        # killing parents, including nested sessions not represented by Popen.
        tracked = {p.pid: _identity(p.pid) for p in self.started if p.poll() is None}
        for _ in range(5):
            for pid, identity in list(tracked.items()):
                if identity is not None and _identity(pid) == identity:
                    try:
                        os.kill(pid, signal.SIGSTOP)
                    except ProcessLookupError:
                        pass
                    children, _ = _processes(pid, identity)
                    for child, start in children.items():
                        tracked.setdefault(child, start)
            time.sleep(.01)
        # Markers also cover children whose parent was already killed by a
        # failing assertion. Only fixture-created marker files are read.
        for marker in self.root.iterdir():
            try:
                pid, identity = marker.read_text().split()
                tracked.setdefault(int(pid), identity)
            except (ValueError, OSError):
                pass
        for pid, identity in tracked.items():
            if identity is not None and _identity(pid) == identity:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for popen in self.started:
            if popen.poll() is None:
                popen.kill()
                popen.wait()
        self.temp.cleanup()

    def spawn(self, *args, **kwargs):
        popen = subprocess.Popen([sys.executable, '-c', *args], **kwargs)
        self.started.append(popen)
        return popen

    def test_killing_a_tracked_group_leader_also_stops_its_untracked_child(self):
        leader = self.spawn(LEADER, str(self.root / 'child'), start_new_session=True)
        child = read_pid(self.root / 'child')
        tracked = {leader.pid: _identity(leader.pid)}
        _kill_groups(tracked)
        self.assertIn(child, tracked)
        leader.wait(timeout=5)
        deadline = time.monotonic() + 5
        while alive(child) and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(alive(child))

    def test_stop_reaches_nested_group_started_after_last_sample(self):
        root = self.spawn(ROOT, str(self.root / 'leader'), LEADER, str(self.root / 'child'))
        leader = read_pid(self.root / 'leader')
        child = read_pid(self.root / 'child')
        identity = _identity(root.pid)
        # Only the root was sampled, as when cancellation wins the race.
        _stop(Process(root), {root.pid: identity}, root_identity=identity)
        self.assertFalse(alive(leader))
        self.assertFalse(alive(child))

    def test_new_session_started_after_final_scan_is_stopped(self):
        root = self.spawn('''import os,subprocess,sys,time
from pathlib import Path
os.setsid()
identity=Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(') ',1)[1].split()[19]
open(sys.argv[1], 'w').write(f'{os.getpid()} {identity}')
while not os.path.exists(sys.argv[2]): time.sleep(.001)
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(3600)'], start_new_session=True)
identity=Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ',1)[1].split()[19]
open(sys.argv[3], 'w').write(f'{child.pid} {identity}')
time.sleep(3600)
''', str(self.root / 'ready'), str(self.root / 'release'), str(self.root / 'child'))
        read_pid(self.root / 'ready')
        identity = _identity(root.pid)
        real_kill_groups = _kill_groups
        def race(tracked):
            (self.root / 'release').touch()
            read_pid(self.root / 'child')
            real_kill_groups(tracked)
        with patch('drum_score.supervision._kill_groups', side_effect=race):
            _stop(Process(root), {root.pid: identity}, root_identity=identity)
        self.assertFalse(alive(read_pid(self.root / 'child')))

    def test_group_identity_is_rechecked_before_signalling(self):
        sentinel = self.spawn('import time;time.sleep(3600)', start_new_session=True)
        # A synthetic observation changes after the first group-leader check;
        # the real sentinel must remain alive and must not be signalled.
        fields = _stat(sentinel.pid)
        changed = list(fields)
        changed[19] = str(int(fields[19]) + 1)
        observations = iter((fields, changed))
        def stat(pid):
            return next(observations, changed) if int(pid) == sentinel.pid else None
        with patch('drum_score.supervision._freeze_tree'), patch('drum_score.supervision._stat', side_effect=stat), patch('drum_score.supervision.os.killpg') as kill_group:
            _kill_groups({sentinel.pid: fields[19]})
        kill_group.assert_not_called()
        self.assertTrue(alive(sentinel.pid))

    def test_uninterruptible_process_does_not_block_freezing_forever(self):
        fields = ['0'] * 22
        fields[0], fields[19] = 'D', 'synthetic-start'
        with patch('drum_score.supervision._stat', return_value=fields), patch('drum_score.supervision._processes', return_value=({}, 0)), patch('drum_score.supervision.os.kill') as stop, patch('drum_score.supervision.time.monotonic', side_effect=(0, 2)):
            _freeze_tree({123: 'synthetic-start'})
        stop.assert_called_once_with(123, signal.SIGSTOP)


if __name__ == '__main__':
    unittest.main()
