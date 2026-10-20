"""Bounded recoverable native frames; promoted evidence is never evicted."""
from pathlib import Path
import math
import uuid
import score_task as task_state
from video_seek import VideoReader, ConversionError

DEFAULT_ENTRIES = 64
DEFAULT_BYTES = 256 * 1024 * 1024
DEFINITIONS = {
    'hits': 'native requests served from verified candidates or promoted captures',
    'misses': 'native requests requiring decoding, including missing/corrupt/evicted candidates',
    'promotions': 'new source captures copied byte-for-byte from native candidates',
    'evictions': 'unpromoted candidate files removed to satisfy configured limits',
    'actual_decodes': 'successful native read_record invocations',
    'duplicate_decodes': 'successful decodes returning a source hash/PTS/time_base previously decoded',
}

def state(record):
    cache = record.setdefault('native_cache', {'max_entries': DEFAULT_ENTRIES,
        'max_bytes': DEFAULT_BYTES, 'entries': [], 'decoded_positions': [], 'events': []})
    for key in DEFINITIONS:
        cache.setdefault(key, 0)
    return cache

def report(record):
    cache = state(record)
    return {**{k: cache[k] for k in DEFINITIONS}, 'definitions': DEFINITIONS,
        'max_entries': cache['max_entries'], 'max_bytes': cache['max_bytes'],
        'retained_entries': len(cache['entries']),
        'retained_bytes': sum(e['bytes'] for e in cache['entries']),
        'events': cache['events']}


def evict(task, record):
    cache = state(record)
    while (len(cache['entries']) > cache['max_entries'] or
           sum(e['bytes'] for e in cache['entries']) > cache['max_bytes']):
        entry = cache['entries'].pop(0)
        path = task_state.write_path(task, entry['path'])
        if path.is_file():
            path.unlink()
        cache['evictions'] += 1
        cache['events'].append({'reason': 'evicted', 'candidate': entry['id'], 'seconds': entry['requested_seconds']})

def native(task, record, seconds):
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or
        not math.isfinite(seconds) or not 0 <= seconds < record['source']['duration']):
        raise task_state.ReconstructionError('取帧时间必须在视频范围内。')
    cache = state(record)
    reason = 'not_cached'
    for shot in record['captures']:
        if seconds in shot.get('requested_aliases', [shot['requested_seconds']]):
            cache['hits'] += 1
            return shot
    for entry in list(cache['entries']):
        if seconds not in entry['requested_aliases']:
            continue
        try:
            task_state.artifact(task, entry)
        except task_state.ReconstructionError:
            reason = 'missing' if not (Path(task) / entry['path']).exists() else 'corrupt'
            cache['entries'].remove(entry)
            break
        cache['entries'].remove(entry)
        cache['entries'].append(entry)
        cache['hits'] += 1
        return entry
    if reason == 'not_cached' and any(e.get('seconds') == seconds for e in cache['events']):
        reason = 'evicted'
    cache['misses'] += 1
    cache['events'].append({'reason': reason, 'seconds': seconds})
    reader = VideoReader(record['source']['path'], record['source'], record['metrics'])
    try:
        pts, picture = reader.read_record(seconds)
    except ConversionError as error:
        record['last_decode_error'] = error.code
        raise
    finally:
        reader.close()
        task_state.save(task, record)
    position = [record['source']['sha256'], pts['pts'], pts['time_base']]
    cache['actual_decodes'] += 1
    if position in cache['decoded_positions']:
        cache['duplicate_decodes'] += 1
    else:
        cache['decoded_positions'].append(position)
    # Distinct requested times can resolve to one actual native frame.
    for entry in cache['entries']:
        if entry['pts'] == pts['pts'] and entry['time_base'] == pts['time_base']:
            try:
                task_state.artifact(task, entry)
            except task_state.ReconstructionError:
                continue
            entry['requested_aliases'].append(seconds)
            picture.close()
            return entry
    directory = task_state.write_path(task, 'native-cache')
    directory.mkdir(exist_ok=True)
    identifier = 'native-' + uuid.uuid4().hex
    path = task_state.write_path(task, Path('native-cache') / (identifier + '.png'))
    picture.save(path)
    entry = {'id': identifier, 'path': str(path.relative_to(task)),
        'sha256': task_state.digest(path), 'source_sha256': record['source']['sha256'],
        'requested_seconds': seconds, 'requested_aliases': [seconds], **pts,
        'width': picture.width, 'height': picture.height, 'bytes': path.stat().st_size}
    picture.close()
    cache['entries'].append(entry)
    return entry

def capture(task, seconds, expected=None):
    record = task_state.load(task)
    # Preserve the existing public directory protection before looking in cache.
    identifier = f'capture-{len(record["captures"])+1:04d}'
    path = task_state.write_path(task, Path('captures') / (identifier + '.png'))
    entry = native(task, record, seconds)
    if expected is not None and any(entry[key] != expected[key] for key in ('pts', 'time_base')):
        evict(task, record)
        task_state.save(task, record)
        raise task_state.ReconstructionError('重新取得的帧与导航实际 PTS 不一致；请重新导航确认。')
    if entry in record['captures']:
        task_state.save(task, record)
        return entry
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        # A previous interrupted publication may leave an unreferenced file.
        # Keep it intact and publish new evidence at a unique path.
        path = task_state.write_path(task, Path('captures') / (identifier + '-' + uuid.uuid4().hex + '.png'))
    path.write_bytes(task_state.artifact(task, entry).read_bytes())
    shot = {**entry, 'id': identifier, 'path': str(path.relative_to(task)),
            'requested_seconds': seconds, 'native_candidate': entry['id']}
    record['captures'].append(shot)
    state(record)['promotions'] += 1
    record['metrics']['native_retained'] = len(record['captures'])
    evict(task, record)
    task_state.save(task, record)
    return shot
