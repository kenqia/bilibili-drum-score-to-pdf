"""Recover only the exact task created by a supervisor that disappeared."""
from pathlib import Path
import os
import select
import shutil
import signal
import sys
import time

from .supervision import _processes


def main():
    descriptor, worker, root_name, device, inode = sys.argv[1:]
    descriptor, worker, device, inode = map(int, (descriptor, worker, device, inode))
    root = Path(root_name)
    tracked = {}
    os.write(sys.stdout.fileno(), b'R')
    try:
        while True:
            descendants, _ = _processes(worker)
            tracked.update(descendants)
            if select.select([descriptor], [], [], .02)[0]:
                if os.read(descriptor, 1):
                    return 0
                break
        deadline = time.monotonic() + 2
        while True:
            descendants, _ = _processes(worker)
            tracked.update(descendants)
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
            if time.monotonic() >= deadline:
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
