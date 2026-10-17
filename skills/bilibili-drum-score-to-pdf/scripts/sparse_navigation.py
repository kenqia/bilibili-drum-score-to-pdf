"""Adaptive score navigation. Sparse continuity is not strict time coverage."""
import time
from functools import lru_cache
from pathlib import Path

from PIL import Image
import cv2
import automatic_score as automatic
import native_cache
import score_task as state
import row_manifest

POLICY = 'adaptive-score-rows/1'


def covered(record, first, last):
    """Only actual continuous intervals can prove an unobserved page change."""
    cursor = first['timestamp']
    end = last['timestamp'] + record['source'].get('frame_duration', .04) / 2
    for low, high in sorted(record.get('overview', {}).get('scan', {}).get('completed_intervals', [])):
        if low <= cursor + 1e-6:
            cursor = max(cursor, high)
    return cursor >= min(end, record['source']['duration'])


def numbered_evidence(record, first, last):
    return next((decision for decision in reversed(record.get('continuity_reviews', []))
                 if decision['previous_capture'] == first['id'] and decision['capture'] == last['id']
                 and decision['source_sha256'] == record['source']['sha256']
                 and decision['previous_sha256'] == first['sha256'] and decision['sha256'] == last['sha256']), None)


def compare(task, record, first, last):
    """Count complete rows and require a unique overlap or spatial movement."""
    descriptions = record.get('row_manifest', {}).get('observations', {})
    with Image.open(state.artifact(task, first)) as old_image, Image.open(state.artifact(task, last)) as new_image:
        old = descriptions.get(first['id'])
        new = descriptions.get(last['id'])
        old_regions = old['regions'] if old else automatic.detect(old_image)[0]
        new_regions = new['regions'] if new else automatic.detect(new_image)[0]
        old_rows = [{**r, 'capture': first['id']} for r in old_regions if r['kind'] == 'system']
        new_rows = [{**r, 'capture': last['id']} for r in new_regions if r['kind'] == 'system']
        if automatic._same(automatic._signature(old_image), automatic._signature(new_image)):
            return {'proved': True, 'new_complete_rows': 0, 'overlap_rows': len(new_rows), 'reason': 'repeated_rows'}
        if not old_rows or not new_rows:
            return {'proved': False, 'new_complete_rows': len(new_rows), 'overlap_rows': 0, 'reason': 'layout_or_endpoint_gap'}
        spacing = max(1, round(old_rows[0]['staff_spacing']))
        old_signatures = [automatic._row_signature(old_image, r, spacing=spacing) for r in old_rows]
        new_signatures = [automatic._row_signature(new_image, r, spacing=spacing) for r in new_rows]
        overlaps = [size for size in range(1, min(len(old_rows), len(new_rows)) + 1)
                    if all(automatic._same(a, b) for a, b in zip(old_signatures[-size:], new_signatures[:size]))]
        if len(overlaps) == 1:
            return {'proved': True, 'new_complete_rows': len(new_rows) - overlaps[0],
                    'overlap_rows': overlaps[0], 'reason': 'unique_row_overlap'}
        if len(old_rows) == len(new_rows) and all(automatic._same(
                cv2.resize(a, (480, 128), interpolation=cv2.INTER_AREA),
                cv2.resize(b, (480, 128), interpolation=cv2.INTER_AREA))
                for a, b in zip(old_signatures, new_signatures)):
            # Navigation may ignore raster detail to choose a jump, but this
            # must never approve notation or invent a native row identity.
            return {'proved': False, 'new_complete_rows': 0, 'overlap_rows': 0,
                    'reason': 'similar_rows_need_review', 'visual_review_needed': True}
        masks = {first['id']: automatic._signature(old_image), last['id']: automatic._signature(new_image)}
        mapping = automatic._spatial_continuation(old_rows, new_rows,
            [automatic._row_signature(old_image, r, core=True, spacing=spacing) for r in old_rows],
            [automatic._row_signature(new_image, r, core=True, spacing=spacing) for r in new_rows], masks.__getitem__)
        return {'proved': bool(mapping), 'new_complete_rows': len(new_rows) - len(mapping),
                'overlap_rows': len(mapping), 'reason': 'unique_scroll' if mapping else 'unproved_row_continuation'}


def collect(task, max_observations=128):
    began = time.monotonic()
    record = state.load(task)
    survey = record.setdefault('overview', {'candidates': [], 'panels': [], 'resamples': [],
        'scan': {'complete': False, 'frames_observed': 0, 'completed_intervals': [],
                 'cursor': 0, 'policy_version': automatic.SCAN_POLICY_VERSION}})
    survey['mode'] = 'sparse'
    if survey['scan'].get('policy_version') != automatic.SCAN_POLICY_VERSION:
        survey.setdefault('scan_history', []).append(dict(survey['scan']))
        survey['scan'] = {'complete': False, 'frames_observed': 0, 'completed_intervals': [],
                          'cursor': 0, 'policy_version': automatic.SCAN_POLICY_VERSION}
    duration = record['source']['duration']
    frame = record['source'].get('frame_duration', .04)
    end = max(0, duration - frame - 1e-6)
    navigation = record.setdefault('navigation', {'policy_version': POLICY, 'cursor': 0,
        'step': min(12, max(.5, duration / 32)), 'decisions': [], 'endpoints': {},
        'status': 'pending', 'unresolved': []})
    if navigation['policy_version'] != POLICY:
        raise state.ReconstructionError('导航版本已改变；保留原任务并建立新任务。')
    previous_wall = navigation.get('wall_seconds', 0)
    state.save(task, record)

    def observe(seconds, reason):
        nonlocal record
        candidates = record['overview']['candidates']
        if (len(candidates) >= automatic.MAX_EVENTS or
                sum((Path(task) / c['path']).stat().st_size for c in candidates) >= automatic.MAX_NATIVE_BYTES):
            raise state.ReconstructionError('导航来源达到资源上限；保留进度。')
        shot = native_cache.capture(task, seconds)
        current = record = state.load(task)
        current_survey = current['overview']
        if not any(c['id'] == shot['id'] for c in current_survey['candidates']):
            current_survey['candidates'].append(shot)
            current_survey['candidates'].sort(key=lambda c: c['timestamp'])
        current['navigation']['decisions'].append({'action': 'observe', 'reason': reason,
            'requested_seconds': seconds, 'capture': shot['id'], 'pts': shot['pts'],
            'time_base': shot['time_base'], 'timestamp': shot['timestamp']})
        with Image.open(state.artifact(task, shot)) as image:
            regions, risks, partial = automatic.detect(image)
        row_manifest.observe(current, shot, regions, risks, partial)
        current.pop('freeze', None)
        state.save(task, current)
        return shot

    for name, seconds in (('first', 0), ('last', end)):
        if name not in record['navigation']['endpoints']:
            shot = observe(seconds, name + '_endpoint_and_layout')
            with Image.open(state.artifact(task, shot)) as image:
                regions, risks, partial = automatic.detect(image)
            record['navigation']['endpoints'][name] = {'capture': shot['id'],
                'pts': shot['pts'], 'time_base': shot['time_base'],
                'complete_rows': sum(r['kind'] == 'system' for r in regions),
                'risks': risks, 'partial': partial}
            state.save(task, record)
    for _ in range(max_observations):
        navigation = record['navigation']
        if navigation['cursor'] >= end:
            break
        previous_id = navigation.get('cursor_capture', navigation['endpoints']['first']['capture'])
        previous = next(c for c in record['overview']['candidates'] if c['id'] == previous_id)
        target = min(end, navigation['cursor'] + navigation['step'])
        shot = observe(target, 'forward_search')
        comparison = compare(task, record, previous, shot)
        navigation = record['navigation']
        old_step = navigation['step']
        if comparison['new_complete_rows'] == 0 and (comparison['proved'] or comparison.get('visual_review_needed')):
            next_step = min(30, old_step * 1.7)
        elif comparison['proved']:
            next_step = min(30, old_step * 1.2) if comparison['new_complete_rows'] == 1 else max(.5, old_step / 1.4)
        else:
            next_step = max(.5, old_step / 2)
        navigation.update(cursor=target, cursor_capture=shot['id'], step=next_step)
        navigation['decisions'].append({'action': 'adjust_step', 'from_capture': previous['id'],
            'to_capture': shot['id'], 'previous_step': old_step, 'next_step': navigation['step'],
            **comparison})
        state.save(task, record)
    record = state.load(task)
    navigation = record['navigation']
    navigation['status'] = 'observed' if navigation['cursor'] >= end else 'pending'
    state.save(task, record)
    if navigation['status'] == 'observed':
        refine(task, observe, max_observations)
        record = state.load(task)
        navigation = record['navigation']
    record['overview']['panels'] = automatic._panels(task, record['overview']['candidates'])
    navigation['wall_seconds'] = previous_wall + time.monotonic() - began
    state.save(task, record)
    return navigation


def refine(task, observe, budget):
    """Return to missing joins; continuous decoding stays inside a risk interval."""
    @lru_cache(maxsize=256)
    def comparison(first_id, last_id):
        captures = {shot['id']: shot for shot in record['captures']}
        return compare(task, record, captures[first_id], captures[last_id])

    for _ in range(budget):
        record = state.load(task)
        candidates = record['overview']['candidates']
        gap = next(((first, last) for first, last in zip(candidates, candidates[1:])
                    if not covered(record, first, last) and not numbered_evidence(record, first, last)
                    and not comparison(first['id'], last['id'])['proved']
                    and not comparison(first['id'], last['id']).get('visual_review_needed')), None)
        if gap is None:
            record['navigation']['status'] = 'observed'
            record['navigation']['unresolved'] = [
                {'code': 'native_difference_needs_visual_review', 'previous_capture': first['id'],
                 'capture': last['id'], 'reason': 'Navigation-scale similarity is not native notation evidence.'}
                for first, last in zip(candidates, candidates[1:])
                if not covered(record, first, last) and not numbered_evidence(record, first, last)
                and comparison(first['id'], last['id']).get('visual_review_needed')]
            state.save(task, record)
            return
        first, last = gap
        span = last['timestamp'] - first['timestamp']
        interval = [first['timestamp'], min(record['source']['duration'],
                    last['timestamp'] + record['source'].get('frame_duration', .04))]
        decisions = record['navigation']['decisions']
        if span <= max(.5, 2 * record['source'].get('frame_duration', .04)):
            if any(d['action'] == 'local_scan' and d['interval'] == interval for d in decisions):
                record['navigation']['unresolved'] = [{'code': 'local_scan_incomplete', 'interval': interval}]
                record['navigation']['status'] = 'blocked'
                state.save(task, record)
                return
            decisions.append({'action': 'local_scan', 'interval': interval,
                              'reason': 'unproved_row_continuation'})
            state.save(task, record)
            automatic.overview(task, [interval], 'local continuation risk')
        else:
            target = (first['timestamp'] + last['timestamp']) / 2
            decisions.append({'action': 'backtrack', 'from_capture': first['id'], 'to_capture': last['id'],
                              'target': target, 'reason': 'unproved_row_continuation'})
            state.save(task, record)
            observe(target, 'gap_backtrack')
    record = state.load(task)
    record['navigation']['status'] = 'pending'
    state.save(task, record)
