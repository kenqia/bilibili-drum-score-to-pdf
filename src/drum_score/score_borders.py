"""Remove only proven thin symmetric black video pillars from delivery crop."""
import numpy as np
from PIL import Image


def trim(paths, region, check=lambda: None):
    width = region[2] - region[0]
    limit = min(8, width // 100)
    if limit < 1:
        return region
    candidate = None
    for path in paths:
        check()
        with Image.open(path) as original:
            if tuple(region) != (0, 0, original.width, original.height):
                return region
            rgb = np.asarray(original.convert('RGB'))
        black = (rgb <= 8).all(axis=(0, 2))
        left = 0
        while left < width and black[left]:
            left += 1
        right = 0
        while right < width and black[width - 1 - right]:
            right += 1
        # H.264 can leave one constant gray transition column beside a black
        # pillar. Accept it only when the entire column remains achromatic and
        # uniform, then still require white paper immediately inside.
        def transition(column):
            values = rgb[:, column].astype(np.int16)
            return (values.max() <= 190 and int(values.max()) - int(values.min()) <= 8
                    and (values.max(axis=1) - values.min(axis=1)).max() <= 3)
        if 0 < left < limit and transition(left):
            left += 1
        if 0 < right < limit and transition(width - 1 - right):
            right += 1
        if not (1 <= left <= limit and 1 <= right <= limit and abs(left - right) <= 2):
            return region
        if candidate is not None and candidate != (left, right):
            return region
        candidate = left, right
        if ((rgb[:, left:left + 8] > 190).all(axis=2).mean() < .95
                or (rgb[:, width - right - 8:width - right] > 190).all(axis=2).mean() < .95):
            return region
    if candidate is None:
        return region
    return (region[0] + candidate[0], region[1], region[2] - candidate[1], region[3])
