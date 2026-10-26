"""Private operator history, independent of delivery retention and task retries."""
from functools import lru_cache
import json
import math
import re
import secrets
import time

RETENTION_SECONDS = 7 * 86400
DEFAULT_BYTES = 256 * 1024**2
# The existing worker accepts manifests up to 16 MiB. Reserve separately for
# every admitted operation, including queued work, before doing any work.
MAX_RECORD_BYTES = 17 * 1024**2
DATABASE_OVERHEAD_BYTES = 64 * 1024**2
TERMINAL = ('complete', 'failed', 'cancelled', 'interrupted', 'rejected')
OPERATIONS = ('submit', 'retry', 'layout', 'rejection')


@lru_cache(maxsize=1)
def program():
    from .core import _program_identity
    return _program_identity()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def validate_records(db, check):
    """Validate private history independently of still-existing task identities."""
    for row in db.execute('SELECT * FROM processing_records'):
        check()
        if (not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', row['id'])
                or row['operation'] not in OPERATIONS
                or row['status'] not in (*TERMINAL, 'queued', 'running', 'cancelling', 'finishing', 'record_failed')
                or row['reserved'] not in (0, MAX_RECORD_BYTES)
                or not isinstance(row['content'], str)
                or not 0 < row['bytes'] <= MAX_RECORD_BYTES
                or row['bytes'] != len(row['content'].encode('utf-8'))):
            raise ValueError('Invalid record')
        for field in ('task', 'attempt'):
            if row[field] is not None and not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', row[field]):
                raise ValueError('Invalid record identity')
        for field in ('created_at', 'started_at', 'finished_at', 'expires_at'):
            value = row[field]
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError('Invalid record time')
        finished = row['status'] in TERMINAL or (row['status'] == 'record_failed' and row['finished_at'] is not None)
        if (row['created_at'] is None or finished != (row['finished_at'] is not None)
                or finished != (row['expires_at'] is not None)
                or (finished and (row['expires_at'] <= row['finished_at']
                    or (row['status'] != 'record_failed' and row['reserved'] != 0)))
                or (not finished and row['reserved'] != MAX_RECORD_BYTES)):
            raise ValueError('Invalid record lifecycle')
        content = json.loads(row['content'])
        if (set(content) != {'schema_version', 'input', 'settings', 'program', 'error', 'output', 'description_policy'}
                or content['schema_version'] != 1 or not isinstance(content['program'], dict)):
            raise ValueError('Invalid record content')


def iter_records(db, *, task=None, status=None, since=None, until=None, limit=100):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError('Invalid record limit')
    clauses, values = ['(expires_at IS NULL OR expires_at>?)'], [time.time()]
    if task is not None:
        if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', task):
            raise ValueError('Invalid task')
        clauses.append('task=?')
        values.append(task)
    if status is not None:
        if status not in (*TERMINAL, 'queued', 'running', 'cancelling', 'finishing', 'record_failed'):
            raise ValueError('Invalid status')
        clauses.append('status=?')
        values.append(status)
    for key, value, operator in (('since', since, '>='), ('until', until, '<')):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Invalid ' + key)
            clauses.append('created_at' + operator + '?')
            values.append(value)
    values.append(limit)
    rows = db.execute('SELECT * FROM processing_records WHERE ' + ' AND '.join(clauses)
                      + ' ORDER BY created_at DESC,id DESC LIMIT ?', values)
    for row in rows:
        content = json.loads(row['content'])
        content.update({key: row[key] for key in ('id', 'task', 'attempt', 'operation', 'status',
                       'stage', 'created_at', 'started_at', 'finished_at', 'expires_at')})
        yield content


class Records:
    def __init__(self, jobs):
        self.jobs = jobs

    def query(self, **filters):
        with self.jobs.transaction(write=False) as db:
            return list(iter_records(db, **filters))

    def cleanup(self, db, now):
        db.execute('DELETE FROM processing_records WHERE expires_at<=?', (now,))

    def admit(self, db, reserve=MAX_RECORD_BYTES):
        from .jobs import JobError
        self.cleanup(db, time.time())
        if db.execute("SELECT 1 FROM processing_records WHERE status='record_failed' LIMIT 1").fetchone():
            raise JobError('records_unavailable', '服务暂不可用，请稍后重试。', 503)
        used = db.execute('SELECT COALESCE(SUM(MAX(bytes,reserved)),0) FROM processing_records').fetchone()[0]
        if used + reserve > self.jobs.record_bytes:
            raise JobError('records_full', '服务暂不可用，请稍后重试。', 503)
        self.jobs.capacity(db=db, log_reserve=reserve)

    def disk_reservation(self, db, extra=0):
        pending = db.execute('SELECT COALESCE(SUM(MAX(reserved-bytes,0)),0) FROM processing_records').fetchone()[0]
        # Count future pages twice (database plus rollback journal), reserve a
        # journal for the existing DB, and leave explicit page/index headroom.
        return 2 * (pending + extra) + self.jobs.database.stat().st_size + DATABASE_OVERHEAD_BYTES

    def start(self, db, operation, *, task=None, source=None, settings=None):
        self.admit(db)
        now = time.time()
        record = secrets.token_urlsafe(24)
        content = encode(dict(schema_version=1, input={'url': source}, settings=settings,
                              program=program(), error=None, output=None, description_policy=None))
        db.execute('INSERT INTO processing_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (record, task, None, operation, 'queued' if operation != 'layout' else 'running',
                    'queued' if operation != 'layout' else 'layout', now,
                    now if operation == 'layout' else None, None, None, MAX_RECORD_BYTES,
                    len(content.encode('utf-8')), content))
        return record

    def conversion(self, db, task):
        return db.execute("SELECT * FROM processing_records WHERE task=? AND operation IN ('submit','retry') AND (finished_at IS NULL OR status='record_failed')",
                          (task,)).fetchone()

    def update(self, db, record, *, status=None, stage=None, attempt=None, settings=None, output=None):
        if record is None:
            return
        content = json.loads(record['content'])
        if settings is not None:
            content['settings'] = settings
        if output is not None:
            content['output'] = output
            origin = output.get('source', {})
            content['input']['resolved_url'] = origin.get('url')
            content['description_policy'] = origin.get('description_policy')
            content['program'] = output.get('program', content['program'])
            if 'resources' in output:
                content['settings'] = {**(content['settings'] or {}), 'limits': output['resources'].get('limits')}
        payload = encode(content)
        if len(payload.encode('utf-8')) > record['reserved']:
            raise ValueError('Record exceeds reserved budget')
        now = time.time()
        db.execute('UPDATE processing_records SET status=?,stage=?,attempt=COALESCE(?,attempt),started_at=COALESCE(started_at,?),content=?,bytes=? WHERE id=? AND finished_at IS NULL',
                   (status or record['status'], stage or record['stage'], attempt,
                    now if status == 'running' else None, payload, len(payload.encode('utf-8')), record['id']))

    def finish(self, db, record, status, *, code=None, output=None, details=None):
        if record is None or (record['finished_at'] is not None and record['status'] != 'record_failed'):
            return
        content = json.loads(record['content'])
        if code:
            # Store controlled categories, never arbitrary exception strings.
            code = code if re.fullmatch(r'[a-z][a-z0-9_]{0,79}', code) else 'operation_failed'
            content['error'] = {'code': code, 'stage': record['stage']}
        if status != 'complete' or output is not None:
            content['output'] = output
        if details:
            if details.get('conversion_failure'):
                content['error']['conversion_failure'] = details['conversion_failure']
            content['description_policy'] = details.get('description_policy')
            if details.get('url'):
                from .public_video import video_origin
                content['input']['resolved_url'] = video_origin(details['url'])['url']
        if output and isinstance(output, dict) and 'source' in output:
            origin = output['source']
            content['input']['resolved_url'] = origin.get('url')
            content['description_policy'] = origin.get('description_policy')
            content['program'] = output.get('program', content['program'])
            if 'resources' in output:
                content['settings'] = {**(content['settings'] or {}), 'limits': output['resources'].get('limits')}
        payload = encode(content)
        size = len(payload.encode('utf-8'))
        if size > record['reserved']:
            raise ValueError('Record exceeds reserved budget')
        now = record['finished_at'] if record['finished_at'] is not None else time.time()
        db.execute("UPDATE processing_records SET status=?,stage=?,finished_at=?,expires_at=?,reserved=0,content=?,bytes=? WHERE id=? AND (finished_at IS NULL OR status='record_failed')",
                   (status, status, now, record['expires_at'] or now + self.jobs.record_retention_seconds, payload, size, record['id']))

    def reject(self, code):
        # Best effort at the HTTP boundary: failures must not recursively log.
        from .jobs import JobError
        import sqlite3
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', code):
            code = 'invalid_request'
        try:
            with self.jobs.transaction() as db:
                self.admit(db, 4096)
                now = time.time()
                content = encode(dict(schema_version=1, input=None, settings=None, program=program(),
                                      error={'code': code, 'stage': 'admission'}, output=None,
                                      description_policy=None))
                db.execute('INSERT INTO processing_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (secrets.token_urlsafe(24), None, None, 'rejection', 'rejected', 'rejected',
                            now, None, now, now + self.jobs.record_retention_seconds, 0,
                            len(content.encode('utf-8')), content))
        except (JobError, sqlite3.Error, OSError, ValueError):
            return

    def recover(self):
        """Repair terminal gaps and abandoned layouts without refreshing deadlines."""
        from .jobs import JobError
        from .relayout import slot
        with self.jobs.transaction() as db:
            identities = list(db.execute("SELECT id FROM processing_records WHERE status='record_failed' AND operation IN ('submit','retry')"))
            for identity in identities:
                record = db.execute('SELECT * FROM processing_records WHERE id=?', (identity[0],)).fetchone()
                current = db.execute('SELECT * FROM tasks WHERE id=?', (record['task'],)).fetchone()
                if current is not None and current['state'] in ('complete', 'failed', 'cancelled', 'interrupted'):
                    self.jobs.finish_record(db, record, current['state'], code=current['error_code'])
        try:
            with slot(self.jobs):
                with self.jobs.transaction() as db:
                    identities = list(db.execute("SELECT id FROM processing_records WHERE operation='layout' AND (finished_at IS NULL OR status='record_failed')"))
                    for identity in identities:
                        record = db.execute('SELECT * FROM processing_records WHERE id=?', (identity[0],)).fetchone()
                        self.jobs.finish_record(db, record, 'interrupted', code='interrupted')
        except JobError as error:
            if error.code != 'service_busy':
                raise


def main(argv=None):
    import sqlite3
    from .arguments import PublicParser
    from .maintenance import Tree, connect, Budget, MaintenanceError
    from .schema import validate_schema
    parser = PublicParser(prog='drum-score-records', description='查询私有整理记录，逐行输出 JSON；不创建数据目录。')
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--task')
    parser.add_argument('--status')
    parser.add_argument('--since', type=float, help='接收时间下界，Unix秒，含边界')
    parser.add_argument('--until', type=float, help='接收时间上界，Unix秒，不含边界')
    parser.add_argument('--limit', type=int, default=100, help='最新记录数，1至1000，默认100')
    args = parser.parse_args(argv)
    tree = None
    try:
        tree = Tree(args.data_root)
        budget = Budget(60, 1024**3, 100000, 1)
        db = connect(tree, budget)
        try:
            validate_schema(db)
            db.execute('BEGIN')
            # Stream each record; never accumulate hundreds of manifests in RAM.
            for record in iter_records(db, task=args.task, status=args.status, since=args.since,
                                       until=args.until, limit=args.limit):
                budget.check()
                print(encode(record))
        finally:
            db.close()
        return 0
    except (OSError, ValueError, sqlite3.Error, MaintenanceError):
        print('{"error":{"code":"records_unavailable","message":"无法查询整理记录。"}}', file=__import__('sys').stderr)
        return 2
    finally:
        if tree is not None:
            tree.close()


if __name__ == '__main__':
    raise SystemExit(main())
