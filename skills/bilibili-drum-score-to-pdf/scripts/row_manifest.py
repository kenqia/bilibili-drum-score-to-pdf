"""Persistent score positions, separate from observation and display order."""
import copy
import uuid
import cv2
import numpy as np
from PIL import Image


def intersects(first, second):
    return first[0] < second[2] and first[2] > second[0] and first[1] < second[3] and first[3] > second[1]


def affects(issue, source):
    """A task-level doubt blocks the task without contaminating every row."""
    if not isinstance(issue, dict):
        return False
    if issue.get('positions'):
        return source.get('position') in issue['positions']
    if issue.get('capture') != source.get('capture'):
        return False
    if issue.get('bbox'):
        return intersects(issue['bbox'], source['bbox'])
    if issue.get('lines') and issue.get('paper_bbox'):
        paper = issue['paper_bbox']
        return intersects([paper[0], min(issue['lines']), paper[2], max(issue['lines']) + 1], source['bbox'])
    return bool(issue.get('capture'))


def observe(record, shot, regions, risks, partial):
    from automatic_score import PROGRAM_CHECK_VERSION
    manifest = record.setdefault('row_manifest', {'version': 'score-rows/1',
        'source_sha256': record['source']['sha256'], 'rows': [], 'source_positions': {},
        'continuity_complete': False, 'unresolved': []})
    manifest.setdefault('observations', {})[shot['id']] = {
        'capture': shot['id'], 'pts': shot['pts'], 'time_base': shot['time_base'],
        'geometry_policy_version': PROGRAM_CHECK_VERSION,
        'timestamp': shot['timestamp'], 'regions': regions, 'risks': risks, 'partial': partial,
        'complete_rows': sum(row['kind'] == 'system' for row in regions)}
    manifest['continuity_complete'] = False


def source_key(row):
    anchor = round(row['bbox'][1] + row['staff_top'], 3) if row['kind'] == 'system' else 'header'
    return f"{row['capture']}:{anchor}"


def track(record, shot, previous, comparison):
    """Checkpoint provisional rows before navigation has finished the song."""
    manifest = record['row_manifest']
    observations = manifest['observations']
    systems = [r for r in observations[shot['id']]['regions'] if r['kind'] == 'system']
    old = [r for r in observations.get(previous['id'] if previous else '', {}).get('regions', [])
           if r['kind'] == 'system']
    known = manifest['source_positions']
    for index, region in enumerate(systems):
        key = source_key({**region, 'capture': shot['id']})
        match = comparison.get('matches', {}).get(index)
        old_key = source_key({**old[match], 'capture': previous['id']}) if match is not None else None
        identifier = known.get(key) or known.get(old_key) or 'row-' + uuid.uuid4().hex
        known[key] = identifier
        row = next((item for item in manifest['rows'] if item['id'] == identifier), None)
        if row is None:
            row = {'id': identifier, 'position': identifier, 'order': len(manifest['rows']),
                'kind': 'system', 'selected': {'capture': shot['id'], 'bbox': region['bbox']},
                'sources': [], 'status': 'unresolved', 'issues': [{'code': 'navigation_not_finalized'}],
                'continuation': [], 'selection_reason': 'provisional complete-row observation'}
            manifest['rows'].append(row)
        source = {field: shot[field] for field in ('pts', 'time_base', 'timestamp', 'sha256', 'source_sha256')}
        source.update(capture=shot['id'], bbox=region['bbox'], key=key)
        if not any(item['capture'] == source['capture'] and item['bbox'] == source['bbox'] for item in row['sources']):
            row['sources'].append(source)
    manifest['rows'].sort(key=lambda row: (row['sources'][0]['timestamp'], row['selected']['bbox'][1]))
    for index, row in enumerate(manifest['rows']):
        row['order'] = index


def bind(record):
    """Link selected rows to the actual crop material without changing identity."""
    for row in record.get('row_manifest', {}).get('rows', []):
        match = next(((index, region) for index, region in enumerate(record.get('regions', []))
                      if region.get('position') == row['position'] and region['kind'] == 'system'), None)
        if match:
            index, region = match
            row['region_index'] = index
            row['crop'] = {key: region[key] for key in ('path', 'sha256', 'width', 'height')}


def from_selection(record):
    """Manual choices use their explicit positions and genuine review assertions."""
    previous = record.get('row_manifest', {})
    captures = {shot['id']: shot for shot in record['captures']}
    review = record['source_review']
    complete = review.get('complete') is True and not review.get('unresolved')
    issues = copy.deepcopy(review.get('unresolved', []))
    if not complete and not issues:
        issues.append({'code': 'source_review_incomplete'})
    rows = []
    explicit_positions = {}
    for index, region in enumerate(record['regions']):
        if region['kind'] != 'system':
            continue
        shot = captures[region['capture']]
        position = region.get('position', f'local-row-{index}')
        if region.get('position'):
            explicit_positions.setdefault(source_key(region), set()).add(position)
        source = {key: shot[key] for key in ('pts', 'time_base', 'timestamp', 'sha256', 'source_sha256')}
        source.update(capture=region['capture'], bbox=region['bbox'])
        old = next((row for row in previous.get('rows', []) if row['position'] == position), {})
        sources = [s for s in old.get('sources', []) if s['capture'] != source['capture'] or s['bbox'] != source['bbox']]
        for overlap in review.get('overlap_reviews', []):
            candidate = overlap['candidate']
            if overlap['position'] == position and candidate['capture'] in captures:
                alternative = captures[candidate['capture']]
                alternate = {key: alternative[key] for key in ('pts', 'time_base', 'timestamp', 'sha256', 'source_sha256')}
                alternate.update(capture=candidate['capture'], bbox=candidate['bbox'])
                if alternate not in sources and alternate != source:
                    sources.append(alternate)
        row_issues = [issue for issue in issues if affects(issue, {**source, 'position': position})]
        rows.append({'id': position, 'position': position, 'order': len(rows), 'kind': 'system',
            'selected': {'capture': region['capture'], 'bbox': region['bbox']},
            'sources': sources + [source], 'status': 'complete' if complete else 'unresolved',
            'region_index': index, 'crop': {key: region[key] for key in ('path', 'sha256', 'width', 'height')},
            'issues': row_issues, 'continuation': copy.deepcopy(review),
            'selection_reason': 'explicit source selection'})
    known = dict(previous.get('source_positions', {}))
    for key, positions in explicit_positions.items():
        if len(positions) == 1:
            known[key] = next(iter(positions))
        else:
            known.pop(key, None)
    record['row_manifest'] = {**previous, 'version': 'score-rows/1', 'source_positions': known,
        'source_sha256': record['source']['sha256'], 'rows': rows,
        'continuity_complete': complete and bool(rows), 'unresolved': issues}
    bind(record)


def update(task, record, chosen, observations, events, unresolved):
    """Reuse identities through every known source, including inserted samples."""
    previous = record.get('row_manifest', {})
    known = previous.get('source_positions', {})
    grouped = {}
    for item in observations:
        for row in item[3]:
            if row.get('position'):
                grouped.setdefault(row['position'], []).append(row)
    for row in chosen:
        grouped.setdefault(row['position'], []).append(row)
    positions = {}
    used = set()
    history = copy.deepcopy(previous.get('identity_history', []))
    priority = {row['id']: index for index, row in enumerate(previous.get('rows', []))}
    for label, sources in grouped.items():
        candidates = {known[source_key(row)] for row in sources if source_key(row) in known}
        available = candidates - used
        identifier = min(available, key=lambda value: (priority.get(value, -1), value)) if available else 'row-' + uuid.uuid4().hex
        positions[label] = identifier
        used.add(identifier)
        if candidates and (len(candidates) > 1 or not available):
            history.append({'action': 'merge' if available else 'split',
                            'previous': sorted(candidates), 'current': identifier,
                            'evidence': [source_key(row) for row in sources]})
    old_rows = {row['id']: row for row in previous.get('rows', [])}
    source_positions = dict(known)
    rows = []
    current_groups = {source_key(row): label for label, sources in grouped.items() for row in sources}
    for issue in unresolved:
        if issue.get('previous_capture') and not issue.get('bbox') and not issue.get('positions'):
            boundary = []
            for capture, last in ((issue['previous_capture'], True), (issue.get('capture'), False)):
                candidates = [s for sources in grouped.values() for s in sources if s['capture'] == capture]
                if candidates:
                    selected = (max if last else min)(candidates, key=lambda s: s['bbox'][1])
                    boundary.append(selected['position'])
            issue['positions'] = boundary
            issue['scope'] = 'continuation'
        if issue.get('positions'):
            issue['positions'] = [positions.get(label, label) for label in issue['positions']]
    risks_by_capture = {item[1]['id']: item[5] for item in observations}
    captures = {shot['id']: shot for shot in record['captures']}
    for row in chosen:
        label = row['position']
        identifier = positions[label]
        row['position'] = identifier
        sources = [copy.deepcopy(source) for source in old_rows.get(identifier, {}).get('sources', [])
                   if source.get('key') not in current_groups or current_groups[source['key']] == label]
        for candidate in grouped[label]:
            key = source_key(candidate)
            source_positions[key] = identifier
            shot = captures[candidate['capture']]
            source = {field: shot[field] for field in
                      ('pts', 'time_base', 'timestamp', 'sha256', 'source_sha256')}
            source.update(capture=candidate['capture'], bbox=candidate['bbox'], key=key, position=identifier)
            source['issues'] = [risk for risk in risks_by_capture.get(candidate['capture'], [])
                                if risk.get('bbox') and intersects(risk['bbox'], candidate['bbox'])]
            cached = next((s for s in sources if s['capture'] == source['capture'] and s['bbox'] == source['bbox']), None)
            if cached and 'quality' in cached:
                source['quality'] = {**cached['quality'], 'risk_count': len(source['issues'])}
            else:
                import score_task
                with Image.open(score_task.artifact(task, shot)) as image:
                    grey = np.asarray(image.crop(candidate['bbox']).convert('L'))
                source['quality'] = {'sharpness': float(cv2.Laplacian(grey, cv2.CV_64F).var()),
                                     'risk_count': len(source['issues'])}
            if cached:
                sources[sources.index(cached)] = source
            else:
                sources.append(source)
        if row['kind'] != 'system':
            continue
        eligible = [candidate for candidate in grouped[label] if not any(
            risk.get('bbox') and intersects(risk['bbox'], candidate['bbox'])
            for risk in risks_by_capture.get(candidate['capture'], []))]
        def quality(candidate):
            return next(source['quality']['sharpness'] for source in sources
                        if source['capture'] == candidate['capture'] and source['bbox'] == candidate['bbox'])
        previous_choice = old_rows.get(identifier, {}).get('selected')
        retained = next((candidate for candidate in eligible if previous_choice == {
            'capture': candidate['capture'], 'bbox': candidate['bbox']}), row)
        if eligible and not any(candidate['capture'] == retained['capture'] and
                                candidate['bbox'] == retained['bbox'] for candidate in eligible):
            retained = eligible[0]
        best = max(eligible, key=quality) if eligible else row
        if not eligible or quality(best) <= quality(retained) * 1.2:
            best = retained
        if best is not row:
            row.update(best, position=identifier)
        issues = [issue for issue in unresolved if any(affects(issue, source) for source in sources)]
        rows.append({'id': identifier, 'position': identifier, 'order': len(rows),
                     'kind': 'system', 'selected': {'capture': row['capture'], 'bbox': row['bbox']},
                     'sources': sources, 'status': 'unresolved' if issues else 'complete',
                     'issues': issues, 'selection_reason': 'risk-free native source; replace only for >20% sharper evidence'})
    for event in events:
        event['positions'] = [positions.get(label, label) for label in event.get('positions', [])]
    for row in rows:
        row['continuation'] = [copy.deepcopy(event) for event in events
                               if row['id'] in event.get('positions', [])]
    manifest = {'version': 'score-rows/1', 'source_sha256': record['source']['sha256'],
                'rows': rows, 'source_positions': source_positions,
                'identity_history': history,
                'observations': previous.get('observations', {}),
                'continuity_complete': not unresolved and bool(rows), 'unresolved': copy.deepcopy(unresolved)}
    record['row_manifest'] = manifest
    return manifest
