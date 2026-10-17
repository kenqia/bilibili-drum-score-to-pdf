"""Adaptive score navigation. Sparse continuity is not strict time coverage."""
import math
import time

from PIL import Image
import automatic_score as automatic
import native_cache
import score_task as state

POLICY = 'adaptive-score-rows/1'


def collect(task, max_observations=128):
    record = state.load(task)
    survey = record.setdefault('overview', {'candidates': [], 'panels': [], 'resamples': [],
        'scan': {'complete': False, 'frames_observed': 0, 'completed_intervals': [],
                 'cursor': 0, 'policy_version': automatic.SCAN_POLICY_VERSION}})
    survey['mode'] = 'sparse'
    duration = record['source']['duration']
    frame = record['source'].get('frame_duration', .04)
    end = max(0, duration - frame - 1e-6)
    navigation = record.setdefault('navigation', {'policy_version': POLICY, 'cursor': 0,
        'step': min(12, max(.5, duration / 32)), 'decisions': [], 'endpoints': {},
        'status': 'pending', 'unresolved': []})
    if navigation['policy_version'] != POLICY:
        raise state.ReconstructionError('导航版本已改变；保留原任务并建立新任务。')
    state.save(task, record)

    def observe(seconds, reason):
        shot = native_cache.capture(task, seconds)
        current = state.load(task)
        current_survey = current['overview']
        if not any(c['id'] == shot['id'] for c in current_survey['candidates']):
            current_survey['candidates'].append(shot)
            current_survey['candidates'].sort(key=lambda c: c['timestamp'])
        current['navigation']['decisions'].append({'action': 'observe', 'reason': reason,
            'requested_seconds': seconds, 'capture': shot['id'], 'pts': shot['pts'],
            'time_base': shot['time_base'], 'timestamp': shot['timestamp']})
        current.pop('freeze', None)
        state.save(task, current)
        return shot

    for name, seconds in (('first', 0), ('last', end)):
        record = state.load(task)
        if name not in record['navigation']['endpoints']:
            shot = observe(seconds, name + '_endpoint_and_layout')
            record = state.load(task)
            with Image.open(state.artifact(task, shot)) as image:
                regions, risks, partial = automatic.detect(image)
            record['navigation']['endpoints'][name] = {'capture': shot['id'],
                'pts': shot['pts'], 'time_base': shot['time_base'],
                'complete_rows': sum(r['kind'] == 'system' for r in regions),
                'risks': risks, 'partial': partial}
            state.save(task, record)
    began = time.monotonic()
    for _ in range(max_observations):
        record = state.load(task)
        navigation = record['navigation']
        if navigation['cursor'] >= end:
            break
        previous = next(c for c in record['overview']['candidates']
                        if c['requested_seconds'] == navigation['cursor'])
        target = min(end, navigation['cursor'] + navigation['step'])
        shot = observe(target, 'forward_search')
        with Image.open(state.artifact(task, previous)) as first, Image.open(state.artifact(task, shot)) as second:
            unchanged = automatic._same(automatic._signature(first), automatic._signature(second))
        record = state.load(task)
        navigation = record['navigation']
        old_step = navigation['step']
        navigation.update(cursor=target, step=min(30, old_step * 1.7) if unchanged else max(.5, old_step / 1.4))
        navigation['decisions'].append({'action': 'adjust_step', 'from_capture': previous['id'],
            'to_capture': shot['id'], 'previous_step': old_step, 'next_step': navigation['step'],
            'reason': 'repeated_rows' if unchanged else 'new_score_content'})
        state.save(task, record)
    record = state.load(task)
    navigation = record['navigation']
    navigation['status'] = 'observed' if navigation['cursor'] >= end else 'pending'
    navigation['wall_seconds'] = navigation.get('wall_seconds', 0) + time.monotonic() - began
    record['overview']['panels'] = automatic._panels(task, record['overview']['candidates'])
    state.save(task, record)
    return navigation
