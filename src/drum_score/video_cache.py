"""Single-worker shared source acquisition with bounded, separately owned media cache."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import stat
import threading
import time

from .core import ConversionError, ResourceBudget
from . import supervision


def inventory(root):
    return [[p.relative_to(root).as_posix(), s.st_dev, s.st_ino, s.st_ctime_ns]
            for p in root.rglob('*') if stat.S_ISREG((s := p.lstat()).st_mode)]


class VideoCache:
    def __init__(self, jobs, descriptor, stopping, limits=None):
        self.jobs, self.descriptor, self.stopping = jobs, os.dup(descriptor), stopping
        self.limits = ResourceBudget(limits).limits
        self.lock = threading.RLock()
        self.active = {}
        self.pool = ThreadPoolExecutor(max_workers=8)
        cache = jobs.root / 'cache'
        if cache.is_symlink():
            raise ValueError('Unsafe cache root')
        cache.mkdir(mode=0o700, exist_ok=True)
        self.cleanup(recover=True)

    def close(self):
        try:
            self.pool.shutdown(wait=True)
        finally:
            os.close(self.descriptor)

    def rows(self):
        with self.jobs.transaction(write=False) as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM video_cache')]
        for row in rows:
            if (not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', row['root_name'])
                or not re.fullmatch(r'[0-9a-f]{64}(?:-[A-Za-z0-9_-]{20,64})?', row['key'])
                or row['storage'] not in ('cache','attempts')
                or row['state'] not in ('filling','ready','unavailable')
                or type(row['reservation_bytes']) is not int or row['reservation_bytes'] < 0):
                raise ValueError('Invalid cache registration')
            entries = json.loads(row['files'])
            if not isinstance(entries,list) or any(not isinstance(e,list) or len(e)!=4
                or e[0] not in ('payload/video.mp4','payload/manifest.json')
                or any(type(v) is not int or v<0 for v in e[1:]) for e in entries):
                raise ValueError('Invalid cache inventory')
        return rows

    def remove(self, row):
        # Reuse the exact no-follow managed-file deletion protocol. There is no
        # task row for a cache entry, so the relative root is supplied explicitly.
        root = self.jobs.root / row['storage'] / row['root_name']
        from .managed_cache_files import remove
        removed = remove(self.jobs.root, root, row, json.loads(row['files']))
        if removed:
            with self.jobs.transaction() as db:
                db.execute('DELETE FROM video_cache WHERE key=?', (row['key'],))
        return removed

    def cleanup(self, *, recover=False):
        with self.lock:
            for row in self.rows():
                if any(row['key'] == k or row['key'].startswith(k + '-') for k in self.active):
                    continue
                if recover and row['state'] == 'filling':
                    # The worker lease proves every prior guardian has stopped.
                    with self.jobs.transaction() as db:
                        db.execute("UPDATE video_cache SET state='unavailable',reservation_bytes=0 WHERE key=?", (row['key'],))
                if row['state'] != 'ready' or row['expires_at'] <= time.time():
                    self.remove(row)

    def hit(self, row):
        if row['state'] != 'ready' or row['expires_at'] <= time.time():
            return None
        root = self.jobs.root / row['storage'] / row['root_name']
        try:
            from .managed_cache_files import open_media
            with open_media(self.jobs.root, root, row) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
                    return None
            origin = json.loads(row['source'])
            origin['cache'] = {'status': 'hit', 'published_at': row['published_at'], 'expires_at': row['expires_at']}
            return {'path': str(root / 'payload' / 'video.mp4'), 'origin': origin, 'sha256': row['sha256']}
        except (OSError, ValueError, KeyError):
            return None

    def allocate(self, key, inspection):
        reservation = min(int(self.limits['input_bytes']), int(inspection['version']['bytes']) if inspection.get('version') else int(self.limits['input_bytes'])) + 1024**2
        rows = self.rows()
        def usage():
            total = 0
            for p in (self.jobs.root / 'cache').rglob('*'):
                try:
                    s = p.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(s.st_mode):
                    total += s.st_size
            return total + sum(r['reservation_bytes'] + r['media_bytes'] for r in self.rows() if r['storage'] == 'cache')
        # Reserve the whole bounded transfer before creating a cache media writer.
        # No second media copy is made by the preparation operation.
        for row in sorted(rows, key=lambda r: (r['expires_at'] or 0, r['published_at'] or 0)):
            if usage() + reservation <= self.jobs.cache_bytes:
                break
            if not any(row['key'] == k or row['key'].startswith(k + '-') for k in self.active):
                self.remove(row)
        cached = not inspection.get('_skip_cache') and bool(inspection.get('version')) and usage() + reservation <= self.jobs.cache_bytes and not any(r['key'] == key for r in self.rows())
        name = secrets.token_urlsafe(24)
        root = self.jobs.root / ('cache' if cached else 'attempts') / name
        root.mkdir(mode=0o700, parents=True)
        info = root.stat()
        row_key = key if cached else key + '-' + name
        safe = {**inspection['origin'], 'cid': inspection['backend_details']['cid'], 'version': inspection['version']}
        try:
            with self.jobs.transaction() as db:
                db.execute('INSERT INTO video_cache(key,source,state,reservation_bytes,root_name,storage,device,inode) VALUES(?,?,?,?,?,?,?,?)',
                           (row_key, json.dumps(safe), 'filling', reservation, name, 'cache' if cached else 'attempts', info.st_dev, info.st_ino))
                self.jobs.capacity(db=db)
        except BaseException:
            try:
                root.rmdir()
            except OSError:
                pass
            raise
        return root, cached, row_key

    def fetch(self, key, inspection, event):
        root = None
        cached = False
        try:
            with self.lock:
                root, cached, row_key = self.allocate(key, inspection)
            def cancel():
                self.jobs.capacity()
                return event.is_set() or self.stopping.is_set()
            # Independent tree and lease; no task attempt owns this acquisition.
            def register(complete):
                entries = [['payload/' + p.name, s.st_dev, s.st_ino, s.st_ctime_ns]
                    for p in complete.iterdir() if stat.S_ISREG((s := p.lstat()).st_mode)]
                with self.jobs.transaction() as db:
                    db.execute('UPDATE video_cache SET files=? WHERE key=?', (json.dumps(entries), row_key))
            with supervision.guardian_lease(self.descriptor):
                result = supervision.run(inspection['origin']['url'], root / 'payload', operation='fetch', inspection=inspection,
                    limits={**self.limits, 'input_bytes': min(self.limits['input_bytes'], inspection['version']['bytes']) if inspection.get('version') else self.limits['input_bytes'], 'temp_bytes': self.jobs.job_temp_bytes}, cancel=cancel, register=register)
            info = inventory(root)
            origin = result['origin']
            if cached:
                now = time.time()
                origin['version'] = inspection['version']
                with self.jobs.transaction() as db:
                    db.execute("UPDATE video_cache SET state='ready',reservation_bytes=0,media_bytes=?,sha256=?,full_duration=?,width=?,height=?,published_at=?,expires_at=?,source=?,files=? WHERE key=?",
                        (result['bytes'], result['sha256'], result['metadata']['duration'], result['metadata']['width'], result['metadata']['height'], now,
                         now+self.jobs.cache_retention_seconds, json.dumps(origin), json.dumps(info), row_key))
                origin['cache'] = {'status': 'fill', 'published_at': now, 'expires_at': now+self.jobs.cache_retention_seconds}
            else:
                with self.jobs.transaction() as db:
                    db.execute("UPDATE video_cache SET state='unavailable',reservation_bytes=0,media_bytes=?,files=? WHERE key=?", (result['bytes'], json.dumps(info), row_key))
                origin['cache'] = {'status': 'bypass_capacity' if inspection.get('version') else 'bypass_version', 'published_at': None, 'expires_at': None}
            return {'path': str(root / 'payload' / 'video.mp4'), 'origin': origin, 'sha256': result['sha256'], '_temporary': not cached, '_root': str(root), '_files': info, '_row_key': row_key, '_fetch_resources': result['resources']}
        except BaseException:
            if root is not None:
                with self.jobs.transaction() as db:
                    db.execute("UPDATE video_cache SET state='unavailable',reservation_bytes=0 WHERE key=?", (row_key,))
            raise

    @contextmanager
    def source(self, url, attempt, cancel, deadline, progress=lambda stage: None):
        progress('preflight')
        preparation_started = time.monotonic()
        inspection = supervision.run(url, attempt / '.inspection', operation='inspect', limits={**self.limits, 'wall_seconds': max(.001, deadline-time.monotonic()), 'temp_bytes': self.jobs.job_temp_bytes}, cancel=cancel)
        inspection_seconds = time.monotonic()-preparation_started
        version = inspection.get('version')
        if version is None:
            yield {'bypass': True, '_preparation': {'status': 'bypass_version', 'inspection_seconds': inspection_seconds, 'wait_seconds': 0, 'acquisition_resources': None}}
            return
        key = hashlib.sha256(json.dumps([inspection['origin'], inspection['backend_details']['cid'], inspection['info']['duration'], version], sort_keys=True).encode()).hexdigest()
        started = time.monotonic()
        record = None
        result = None
        with self.lock:
            # Existing published state is usable only after fresh source preflight.
            row = next((r for r in self.rows() if r['key'] == key), None) if version else None
            held_invalid = False
            if row:
                result = self.hit(row)
                if result is None:
                    if key in self.active:
                        # A filling row belongs to the shared future; new waiters
                        # must join it. Only an invalid published entry can be
                        # pinned by an existing converter and require a bypass.
                        held_invalid = row['state'] == 'ready'
                    else:
                        self.remove(row)
            if held_invalid:
                # A previous converter still owns the registered bytes. A new
                # acquisition cannot reuse its stale future or erase its quota.
                key = hashlib.sha256((key + secrets.token_urlsafe(24)).encode()).hexdigest()
                inspection = {**inspection, '_skip_cache': True}
            if key not in self.active:
                self.active[key] = {'users': 0, 'cancel': threading.Event(), 'future': None}
            record = self.active[key]
            record['users'] += 1
            coalesced = result is None and record['future'] is not None
            if result is None and record['future'] is None:
                record['future'] = self.pool.submit(self.fetch, key, inspection, record['cancel'])
                record['future'].add_done_callback(lambda future: self.reap(key))
        try:
            progress('cache_hit' if result is not None else 'source_wait')
            while result is None:
                if cancel() or time.monotonic() >= deadline:
                    raise ConversionError('cancelled' if cancel() else 'resource_limit', '来源等待已取消或超过总处理时限。')
                if record['future'].done():
                    try:
                        result = dict(record['future'].result())
                    except ConversionError as error:
                        if error.code not in ('http_unavailable','undecodable_video','unsupported_stream','network_timeout','cache_resource_changed'):
                            raise
                        # The preferred representation failed. Preserve the existing
                        # bounded format/backup fallback without caching its bytes
                        # under a different representation's version identity.
                        yield {'bypass': True, 'bypass_reason': 'bypass_transfer', '_preparation': {
                            'status': 'bypass_transfer', 'inspection_seconds': inspection_seconds,
                            'wait_seconds': time.monotonic()-started, 'acquisition_resources': None}}
                        return
                else:
                    time.sleep(.02)
            result = dict(result)
            policy = inspection['backend_details'].get('description_policy')
            if policy is not None:
                result['origin'] = {**result['origin'], 'description_policy': policy}
            if coalesced:
                result['origin'] = {**result['origin'], 'cache': {**result['origin']['cache'], 'status': 'coalesced'}}
            result['origin'] = {**result['origin'], 'cache': {**result['origin']['cache'], 'wait_seconds': time.monotonic()-started}}
            result['_preparation'] = {'status': result['origin']['cache']['status'], 'inspection_seconds': inspection_seconds, 'wait_seconds': time.monotonic()-started, 'acquisition_resources': result.get('_fetch_resources')}
            from .managed_cache_files import open_media
            row = next(r for r in self.rows() if r['key'] == result.get('_row_key', key))
            with open_media(self.jobs.root, Path(result['path']).parent.parent, row) as stream:
                result['_descriptor'] = stream.fileno()
                yield result
        finally:
            pending = None
            with self.lock:
                record['users'] -= 1
                if record['users'] == 0:
                    record['cancel'].set()
                    pending = record['future']
                    self.reap(key)
            if pending is not None:
                try:
                    pending.result()  # Last owner settles only after tree/guardian cleanup.
                except BaseException:
                    pass
                self.reap(key)

    def reap(self, key):
        with self.lock:
            record = self.active.get(key)
            if not record or record['users'] or (record['future'] and not record['future'].done()):
                return
            self.active.pop(key, None)
            if record['future']:
                try:
                    result = record['future'].result()
                except BaseException:
                    self.cleanup()
                    return
                if result.get('_temporary'):
                    row = next((r for r in self.rows() if r['key'] == result['_row_key']), None)
                    if row:
                        self.remove(row)
