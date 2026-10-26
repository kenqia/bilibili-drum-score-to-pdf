"""Video page order needs observed native cuts, never a motion prior."""
import cv2
import numpy as np
from PIL import Image

from .video_seek import ConversionError


def _pixels(path, region):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB').crop(region))


def _same(a, b, invalid):
    from .imaging import _ink_overlap, _matching_invalid
    valid = ~(_matching_invalid(a, invalid) | _matching_invalid(b, invalid))
    score, ink = _ink_overlap(a, b, 0, invalid)
    return (ink >= 128 and score >= .98 and valid.mean() > .5
            and np.abs(a.astype(np.int16) - b)[valid].mean() < 2)


def _notation(pixels, invalid):
    from .imaging import _matching_invalid
    ink = (pixels.min(axis=2) < 150).astype(np.uint8)
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        np.ones((1, max(20, pixels.shape[1] // 12)), np.uint8))
    return (ink & ~horizontal).astype(bool) & ~_matching_invalid(pixels, invalid)


def _possible_overlap(a, b, invalid):
    # Staff lines alone cannot establish a position. Search both directions so
    # a backward continuation cannot become a forward page cut.
    first, second = _notation(a, invalid), _notation(b, invalid)
    minimum = max(32, len(first) // 12)
    for delta in range(-len(first) + minimum, len(first) - minimum + 1):
        top, bottom = max(0, delta), min(len(first), len(first) + delta)
        x, y = first[top:bottom], second[top - delta:bottom - delta]
        union = np.count_nonzero(x | y)
        if union >= 64 and np.count_nonzero(x & y) / union > .65:
            return True
    return False


def prove_cut(paths, records, region, old_path, new_path, history, check, invalid=None):
    """Return one native cut only when all retained observations support it."""
    from .imaging import system_groups, verify_edges
    if len(paths) < 4:
        return None
    if any(right['timestamp'] <= left['timestamp']
           or right['native_ordinal'] != left['native_ordinal'] + 1
           or right['previous_native_pts'] != left['pts']
           or right['decode_sequence'] != left['decode_sequence']
           for left, right in zip(records, records[1:])):
        return None
    a, b = _pixels(old_path, region), _pixels(new_path, region)
    if _possible_overlap(a, b, invalid):
        return None
    for path in history:
        check()
        if _same(_pixels(path, region), b, invalid):
            return None
    sides = []
    for path in paths:
        check()
        pixels = _pixels(path, region)
        if _same(pixels, a, invalid):
            sides.append(0)
        elif _same(pixels, b, invalid):
            sides.append(1)
        else:
            # A third page or transition containing unique notation is not
            # expendable. Keep the conversion failed until it can be covered.
            return None
    boundary = next((index for index, side in enumerate(sides) if side == 1), None)
    if boundary is None or boundary < 2 or len(sides) - boundary < 2:
        return None
    if sides != [0] * boundary + [1] * (len(sides) - boundary):
        return None
    for pixels in (a, b):
        with Image.fromarray(pixels) as image:
            system_groups(image)
            verify_edges(image)
    return boundary, {'kind': 'native_page_cut', 'continuity': 'unverified',
        'native_sequence': records[boundary]['decode_sequence'],
        'adjacent_native_ordinals': [boundary - 1, boundary],
        'cut_range_seconds': [records[boundary - 1]['timestamp'], records[boundary]['timestamp']],
        'stable_native_frames': [boundary, len(paths) - boundary]}
