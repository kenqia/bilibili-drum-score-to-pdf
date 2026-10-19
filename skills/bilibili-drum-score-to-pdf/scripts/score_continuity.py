"""Source-bound row continuity evidence shared by navigation and freezing.

compare returns the existing proved/new_complete_rows/overlap_rows/reason
receipt and optional matches. A printed-bar gap or content conflict prevents
pixel deduplication in selection, but does not prove continuity. Numbered joins
and strict time coverage remain separate evidence. This module does not choose
sampling positions, publish task state, or approve source completeness.
"""
from PIL import Image
import cv2
import score_geometry
import score_task as state
import row_manifest
import row_anchors

NAVIGATION_POLICY = 'adaptive-score-rows/2'


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
        old_regions = old['regions'] if old else score_geometry.detect(old_image)[0]
        new_detection = None if new else score_geometry.detect(new_image)
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
        if use_anchors and (not complete_anchors or len(old_anchors) != len(old_rows) or
                            len(new_anchors) != len(new_rows)):
            return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                    'overlap_rows': 0, 'reason': 'row_anchor_needs_review', 'visual_review_needed': True,
                    'anchors': {'previous': [a.get('start_bar') for a in old_anchors],
                                'current': [a.get('start_bar') for a in new_anchors]},
                    'action': 'review-row-anchors or assemble with actual source evidence'}
        if complete_anchors:
            values = [[a['start_bar'] for a in anchors] for anchors in (old_anchors, new_anchors)]
            if any(any(type(v) is not int or v < 1 for v in group) or
                   any(a >= b for a, b in zip(group, group[1:])) for group in values):
                return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                        'overlap_rows': 0, 'reason': 'row_anchor_conflict', 'visual_review_needed': True}
        if numbered_evidence(record, first, last):
            return {'proved': True, 'new_complete_rows': len(complete_indices), 'overlap_rows': 0,
                    'reason': 'numbered_new_positions', 'matches': {}}
        same_numbers = not complete_anchors or [a['start_bar'] for a in old_anchors] == [a['start_bar'] for a in new_anchors]
        if same_numbers and score_geometry.same_observation(old_image, new_image):
            return {'proved': True, 'new_complete_rows': 0, 'overlap_rows': len(new_rows),
                    'reason': 'repeated_rows', 'matches': {index: index for index in range(min(len(old_rows), len(new_rows)))}}
        if not old_rows or not new_rows:
            return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                    'overlap_rows': 0, 'reason': 'layout_or_endpoint_gap'}
        spacing = max(1, round(old_rows[0]['staff_spacing']))
        old_signatures = [score_geometry.row_signature(old_image, r, spacing=spacing) for r in old_rows]
        new_signatures = [score_geometry.row_signature(new_image, r, spacing=spacing) for r in new_rows]
        if use_anchors and len(old_anchors) == len(old_rows) and len(new_anchors) == len(new_rows):
            old_values = [a['start_bar'] for a in old_anchors]
            new_values = [a['start_bar'] for a in new_anchors]
            mapping = {j: old_values.index(value) for j, value in enumerate(new_values) if value in old_values}
            native = {first['id']: score_geometry.signature(old_image), last['id']: score_geometry.signature(new_image)}
            if any(not score_geometry.same_row(old_image, old_rows[i], new_image, new_rows[j], spacing)
                   and not score_geometry.native_visible_match(old_rows[i], new_rows[j], native.__getitem__)
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
        overlaps = score_geometry.overlap_sizes(old_signatures, new_signatures)
        if len(overlaps) == 1:
            return {'proved': True, 'new_complete_rows': len(complete_indices-set(range(overlaps[0]))),
                    'overlap_rows': overlaps[0], 'reason': 'unique_row_overlap',
                    'matches': {index: len(old_rows) - overlaps[0] + index for index in range(overlaps[0])}}
        masks = {first['id']: score_geometry.signature(old_image), last['id']: score_geometry.signature(new_image)}
        mapping = score_geometry.spatial_continuation(old_rows, new_rows,
            [score_geometry.row_signature(old_image, r, core=True, spacing=spacing) for r in old_rows],
            [score_geometry.row_signature(new_image, r, core=True, spacing=spacing) for r in new_rows], masks.__getitem__)
        if mapping:
            return {'proved': True, 'new_complete_rows': len(complete_indices-set(mapping)),
                    'overlap_rows': len(mapping), 'reason': 'unique_scroll', 'matches': mapping}
        small_old = [cv2.resize(value, (480, 128), interpolation=cv2.INTER_AREA) for value in old_signatures]
        small_new = [cv2.resize(value, (480, 128), interpolation=cv2.INTER_AREA) for value in new_signatures]
        tentative = [(i, j) for i, a in enumerate(small_old) for j, b in enumerate(small_new)
                     if score_geometry.same_ink(a, b)]
        same_layout = len(old_rows) == len(new_rows) and all(score_geometry.same_ink(a, b) for a, b in zip(small_old, small_new))
        if same_layout or (len({i for i, _ in tentative}) >= 2 and len({j for _, j in tentative}) >= 2):
            # Only a search heuristic. It cannot approve symbols or row identity.
            return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows),
                    'overlap_rows': 0, 'reason': 'similar_rows_need_review', 'visual_review_needed': True}
        return {'proved': False, 'new_complete_rows': None, 'detected_complete_rows': len(new_rows), 'overlap_rows': 0,
                'reason': 'unproved_row_continuation'}
