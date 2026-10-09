"""Geometry-only suggestions. These records never assert actual image review."""
import copy
import math


def suggest(packet):
    """Return v3 structural suggestions and uncertainty; no pixel identity or acceptance."""
    frames = packet['frames']
    structure = dict(schema_version=3, rows=[], observations=[], transitions=[],
                     coverage=dict(first_frame=frames[0]['id'], last_frame=frames[-1]['id'], unresolved=[]))
    issues, audits, previous, next_instance = [], [], [], 0
    for frame in frames:
        analysis = frame.get('analysis', {})
        candidates = sorted((c for c in packet['candidates'] if c['frame_id'] == frame['id']), key=lambda c: c['index'])
        current = []
        for candidate, group in zip(candidates, analysis.get('groups', [])):
            top, bottom, spacing = group['top'], group['bottom'], group['spacing']
            if not all(type(v) in (int, float) and math.isfinite(v) for v in (top, bottom, spacing)) or spacing <= 0 or abs(bottom-top-4*spacing) > spacing/2:
                issues.append(dict(reason='uncertain_staff_geometry', frame_id=frame['id']))
                continue
            current.append(dict(id=candidate['id'], frame_id=frame['id'], instance_id='',
                                staff_y=analysis['bbox'][1]+top, spacing=spacing,
                                bbox=copy.deepcopy(candidate['bbox']), complete=False,
                                evidence='Script five-line geometry suggestion; visual confirmation required.'))
        pairs = []
        if previous:
            possibilities = {}
            for a in previous:
                for b in current:
                    delta = a['staff_y']-b['staff_y']
                    if delta < -min(a['spacing'], b['spacing'])/2:
                        continue
                    matches = [(x, y) for x in previous for y in current
                               if abs(x['staff_y']-y['staff_y']-delta) <= min(x['spacing'], y['spacing'])/2
                               and abs(x['spacing']/y['spacing']-1) <= .03
                               and abs((x['bbox'][2]-x['bbox'][0])/(y['bbox'][2]-y['bbox'][0])-1) <= .03
                               and abs(x['bbox'][0]-y['bbox'][0]) <= max(2, x['spacing']/2)]
                    if len(matches) >= 2 and len({x['id'] for x,y in matches}) == len(matches) == len({y['id'] for x,y in matches}):
                        key = tuple((x['id'], y['id']) for x,y in matches)
                        possibilities[key] = matches
            best = max((len(p) for p in possibilities.values()), default=0)
            winners = [p for p in possibilities.values() if len(p) == best]
            if len(winners) == 1:
                pairs = winners[0]
            else:
                issues.append(dict(reason='uncertain_correspondence', from_frame=previous[0]['frame_id'], to_frame=frame['id']))
            structure['transitions'].append(dict(from_frame=previous[0]['frame_id'], to_frame=frame['id'],
                matches=[[a['id'],b['id']] for a,b in pairs], evidence='Script ordered common-displacement suggestion; Agent must confirm identity.'))
            audits.append(dict(from_frame=previous[0]['frame_id'], to_frame=frame['id'],
                               status='suggested' if pairs else 'uncertain', matches=[[a['id'],b['id']] for a,b in pairs]))
        for a,b in pairs:
            b['instance_id'] = a['instance_id']
        for sighting in current:
            if not sighting['instance_id']:
                sighting['instance_id'] = f'suggested-{next_instance:03d}'
                next_instance += 1
            if not any(r['instance_id'] == sighting['instance_id'] for r in structure['rows']):
                details = [i['id'] for i in packet['images'] if i.get('frame_id') == frame['id'] and i['kind'] in ('detail','native_detail')]
                structure['rows'].append(dict(instance_id=sighting['instance_id'], observation_id=sighting['id'],
                    frame_id=frame['id'], coordinate_space='native_pixels', roi=[0,0,frame['width'],frame['height']],
                    bbox=copy.deepcopy(sighting['bbox']), evidence_images=details, complete=False,
                    cursor='uncertain', occlusion='uncertain', boundary_verified=False,
                    evidence='Script crop suggestion; native detail review required.'))
        if not current:
            issues.append(dict(reason='missing_staff_geometry', frame_id=frame['id']))
        structure['observations'].extend(current)
        previous = current
    return dict(structure=structure, issues=issues, geometry=audits, basis='five_line_geometry_and_spatial_order', visual_review=False)
