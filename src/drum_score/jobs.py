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
from .processing_records import Records, DEFAULT_BYTES, RETENTION_SECONDS, MAX_RECORD_BYTES

from .public_video import InputError, video_origin
from .conversion_options import normalize_options


UNFINISHED = ('queued', 'running', 'cancelling', 'finishing')
ACTIVE = ('running', 'cancelling', 'finishing')
IDENTITY_RETENTION_SECONDS = 30 * 86400
from .schema import SCHEMA_VERSION, SCHEMA_STATEMENTS, validate_schema


class JobError(Exception):
    def __init__(self, code, message, status=409, *, retry_after_seconds=None):
        self.code, self.message, self.status = code, message, status
        self.retry_after_seconds = retry_after_seconds
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
                 retained_bytes=4 * 1024**3, job_temp_bytes=1024**3,
                 cache_bytes=1024**3, cache_retention_seconds=86400,
                 record_bytes=DEFAULT_BYTES, record_retention_seconds=RETENTION_SECONDS):
        values = (retention_seconds, diagnostic_seconds, diagnostic_bytes,
                  min_free_bytes, retained_bytes, job_temp_bytes, cache_bytes, cache_retention_seconds,
                  record_bytes, record_retention_seconds)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or v <= 0 for v in values) or job_temp_bytes > retained_bytes or cache_bytes > 1024**3:
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
        self.cache_bytes = int(cache_bytes)
        self.cache_retention_seconds = cache_retention_seconds
        self.record_bytes = int(record_bytes)
        self.record_retention_seconds = record_retention_seconds
        self.records = Records(self)
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
                db.execute('INSERT INTO submission_control VALUES(1,0)')
                db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            else:
                validate_schema(db)
        os.chmod(self.database, 0o600)

    @contextmanager
    def transaction(self, *, write=True):
        with self._transaction_lock:
            db = sqlite3.connect(self.database, timeout=1, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA secure_delete=ON')
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

    def admit(self, db, ip_key, now):
        control = db.execute('SELECT paused FROM submission_control WHERE id=1').fetchone()
        if control is None or control['paused'] != 0:
            raise JobError('submissions_paused', '服务暂时停止接收新任务，请稍后再试。已有任务和结果访问不受影响。', 503)
        wait = 0
        for seconds, count in ((600, 10), (86400, 100)):
            event = db.execute('SELECT admitted_at FROM submission_events WHERE ip_key=? AND admitted_at>? ORDER BY admitted_at DESC LIMIT 1 OFFSET ?',
                (ip_key, now - seconds, count - 1)).fetchone()
            if event:
                wait = max(wait, math.ceil(event['admitted_at'] + seconds - now))
        if wait:
            raise JobError('submission_limit', f'此网络提交次数已达上限，请在 {wait} 秒后重试。', 429,
                retry_after_seconds=wait)
        if db.execute("SELECT 1 FROM tasks WHERE ip_key=? AND state IN ('queued','running','cancelling','finishing')", (ip_key,)).fetchone():
            raise JobError('ip_busy', '此网络已有一个未完成任务，请等待或取消后重试。', 429)
        if db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued'").fetchone()[0] >= 10:
            raise JobError('queue_full', '等待队列已满，请稍后重试。', 429)
        self.capacity(reserve=True, db=db, log_reserve=MAX_RECORD_BYTES)
        self.records.admit(db)

    def enqueue(self, url, ip, *, options=None):
        from .video_seek import ConversionError
        try:
            options = normalize_options(options)
        except ConversionError as error:
            raise JobError(error.code, str(error), 422) from None
        try:
            source = video_origin(url)
        except (InputError, TypeError, AttributeError):
            raise JobError('invalid_bilibili_url', '请提供公开 HTTPS B站 BV 链接或 b23.tv 短链接，分 P 使用单个正整数 p。', 422) from None
        task, capability = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with self.transaction() as db:
            now = time.time()
            ip_key = sha256(ip.encode()).hexdigest()
            self.admit(db, ip_key, now)
            db.execute('INSERT INTO tasks(id,capability_hash,source,ip_key,state,stage,created_at,queued_at,options) VALUES(?,?,?,?,?,?,?,?,?)',
                (task, sha256(capability.encode()).hexdigest(), json.dumps(source), ip_key, 'queued', 'queued', now, now, json.dumps(options)))
            db.execute('DELETE FROM submission_events WHERE admitted_at<=?', (now - 86400,))
            db.execute('INSERT INTO submission_events VALUES(?,?)', (ip_key, now))
            self.records.start(db, 'submit', task=task, source=source['url'], settings={'options': options})
        return {'id': task, 'capability': capability, 'link': f'/task/{task}#{capability}'}

    def view(self, task, capability):
        with self.transaction(write=False) as db:
            row = self.authorize(db, task, capability)
            self.check_live(row)
            position = db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued' AND (queued_at<? OR (queued_at=? AND id<=?))",
                (row['queued_at'], row['queued_at'], task)).fetchone()[0] if row['state'] == 'queued' else None
            summary = json.loads(row['summary']) if row['summary'] else None
            return {'id': task, 'state': row['state'], 'stage': row['stage'], 'source': json.loads(row['source']),
                'options': normalize_options(json.loads(row['options'])),
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
            record = self.records.conversion(db, task)
            if state == 'cancelled':
                self.finish_record(db, record, state, code='cancelled')
            elif state == 'cancelling':
                self.write_record(db, record, status=state)
        return self.view(task, capability)

    def retry(self, task, capability, ip):
        with self.transaction() as db:
            row = self.authorize(db, task, capability)
            self.check_live(row)
            if row['state'] not in ('failed', 'cancelled', 'interrupted'):
                raise JobError('not_retryable', '只有失败、取消或中断的任务可以重试。')
            if json.loads(row['source']).get('kind') == 'youtube':
                raise JobError('invalid_bilibili_url', 'YouTube 接入已撤回，请提供 B站链接。', 422)
            ip_key = sha256(ip.encode()).hexdigest()
            now = time.time()
            self.admit(db, ip_key, now)
            db.execute("UPDATE tasks SET state='queued',stage='queued',ip_key=?,queued_at=?,attempt=NULL,summary=NULL,error_code=NULL,error_message=NULL,completed_at=NULL,expires_at=NULL WHERE id=?",
                (ip_key, now, task))
            db.execute('DELETE FROM submission_events WHERE admitted_at<=?', (now - 86400,))
            db.execute('INSERT INTO submission_events VALUES(?,?)', (ip_key, now))
            self.records.start(db, 'retry', task=task, source=json.loads(row['source'])['url'], settings={'options': json.loads(row['options'])})
        return self.view(task, capability)

    def attempt_root(self, task, attempt):
        if not all(re.fullmatch(r'[A-Za-z0-9_-]{20,64}', value or '') for value in (task, attempt)):
            raise ValueError('无效的任务目录标识。')
        path = self.root / 'attempts' / task / attempt
        for parent in (path, path.parent, path.parent.parent):
            if parent.is_symlink():
                raise ValueError('任务目录不能是符号链接。')
        return path

    def capacity(self, *, reserve=False, db=None, log_reserve=0):
        if db is None:
            with self.transaction(write=reserve) as connection:
                return self.capacity(reserve=reserve, db=connection, log_reserve=log_reserve)
        # Count even unrecognized files, never delete live results to admit work.
        total = 0
        if (self.root / 'attempts').is_symlink():
            raise JobError('storage_unavailable', '服务存储目录不可用，请联系运营者。', 503)
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            if Path(directory) == self.root:
                dirs[:] = [name for name in dirs if name in ('attempts', 'cache')]
                files = []
            for name in files:
                try:
                    info = (Path(directory) / name).lstat()
                    if stat.S_ISREG(info.st_mode):
                        total += info.st_size
                except FileNotFoundError:
                    pass
        free = os.statvfs(self.root)
        available = free.f_bavail * free.f_frsize
        if (self.root / 'cache').is_symlink():
            raise JobError('storage_unavailable', '缓存目录不可用。', 503)
        if db is None:
            with self.transaction(write=False) as connection:
                shared = connection.execute('SELECT COALESCE(SUM(reservation_bytes+media_bytes),0) FROM video_cache').fetchone()[0]
        else:
            shared = db.execute('SELECT COALESCE(SUM(reservation_bytes+media_bytes),0) FROM video_cache').fetchone()[0]
        reservation = shared
        if reserve:
            active = db.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('running','cancelling','finishing')").fetchone()[0]
            # Conservatively reserve the whole budget, including bytes already
            # materialized, for every active attempt and the proposed next one.
            reservation += (active + 1) * self.job_temp_bytes
        logs = self.records.disk_reservation(db, log_reserve)
        if total + reservation > self.retained_bytes or available < self.min_free_bytes + reservation + logs:
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


    def remember_staging(self, row, root, *, print_layout=False):
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
                if print_layout:
                    value['print_layout'] = True
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


    def recover_staging(self, row=None, *, print_locked=False):
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
                if set(value) not in ({"name", "device", "inode"}, {"name", "device", "inode", "print_layout"}) or not re.fullmatch(
                    r"\.drum-score-job-[a-z0-9_]+", value["name"]
                ):
                    continue
                if value.get('print_layout') and not print_locked:
                    from .relayout import slot
                    try:
                        with slot(self):
                            self.recover_staging({'id': item['task'], 'attempt': item['attempt']},
                                                 print_locked=True)
                    except JobError as error:
                        if error.code != 'service_busy':
                            raise
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

    def remove_files(self, managed, entries, *, print_locked=False):
        if not print_locked and any(entry[0] == '.staging-ownership.json' for entry in entries):
            from .relayout import slot
            try:
                with slot(self):
                    return self.remove_files(managed, entries, print_locked=True)
            except JobError as error:
                if error.code == 'service_busy':
                    return
                raise
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
            self.records.cleanup(db, now)
            db.execute('DELETE FROM submission_events WHERE admitted_at<=?', (now - 86400,))
            db.execute("""UPDATE tasks SET state='expired',stage='expired',summary=NULL,
                error_code=NULL,error_message=NULL,source='{}',options='{}',ip_key=''
                WHERE expires_at<=? AND state NOT IN ('queued','running','cancelling','finishing','expired')""", (now,))
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
        # Attempt normal identity-checked cleanup before forgetting old identities.
        # Unknown or replaced files remain on disk and still count toward capacity.
        with self.transaction() as db:
            cutoff = now - IDENTITY_RETENTION_SECONDS
            db.execute("""DELETE FROM managed_attempts WHERE task IN
                (SELECT id FROM tasks WHERE state='expired' AND expires_at<=?)""", (cutoff,))
            db.execute("DELETE FROM tasks WHERE state='expired' AND expires_at<=?", (cutoff,))

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
            if self.records.conversion(db, row['id']) is None:
                # Legacy queued work gets history when first executed after
                # explicit upgrade; completed legacy history cannot be invented.
                try:
                    self.records.start(db, 'submit', task=row['id'], source=json.loads(row['source']).get('url'), settings={'options': json.loads(row['options'])})
                except JobError as error:
                    if error.code in ('records_full', 'records_unavailable'):
                        return None
                    raise
            try:
                self.capacity(reserve=True, db=db)
            except JobError as error:
                if active:
                    return None  # Retain FIFO waiting while active reservations consume space.
                db.execute("UPDATE tasks SET state='failed',stage='failed',error_code=?,error_message=?,expires_at=? WHERE id=?",
                    (error.code, error.message, time.time() + self.diagnostic_seconds, row['id']))
                self.finish_record(db, self.records.conversion(db, row['id']), 'failed', code=error.code)
                return None
            attempt = secrets.token_urlsafe(24)
            db.execute("UPDATE tasks SET state='running',stage='starting',attempt=? WHERE id=?", (attempt, row['id']))
            self.write_record(db, self.records.conversion(db, row['id']), status='running', stage='starting', attempt=attempt)
            return dict(db.execute('SELECT * FROM tasks WHERE id=?', (row['id'],)).fetchone())

    def stage(self, row, stage):
        with self.transaction() as db:
            db.execute("UPDATE tasks SET stage=? WHERE id=? AND attempt=? AND state='running'",
                (stage, row['id'], row['attempt']))
            current = db.execute('SELECT attempt,state FROM tasks WHERE id=?', (row['id'],)).fetchone()
            if current and current['attempt'] == row['attempt'] and current['state'] == 'running':
                self.write_record(db, self.records.conversion(db, row['id']), stage=stage, attempt=row['attempt'])

    def cancelled(self, row):
        with self.transaction(write=False) as db:
            current = db.execute('SELECT state,attempt FROM tasks WHERE id=?', (row['id'],)).fetchone()
            return current is None or current['attempt'] != row['attempt'] or current['state'] != 'running'

    def publishing(self, row):
        with self.transaction(write=False) as db:
            current = db.execute('SELECT state,attempt FROM tasks WHERE id=?', (row['id'],)).fetchone()
            return current is not None and current['attempt'] == row['attempt'] and current['state'] in ('finishing', 'complete')

    def settle(self, row, state, code=None, message=None, *, details=None, private_code=None):
        with self.transaction() as db:
            changed = db.execute("UPDATE tasks SET state=?,stage=?,error_code=?,error_message=?,expires_at=COALESCE(expires_at,?) WHERE id=? AND attempt=? AND state IN ('running','cancelling','finishing')",
                (state, state, code, message, time.time() + self.diagnostic_seconds, row['id'], row['attempt'])).rowcount
            if changed:
                self.finish_record(db, self.records.conversion(db, row['id']), state,
                                   code=private_code or code or ('cancelled' if state == 'cancelled' else None), details=details)

    def finish_record(self, db, record, state, **values):
        self.write_record(db, record, state, **values)

    def read_manifest(self, db, row):
        managed = db.execute('SELECT * FROM managed_attempts WHERE task=? AND attempt=?',
                             (row['task'] if 'task' in row.keys() else row['id'], row['attempt'])).fetchone()
        if managed is None:
            raise ValueError('Unmanaged manifest')
        descriptor = self._attempt_descriptor(managed)
        result = None
        try:
            result = os.open('result', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            fd = os.open('manifest.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=result)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024**2:
                    raise ValueError('Invalid manifest')
                payload = stream.read(16 * 1024**2 + 1)
                if len(payload) > 16 * 1024**2:
                    raise ValueError('Invalid manifest')
                return json.loads(payload)
        finally:
            if result is not None:
                os.close(result)
            os.close(descriptor)

    def write_record(self, db, record, state=None, **values):
        # A logging failure must not turn a decided result into a conversion
        # failure. Keep a visible gap and refuse admissions until recovery.
        db.execute('SAVEPOINT finish_record')
        try:
            if state is None or state == 'finishing':
                if state == 'finishing' and record is not None:
                    values['output'] = self.read_manifest(db, {'task': record['task'],
                        'attempt': values.get('attempt', record['attempt'])})
                self.records.update(db, record, **({'status': 'finishing', 'stage': 'finishing'} if state else {}), **values)
            else:
                if (state == 'complete' and record is not None and record['operation'] in ('submit', 'retry')
                        and values.get('output') is None and json.loads(record['content'])['output'] is None):
                    values['output'] = self.read_manifest(db, record)
                self.records.finish(db, record, state, **values)
        except (sqlite3.Error, ValueError, OSError):
            db.execute('ROLLBACK TO finish_record')
            if record is not None:
                now = time.time() if state in ('complete', 'failed', 'cancelled', 'interrupted') else None
                db.execute("UPDATE processing_records SET status='record_failed',finished_at=COALESCE(finished_at,?),expires_at=COALESCE(expires_at,?) WHERE id=?",
                           (now, now + self.record_retention_seconds if now is not None else None, record['id']))
        finally:
            db.execute('RELEASE finish_record')

    def finishing(self, row, summary):
        with self.transaction() as db:
            now = time.time()
            changed = db.execute("UPDATE tasks SET state='finishing',stage='finishing',summary=?,completed_at=?,expires_at=? WHERE id=? AND attempt=? AND state='running'",
                (json.dumps(summary, ensure_ascii=False), now, now + self.retention_seconds, row['id'], row['attempt'])).rowcount
            if changed:
                # Preserve the actual web-delivery manifest before result expiry.
                self.finish_record(db, self.records.conversion(db, row['id']), 'finishing', attempt=row['attempt'])
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
