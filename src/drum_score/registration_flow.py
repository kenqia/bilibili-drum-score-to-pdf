"""Bounded recovery using actual native observations, never invented positions."""
import math

from .video_seek import ConversionError

MAX_REFINEMENT_REQUESTS = 64
MAX_REFINEMENT_INTERVALS = 12
MAX_REFINEMENT_SPAN = 2.0


def register_refined(paths, region, records, refine, check, *, invalid=None):
    from .imaging import register
    attempted = {}
    narrow = []
    requests = 0
    evidence = []
    resume = None
    while True:
        check()
        try:
            placements = register(paths, region, observations=records,
                budget_check=check, invalid=invalid, resume=resume,
                allow_narrow=lambda left, right: any(
                    begin <= records[left]['timestamp'] <= records[right]['timestamp'] <= end
                    for begin, end in narrow))
            return placements, {'refinement_requests': requests, 'intervals': evidence,
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
                    raise
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
