"""Remove only the same private directory inode, without following links."""

import os
import stat
import time


def remove_owned_tree(parent, name, identity, *, deadline=None, remaining=None):
    deadline = time.monotonic() + 5 if deadline is None else deadline
    remaining = [32768] if remaining is None else remaining
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
        )
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != identity:
            return False
        for leaf in os.listdir(descriptor):
            if remaining[0] <= 0 or time.monotonic() >= deadline:
                return False
            remaining[0] -= 1
            metadata = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
            if metadata.st_dev != identity[0]:
                continue
            if stat.S_ISDIR(metadata.st_mode):
                remove_owned_tree(
                    descriptor,
                    leaf,
                    (metadata.st_dev, metadata.st_ino),
                    deadline=deadline,
                    remaining=remaining,
                )
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                check = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
                if (check.st_dev, check.st_ino, check.st_ctime_ns) == (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_ctime_ns,
                ):
                    os.unlink(leaf, dir_fd=descriptor)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != identity:
            return False
        try:
            os.rmdir(name, dir_fd=parent)
        except OSError:
            return False
        return True
    except OSError:
        return False
    finally:
        os.close(descriptor)
