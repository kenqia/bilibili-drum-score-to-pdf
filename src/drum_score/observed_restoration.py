"""Copy same-position exposed source pixels only after registration succeeds."""
import numpy as np
from PIL import Image


def _colored(pixels):
    return pixels.max(axis=2).astype(np.int16) - pixels.min(axis=2) > 40


def _rectangles(mask):
    """Coalesce identical horizontal runs; boxes never include unmasked pixels."""
    active = {}
    for y, row in enumerate(mask):
        edges = np.flatnonzero(np.diff(np.pad(row.astype(np.int8), (1, 1))))
        current = {}
        for left, right in zip(edges[::2], edges[1::2]):
            key = int(left), int(right)
            current[key] = active.pop(key, [int(left), y, int(right), y])
            current[key][3] = y + 1
        yield from active.values()
        active = current
    yield from active.values()


def restore(output, paths, region, placements, records, invalid, *, match_region, check):
    """A screen mask certifies obstruction; a translated unmasked sample exposes it.

    Never select a pixel by brightness, temporal median or majority. A mark that
    moves with the source has no screen-mask evidence and remains untouched.
    """
    width, height = region[2] - region[0], region[3] - region[1]
    fixed = np.zeros((height, width), dtype=bool)
    if invalid is not None:
        x, y = region[0] - match_region[0], region[1] - match_region[1]
        fixed = invalid[y:y + height, x:x + width]
    report = {'method': 'registered_exposed_source_pixels', 'restored_pixels': 0,
              'unrecovered_masked_pixels': 0, 'blocks': [],
              'unconfirmed_overlays': 'retained', 'musically_proofread': False}
    if not fixed.any():
        return report
    with Image.open(output) as image:
        result = np.array(image.convert('RGB'))
    end = 0
    for owner in placements:
        check()
        offset = owner['offset']
        begin, finish = end, offset + height
        if finish <= begin:
            continue
        end = finish
        for top in range(begin, finish, 256):
            check()
            bottom = min(top + 256, finish)
            pending = fixed[top - offset:bottom - offset].copy()
            for candidate in placements:
                if not pending.any():
                    break
                if candidate['sample'] == owner['sample']:
                    continue
                other = candidate['offset']
                a, b = max(top, other), min(bottom, other + height)
                if b <= a:
                    continue
                check()
                with Image.open(paths[candidate['sample']]) as image:
                    pixels = np.array(image.convert('RGB').crop((region[0], region[1] + a - other,
                                                               region[2], region[1] + b - other)))
                exposed = pending[a - top:b - top] & ~fixed[a - other:b - other] & ~_colored(pixels)
                if not exposed.any():
                    continue
                target = result[a:b]
                target[exposed] = pixels[exposed]
                pending[a - top:b - top][exposed] = False
                record = records[candidate['sample']]
                for left, upper, right, lower in _rectangles(exposed):
                    report['blocks'].append({'source_sample': candidate['sample'],
                        'source_pts': record['pts'], 'source_time_base': record['time_base'],
                        'source_timestamp': record['timestamp'], 'original_sample': owner['sample'],
                        'original_box': [region[0] + left, region[1] + a + upper - offset,
                                         region[0] + right, region[1] + a + lower - offset],
                        'source_box': [region[0] + left, region[1] + a + upper - other,
                                       region[0] + right, region[1] + a + lower - other],
                        'target_box': [left, a + upper, right, a + lower],
                        'evidence': 'screen_fixed_mask_and_registered_unmasked_observation'})
                report['restored_pixels'] += int(exposed.sum())
            report['unrecovered_masked_pixels'] += int(pending.sum())
    Image.fromarray(result).save(output)
    return report
