"""Real process trees: stopping a task must not orphan members of nested groups."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.supervision import _identity, _kill_groups, _stop

# A group leader (like the downloader worker, which calls setsid) with one child
# in its own group. The child is started last, so a sampler may not see it yet.
LEADER = '''import subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])
open(sys.argv[1], 'w').write(f'{child.pid}')
time.sleep(3600)
'''
ROOT = '''import os, subprocess, sys, time
os.setsid()
leader = subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[3]], start_new_session=True)
open(sys.argv[1], 'w').write(f'{leader.pid}')
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
            return int(path.read_text())
        time.sleep(.02)
    raise AssertionError('fixture process did not start')


@unittest.skipUnless(Path('/proc').is_dir(), 'Linux process tree contract')
class StopProcessTree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.started = []

    def tearDown(self):
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


if __name__ == '__main__':
    unittest.main()
