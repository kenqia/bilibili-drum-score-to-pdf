"""Bounded recovery using actual native observations, never invented positions."""
import math

from .video_seek import ConversionError

MAX_REFINEMENT_REQUESTS = 64
MAX_REFINEMENT_INTERVALS = 12
MAX_REFINEMENT_SPAN = 2.0


def register_refined(paths, region, records, refine, check, *, invalid=None, native_window=None, bounds=None):
    from .imaging import register
    attempted = {}
    narrow = []
    requests = 0
    evidence = []
    resume = None
    native_attempted = set()
    # A native excursion larger than the endpoint difference can hide a short
    # page. Inspect its actual peak-change frame before allowing that page to
    # disappear between them. These seeks share the existing request budget.
    from PIL import Image
    import numpy as np
    index = 1
    while index < len(records):
        check()
        left, right = records[index - 1], records[index]
        witness = right.get('native_motion_peak_change_timestamp')
        if (witness is not None and left['timestamp'] < witness < right['timestamp']
                and right.get('native_intermediate_frames', 0) > 0):
            with Image.open(paths[index - 1]) as before, Image.open(paths[index]) as after:
                a, b = before.convert('L'), after.convert('L')
                a.thumbnail((128, 128))
                b.thumbnail((128, 128))
                difference = float(np.abs(np.asarray(a).astype(np.int16) - np.asarray(b)).mean())
            if right.get('native_motion_max_luma_difference', 0) > max(1, difference * 2):
                if (requests >= MAX_REFINEMENT_REQUESTS
                        or len(attempted) >= MAX_REFINEMENT_INTERVALS):
                    raise ConversionError('discontinuity', '补帧预算耗尽，短暂画面覆盖未能确认。')
                attempted[(left['timestamp'], right['timestamp'])] = 0
                requests += 1
                path, record = refine(witness)
                if not left['timestamp'] < record['timestamp'] < right['timestamp']:
                    raise ConversionError('discontinuity', '未能取得采样间的原生变化画面。')
                paths.insert(index, path)
                records.insert(index, {**record, 'requires_unique_registration': True,
                    'native_change_coverage_witness': True})
                evidence.append({'start_seconds': left['timestamp'], 'end_seconds': right['timestamp'],
                    'reason': 'native_change_excursion', 'requested': 1, 'added': 1})
                index += 1
        index += 1
    while True:
        check()
        try:
            placements = register(paths, region, observations=records,
                budget_check=check, invalid=invalid, resume=resume,
                allow_narrow=lambda left, right: any(
                    begin <= records[left]['timestamp'] <= records[right]['timestamp'] <= end
                    for begin, end in narrow))
            return placements, {'continuity': ('unverified' if any(
                    item.get('transition', {}).get('kind') == 'native_page_cut' for item in placements)
                    else 'overlap_verified'), 'refinement_requests': requests, 'intervals': evidence,
                'transitions': [{'sample': item['sample'], **item['transition']}
                                for item in placements if 'transition' in item]}
        except ConversionError as error:
            interval = getattr(error, 'registration_interval', None)
            resume = getattr(error, 'registration_resume', None)
            if interval is None:
                raise
            left, right = interval
            begin, end = records[left]['timestamp'], records[right]['timestamp']
            if not 0 < end - begin <= MAX_REFINEMENT_SPAN:
                raise
            # Find an already refined parent interval after new frames split it.
            key = next((key for key in attempted if key[0] <= begin < end <= key[1]), (begin, end))
            stage = attempted.get(key, 0)
            if stage >= 2:
                if key in narrow:
                    if native_window is None or key in native_attempted or requests >= MAX_REFINEMENT_REQUESTS:
                        raise
                    native_attempted.add(key)
                    # Include two native observations on either side even for
                    # low-rate video; never exceed the existing two-second span.
                    margin = min(.5, max(.1, (end - begin) * 2))
                    lower = max(bounds[0], begin - margin)
                    upper = min(bounds[1], end + margin)
                    if upper - lower > MAX_REFINEMENT_SPAN:
                        raise
                    additions = native_window(lower, upper, MAX_REFINEMENT_REQUESTS - requests)
                    requests += len(additions)
                    from .page_transitions import prove_cut
                    proof = prove_cut([path for path, _ in additions],
                        [record for _, record in additions], region, paths[left], paths[right],
                        [paths[item['sample']] for item in resume['placements']], check, invalid)
                    if proof is None:
                        raise
                    boundary, transition = proof
                    additions[boundary][1]['page_transition'] = transition
                    lo = next(index for index, record in enumerate(records) if record['timestamp'] >= lower)
                    hi = next((index for index, record in enumerate(records) if record['timestamp'] >= upper), len(records))
                    paths[lo:hi] = [path for path, _ in additions]
                    records[lo:hi] = [record for _, record in additions]
                    evidence.append({'start_seconds': lower, 'end_seconds': upper,
                        'reason': 'native_page_cut', 'requested': len(additions), 'added': len(additions)})
                    resume = None
                    continue
                narrow.append(key)
                continue
            if key not in attempted and len(attempted) >= MAX_REFINEMENT_INTERVALS:
                raise
            attempted[key] = stage + 1
            spacing = (.25, .1)[stage]
            wanted = [begin + spacing * n for n in range(1, math.ceil((end - begin) / spacing))
                      if begin + spacing * n < end - 1e-6]
            if requests + len(wanted) > MAX_REFINEMENT_REQUESTS:
                raise
            additions = []
            known = {(record['pts'], tuple(record['time_base'])) for record in records}
            for timestamp in wanted:
                check()
                requests += 1
                path, record = refine(timestamp)
                identity = record['pts'], tuple(record['time_base'])
                # Seeking can return an endpoint or the same native frame twice.
                # Keep original decoder order, including delayed tail PTS.
                if begin < record['timestamp'] < end and identity not in known:
                    if additions and record['timestamp'] <= additions[-1][1]['timestamp']:
                        # Independent increasing seeks must not hide native PTS
                        # regression by sorting the observations after decoding.
                        raise error
                    known.add(identity)
                    additions.append((path, {**record, 'requires_unique_registration': True}))
            paths[right:right] = [path for path, _ in additions]
            records[right:right] = [record for _, record in additions]
            evidence.append({'start_seconds': begin, 'end_seconds': end,
                'spacing_seconds': spacing, 'requested': len(wanted), 'added': len(additions)})
