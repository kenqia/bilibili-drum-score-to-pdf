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
    first, second = a.min(axis=2), b.min(axis=2)
    unexplained = ((first < 245) & (second > 250) | (second < 245) & (first > 250)) & valid
    if unexplained.any():
        return False
    return (ink >= 128 and score >= .98 and valid.mean() > .5
            and np.abs(a.astype(np.int16) - b)[valid].mean() < 2)


def _notation(pixels, invalid):
    from .imaging import _matching_invalid
    ink = (pixels.min(axis=2) < 150).astype(np.uint8)
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        np.ones((1, max(20, int(pixels.shape[1] * .6))), np.uint8))
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


def _replace_bottom_fragment(old, new, invalid):
    # Only a detached, boundary-touching fragment may be removed. Every visible
    # pixel must match one unique location inside a complete later observation.
    ink = old.min(axis=2) < 180
    blank = np.flatnonzero(~ink.any(axis=1))
    if not len(blank):
        return None
    top = int(blank[-1]) + 1
    if not 0 < len(old) - top <= len(old) // 3:
        return None
    template = ink[top:].astype(np.float32)
    independent = int(np.count_nonzero(_notation(old, invalid)[top:]))
    if independent < 32:
        return None
    target = (new.min(axis=2) < 180).astype(np.float32)
    cost = cv2.matchTemplate(target, template, cv2.TM_SQDIFF_NORMED).ravel()
    matches = np.flatnonzero(cost < .08)
    if not len(matches) or matches[-1] - matches[0] > 2:
        return None
    y = int(matches[np.argmin(cost[matches])])
    original, candidate = old[top:], new[y:y + len(template)]
    # Dark ink locates a candidate, but cannot license dropping pale dynamics,
    # colored text or other marks in the removed strip. Require agreement of
    # every observed RGB pixel, including pixels unknown during registration.
    difference = np.abs(original.astype(np.int16) - candidate.astype(np.int16))
    if np.any(difference > 8):
        return None
    return {'source_region': [0, top, old.shape[1], len(old)],
            'target_region': [0, y, new.shape[1], y + len(template)],
            'independent_ink_pixels': independent, 'pixel_cost': float(cost[y]),
            'trim_bottom_rows': len(old) - top}


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
    for owner in history:
        check()
        if _same(_pixels(owner['path'], region), b, invalid):
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
    # Edge replacement must use the actual adjacent native samples recorded
    # below, including their RGB playback marks, rather than another stable view.
    a, b = _pixels(paths[boundary - 1], region), _pixels(paths[boundary], region)
    replacement = None
    with Image.fromarray(b) as image:
        system_groups(image)
        verify_edges(image)
    with Image.fromarray(a) as image:
        system_groups(image)
        try:
            verify_edges(image, sides=('bottom',))
        except ConversionError:
            replacement = _replace_bottom_fragment(a, b, invalid)
            if replacement is None:
                raise
            # Compose can have retained an earlier RGB observation of this
            # position. Every possible owner of the removed strip must agree.
            fragment_top = replacement['source_region'][1]
            final_offset = history[-1]['offset']
            for owner in history:
                check()
                top = max(fragment_top + final_offset, owner['offset'])
                bottom = min(len(a) + final_offset, owner['offset'] + len(a))
                if bottom <= top:
                    continue
                observed = _pixels(owner['path'], region)[top - owner['offset']:bottom - owner['offset']]
                expected = a[top - final_offset:bottom - final_offset]
                if np.any(np.abs(observed.astype(np.int16) - expected.astype(np.int16)) > 8):
                    return None
    transition = {'kind': 'native_page_cut', 'continuity': 'unverified',
        'native_sequence': records[boundary]['decode_sequence'],
        'adjacent_native_ordinals': [boundary - 1, boundary],
        'cut_range_seconds': [records[boundary - 1]['timestamp'], records[boundary]['timestamp']],
        'stable_native_frames': [boundary, len(paths) - boundary]}
    if replacement is not None:
        transition['edge_replacement'] = replacement
    return boundary, transition
