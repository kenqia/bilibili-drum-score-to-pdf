"""Adaptive score navigation. Sparse continuity is not strict time coverage."""
import time
import hashlib
from pathlib import Path

from PIL import Image
import cv2
import automatic_score as automatic
import native_cache
import score_task as state
import row_manifest
import row_anchors

POLICY = 'adaptive-score-rows/2'



def save_navigation(task, record):
    navigation = record['navigation']
    decisions = navigation['decisions']
    navigation['sampling_counts'] = {
        'forward_requests': sum(d['action'] == 'observe' and d['reason'] == 'forward_search' for d in decisions),
        'backtrack_requests': sum(d['action'] == 'observe' and d['reason'] == 'gap_backtrack' for d in decisions),
        'endpoint_requests': sum(d['action'] == 'observe' and d['reason'].endswith('_endpoint_and_layout') for d in decisions),
        'local_scan_attempts': sum(d['action'] == 'local_scan' for d in decisions),
        'span_adjustment_events': sum(d['action'] == 'adjust_step' for d in decisions),
    }
    state.save(task, record)


def covered(record, first, last):
    """Only actual continuous intervals can prove an unobserved page change."""
    cursor = first['timestamp']
    end = last['timestamp'] + record['source'].get('frame_duration', .04) / 2
    for low, high in sorted(record.get('overview', {}).get('scan', {}).get('completed_intervals', [])):
        if low <= cursor + 1e-6:
            cursor = max(cursor, high)
    return cursor >= min(end, record['source']['duration'])


def numbered_conflicts(record, proposed=None):
    captures = {shot['id']: shot for shot in record['captures']}
    known, conflicts = {}, []
    reviews = record.get('continuity_reviews', []) + ([proposed] if proposed else [])
    for review in reviews:
        for capture, bounds in ((review['previous_capture'], review['previous_bars']), (review['capture'], review['bars'])):
            shot = captures[capture]
            key = (shot['pts'], tuple(shot['time_base']), shot['sha256'])
            if key in known and known[key] != bounds:
                conflicts.append({'code': 'contradictory_bar_ranges', 'capture': capture,
                                  'previous': known[key], 'proposed': bounds})
            known[key] = bounds
    return conflicts


def numbered_evidence(record, first, last):
    if numbered_conflicts(record):
        return None
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
        new_detection = None if new else automatic.detect(new_image)
        new_regions = new['regions'] if new else new_detection[0]
        new_risks = new.get('risks', []) if new else new_detection[1]
        old_rows = [{**r, 'capture': first['id']} for r in old_regions if r['kind'] == 'system']
        new_rows = [{**r, 'capture': last['id']} for r in new_regions if r['kind'] == 'system']
        complete_indices = {index for index, row in enumerate(new_rows) if not any(
            risk.get('bbox') and row_manifest.intersects(risk['bbox'], row['bbox']) for risk in new_risks)}
        old_anchors = old.get('anchors', []) if old else []
        new_anchors = new.get('anchors', []) if new else []
        complete_anchors = bool(old_anchors and new_anchors) and all(
            a['start_bar'] is not None and not a.get('conflict') for a in old_anchors+new_anchors)
        use_anchors = complete_anchors or any(a.get('conflict') for a in old_anchors+new_anchors) or (bool(old_anchors or new_anchors) and not (
            row_anchors.fallback_allowed(record, first) and row_anchors.fallback_allowed(record, last)))
        if use_anchors:
            missing = row_anchors.missing(record, first, old_anchors) + row_anchors.missing(record, last, new_anchors)
            if missing:
                return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                        'overlap_rows': 0, 'reason': 'row_anchor_needs_review', 'visual_review_needed': True}
        if numbered_evidence(record, first, last):
            return {'proved': True, 'new_complete_rows': len(complete_indices), 'overlap_rows': 0,
                    'reason': 'numbered_new_positions', 'matches': {}}
        same_numbers = not complete_anchors or [a['start_bar'] for a in old_anchors] == [a['start_bar'] for a in new_anchors]
        if same_numbers and automatic.same_observation(old_image, new_image):
            return {'proved': True, 'new_complete_rows': 0, 'overlap_rows': len(new_rows),
                    'reason': 'repeated_rows', 'matches': {index: index for index in range(min(len(old_rows), len(new_rows)))}}
        if not old_rows or not new_rows:
            return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                    'overlap_rows': 0, 'reason': 'layout_or_endpoint_gap'}
        spacing = max(1, round(old_rows[0]['staff_spacing']))
        old_signatures = [automatic._row_signature(old_image, r, spacing=spacing) for r in old_rows]
        new_signatures = [automatic._row_signature(new_image, r, spacing=spacing) for r in new_rows]
        if use_anchors and len(old_anchors) == len(old_rows) and len(new_anchors) == len(new_rows):
            old_values = [a['start_bar'] for a in old_anchors]
            new_values = [a['start_bar'] for a in new_anchors]
            mapping = {j: old_values.index(value) for j, value in enumerate(new_values) if value in old_values}
            native = {first['id']: automatic._signature(old_image), last['id']: automatic._signature(new_image)}
            if any(not automatic.same_row(old_image, old_rows[i], new_image, new_rows[j], spacing)
                   and not automatic._native_visible_match(old_rows[i], new_rows[j], native.__getitem__)
                   for j, i in mapping.items()):
                return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                        'overlap_rows': 0, 'reason': 'printed_bar_content_conflict', 'visual_review_needed': True}
            if mapping and list(mapping) == list(range(len(mapping))) and list(mapping.values()) == list(
                    range(len(old_rows)-len(mapping), len(old_rows))) and all(
                        value > max(old_values) for value in new_values[len(mapping):]):
                return {'proved': True, 'new_complete_rows': len(complete_indices-set(mapping)),
                        'overlap_rows': len(mapping), 'reason': 'printed_bar_overlap', 'matches': mapping}
            if not mapping:
                return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                        'overlap_rows': 0, 'reason': 'printed_bar_gap_needs_continuation'}
        overlaps = [size for size in range(1, min(len(old_rows), len(new_rows)) + 1)
                    if all(automatic._same(a, b) for a, b in zip(old_signatures[-size:], new_signatures[:size]))]
        if len(overlaps) == 1:
            return {'proved': True, 'new_complete_rows': len(complete_indices-set(range(overlaps[0]))),
                    'overlap_rows': overlaps[0], 'reason': 'unique_row_overlap',
                    'matches': {index: len(old_rows) - overlaps[0] + index for index in range(overlaps[0])}}
        masks = {first['id']: automatic._signature(old_image), last['id']: automatic._signature(new_image)}
        mapping = automatic._spatial_continuation(old_rows, new_rows,
            [automatic._row_signature(old_image, r, core=True, spacing=spacing) for r in old_rows],
            [automatic._row_signature(new_image, r, core=True, spacing=spacing) for r in new_rows], masks.__getitem__)
        if mapping:
            return {'proved': True, 'new_complete_rows': len(complete_indices-set(mapping)),
                    'overlap_rows': len(mapping), 'reason': 'unique_scroll', 'matches': mapping}
        small_old = [cv2.resize(value, (480, 128), interpolation=cv2.INTER_AREA) for value in old_signatures]
        small_new = [cv2.resize(value, (480, 128), interpolation=cv2.INTER_AREA) for value in new_signatures]
        tentative = [(i, j) for i, a in enumerate(small_old) for j, b in enumerate(small_new)
                     if automatic._same(a, b)]
        same_layout = len(old_rows) == len(new_rows) and all(automatic._same(a, b) for a, b in zip(small_old, small_new))
        if same_layout or (len({i for i, _ in tentative}) >= 2 and len({j for _, j in tentative}) >= 2):
            # Only a search heuristic. It cannot approve symbols or row identity.
            return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                    'overlap_rows': 0, 'reason': 'similar_rows_need_review', 'visual_review_needed': True}
        return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows), 'overlap_rows': 0,
                'reason': 'unproved_row_continuation'}


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
    save_navigation(task, record)

    def observe(seconds, reason):
        nonlocal record
        candidates = record['overview']['candidates']
        if (len(candidates) >= automatic.MAX_EVENTS or
                sum((Path(task) / c['path']).stat().st_size for c in candidates) >= automatic.MAX_NATIVE_BYTES):
            raise state.ReconstructionError('导航来源达到资源上限；保留进度。')
        shot = native_cache.capture(task, seconds)
        current = record = state.load(task)
        current_survey = current['overview']
        shot = next((candidate for candidate in current_survey['candidates']
                     if candidate['pts'] == shot['pts'] and candidate['time_base'] == shot['time_base']), shot)
        if not any(c['id'] == shot['id'] for c in current_survey['candidates']):
            current_survey['candidates'].append(shot)
            current_survey['candidates'].sort(key=lambda c: c['timestamp'])
        current['navigation']['decisions'].append({'action': 'observe', 'reason': reason,
            'requested_seconds': seconds, 'capture': shot['id'], 'pts': shot['pts'],
            'time_base': shot['time_base'], 'timestamp': shot['timestamp']})
        with Image.open(state.artifact(task, shot)) as image:
            regions, risks, partial = automatic.detect(image)
            anchors = row_anchors.readings(current, shot, image, regions, task=task)
        row_manifest.observe(current, shot, regions, risks, partial)
        current['row_manifest']['observations'][shot['id']]['anchors'] = anchors
        earlier = [candidate for candidate in current_survey['candidates'] if candidate['timestamp'] < shot['timestamp']]
        previous = earlier[-1] if earlier else None
        comparison = compare(task, current, previous, shot) if previous else {}
        row_manifest.track(current, shot, previous, comparison)
        current.pop('freeze', None)
        save_navigation(task, current)
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
            save_navigation(task, record)
    def anchor_gate():
        problems = []
        refreshed = False
        for shot in record['overview']['candidates']:
            observed = record['row_manifest']['observations'].get(shot['id'])
            if observed is None or observed.get('geometry_policy_version') != automatic.PROGRAM_CHECK_VERSION:
                with Image.open(state.artifact(task, shot)) as image:
                    regions, risks, partial = automatic.detect(image)
                    anchors = row_anchors.readings(record, shot, image, regions, task=task)
                row_manifest.observe(record, shot, regions, risks, partial)
                observed = record['row_manifest']['observations'][shot['id']]
                observed['anchors'] = anchors
                refreshed = True
            if 'anchors' not in observed or any(a['start_bar'] is None for a in observed['anchors']):
                refreshed = True
                with Image.open(state.artifact(task, shot)) as image:
                    observed['anchors'] = row_anchors.readings(record, shot, image, observed['regions'], task=task)
            problems.extend(row_anchors.missing(record, shot, observed['anchors']))
        if problems:
            record['navigation'].update(status='blocked', unresolved=problems)
            record['overview']['panels'] = automatic._panels(task, record['overview']['candidates'])
            record['navigation']['wall_seconds'] = previous_wall + time.monotonic()-began
            save_navigation(task, record)
        elif refreshed:
            save_navigation(task, record)
        return bool(problems)

    if anchor_gate():
        return record['navigation']
    navigation = record['navigation']
    navigation['unresolved'] = []
    for _ in range(max_observations):
        navigation = record['navigation']
        if navigation['cursor'] >= end:
            break
        pending_forward = navigation.get('pending_forward')
        previous_id = pending_forward['previous_capture'] if pending_forward else navigation.get(
            'cursor_capture', navigation['endpoints']['first']['capture'])
        previous = next(c for c in record['overview']['candidates'] if c['id'] == previous_id)
        target = pending_forward['target'] if pending_forward else min(end, navigation['cursor'] + navigation['step'])
        if pending_forward:
            shot = next(c for c in record['overview']['candidates'] if c['id'] == pending_forward['capture'])
        else:
            shot = observe(target, 'forward_search')
            record['navigation']['pending_forward'] = {'previous_capture': previous_id,
                                                      'capture': shot['id'], 'target': target}
            save_navigation(task, record)
        if anchor_gate():
            return record['navigation']
        comparison = compare(task, record, previous, shot)
        register_problem(record, previous, shot, comparison)
        navigation = record['navigation']
        if comparison.get('visual_review_needed'):
            navigation.update(status='blocked', unresolved=[{'code': 'native_difference_needs_visual_review',
                'capture': shot['id'], 'previous_capture': previous['id'], 'reason': comparison['reason']}])
            save_navigation(task, record)
            return navigation
        navigation.pop('pending_forward', None)
        old_step = navigation['step']
        if comparison['new_complete_rows'] is None:
            next_step = old_step
        elif comparison['new_complete_rows'] == 0 and comparison['proved']:
            next_step = min(30, old_step * 1.7)
        elif comparison['proved'] or comparison.get('visual_review_needed'):
            next_step = min(30, old_step * 1.2) if comparison['new_complete_rows'] == 1 else max(.5, old_step / 1.4)
        else:
            next_step = max(.5, old_step / 2)
        navigation.update(cursor=target, cursor_capture=shot['id'], step=next_step)
        navigation['decisions'].append({'action': 'adjust_step', 'from_capture': previous['id'],
            'to_capture': shot['id'], 'previous_step': old_step, 'next_step': navigation['step'],
            **comparison})
        save_navigation(task, record)
    record = state.load(task)
    navigation = record['navigation']
    navigation['status'] = 'observed' if navigation['cursor'] >= end else 'pending'
    save_navigation(task, record)
    if navigation['status'] == 'observed':
        refine(task, observe, max_observations)
        record = state.load(task)
        navigation = record['navigation']
    record['overview']['panels'] = automatic._panels(task, record['overview']['candidates'])
    navigation['wall_seconds'] = previous_wall + time.monotonic() - began
    save_navigation(task, record)
    return navigation


def register_problem(record, first, last, comparison):
    if comparison['proved']:
        return
    problems = record['navigation'].setdefault('problems', [])
    if any(p['start_timestamp'] <= first['timestamp'] and p['end_timestamp'] >= last['timestamp'] for p in problems):
        return
    identity = ':'.join(str(v) for v in (record['source']['sha256'], first['pts'], first['time_base'],
                                       last['pts'], last['time_base']))
    problems.append({'id': 'join-'+hashlib.sha256(identity.encode()).hexdigest()[:24],
        'previous_capture': first['id'], 'capture': last['id'],
        'start_timestamp': first['timestamp'], 'end_timestamp': last['timestamp'],
        'interval': [first['timestamp'], min(record['source']['duration'],
                     last['timestamp']+record['source'].get('frame_duration', .04))],
        'status': 'pending', 'attempts': 0, 'no_gain_streak': 0, 'history': []})


def problem_evidence(task, record, problem):
    candidates = [c for c in record['overview']['candidates']
                  if problem['start_timestamp'] <= c['timestamp'] <= problem['end_timestamp']]
    gaps = []
    for first, last in zip(candidates, candidates[1:]):
        if covered(record, first, last):
            continue
        result = compare(task, record, first, last)
        if not result['proved']:
            gaps.append((first, last, result))
    return gaps, sum(b['timestamp']-a['timestamp'] for a, b, _ in gaps)


def refine(task, observe, budget):
    """Measure progress against persistent original problems, not new pairs."""
    for operation in range(budget+1):
        record = state.load(task)
        candidates = record['overview']['candidates']
        anchor_issues = []
        for shot in candidates:
            observation = record.get('row_manifest', {}).get('observations', {}).get(shot['id'])
            if (observation is None or 'anchors' not in observation or
                    observation.get('geometry_policy_version') != automatic.PROGRAM_CHECK_VERSION):
                with Image.open(state.artifact(task, shot)) as image:
                    regions, risks, partial = automatic.detect(image)
                    anchors = row_anchors.readings(record, shot, image, regions, task=task)
                row_manifest.observe(record, shot, regions, risks, partial)
                observation = record['row_manifest']['observations'][shot['id']]
                observation['anchors'] = anchors
            anchor_issues.extend(row_anchors.missing(record, shot, observation['anchors']))
        if anchor_issues:
            record['navigation'].update(status='blocked', unresolved=anchor_issues)
            save_navigation(task, record)
            return
        for first, last in zip(candidates, candidates[1:]):
            if not covered(record, first, last):
                register_problem(record, first, last, compare(task, record, first, last))
        pending = []
        for problem in record['navigation'].get('problems', []):
            gaps, remaining = problem_evidence(task, record, problem)
            if remaining < problem.get('remaining_unproved_seconds', remaining)-1e-6:
                problem['no_gain_streak'] = 0
            problem['remaining_unproved_seconds'] = remaining
            if problem['history'] and problem['history'][-1]['status'] == 'started':
                attempt = problem['history'][-1]
                gained = remaining < attempt['remaining_before']-1e-6
                problem['no_gain_streak'] = 0 if gained else problem['no_gain_streak']+1
                attempt.update(status='finished', remaining_after=remaining, gained_evidence=gained)
            if not gaps:
                problem['status'] = 'resolved'
                continue
            visual = next((g for g in gaps if g[2].get('visual_review_needed')), None)
            if problem['no_gain_streak'] >= 2:
                problem.update(status='needs_review', stop_reason='two_attempts_without_evidence_gain')
            elif visual:
                problem.update(status='needs_review', stop_reason=visual[2]['reason'])
            else:
                problem['status'] = 'pending'
                pending.append((problem, gaps[0]))
        navigation = record['navigation']
        navigation['unresolved'] = [
            {'code': 'native_difference_needs_visual_review' if p.get('stop_reason') == 'similar_rows_need_review'
             else 'continuation_problem_needs_review', 'problem_id': p['id'],
             'previous_capture': p['previous_capture'], 'capture': p['capture'],
             'interval': p['interval'], 'reason': p.get('stop_reason'), 'scope': 'continuation'}
            for p in navigation.get('problems', []) if p['status'] == 'needs_review']
        if not pending or operation == budget:
            navigation['status'] = 'blocked' if navigation['unresolved'] else 'pending' if pending else 'observed'
            save_navigation(task, record)
            return
        problem, (first, last, _) = pending[0]
        span = last['timestamp']-first['timestamp']
        target = (first['timestamp']+last['timestamp'])/2
        interval = [first['timestamp'], min(problem['interval'][1],
                    last['timestamp']+record['source'].get('frame_duration', .04))]
        stalled = any(d['action'] == 'observe' and d['requested_seconds'] == target
                      for d in navigation['decisions'])
        local = span <= max(.5, 2*record['source'].get('frame_duration', .04)) or stalled
        if local and any(h['action'] == 'local_scan' and h.get('interval') == interval for h in problem['history']):
            problem.update(status='needs_review', stop_reason='local_scan_incomplete')
            problem['no_gain_streak'] = max(2, problem['no_gain_streak'])
            save_navigation(task, record)
            continue
        attempt = {'action': 'local_scan' if local else 'backtrack', 'status': 'started',
                   'remaining_before': problem['remaining_unproved_seconds'], 'target': target, 'interval': interval}
        problem['history'].append(attempt)
        problem['attempts'] = len(problem['history'])
        navigation['decisions'].append({'action': attempt['action'], 'problem_id': problem['id'],
            'from_capture': first['id'], 'to_capture': last['id'], 'target': target,
            'interval': interval, 'reason': 'unproved_row_continuation'})
        save_navigation(task, record)
        if local:
            automatic.overview(task, [interval], 'local continuation risk: '+problem['id'])
        else:
            observe(target, 'gap_backtrack')
