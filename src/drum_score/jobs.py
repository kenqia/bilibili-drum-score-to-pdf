"""Short SQLite transactions for capability-owned anonymous tasks."""
from contextlib import contextmanager
from hashlib import sha256, file_digest
from pathlib import Path
import hmac
import json
import os
import secrets
import sqlite3
import time
import re
import stat
import math
import threading

from .public_video import InputError, video_origin


UNFINISHED = ('queued', 'running', 'cancelling', 'finishing')
ACTIVE = ('running', 'cancelling', 'finishing')
from .schema import SCHEMA_VERSION, SCHEMA_STATEMENTS, validate_schema


class JobError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def controlled_root(path):
    root = Path(path).absolute()
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise ValueError('任务数据目录不能经过符号链接。')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError('任务数据目录必须是目录。')
    return root


class Jobs:
    def __init__(self, root, *, retention_seconds=86400, diagnostic_seconds=3600,
                 diagnostic_bytes=8 * 1024**2, min_free_bytes=512 * 1024**2,
                 retained_bytes=4 * 1024**3, job_temp_bytes=1024**3):
        values = (retention_seconds, diagnostic_seconds, diagnostic_bytes,
                  min_free_bytes, retained_bytes, job_temp_bytes)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or v <= 0 for v in values) or job_temp_bytes > retained_bytes:
            raise ValueError('无效的服务资源参数。')
        # SQLite has one writer. Serialize this scheduler's short connections
        # locally instead of letting eight supervisors compete in SQLite's busy loop.
        self._transaction_lock = threading.RLock()
        self.root = controlled_root(root)
        identity = self.root.stat()
        self.root_identity = (identity.st_dev, identity.st_ino)
        self.retention_seconds = retention_seconds
        self.diagnostic_seconds = diagnostic_seconds
        self.diagnostic_bytes = int(diagnostic_bytes)
        self.min_free_bytes = int(min_free_bytes)
        self.retained_bytes = int(retained_bytes)
        self.job_temp_bytes = int(job_temp_bytes)
        self.database = self.root / 'tasks.sqlite3'
        if self.database.is_symlink():
            raise ValueError('任务数据库不能是符号链接。')
        with self.transaction() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version != SCHEMA_VERSION and (version != 0 or tables):
                raise ValueError('不支持的任务数据库 schema；请恢复匹配版本的数据与程序。')
            if not tables:
                for statement in SCHEMA_STATEMENTS:
                    db.execute(statement)
                db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            else:
                validate_schema(db)

    @contextmanager
    def transaction(self, *, write=True):
        with self._transaction_lock:
            db = sqlite3.connect(self.database, timeout=1, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield db
                db.commit()
            except sqlite3.OperationalError as error:
                db.rollback()
                # Only real SQLite lock errors are safe to retry. An unknown
                # commit acknowledgement may already have changed durable state.
                code = getattr(error, 'sqlite_errorcode', 0) & 0xff
                if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise JobError('service_busy', '服务正在处理其他请求，请稍后重试。', 503) from None
                raise JobError('database_unavailable', '数据库操作未完成，请稍后重试。', 503) from None
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def authorize(self, db, task, capability):
        row = db.execute('SELECT * FROM tasks WHERE id=?', (task,)).fetchone()
        digest = sha256(capability.encode()).hexdigest()
        if not hmac.compare_digest(row['capability_hash'] if row else '0' * 64, digest):
            row = None
        if row is None:
            raise JobError('not_found', '任务不存在或访问链接无效。', 404)
        return row

    def check_live(self, row):
        if row['state'] == 'expired' or (row['expires_at'] is not None and row['expires_at'] <= time.time()):
            raise JobError('expired', '结果已到期，请重新提交来源链接。', 410)

    def admit(self, db, ip_key):
        if db.execute("SELECT 1 FROM tasks WHERE ip_key=? AND state IN ('queued','running','cancelling','finishing')", (ip_key,)).fetchone():
            raise JobError('ip_busy', '此网络已有一个未完成任务，请等待或取消后重试。', 429)
        if db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued'").fetchone()[0] >= 10:
            raise JobError('queue_full', '等待队列已满，请稍后重试。', 429)
        self.capacity(reserve=True, db=db)

    def enqueue(self, url, ip):
        try:
            source = video_origin(url)
        except (InputError, TypeError, AttributeError):
            raise JobError('invalid_bilibili_url', '请提供公开 HTTPS B站 BV 链接或 b23.tv 短链接，分 P 使用单个正整数 p。', 422) from None
        task, capability = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        now = time.time()
        with self.transaction() as db:
            ip_key = sha256(ip.encode()).hexdigest()
            self.admit(db, ip_key)
            db.execute('INSERT INTO tasks(id,capability_hash,source,ip_key,state,stage,created_at,queued_at) VALUES(?,?,?,?,?,?,?,?)',
                (task, sha256(capability.encode()).hexdigest(), json.dumps(source), ip_key, 'queued', 'queued', now, now))
        return {'id': task, 'capability': capability, 'link': f'/task/{task}#{capability}'}

    def view(self, task, capability):
        with self.transaction(write=False) as db:
            row = self.authorize(db, task, capability)
            self.check_live(row)
            position = db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued' AND (queued_at<? OR (queued_at=? AND id<=?))",
                (row['queued_at'], row['queued_at'], task)).fetchone()[0] if row['state'] == 'queued' else None
            summary = json.loads(row['summary']) if row['summary'] else None
            return {'id': task, 'state': row['state'], 'stage': row['stage'], 'source': json.loads(row['source']),
                'queue_position': position, 'created_at': row['created_at'], 'completed_at': row['completed_at'],
                'expires_at': row['expires_at'], 'result': summary,
                'error': {'code': row['error_code'], 'message': row['error_message']} if row['error_code'] else None}

    def cancel(self, task, capability):
        with self.transaction() as db:
            row = self.authorize(db, task, capability)
            self.check_live(row)
            state = {'queued': 'cancelled', 'running': 'cancelling'}.get(row['state'], row['state'])
            db.execute("UPDATE tasks SET state=?,stage=?,expires_at=CASE WHEN ?='cancelled' THEN COALESCE(expires_at,?) ELSE expires_at END WHERE id=?",
                (state, state if state in ('cancelled', 'cancelling') else row['stage'], state, time.time() + self.diagnostic_seconds, task))
        return self.view(task, capability)

    def retry(self, task, capability, ip):
        with self.transaction() as db:
            row = self.authorize(db, task, capability)
            self.check_live(row)
            if row['state'] not in ('failed', 'cancelled', 'interrupted'):
                raise JobError('not_retryable', '只有失败、取消或中断的任务可以重试。')
            ip_key = sha256(ip.encode()).hexdigest()
            self.admit(db, ip_key)
            db.execute("UPDATE tasks SET state='queued',stage='queued',ip_key=?,queued_at=?,attempt=NULL,summary=NULL,error_code=NULL,error_message=NULL,completed_at=NULL,expires_at=NULL WHERE id=?",
                (ip_key, time.time(), task))
        return self.view(task, capability)

    def attempt_root(self, task, attempt):
        if not all(re.fullmatch(r'[A-Za-z0-9_-]{20,64}', value or '') for value in (task, attempt)):
            raise ValueError('无效的任务目录标识。')
        path = self.root / 'attempts' / task / attempt
        for parent in (path, path.parent, path.parent.parent):
            if parent.is_symlink():
                raise ValueError('任务目录不能是符号链接。')
        return path

    def capacity(self, *, reserve=False, db=None):
        # Count even unrecognized files, never delete live results to admit work.
        total = 0
        if (self.root / 'attempts').is_symlink():
            raise JobError('storage_unavailable', '服务存储目录不可用，请联系运营者。', 503)
        for directory, dirs, files in os.walk(self.root / 'attempts', followlinks=False):
            for name in files:
                try:
                    info = (Path(directory) / name).lstat()
                    if stat.S_ISREG(info.st_mode):
                        total += info.st_size
                except FileNotFoundError:
                    pass
        free = os.statvfs(self.root)
        available = free.f_bavail * free.f_frsize
        reservation = 0
        if reserve:
            if db is None:
                with self.transaction() as connection:
                    return self.capacity(reserve=True, db=connection)
            active = db.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('running','cancelling','finishing')").fetchone()[0]
            # Conservatively reserve the whole budget, including bytes already
            # materialized, for every active attempt and the proposed next one.
            reservation = (active + 1) * self.job_temp_bytes
        if total + reservation > self.retained_bytes or available < self.min_free_bytes + reservation:
            raise JobError('storage_full', '服务存储空间不足，请稍后重试。', 503)
        return total

    def register_attempt(self, row):
        path = self.attempt_root(row['id'], row['attempt'])
        path.mkdir(mode=0o700, parents=True)
        info = path.lstat()
        with self.transaction() as db:
            db.execute('INSERT INTO managed_attempts(task,attempt,device,inode) VALUES(?,?,?,?)',
                (row['id'], row['attempt'], info.st_dev, info.st_ino))
        return path

    def _attempt_descriptor(self, managed):
        path = self.attempt_root(managed["task"], managed["attempt"])
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != self.root_identity:
                raise ValueError("Changed service root")
            for name in path.relative_to(self.root).parts:
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != (managed["device"], managed["inode"]):
                raise ValueError("Changed attempt root")
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise


    def remember_staging(self, row, root):
        if (
            root.parent != self.attempt_root(row["id"], row["attempt"])
            or not re.fullmatch(r"\.drum-score-job-[a-z0-9_]+", root.name)
            or list(root.iterdir())
        ):
            raise ValueError("Invalid new staging root")
        with self.transaction() as db:
            managed = dict(
                db.execute(
                    "SELECT * FROM managed_attempts WHERE task=? AND attempt=?",
                    (row["id"], row["attempt"]),
                ).fetchone()
            )
            descriptor = self._attempt_descriptor(managed)
            try:
                info = root.lstat()
                value = dict(name=root.name, device=info.st_dev, inode=info.st_ino)
                fd = os.open(
                    ".staging-ownership.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=descriptor,
                )
                with os.fdopen(fd, "w") as stream:
                    json.dump(value, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                    marker = os.fstat(stream.fileno())
                os.fsync(descriptor)
                entries = json.loads(managed["files"])
                entries.append(
                    [
                        ".staging-ownership.json",
                        marker.st_dev,
                        marker.st_ino,
                        marker.st_ctime_ns,
                    ]
                )
                db.execute(
                    "UPDATE managed_attempts SET files=? WHERE task=? AND attempt=?",
                    (json.dumps(entries), row["id"], row["attempt"]),
                )
            finally:
                os.close(descriptor)


    def recover_staging(self, row=None):
        from .owned_tree import remove_owned_tree

        with self.transaction() as db:
            managed = [dict(item) for item in db.execute(
                "SELECT * FROM managed_attempts" + (" WHERE task=? AND attempt=?" if row else ""),
                (row['id'], row['attempt']) if row else (),
            )]
        for item in managed:
            entries = json.loads(item["files"])
            marker = next(
                (entry for entry in entries if entry[0] == ".staging-ownership.json"),
                None,
            )
            if marker is None:
                continue
            descriptor = None
            try:
                descriptor = self._attempt_descriptor(item)
                fd = os.open(
                    marker[0],
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=descriptor,
                )
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_size > 4096
                        or [info.st_dev, info.st_ino, info.st_ctime_ns] != marker[1:]
                    ):
                        continue
                    value = json.loads(stream.read(4097))
                if set(value) != {"name", "device", "inode"} or not re.fullmatch(
                    r"\.drum-score-job-[a-z0-9_]+", value["name"]
                ):
                    continue
                if not remove_owned_tree(
                    descriptor, value["name"], (value["device"], value["inode"])
                ):
                    continue
                check = os.stat(marker[0], dir_fd=descriptor, follow_symlinks=False)
                if [check.st_dev, check.st_ino, check.st_ctime_ns] != marker[1:]:
                    continue
                os.unlink(marker[0], dir_fd=descriptor)
                with self.transaction() as db:
                    db.execute(
                        "UPDATE managed_attempts SET files=? WHERE task=? AND attempt=? AND files=?",
                        (
                            json.dumps([entry for entry in entries if entry != marker]),
                            item["task"],
                            item["attempt"],
                            item["files"],
                        ),
                    )
            except (OSError, ValueError, TypeError, KeyError):
                pass
            finally:
                if descriptor is not None:
                    os.close(descriptor)


    def remember_result(self, row, result):
        root = self.attempt_root(row['id'], row['attempt'])
        references = [dict(path='manifest.json'), result['pdf'], *result['pages'],
                      *[ref for ref in result.get('samples', []) if ref.get('retained', True)],
                      *([result['longshot']] if result.get('longshot', {}).get('retained', True) and 'longshot' in result else [])]
        entries = []
        for reference in references:
            relative = Path('result') / reference['path']
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Invalid managed artifact')
            path = root / relative
            for parent in path.parents:
                if parent == root:
                    break
                if parent.is_symlink():
                    raise ValueError('Invalid managed artifact')
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Invalid managed artifact')
            entries.append([relative.as_posix(), info.st_dev, info.st_ino, info.st_ctime_ns])
        with self.transaction() as db:
            old = db.execute('SELECT files FROM managed_attempts WHERE task=? AND attempt=?',
                (row['id'], row['attempt'])).fetchone()
            entries.extend(entry for entry in json.loads(old['files']) if entry[0] == '.staging-ownership.json')
            db.execute('UPDATE managed_attempts SET files=? WHERE task=? AND attempt=?',
                       (json.dumps(entries), row['id'], row['attempt']))

    def remove_files(self, managed, entries):
        # Every unlink is relative to no-follow directory FDs and recorded inodes.
        try:
            root = self.attempt_root(managed['task'], managed['attempt'])
        except ValueError:
            return
        descriptor = None
        parent_descriptor = None
        try:
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != self.root_identity:
                os.close(descriptor)
                return
            for component in root.relative_to(self.root).parts:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                if parent_descriptor is not None:
                    os.close(parent_descriptor)
                parent_descriptor, descriptor = descriptor, child
        except OSError:
            if descriptor is not None:
                os.close(descriptor)
            if parent_descriptor is not None:
                os.close(parent_descriptor)
            return
        try:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != (managed['device'], managed['inode']):
                return
            directories = set()
            for name, device, inode, changed_ns in entries:
                if name == '.staging-ownership.json':
                    continue  # Only recover_staging may release this ownership record.
                relative = Path(name)
                if relative.is_absolute() or '..' in relative.parts:
                    continue
                directories.update(relative.parents)
                current = os.dup(descriptor)
                try:
                    for component in relative.parts[:-1]:
                        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                        os.close(current)
                        current = child
                    metadata = os.stat(relative.name, dir_fd=current, follow_symlinks=False)
                    if stat.S_ISREG(metadata.st_mode) and (metadata.st_dev, metadata.st_ino, metadata.st_ctime_ns) == (device, inode, changed_ns):
                        os.unlink(relative.name, dir_fd=current)
                except (FileNotFoundError, NotADirectoryError):
                    pass
                except OSError:
                    continue  # Symlinks/replaced directories are never followed.
                finally:
                    os.close(current)
            for relative in sorted(directories, key=lambda item: len(item.parts), reverse=True):
                if relative == Path('.'):
                    continue
                current = os.dup(descriptor)
                try:
                    for component in relative.parts[:-1]:
                        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                        os.close(current)
                        current = child
                    os.rmdir(relative.name, dir_fd=current)
                except OSError:
                    pass
                finally:
                    os.close(current)
            try:
                info = os.stat(root.name, dir_fd=parent_descriptor, follow_symlinks=False)
                if (info.st_dev, info.st_ino) == (managed['device'], managed['inode']) and stat.S_ISDIR(info.st_mode):
                    os.rmdir(root.name, dir_fd=parent_descriptor)
            except OSError:
                pass
        finally:
            os.close(descriptor)
            os.close(parent_descriptor)

    def discard(self, row):
        if not row['attempt']:
            return
        with self.transaction() as db:
            managed = db.execute('SELECT * FROM managed_attempts WHERE task=? AND attempt=?',
                (row['id'], row['attempt'])).fetchone()
        if managed:
            self.remove_files(managed, json.loads(managed['files']))

    def cleanup(self):
        # Expiry/auth/open share SQLite serialization. Existing FDs survive unlink.
        now = time.time()
        with self.transaction() as db:
            db.execute("""UPDATE tasks SET state='expired',stage='expired',summary=NULL,
                error_code=NULL,error_message=NULL,source='{}',ip_key=''
                WHERE expires_at<=? AND state NOT IN ('queued','running','cancelling','finishing')""", (now,))
            managed = [dict(row) for row in db.execute("""SELECT m.* FROM managed_attempts m
                JOIN tasks t ON m.task=t.id WHERE t.state='expired' OR
                (t.state IN ('failed','cancelled','interrupted') OR t.attempt<>m.attempt)""")]
            # Diagnostic text has a global byte budget; result retention is independent.
            records = list(db.execute("SELECT id,error_code,error_message FROM tasks WHERE error_code IS NOT NULL ORDER BY queued_at DESC"))
            size = 0
            for row in records:
                size += len((row['error_code'] + (row['error_message'] or '')).encode('utf-8'))
                if size > self.diagnostic_bytes:
                    db.execute('UPDATE tasks SET error_code=NULL,error_message=NULL WHERE id=?', (row['id'],))
        for item in managed:
            self.remove_files(item, json.loads(item['files']))

    def claim(self, *, concurrency=1):
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= 8:
            raise ValueError("并行度必须是 1 至 8 的整数。")
        with self.transaction() as db:
            active = db.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('running','cancelling','finishing')").fetchone()[0]
            if active >= concurrency:
                return None
            row = db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY queued_at,id LIMIT 1").fetchone()
            if row is None:
                return None
            try:
                self.capacity(reserve=True, db=db)
            except JobError as error:
                if active:
                    return None  # Retain FIFO waiting while active reservations consume space.
                db.execute("UPDATE tasks SET state='failed',stage='failed',error_code=?,error_message=?,expires_at=? WHERE id=?",
                    (error.code, error.message, time.time() + self.diagnostic_seconds, row['id']))
                return None
            attempt = secrets.token_urlsafe(24)
            db.execute("UPDATE tasks SET state='running',stage='starting',attempt=? WHERE id=?", (attempt, row['id']))
            return dict(db.execute('SELECT * FROM tasks WHERE id=?', (row['id'],)).fetchone())

    def stage(self, row, stage):
        with self.transaction() as db:
            db.execute("UPDATE tasks SET stage=? WHERE id=? AND attempt=? AND state='running'",
                (stage, row['id'], row['attempt']))

    def cancelled(self, row):
        with self.transaction(write=False) as db:
            current = db.execute('SELECT state,attempt FROM tasks WHERE id=?', (row['id'],)).fetchone()
            return current is None or current['attempt'] != row['attempt'] or current['state'] != 'running'

    def publishing(self, row):
        with self.transaction(write=False) as db:
            current = db.execute('SELECT state,attempt FROM tasks WHERE id=?', (row['id'],)).fetchone()
            return current is not None and current['attempt'] == row['attempt'] and current['state'] in ('finishing', 'complete')

    def settle(self, row, state, code=None, message=None):
        with self.transaction() as db:
            db.execute("UPDATE tasks SET state=?,stage=?,error_code=?,error_message=?,expires_at=COALESCE(expires_at,?) WHERE id=? AND attempt=? AND state IN ('running','cancelling','finishing')",
                (state, state, code, message, time.time() + self.diagnostic_seconds, row['id'], row['attempt']))

    def finishing(self, row, summary):
        with self.transaction() as db:
            now = time.time()
            changed = db.execute("UPDATE tasks SET state='finishing',stage='finishing',summary=?,completed_at=?,expires_at=? WHERE id=? AND attempt=? AND state='running'",
                (json.dumps(summary, ensure_ascii=False), now, now + self.retention_seconds, row['id'], row['attempt'])).rowcount
            return bool(changed)

    def open_artifact(self, task, capability, page=None):
        # Open inside the same transaction as expiry/auth, then stream from the FD.
        with self.transaction() as db:
            row = self.authorize(db, task, capability)
            self.check_live(row)
            if row['state'] != 'complete':
                raise JobError('not_ready', '结果尚未就绪。')
            summary = json.loads(row['summary'])
            if page is not None and not 1 <= page <= summary['page_count']:
                raise JobError('not_found', '页面不存在。', 404)
            reference = summary['pdf'] if page is None else summary['pages'][page - 1]
            if not isinstance(reference['path'], str) or '/' in reference['path'] or '\\' in reference['path'] or reference['path'] in ('.', '..'):
                raise JobError('result_unavailable', '结果文件不可用，请重新提交。', 409)
            path = self.attempt_root(task, row['attempt']) / 'result'
            descriptor = None
            stream = None
            try:
                descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                for component in path.relative_to(self.root).parts:
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
                stream = os.open(reference['path'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                metadata = os.fstat(stream)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != reference['bytes']:
                    raise OSError
                with os.fdopen(os.dup(stream), 'rb') as verification:
                    if file_digest(verification, 'sha256').hexdigest() != reference['sha256']:
                        raise OSError
                os.lseek(stream, 0, os.SEEK_SET)
                return stream, metadata.st_size
            except OSError:
                if stream is not None:
                    os.close(stream)
                raise JobError('result_unavailable', '结果文件不可用，请重新提交。', 409) from None
            finally:
                if descriptor is not None:
                    os.close(descriptor)
