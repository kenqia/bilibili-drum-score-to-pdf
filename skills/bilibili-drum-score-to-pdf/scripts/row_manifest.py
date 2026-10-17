"""Persistent score positions, separate from observation and display order."""
import copy
import uuid


def observe(record, shot, regions, risks, partial):
    manifest = record.setdefault('row_manifest', {'version': 'score-rows/1',
        'source_sha256': record['source']['sha256'], 'rows': [], 'source_positions': {},
        'continuity_complete': False, 'unresolved': []})
    manifest.setdefault('observations', {})[shot['id']] = {
        'capture': shot['id'], 'pts': shot['pts'], 'time_base': shot['time_base'],
        'timestamp': shot['timestamp'], 'regions': regions, 'risks': risks, 'partial': partial,
        'complete_rows': sum(row['kind'] == 'system' for row in regions)}
    manifest['continuity_complete'] = False


def source_key(row):
    anchor = round(row['bbox'][1] + row['staff_top'], 3) if row['kind'] == 'system' else 'header'
    return f"{row['capture']}:{anchor}"


def update(record, chosen, observations, events, unresolved):
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
    for label, sources in grouped.items():
        candidates = {known[source_key(row)] for row in sources if source_key(row) in known}
        if len(candidates) > 1:
            unresolved.append({'code': 'conflicting_row_identity', 'positions': sorted(candidates)})
        positions[label] = sorted(candidates)[0] if candidates else 'row-' + uuid.uuid4().hex
    old_rows = {row['id']: row for row in previous.get('rows', [])}
    source_positions = dict(known)
    rows = []
    for row in chosen:
        label = row['position']
        identifier = positions[label]
        row['position'] = identifier
        sources = copy.deepcopy(old_rows.get(identifier, {}).get('sources', []))
        captures = {shot['id']: shot for shot in record['captures']}
        for candidate in grouped[label]:
            key = source_key(candidate)
            source_positions[key] = identifier
            shot = captures[candidate['capture']]
            source = {field: shot[field] for field in
                      ('pts', 'time_base', 'timestamp', 'sha256', 'source_sha256')}
            source.update(capture=candidate['capture'], bbox=candidate['bbox'])
            if source not in sources:
                sources.append(source)
        if row['kind'] != 'system':
            continue
        issues = [issue for issue in unresolved if issue.get('capture') in
                  {source['capture'] for source in sources} or not issue.get('capture')]
        rows.append({'id': identifier, 'position': identifier, 'order': len(rows),
                     'kind': 'system', 'selected': {'capture': row['capture'], 'bbox': row['bbox']},
                     'sources': sources, 'status': 'unresolved' if issues else 'complete',
                     'issues': issues, 'selection_reason': 'complete native source; preserve valid selection'})
    for event in events:
        event['positions'] = [positions.get(label, label) for label in event.get('positions', [])]
    for row in rows:
        row['continuation'] = [copy.deepcopy(event) for event in events
                               if row['id'] in event.get('positions', [])]
    manifest = {'version': 'score-rows/1', 'source_sha256': record['source']['sha256'],
                'rows': rows, 'source_positions': source_positions,
                'observations': previous.get('observations', {}),
                'continuity_complete': not unresolved and bool(rows), 'unresolved': copy.deepcopy(unresolved)}
    record['row_manifest'] = manifest
    return manifest
