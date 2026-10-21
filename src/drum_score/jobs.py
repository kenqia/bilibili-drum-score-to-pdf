"""Short SQLite transactions for capability-owned anonymous tasks."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import hmac
import json
import os
import secrets
import sqlite3
import time
import re
import shutil
import stat

from public_video import InputError, video_origin


UNFINISHED = ('queued', 'running', 'cancelling', 'finishing')
ACTIVE = ('running', 'cancelling', 'finishing')


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
    def __init__(self, root, *, retention_seconds=86400):
        self.root = controlled_root(root)
        self.retention_seconds = retention_seconds
        self.database = self.root / 'tasks.sqlite3'
        if self.database.is_symlink():
            raise ValueError('任务数据库不能是符号链接。')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, capability_hash TEXT NOT NULL, source TEXT NOT NULL,
                  ip_key TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL,
                  created_at REAL NOT NULL, queued_at REAL NOT NULL,
                  attempt TEXT, completed_at REAL, expires_at REAL,
                  summary TEXT, error_code TEXT, error_message TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS unfinished_ip ON tasks(ip_key)
                  WHERE state IN ('queued','running','cancelling','finishing');
                CREATE UNIQUE INDEX IF NOT EXISTS single_active ON tasks((1))
                  WHERE state IN ('running','cancelling','finishing');
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.database, timeout=1, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.OperationalError:
            db.rollback()
            raise JobError('service_busy', '服务正在处理其他请求，请稍后重试。', 503) from None
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

    def enqueue(self, url, ip):
        try:
            source = video_origin(url)
        except (InputError, TypeError, AttributeError):
            raise JobError('invalid_bilibili_url', '请提供公开 HTTPS B站 BV 链接，分 P 使用单个正整数 p。', 422) from None
        task, capability = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        now = time.time()
        with self.transaction() as db:
            ip_key = sha256(ip.encode()).hexdigest()
            self.admit(db, ip_key)
            db.execute('INSERT INTO tasks(id,capability_hash,source,ip_key,state,stage,created_at,queued_at) VALUES(?,?,?,?,?,?,?,?)',
                (task, sha256(capability.encode()).hexdigest(), json.dumps(source), ip_key, 'queued', 'queued', now, now))
        return {'id': task, 'capability': capability, 'link': f'/task/{task}#{capability}'}

    def view(self, task, capability):
        with self.transaction() as db:
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
            db.execute('UPDATE tasks SET state=?,stage=? WHERE id=?', (state, state if state in ('cancelled', 'cancelling') else row['stage'], task))
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

    def discard(self, row):
        if row['attempt']:
            path = self.attempt_root(row['id'], row['attempt'])
            if path.exists():
                shutil.rmtree(path)

    def claim(self):
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM tasks WHERE state IN ('running','cancelling','finishing')").fetchone():
                return None
            row = db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY queued_at,id LIMIT 1").fetchone()
            if row is None:
                return None
            attempt = secrets.token_urlsafe(24)
            db.execute("UPDATE tasks SET state='running',stage='starting',attempt=? WHERE id=?", (attempt, row['id']))
            return dict(db.execute('SELECT * FROM tasks WHERE id=?', (row['id'],)).fetchone())

    def stage(self, row, stage):
        with self.transaction() as db:
            db.execute("UPDATE tasks SET stage=? WHERE id=? AND attempt=? AND state='running'",
                (stage, row['id'], row['attempt']))

    def cancelled(self, row):
        with self.transaction() as db:
            current = db.execute('SELECT state,attempt FROM tasks WHERE id=?', (row['id'],)).fetchone()
            return current is None or current['attempt'] != row['attempt'] or current['state'] != 'running'

    def publishing(self, row):
        with self.transaction() as db:
            current = db.execute('SELECT state,attempt FROM tasks WHERE id=?', (row['id'],)).fetchone()
            return current is not None and current['attempt'] == row['attempt'] and current['state'] in ('finishing', 'complete')

    def settle(self, row, state, code=None, message=None):
        with self.transaction() as db:
            db.execute("UPDATE tasks SET state=?,stage=?,error_code=?,error_message=? WHERE id=? AND attempt=? AND state IN ('running','cancelling','finishing')",
                (state, state, code, message, row['id'], row['attempt']))

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
            path = self.attempt_root(task, row['attempt']) / 'result'
            descriptor = None
            try:
                descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                for component in path.relative_to(self.root).parts:
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
                stream = os.open(reference['path'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                metadata = os.fstat(stream)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != reference['bytes']:
                    os.close(stream)
                    raise OSError
                return stream, metadata.st_size
            except OSError:
                raise JobError('result_unavailable', '结果文件不可用，请重新提交。', 409) from None
            finally:
                if descriptor is not None:
                    os.close(descriptor)
