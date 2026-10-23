"""Recover only the exact task created by a supervisor that disappeared."""
from pathlib import Path
import os
import select
import shutil
import signal
import sys
import time

from .supervision import _kill_groups, _processes


def main():
    descriptor, worker, root_name, device, inode, root_identity = sys.argv[1:7]
    lease = sys.argv[7:] == ['lease']
    descriptor, worker, device, inode = map(int, (descriptor, worker, device, inode))
    root = Path(root_name)
    tracked = {}
    os.write(sys.stdout.fileno(), b'R')
    try:
        while True:
            descendants, _ = _processes(worker, root_identity)
            for pid, identity_value in descendants.items():
                tracked.setdefault(pid, identity_value)
            if select.select([descriptor], [], [], .02)[0]:
                if os.read(descriptor, 1):
                    return 0
                break
        descendants, _ = _processes(worker, root_identity)
        for pid, identity_value in descendants.items():
            tracked.setdefault(pid, identity_value)
        _kill_groups(tracked)
        deadline = time.monotonic() + 2
        while True:
            descendants, _ = _processes(worker, root_identity)
            for pid, identity_value in descendants.items():
                tracked.setdefault(pid, identity_value)
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
            if not lease and time.monotonic() >= deadline:
                return 1  # Do not race a writer that could still use the tree.
            time.sleep(.01)
        try:
            stat = root.lstat()
            if not root.is_symlink() and (stat.st_dev, stat.st_ino) == (device, inode):
                shutil.rmtree(root)
        except FileNotFoundError:
            pass
    finally:
        os.close(descriptor)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
