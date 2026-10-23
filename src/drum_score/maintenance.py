"""Bounded offline snapshots, verification, and restoration. No service startup."""

from contextlib import contextmanager
from pathlib import Path
import ctypes
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sqlite3
import stat
import time

from .arguments import PublicParser
from .public_video import video_origin
from .schema import SCHEMA_VERSION, validate_schema
from .owned_tree import remove_owned_tree

FORMAT = 1
DB_LIMIT = 64 * 1024**2
JSON_LIMIT = 16 * 1024**2


class MaintenanceError(Exception):
    def __init__(self, code, *, residue_name=None, output_published=False):
        self.code = code
        self.residue_name = residue_name
        self.output_published = output_published
        super().__init__(code)


class Budget:
    def __init__(self, timeout, max_bytes, max_files, min_free_bytes):
        values = (timeout, max_bytes, max_files, min_free_bytes)
        if (
            any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or v <= 0
                for v in values
            )
            or max_files > 100000
        ):
            raise MaintenanceError("invalid_request")
        self.deadline = time.monotonic() + timeout
        self.max_bytes, self.max_files, self.min_free = (
            int(max_bytes),
            int(max_files),
            int(min_free_bytes),
        )

    def check(self, size=0, count=0, destination=None):
        if time.monotonic() >= self.deadline:
            raise MaintenanceError("maintenance_timeout")
        if size > self.max_bytes or count > self.max_files:
            raise MaintenanceError("maintenance_limit")
        if destination is not None:
            info = os.fstatvfs(destination)
            if info.f_bavail * info.f_frsize < self.min_free + size:
                raise MaintenanceError("storage_full")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise MaintenanceError("invalid_snapshot")
        value[key] = item
    return value


def parts(name):
    if not isinstance(name, str) or len(name) > 512 or "\\" in name:
        raise MaintenanceError("invalid_snapshot")
    values = name.split("/")
    if any(
        not x or x in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]+", x)
        for x in values
    ):
        raise MaintenanceError("invalid_snapshot")
    return values


class Tree:
    """Keep all reads and writes relative to no-follow directory descriptors."""

    def __init__(self, path):
        self.path = Path(path).absolute()
        self.fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        self.ancestors = [(os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino)]
        try:
            for component in self.path.parts[1:]:
                child = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=self.fd,
                )
                os.close(self.fd)
                self.fd = child
                self.ancestors.append((os.fstat(child).st_dev, os.fstat(child).st_ino))
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @contextmanager
    def parent(self, name, create=False):
        components = parts(name)
        current = os.dup(self.fd)
        try:
            for component in components[:-1]:
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                child = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
                os.close(current)
                current = child
            yield current, components[-1]
        finally:
            os.close(current)

    def open(self, name, write=False):
        with self.parent(name, create=write) as (parent, leaf):
            flags = (
                os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if write
                else os.O_RDONLY | os.O_NONBLOCK
            )
            fd = os.open(leaf, flags | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_dev != os.fstat(self.fd).st_dev
        ):
            os.close(fd)
            raise MaintenanceError("unsafe_file")
        return fd

    def read_json(self, name, budget):
        with os.fdopen(self.open(name), "rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            budget.check(size)
            if size > JSON_LIMIT:
                raise MaintenanceError("maintenance_limit")
            value = stream.read(JSON_LIMIT + 1)
            budget.check()
            return json.loads(value, object_pairs_hook=unique_object)

    def inventory(self, budget):
        files = set()
        directories = set()

        def visit(descriptor, prefix, depth):
            budget.check(count=len(files) + len(directories))
            if depth > 8:
                raise MaintenanceError("invalid_snapshot")
            for name in os.listdir(descriptor):
                budget.check(count=len(files) + len(directories))
                relative = prefix + name
                parts(relative)
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if info.st_dev != os.fstat(self.fd).st_dev:
                    raise MaintenanceError("unsafe_file")
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                    try:
                        directories.add(relative)
                        visit(child, relative + "/", depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    files.add(relative)
                else:
                    raise MaintenanceError("unsafe_file")
            budget.check(count=len(files) + len(directories))

        visit(self.fd, "", 0)
        return files, directories

    def sync_directories(self, budget):
        def sync(descriptor):
            for name in os.listdir(descriptor):
                budget.check()
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                    try:
                        sync(child)
                    finally:
                        os.close(child)
            budget.check()
            os.fsync(descriptor)

        sync(self.fd)

    def database(self):
        return f"/proc/self/fd/{self.fd}/tasks.sqlite3"


def connect(tree, budget, *, writable=False):
    budget.check()
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            fd = tree.open("tasks.sqlite3" + suffix)
        except FileNotFoundError:
            pass
        else:
            os.close(fd)
    with os.fdopen(tree.open("tasks.sqlite3"), "rb") as check:
        if os.fstat(check.fileno()).st_size > DB_LIMIT:
            raise MaintenanceError("maintenance_limit")
    db = sqlite3.connect(
        "file:" + tree.database() + "?mode=" + ("rw" if writable else "ro"),
        uri=True,
        timeout=min(1, max(0.001, budget.deadline - time.monotonic())),
        isolation_level=None,
    )
    db.row_factory = sqlite3.Row
    db.enable_load_extension(False)
    db.execute("PRAGMA trusted_schema=OFF")
    if not writable:
        db.execute("PRAGMA query_only=ON")
    db.set_progress_handler(lambda: int(time.monotonic() >= budget.deadline), 1000)
    return db


def validate(db, budget, *, schema_version=SCHEMA_VERSION):
    budget.check()
    validate_schema(db, version=schema_version)
    pages = db.execute("PRAGMA page_count").fetchone()[0]
    page_size = db.execute("PRAGMA page_size").fetchone()[0]
    if pages * page_size > DB_LIMIT:
        raise MaintenanceError("maintenance_limit")
    if db.execute("PRAGMA integrity_check(1)").fetchall()[0][0] != "ok":
        raise MaintenanceError("invalid_snapshot")
    rows = [
        dict(row)
        for row in db.execute("SELECT * FROM tasks LIMIT ?", (budget.max_files + 1,))
    ]
    budget.check(count=len(rows))
    for row in rows:
        if row["state"] not in (
            "queued",
            "running",
            "cancelling",
            "finishing",
            "complete",
            "failed",
            "cancelled",
            "interrupted",
            "expired",
        ):
            raise MaintenanceError("invalid_snapshot")
        if not all(
            isinstance(row[key], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{20,64}", row[key])
            for key in ("id",)
        ):
            raise MaintenanceError("invalid_snapshot")
        if row["attempt"] is not None and (
            not isinstance(row["attempt"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", row["attempt"])
        ):
            raise MaintenanceError("invalid_snapshot")
        if any(
            not isinstance(row[key], str) or not re.fullmatch(r"[0-9a-f]{64}", row[key])
            for key in (
                ("capability_hash",)
                if row["state"] == "expired"
                else ("capability_hash", "ip_key")
            )
        ):
            raise MaintenanceError("invalid_snapshot")
        for key in ("created_at", "queued_at", "completed_at", "expires_at"):
            value = row[key]
            if value is None and key in ("completed_at", "expires_at"):
                continue
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise MaintenanceError("invalid_snapshot")
        origin = json.loads(row["source"], object_pairs_hook=unique_object)
        if not isinstance(origin, dict) or (
            origin != {}
            if row["state"] == "expired"
            else origin != video_origin(origin.get("url"))
        ):
            raise MaintenanceError("invalid_snapshot")
        if not isinstance(row["stage"], str) or not row["stage"]:
            raise MaintenanceError("invalid_snapshot")
        if row["summary"] is not None and not isinstance(
            json.loads(row["summary"], object_pairs_hook=unique_object), dict
        ):
            raise MaintenanceError("invalid_snapshot")
    return rows


def result_files(tree, db, budget, *, owned=False, schema_version=SCHEMA_VERSION):
    files = []
    for row in validate(db, budget, schema_version=schema_version):
        if row["state"] not in ("complete", "finishing"):
            continue
        if not all(
            isinstance(row[key], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{20,64}", row[key])
            for key in ("id", "attempt")
        ):
            raise MaintenanceError("invalid_snapshot")
        if any(
            not isinstance(row[key], (int, float)) or not math.isfinite(row[key])
            for key in ("completed_at", "expires_at")
        ):
            raise MaintenanceError("invalid_snapshot")
        prefix = f"attempts/{row['id']}/{row['attempt']}/result/"
        manifest = tree.read_json(prefix + "manifest.json", budget)
        references = [manifest["pdf"], *manifest["pages"]]
        if (
            manifest["status"] != "complete"
            or manifest["reliable"] is not False
            or not manifest["pages"]
        ):
            raise MaintenanceError("invalid_snapshot")
        if (
            manifest.get("retention", {}).get("can_reconstruct_from_retained_sources")
            is not False
        ):
            raise MaintenanceError("invalid_snapshot")
        expected = dict(
            status="complete",
            reliable=False,
            warnings=manifest["warnings"],
            page_count=len(manifest["pages"]),
            pdf=manifest["pdf"],
            pages=manifest["pages"],
            source=manifest["source"],
            program=manifest["program"],
            resources=manifest["resources"],
            retention=manifest.get("retention"),
        )
        if json.loads(row["summary"]) != expected:
            raise MaintenanceError("invalid_snapshot")
        names = ["score.pdf"]
        for index, reference in enumerate(manifest["pages"], 1):
            name = reference["path"]
            match = re.fullmatch(r"page-(0*[1-9][0-9]*)\.png", name)
            if match is None or int(match[1]) != index:
                raise MaintenanceError("invalid_snapshot")
            names.append(name)
        for ref, name in zip(references, names):
            if (
                ref["path"] != name
                or not isinstance(ref["bytes"], int)
                or ref["bytes"] <= 0
            ):
                raise MaintenanceError("invalid_snapshot")
            entry = digest_copy(tree, None, prefix + name, budget)
            if entry["bytes"] != ref["bytes"] or entry["sha256"] != ref["sha256"]:
                raise MaintenanceError("invalid_snapshot")
            files.append(entry)
        files.append(digest_copy(tree, None, prefix + "manifest.json", budget))
        budget.check(sum(item["bytes"] for item in files), len(files))
        if owned:
            managed = db.execute(
                "SELECT * FROM managed_attempts WHERE task=? AND attempt=?",
                (row["id"], row["attempt"]),
            ).fetchone()
            if managed is None:
                raise MaintenanceError("invalid_snapshot")
            with tree.parent(prefix + "manifest.json") as (result_fd, _):
                attempt_fd = os.open(
                    "..", os.O_RDONLY | os.O_DIRECTORY, dir_fd=result_fd
                )
                try:
                    info = os.fstat(attempt_fd)
                finally:
                    os.close(attempt_fd)
            if (info.st_dev, info.st_ino) != (managed["device"], managed["inode"]):
                raise MaintenanceError("source_changed")
            entries = json.loads(managed["files"])
            expected_entries = {item[0]: item[1:] for item in entries}
            if set(expected_entries) - {".staging-ownership.json"} != {
                "result/" + name for name in [*names, "manifest.json"]
            }:
                raise MaintenanceError("invalid_snapshot")
            for name in [*names, "manifest.json"]:
                with os.fdopen(tree.open(prefix + name), "rb") as stream:
                    info = os.fstat(stream.fileno())
                if expected_entries["result/" + name] != [
                    info.st_dev,
                    info.st_ino,
                    info.st_ctime_ns,
                ]:
                    raise MaintenanceError("source_changed")
    return files


def register_restored(tree, db, budget):
    # Only a newly created, fully verified restore tree is passed here.
    rows = validate(db, budget)
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DELETE FROM managed_attempts")
        for row in rows:
            if row["state"] not in ("complete", "finishing"):
                continue
            prefix = f"attempts/{row['id']}/{row['attempt']}/result/"
            manifest = tree.read_json(prefix + "manifest.json", budget)
            entries = []
            for name in [
                "manifest.json",
                manifest["pdf"]["path"],
                *[r["path"] for r in manifest["pages"]],
            ]:
                with os.fdopen(tree.open(prefix + name), "rb") as stream:
                    info = os.fstat(stream.fileno())
                entries.append(
                    ["result/" + name, info.st_dev, info.st_ino, info.st_ctime_ns]
                )
            with tree.parent(prefix + "manifest.json") as (result_fd, _):
                attempt_fd = os.open(
                    "..", os.O_RDONLY | os.O_DIRECTORY, dir_fd=result_fd
                )
                try:
                    info = os.fstat(attempt_fd)
                finally:
                    os.close(attempt_fd)
            db.execute(
                "INSERT INTO managed_attempts VALUES(?,?,?,?,?)",
                (
                    row["id"],
                    row["attempt"],
                    info.st_dev,
                    info.st_ino,
                    json.dumps(entries),
                ),
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise


def digest_copy(source, target, name, budget):
    with os.fdopen(source.open(name), "rb") as stream:
        before = os.fstat(stream.fileno())
        budget.check(before.st_size)
        digest = hashlib.sha256()
        output = os.fdopen(target.open(name, write=True), "wb") if target else None
        try:
            while chunk := stream.read(1024 * 1024):
                budget.check(destination=target.fd if target else None)
                digest.update(chunk)
                if output:
                    output.write(chunk)
            after = os.fstat(stream.fileno())
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise MaintenanceError("source_changed")
            if output:
                output.flush()
                os.fsync(output.fileno())
        finally:
            if output:
                output.close()
    return dict(path=name, bytes=before.st_size, sha256=digest.hexdigest())


def publish(parent, temporary, name):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(parent, os.fsencode(temporary), parent, os.fsencode(name), 1):
        raise OSError(ctypes.get_errno(), "Exclusive publish failed")


@contextmanager
def destination(source, output, budget):
    output = Path(output).absolute()
    source_identity = (os.fstat(source.fd).st_dev, os.fstat(source.fd).st_ino)
    source = source.path
    if (
        not output.name
        or output == source
        or output in source.parents
        or source in output.parents
    ):
        raise MaintenanceError("unsafe_path")
    parent = Tree(output.parent)
    temporary = None
    staging = None
    identity = None
    try:
        if source_identity in parent.ancestors:
            raise MaintenanceError("unsafe_path")
        try:
            os.stat(output.name, dir_fd=parent.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise MaintenanceError("output_exists")
        budget.check(destination=parent.fd)
        temporary = ".drum-maintenance-" + os.urandom(12).hex()
        os.mkdir(temporary, 0o700, dir_fd=parent.fd)
        staging = object.__new__(Tree)
        staging.fd = os.open(
            temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent.fd
        )
        staging.path = output.parent / temporary
        staging.ancestors = parent.ancestors + [
            (os.fstat(staging.fd).st_dev, os.fstat(staging.fd).st_ino)
        ]
        identity = staging.ancestors[-1]
        yield staging
        staging.sync_directories(budget)
        budget.check(destination=parent.fd)
        publish(parent.fd, temporary, output.name)
        temporary = None
        try:
            os.fsync(parent.fd)
        except OSError:
            raise MaintenanceError(
                "publication_durability_unknown", output_published=True
            ) from None
    finally:
        if staging:
            staging.close()
        if temporary:
            # Only our private staging, never any pre-existing output.
            if not remove_owned_tree(parent.fd, temporary, identity):
                raise MaintenanceError("cleanup_incomplete", residue_name=temporary)
        parent.close()


def report(operation, files):
    return dict(
        status="complete",
        operation=operation,
        files=len(files),
        bytes=sum(x["bytes"] for x in files),
        backup_format=FORMAT,
        schema=SCHEMA_VERSION,
    )


def backup(
    data_root,
    output,
    *,
    services_stopped=False,
    timeout=60,
    max_bytes=4096 * 1024**2,
    max_files=8192,
    min_free_bytes=2048 * 1024**2,
):
    if not services_stopped:
        raise MaintenanceError("services_must_be_stopped")
    budget = Budget(timeout, max_bytes, max_files, min_free_bytes)
    if Path(data_root).absolute() in (
        Path("/"),
        Path.home(),
        Path("/home"),
        Path("/var"),
        Path("/var/lib"),
        Path("/tmp"),
    ):
        raise MaintenanceError("unsafe_path")
    source = Tree(data_root)
    lock = None
    barrier = None
    reader = None
    try:
        reader = connect(source, budget)
        validate(reader, budget)
        lock = os.open(
            "worker.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=source.fd,
        )
        if not stat.S_ISREG(os.fstat(lock).st_mode) or os.fstat(lock).st_nlink != 1:
            raise MaintenanceError("unsafe_file")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        barrier = connect(source, budget, writable=True)
        barrier.execute("BEGIN IMMEDIATE")
        with destination(source, output, budget) as target:
            db = sqlite3.connect(target.database())
            try:
                page_size = reader.execute("PRAGMA page_size").fetchone()[0]

                def progress(status, remaining, total):
                    budget.check(total * page_size)
                    if total * page_size > DB_LIMIT:
                        raise MaintenanceError("maintenance_limit")

                reader.backup(db, pages=128, progress=progress, sleep=0.01)
            finally:
                db.close()
            os.chmod(target.database(), 0o600)
            snapshot = connect(target, budget)
            try:
                selected = result_files(source, snapshot, budget, owned=True)
            finally:
                snapshot.close()
            files = [digest_copy(target, None, "tasks.sqlite3", budget)]
            budget.check(
                sum(x["bytes"] for x in files + selected),
                len(files + selected),
                target.fd,
            )
            for entry in selected:
                if digest_copy(source, target, entry["path"], budget) != entry:
                    raise MaintenanceError("source_changed")
            files += selected
            budget.check(sum(x["bytes"] for x in files), len(files) + 1, target.fd)
            with os.fdopen(target.open("snapshot.json", write=True), "w") as stream:
                json.dump(
                    dict(
                        format=FORMAT,
                        schema=SCHEMA_VERSION,
                        created_at=time.time(),
                        release=release_identity(),
                        files=files,
                    ),
                    stream,
                )
                stream.flush()
                os.fsync(stream.fileno())
            verified_files(target, budget)
            os.fsync(target.fd)
        return report("backup", files)
    finally:
        if barrier:
            barrier.rollback()
            barrier.close()
        if reader:
            reader.close()
        if lock is not None:
            os.close(lock)
        source.close()


def release_identity():
    package = Path(__file__).parent
    digest = hashlib.sha256()
    for file in sorted([*package.glob("*.py"), *package.glob("static/*")]):
        digest.update(file.relative_to(package).as_posix().encode())
        digest.update(file.read_bytes())
    try:
        version = importlib.metadata.version("bilibili-drum-score-to-pdf")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return dict(
        name="bilibili-drum-score-to-pdf",
        version=version,
        source_sha256=digest.hexdigest(),
    )


def verified_files(source, budget, *, schema_version=SCHEMA_VERSION):
    manifest = source.read_json("snapshot.json", budget)
    if (
        set(manifest) != {"format", "schema", "created_at", "release", "files"}
        or manifest["format"] != FORMAT
        or manifest["schema"] != schema_version
    ):
        raise MaintenanceError("invalid_snapshot")
    release = manifest["release"]
    if (
        set(release) != {"name", "version", "source_sha256"}
        or release["name"] != "bilibili-drum-score-to-pdf"
        or not re.fullmatch("[0-9a-f]{64}", release["source_sha256"])
    ):
        raise MaintenanceError("invalid_snapshot")
    files = manifest["files"]
    if not isinstance(files, list):
        raise MaintenanceError("invalid_snapshot")
    names = set()
    total = 0
    for entry in files:
        if (
            set(entry) != {"path", "bytes", "sha256"}
            or not isinstance(entry["bytes"], int)
            or isinstance(entry["bytes"], bool)
            or entry["bytes"] <= 0
            or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])
        ):
            raise MaintenanceError("invalid_snapshot")
        name = entry["path"]
        parts(name)
        if name != "tasks.sqlite3" and not re.fullmatch(
            r"attempts/[A-Za-z0-9_-]{20,64}/[A-Za-z0-9_-]{20,64}/result/(?:score\.pdf|manifest\.json|page-0*[1-9][0-9]*\.png)",
            name,
        ):
            raise MaintenanceError("invalid_snapshot")
        if name.casefold() in names:
            raise MaintenanceError("invalid_snapshot")
        names.add(name.casefold())
        total += entry["bytes"]
        budget.check(total, len(files) + 1)
    with os.fdopen(source.open("snapshot.json"), "rb") as stream:
        total += os.fstat(stream.fileno()).st_size
    budget.check(total, len(files) + 1)
    listed = {entry["path"] for entry in files} | {"snapshot.json"}
    actual, directories = source.inventory(budget)
    allowed_directories = {
        parent.as_posix()
        for name in listed
        for parent in Path(name).parents
        if parent != Path(".")
    }
    if actual != listed or directories != allowed_directories:
        raise MaintenanceError("invalid_snapshot")
    for entry in files:
        if digest_copy(source, None, entry["path"], budget) != entry:
            raise MaintenanceError("invalid_snapshot")
    db = connect(source, budget)
    try:
        selected = result_files(source, db, budget, schema_version=schema_version)
    finally:
        db.close()
    if listed != {
        "snapshot.json",
        "tasks.sqlite3",
        *[entry["path"] for entry in selected],
    }:
        raise MaintenanceError("invalid_snapshot")
    budget.check()
    return files


def verify(
    backup_root,
    *,
    timeout=60,
    max_bytes=4096 * 1024**2,
    max_files=8192,
    min_free_bytes=2048 * 1024**2,
):
    budget = Budget(timeout, max_bytes, max_files, min_free_bytes)
    if Path(backup_root).name.startswith(".drum-maintenance-"):
        raise MaintenanceError("incomplete_snapshot")
    source = Tree(backup_root)
    try:
        return report("verify", verified_files(source, budget))
    finally:
        source.close()


def restore(
    backup_root,
    output,
    *,
    upgrade_from_v1=False,
    timeout=60,
    max_bytes=4096 * 1024**2,
    max_files=8192,
    min_free_bytes=2048 * 1024**2,
):
    budget = Budget(timeout, max_bytes, max_files, min_free_bytes)
    if Path(backup_root).name.startswith(".drum-maintenance-"):
        raise MaintenanceError("incomplete_snapshot")
    source = Tree(backup_root)
    try:
        files = verified_files(source, budget, schema_version=1 if upgrade_from_v1 else SCHEMA_VERSION)
        with destination(source, output, budget) as target:
            budget.check(sum(entry["bytes"] for entry in files), len(files), target.fd)
            for entry in files:
                if digest_copy(source, target, entry["path"], budget) != entry:
                    raise MaintenanceError("source_changed")
            db = connect(target, budget, writable=True)
            try:
                if upgrade_from_v1:
                    # Only mutate the private, fully verified destination copy.
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        validate_schema(db, version=1)
                        db.execute("DROP INDEX single_active")
                        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                        validate_schema(db)
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise
                result_files(target, db, budget)
                register_restored(target, db, budget)
                result_files(target, db, budget, owned=True)
            finally:
                db.close()
            with os.fdopen(target.open("tasks.sqlite3"), "rb") as stream:
                os.fsync(stream.fileno())
        if upgrade_from_v1:
            # The copied SQLite bytes changed; report the published version,
            # never present old snapshot hashes as hashes of the upgraded DB.
            return dict(status="complete", operation="upgrade-v1", schema=SCHEMA_VERSION,
                        source_schema=1, source_unchanged=True)
        return report("restore", files)
    finally:
        source.close()


def main(argv=None):
    parser = PublicParser(
        prog="drum-score-maintenance",
        description="停服窗口中的完整备份、只读核验与恢复到新目录。",
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("backup", "verify", "restore", "upgrade-v1"):
        child = commands.add_parser(name)
        child.add_argument("--timeout", type=float, default=60)
        child.add_argument("--max-mib", type=float, default=4096)
        child.add_argument("--max-files", type=int, default=8192)
        child.add_argument("--min-free-mib", type=float, default=2048)
        if name == "backup":
            child.add_argument("--data-root", required=True)
            child.add_argument("--services-stopped", action="store_true")
        else:
            child.add_argument("--backup-root", required=True)
        if name != "verify":
            child.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        options = dict(
            timeout=args.timeout,
            max_bytes=args.max_mib * 1024**2,
            max_files=args.max_files,
            min_free_bytes=args.min_free_mib * 1024**2,
        )
        if args.operation == "backup":
            result = backup(
                args.data_root,
                args.output,
                services_stopped=args.services_stopped,
                **options,
            )
        elif args.operation == "verify":
            result = verify(args.backup_root, **options)
        else:
            result = restore(args.backup_root, args.output, upgrade_from_v1=args.operation == "upgrade-v1", **options)
    except Exception as error:
        code = (
            error.code if isinstance(error, MaintenanceError) else "maintenance_failed"
        )
        result = dict(
            status="failed",
            error=dict(
                code=code,
                message="维护操作未完成；请检查停服、版本、路径、完整性与资源额度。",
            ),
        )
        if isinstance(error, MaintenanceError):
            if error.output_published:
                result["error"]["output_published"] = True
            if error.residue_name:
                result["error"]["residue_name"] = error.residue_name
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
