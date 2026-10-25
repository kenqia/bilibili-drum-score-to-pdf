"""Screen-fixed ink needs independently aligned scrolling evidence."""
import cv2
import numpy as np
from PIL import Image

from .registration import profile_of, shift_candidates, pick


def detect(paths, region, check=lambda: None):
    from .imaging import _ink_overlap
    height, width = region[3] - region[1], region[2] - region[0]
    votes = np.zeros((height, width), np.uint16)
    comparisons = 0
    previous = None
    previous_profile = None
    # At most 32 small working pairs; never retain a native image stack.
    stride = max(1, (len(paths) + 31) // 32)
    for path in paths[::stride]:
        check()
        with Image.open(path) as original:
            pixels = np.asarray(original.convert('RGB').crop(region))
        gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
        profile = profile_of(gray, np.zeros(gray.shape, dtype=bool))
        if previous is not None:
            minimum = max(32, height // 2)
            candidates = shift_candidates(previous_profile, profile, -2, height - minimum, minimum)
            shift, _ = pick(candidates, .1, strict=True, reject_ambiguity=True)
            delta = max(0, round(shift)) if shift is not None else 0
            if delta >= 8:
                similarity, ink = _ink_overlap(previous, pixels, delta)
                if similarity >= .65 and ink >= 128:
                    before = cv2.cvtColor(previous, cv2.COLOR_RGB2GRAY).astype(np.int16)
                    after = gray.astype(np.int16)
                    # A screen-stationary mark must contradict the proven
                    # translated source, in both coordinate systems.
                    difference = abs(before[delta:] - after[:-delta]) > 32
                    conflict = np.zeros(gray.shape, dtype=bool)
                    conflict[:-delta] |= difference
                    conflict[delta:] |= difference
                    stable_ink = (abs(before - after) <= 3) & (before < 210) & (after < 210)
                    votes += stable_ink & conflict
                    comparisons += 1
        previous, previous_profile = pixels, profile
    if comparisons < 3:
        return np.zeros((height, width), dtype=bool), comparisons
    mask = votes >= max(3, int(np.ceil(comparisons * .8)))
    # Protect antialiased mark edges without modifying RGB or inferring content.
    mask = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    return mask, comparisons
