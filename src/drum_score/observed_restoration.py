"""Copy same-position exposed source pixels only after registration succeeds."""
import numpy as np
import cv2
from PIL import Image

MAX_BLOCKS = 4096


def _colored(pixels):
    return pixels.max(axis=2).astype(np.int16) - pixels.min(axis=2) > 40


def _cursor_boxes(paths, region, placements, check):
    """Certify only narrow bars which move and expose their old source position."""
    width, height = region[2] - region[0], region[3] - region[1]
    bars = {}
    for item in placements:
        check()
        with Image.open(paths[item['sample']]) as image:
            pixels = np.array(image.convert('RGB').crop(region))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(_colored(pixels).astype(np.uint8))
        found = []
        for label in range(1, count):
            x, y, w, h, area = map(int, stats[label])
            if not (1 <= w <= max(4, int(width * .035)) and h >= height * .75 and area == w * h):
                continue
            color = pixels[y, x]
            if np.max(np.abs(pixels[y:y+h, x:x+w].astype(np.int16) - color)) <= 3:
                found.append((x, y, w, h, tuple(map(int, color))))
        bars[item['sample']] = found
    proven = {item['sample']: [] for item in placements}
    for owner in placements:
        for x, y, w, h, color in bars[owner['sample']]:
            covered = np.zeros(h, dtype=bool)
            for other in placements:
                check()
                if other['sample'] == owner['sample']:
                    continue
                top = max(y + owner['offset'], other['offset'])
                bottom = min(y + h + owner['offset'], other['offset'] + height)
                if bottom - top < height * .5:
                    continue
                first, last = top - owner['offset'] - y, bottom - owner['offset'] - y
                if covered[first:last].all():
                    continue
                # The same bar appears elsewhere on screen. A source-colored
                # notation mark that never disappears cannot satisfy this test.
                relocated = any(abs(bx - x) > w and by == y and bw == w and bh == h and bc == color
                    for bx, by, bw, bh, bc in bars[other['sample']])
                if not relocated:
                    continue
                with Image.open(paths[other['sample']]) as image:
                    witness = np.array(image.convert('RGB').crop((region[0] + x,
                        region[1] + top - other['offset'], region[0] + x + w,
                        region[1] + bottom - other['offset'])))
                if not _colored(witness).any():
                    proven[owner['sample']].append((x, top - owner['offset'], x + w,
                                                   bottom - owner['offset']))
                    covered[first:last] = True
                    if covered.all():
                        break
    return proven


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
              'block_limit_reached': False,
              'unconfirmed_overlays': 'retained', 'musically_proofread': False}
    cursors = _cursor_boxes(paths, region, placements, check)
    if not fixed.any() and not any(cursors.values()):
        return report
    def mask_for(sample):
        mask = fixed.copy()
        for left, top, right, bottom in cursors[sample]:
            mask[top:bottom, left:right] = True
        return mask
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
        owner_mask = mask_for(owner['sample'])
        for top in range(begin, finish, 256):
            check()
            bottom = min(top + 256, finish)
            pending = owner_mask[top - offset:bottom - offset].copy()
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
                exposed = pending[a - top:b - top] & ~mask_for(candidate['sample'])[a - other:b - other] & ~_colored(pixels)
                if not exposed.any():
                    continue
                boxes = []
                for box in _rectangles(exposed):
                    boxes.append(box)
                    if len(boxes) + len(report['blocks']) > MAX_BLOCKS:
                        break
                if len(boxes) + len(report['blocks']) > MAX_BLOCKS:
                    report['block_limit_reached'] = True
                    continue
                target = result[a:b]
                target[exposed] = pixels[exposed]
                pending[a - top:b - top][exposed] = False
                record = records[candidate['sample']]
                for left, upper, right, lower in boxes:
                    report['blocks'].append({'source_sample': candidate['sample'],
                        'source_pts': record['pts'], 'source_time_base': record['time_base'],
                        'source_timestamp': record['timestamp'], 'original_sample': owner['sample'],
                        'original_box': [region[0] + left, region[1] + a + upper - offset,
                                         region[0] + right, region[1] + a + lower - offset],
                        'source_box': [region[0] + left, region[1] + a + upper - other,
                                       region[0] + right, region[1] + a + lower - other],
                        'target_box': [left, a + upper, right, a + lower],
                        'evidence': 'proven_screen_overlay_and_registered_unmasked_observation'})
                report['restored_pixels'] += int(exposed.sum())
            report['unrecovered_masked_pixels'] += int(pending.sum())
    Image.fromarray(result).save(output)
    return report
