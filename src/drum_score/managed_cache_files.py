"""Open and remove cache files through verified no-follow directory descriptors."""
from contextlib import contextmanager
import json
import os
import stat


@contextmanager
def directory(data_root, root, row):
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (*data_root.parts[1:], *root.relative_to(data_root).parts):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != (row['device'], row['inode']):
            raise ValueError('Changed cache root')
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def leaf(root_fd, name):
    parts = name.split('/')
    if not parts or any(p in ('', '.', '..') for p in parts):
        raise ValueError('Invalid cache file')
    descriptor = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


@contextmanager
def open_media(data_root, root, row):
    entries = json.loads(row['files'])
    expected = next(e for e in entries if e[0] == 'payload/video.mp4')
    with directory(data_root, root, row) as descriptor, leaf(descriptor, expected[0]) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or [info.st_dev, info.st_ino, info.st_ctime_ns] != expected[1:] or info.st_size != row['media_bytes']:
                raise ValueError('Changed media')
            yield stream


def remove(data_root, root, row, entries):
    try:
        with directory(data_root, root, row) as descriptor:
            for name, device, inode, changed_ns in entries:
                try:
                    with leaf(descriptor, name) as (parent, filename):
                        current = os.stat(filename, dir_fd=parent, follow_symlinks=False)
                        if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino, current.st_ctime_ns) == (device, inode, changed_ns):
                            os.unlink(filename, dir_fd=parent)
                except FileNotFoundError:
                    pass
            # Only expected empty directories can be removed; unknown files survive.
            try: os.rmdir('payload', dir_fd=descriptor)
            except OSError: pass
        with directory(data_root, root.parent, {'device': root.parent.stat().st_dev, 'inode': root.parent.stat().st_ino}) as parent:
            current = os.stat(root.name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev,current.st_ino) != (row['device'],row['inode']): return False
            os.rmdir(root.name, dir_fd=parent)
        return True
    except FileNotFoundError:
        return True
    except (OSError,ValueError):
        return False
