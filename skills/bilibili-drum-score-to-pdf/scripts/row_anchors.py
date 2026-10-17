"""Source-bound printed bar anchors. OCR is a reading, not a continuity proof."""
from functools import lru_cache
import hashlib
import math
import re

import numpy as np
from PIL import ImageOps

POLICY = 'printed-row-bars/1'


@lru_cache(maxsize=1)
def _recognizer():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


@lru_cache(maxsize=1024)
def _read_patch(size, pixels):
    from PIL import Image
    patch = Image.frombytes('RGB', size, pixels)
    readings = []
    try:
        for scale in (2, 3):
            enlarged = ImageOps.expand(patch.resize((patch.width*scale, patch.height*scale)), border=8, fill='white')
            result, _ = _recognizer()(np.asarray(enlarged), use_det=False, use_cls=False)
            if not result or len(result) != 1:
                return None, None
            text, score = result[0]
            if not re.fullmatch(r'[1-9][0-9]{0,4}', text.strip()) or float(score) < .9:
                return None, float(score)
            readings.append((int(text), float(score)))
    except (ImportError, RuntimeError, ValueError, OSError):
        return None, None
    return (readings[0][0], min(v[1] for v in readings)) if readings[0][0] == readings[1][0] else (None, None)


def read(image, regions):
    result = []
    for index, row in enumerate(r for r in regions if r['kind'] == 'system'):
        spacing = row['staff_spacing']
        top = row['bbox'][1] + row['staff_top']
        left = row['evidence'].get('staff_left', row['bbox'][0]+spacing)
        box = [max(0, round(left-spacing)), max(0, round(top-4*spacing)),
               min(image.width, round(left+3*spacing)), max(0, round(top-spacing))]
        patch = image.crop(box).convert('RGB')
        yy, xx = np.where(np.asarray(patch).min(axis=2) < 180)
        value, score = None, None
        if len(xx):
            patch = patch.crop((int(xx.min()), int(yy.min()), int(xx.max())+1, int(yy.max())+1))
            value, score = _read_patch(patch.size, patch.tobytes())
        result.append({'row': index, 'bbox': row['bbox'], 'start_bar': value,
            'producer': 'program', 'policy_version': POLICY, 'score': score,
            'reading_bbox': box, 'reading_sha256': hashlib.sha256(patch.tobytes()).hexdigest()})
    values = [r['start_bar'] for r in result if r['start_bar'] is not None]
    if any(a >= b for a, b in zip(values, values[1:])):
        for row in result:
            row['conflict'] = 'nonincreasing_printed_bars'
    return result


def readings(record, shot, image, regions, *, task=None):
    observed = record.get('row_manifest', {}).get('observations', {}).get(shot['id'], {})
    boxes = [r['bbox'] for r in regions if r['kind'] == 'system']
    cached = observed.get('anchors')
    if (cached is not None and [a['bbox'] for a in cached] == boxes and
            all(a['start_bar'] is not None and a.get('policy_version') == POLICY for a in cached)):
        return cached
    result = read(image, regions)
    for review in record.get('row_anchor_reviews', []):
        if (review['capture'] == shot['id'] and review['sha256'] == shot['sha256'] and
                review['source_sha256'] == record['source']['sha256']):
            for anchor in review['anchors']:
                if anchor['row'] < len(result) and anchor['bbox'] == result[anchor['row']]['bbox']:
                    result[anchor['row']] = anchor
    if task is not None and any(a['start_bar'] is None for a in result):
        import score_geometry as observed
        import score_task as state
        from PIL import Image
        captures = {s['id']: s for s in record['captures']}
        observations = record.get('row_manifest', {}).get('observations', {})
        for identifier, observation in reversed(list(observations.items())):
            prior = observation.get('anchors', [])
            if (identifier == shot['id'] or len(prior) != len(result) or
                    any(a['start_bar'] is None or a.get('conflict') for a in prior) or
                    not any(a['start_bar'] is not None for a in result) or
                    any(a['start_bar'] is not None and a['start_bar'] != b['start_bar'] for a, b in zip(result, prior))):
                continue
            with Image.open(state.artifact(task, captures[identifier])) as original:
                same = observed.same_observation(original, image)
                if not same:
                    old_regions = observation['regions']
                    old_rows = [r for r in old_regions if r['kind'] == 'system']
                    new_rows = [r for r in regions if r['kind'] == 'system']
                    spacing = max(1, round(new_rows[0]['staff_spacing'])) if new_rows else 1
                    old_headers = [r for r in old_regions if r['kind'] == 'header']
                    new_headers = [r for r in regions if r['kind'] == 'header']
                    same = (len(old_rows) == len(new_rows) and len(old_headers) == len(new_headers) and
                        all(abs(a['bbox'][1]+a['staff_top']-b['bbox'][1]-b['staff_top']) <= 2 and
                            observed.same_row(original, a, image, b, spacing) for a, b in zip(old_rows, new_rows)) and
                        all(observed.same_ink(observed.signature(original.crop(a['bbox'])),
                            observed.signature(image.crop(b['bbox']))) for a, b in zip(old_headers, new_headers)))
            if same:
                for index, anchor in enumerate(result):
                    if anchor['start_bar'] is None:
                        result[index] = {**anchor, 'start_bar': prior[index]['start_bar'], 'producer': 'program',
                            'method': 'verified_same_page_anchor', 'reference_capture': identifier,
                            'reference_sha256': captures[identifier]['sha256'], 'reference_row': index}
                break
    # Ordering conflicts are derived from the merged readings, including Agent corrections.
    for anchor in result:
        if anchor.get('conflict') == 'nonincreasing_printed_bars':
            anchor.pop('conflict')
    values = [a['start_bar'] for a in result if a['start_bar'] is not None]
    if any(a >= b for a, b in zip(values, values[1:])):
        for anchor in result:
            anchor['conflict'] = 'nonincreasing_printed_bars'
    return result


def fallback_allowed(record, shot):
    return any(r.get('fallback_interval') and r['source_sha256'] == record['source']['sha256'] and
               r['fallback_interval'][0] <= shot['timestamp'] <= r['fallback_interval'][1]
               for r in record.get('row_anchor_reviews', []))


def missing(record, shot, anchors):
    fallback = fallback_allowed(record, shot)
    return [{'code': 'row_anchor_conflict' if a.get('conflict') else 'row_anchor_missing',
             'capture': shot['id'], 'bbox': a['bbox'], 'row': a['row'],
             'reading_bbox': a.get('reading_bbox'), 'scope': 'source_region',
             'resume': 'review-row-anchors'}
            for a in anchors if (a['start_bar'] is None and not fallback) or a.get('conflict')]


def review(task, capture, anchors, viewed_captures, notes, fallback_interval=None):
    import score_task as state
    import score_geometry as observed
    from PIL import Image
    record = state.load(task)
    shots = {s['id']: s for s in record['captures']}
    if (not isinstance(capture, str) or capture not in shots or
            not isinstance(viewed_captures, list) or not all(isinstance(v, str) for v in viewed_captures) or
            capture not in viewed_captures or not set(viewed_captures).issubset(shots) or
            not isinstance(notes, str) or not notes.strip() or not isinstance(anchors, list)):
        raise state.ReconstructionError('需要实际查看的来源、逐行读数和具体依据。')
    with Image.open(state.artifact(task, shots[capture])) as image:
        systems = [r for r in observed.detect(image)[0] if r['kind'] == 'system']
    saved = []
    for anchor in anchors:
        if (not isinstance(anchor, dict) or type(anchor.get('row')) is not int or
                not 0 <= anchor['row'] < len(systems) or type(anchor.get('start_bar')) is not int or
                not 1 <= anchor['start_bar'] <= 99999 or any(a['row'] == anchor['row'] for a in saved)):
            raise state.ReconstructionError('逐行锚点需要有效的谱行索引和正整数行首小节号。')
        saved.append({'row': anchor['row'], 'bbox': systems[anchor['row']]['bbox'],
            'start_bar': anchor['start_bar'], 'producer': 'agent', 'policy_version': POLICY, 'notes': notes.strip()})
    ordered = sorted(saved, key=lambda a: a['row'])
    if any(a['start_bar'] >= b['start_bar'] for a, b in zip(ordered, ordered[1:])):
        raise state.ReconstructionError('同页编号顺序冲突，不能直接作为位置锚点。')
    if fallback_interval is not None:
        if (not isinstance(fallback_interval, list) or len(fallback_interval) != 2 or
                any(type(v) not in (float, int) or not math.isfinite(v) for v in fallback_interval) or
                not 0 <= fallback_interval[0] < fallback_interval[1] <= record['source']['duration'] or
                not fallback_interval[0] <= shots[capture]['timestamp'] <= fallback_interval[1] or
                len(set(viewed_captures)) < 2):
            raise state.ReconstructionError('替代证据授权需要有界视频区间及至少两张实际查看的来源。')
    if not saved and fallback_interval is None:
        raise state.ReconstructionError('需要读数或明确的局部替代证据授权。')
    receipt = {'producer': 'agent', 'capture': capture, 'sha256': shots[capture]['sha256'],
        'source_sha256': record['source']['sha256'], 'anchors': saved,
        'viewed_captures': viewed_captures, 'viewed_sha256': {v: shots[v]['sha256'] for v in viewed_captures},
        'notes': notes.strip(), 'fallback_interval': fallback_interval}
    record.setdefault('row_anchor_reviews', []).append(receipt)
    # Other complete pages may inherit this reading transitively. Rebuild derived
    # readings from source-bound review receipts rather than retain stale copies.
    for observation in record.get('row_manifest', {}).get('observations', {}).values():
        observation.pop('anchors', None)
    record.pop('freeze', None)
    state.save(task, record)
    return receipt
