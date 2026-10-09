"""Low resolution navigation and durable, bounded requests for native evidence."""
import math
import subprocess
import time
import numpy as np
from video_seek import ConversionError

LIMITS = dict(requests=8, native_frames=96, requested_frames=32, decode_seconds=600)


def plan(source, metadata):
    began = time.monotonic()
    duration = metadata['duration']
    sampling = dict(version=1, limits=dict(LIMITS), used=dict(requests=0, native_frames=0, requested_frames=0, decode_seconds=0),
                    request_ids=[], thumbnail_checks=0, thumbnail_elapsed=0, navigation_only=True,
                    unresolved=[])
    # The existing two-second protocol fixtures keep their three observations.
    if duration <= 3:
        return [0, duration / 2, None], sampling
    cadence = duration / 255
    command = ['ffmpeg', '-v', 'error', '-nostdin', '-threads', '2', '-i', str(source), '-vf',
               f'fps=1/{cadence},scale=160:90', '-frames:v', '256', '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    try:
        process = subprocess.run(command, capture_output=True, check=True, timeout=90)
        raw = np.frombuffer(process.stdout, dtype=np.uint8)
        frames = raw.reshape((-1, 90, 160))
    except (subprocess.SubprocessError, ValueError, OSError):
        raise ConversionError('decode_failed', '无法生成有界低分辨率导航。') from None
    sampling['thumbnail_checks'] = len(frames)
    sampling['thumbnail_elapsed'] = time.monotonic() - began
    # Small changes are retained; pixels only nominate times, never row identities.
    changes = [(float(np.abs(b.astype(float) - a).mean()), index * cadence)
               for index, (a, b) in enumerate(zip(frames, frames[1:]), 1)]
    selected = {0, duration / 2}
    # Distribute navigation across the whole source before refining strongest changes.
    for segment in range(16):
        local = [(m,t) for m,t in changes if segment * duration / 16 <= t < (segment+1) * duration / 16]
        if local:
            magnitude, timestamp = max(local)
            if magnitude >= 0.08:
                selected.update([max(0,timestamp-cadence), min(duration-cadence/2,timestamp)])
    for magnitude, timestamp in sorted(changes, reverse=True):
        if magnitude < 0.08 or len(selected) >= 46:
            continue
        selected.update([max(0, timestamp - cadence), min(duration - cadence / 2, timestamp)])
    selected = sorted(selected)
    if len(selected) >= 46 and any(m >= 0.08 for m, _ in changes):
        sampling['unresolved'].append('Navigation limit reached; review gaps and request local evidence.')
    return selected + [None], sampling


def check_request(request, state, observation):
    fields = {'schema_version', 'task_id', 'observation_sha256', 'observation_version', 'request_id', 'issue', 'timestamps'}
    if not isinstance(request, dict) or set(request) != fields or type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ConversionError('invalid_request', '补采样请求字段或版本非法。')
    if request['task_id'] != state['task_id'] or request['observation_sha256'] != state['observation_sha256'] or type(request['observation_version']) is not int or request['observation_version'] != state.get('observation_version', 1):
        raise ConversionError('invalid_request', '补采样请求不属于当前观察包。')
    issue = request['issue']
    if not isinstance(issue, dict) or set(issue) != {'reason', 'start', 'end'} or not isinstance(issue['reason'], str) or not issue['reason'].strip() or len(issue['reason']) > 2000:
        raise ConversionError('invalid_request', '需要明确的疑点与局部时间范围。')
    def number(value):
        # Reject integers outside finite float conversion before geometry/time arithmetic.
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    start, end = issue['start'], issue['end']
    if not number(start) or not number(end) or not 0 <= start < end <= observation['source']['duration'] or end-start > 30:
        raise ConversionError('invalid_request', '补采样范围非法或超过 30 秒。')
    timestamps = request['timestamps']
    if not isinstance(timestamps, list) or not 1 <= len(timestamps) <= 8 or any(not number(t) or not start <= t <= end or t >= observation['source']['duration'] for t in timestamps) or len(set(timestamps)) != len(timestamps):
        raise ConversionError('invalid_request', '需要 1 至 8 个范围内不同的有限时间。')
    existing = {f['requested_timestamp'] for f in observation['frames']}
    if any(t in existing for t in timestamps):
        raise ConversionError('invalid_request', '请求重复已采样时间，不能空转。')
    sampling = observation['sampling']
    identifier = request['request_id']
    if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 200 or identifier in sampling['request_ids']:
        raise ConversionError('invalid_request', '补采样请求 ID 非法或重复。')
    used, limits = sampling['used'], sampling['limits']
    if limits != LIMITS or set(used) != set(LIMITS) or any(not number(value) or value < 0 for value in used.values()) or any(type(used[k]) is not int for k in ('requests','native_frames','requested_frames')):
        raise ConversionError('invalid_request', '采样预算记录非法，不能放宽脚本资源上限。')
    if used['requests'] >= limits['requests'] or used['requested_frames'] + len(timestamps) > limits['requested_frames'] or used['native_frames'] + len(timestamps) > limits['native_frames'] or used['decode_seconds'] >= limits['decode_seconds']:
        raise ConversionError('sampling_budget', '累计补采样预算已耗尽，请保留疑点。')
    return timestamps
