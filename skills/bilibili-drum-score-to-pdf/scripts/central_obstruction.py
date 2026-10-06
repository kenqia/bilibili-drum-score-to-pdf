"""Conservative proof for held windows split by a full-height opaque rectangle.

This module only checks observations. Output always comes from a real clean row.
Scrolling and patch stitching require a separate occurrence/coverage model.
"""
import cv2
import numpy as np


def split_white_bbox(image):
    pixels = np.asarray(image.convert('RGB'))
    white = (pixels.min(axis=2) > 210).astype(np.uint8)
    closed = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    boxes = [box for box in stats[1:] if box[2] > image.width * .15 and box[3] > image.height * .5]
    if len(boxes) != 2:
        return None
    left, right = sorted(boxes, key=lambda b: b[0])
    if abs(int(left[1]) - int(right[1])) > 3 or abs(int(left[3]) - int(right[3])) > 3:
        return None
    gap = int(right[0] - left[0] - left[2])
    if not image.width * .05 < gap < image.width * .4:
        return None
    # Include codec ringing at the actual boundary; these pixels cannot prove ink.
    return [max(0, int(left[0] + left[2]) - 5), max(0, int(min(left[1], right[1])) - 5),
            min(image.width, int(right[0]) + 5), min(image.height, int(max(left[1] + left[3], right[1] + right[3])) + 5)]


def complementary_windows(before, after, observations):
    """Require real visible coverage of every pixel hidden in any observation."""
    references = [np.asarray(image.convert('RGB')).astype(np.int16) for image in (before, after)]
    if references[0].shape != references[1].shape:
        return None
    hidden_intersection = np.ones(references[0].shape[:2], dtype=bool)
    evidence = []
    for item, image in observations:
        bbox = split_white_bbox(image)
        observed = np.asarray(image.convert('RGB')).astype(np.int16)
        if bbox is None or observed.shape != references[0].shape:
            return None
        x0, y0, x1, y1 = bbox
        # Only a flat opaque panel is supported, never an arbitrary missing region.
        interior = observed[y0 + 10:y1 - 10, x0 + 10:x1 - 10]
        if interior.size == 0 or np.max(interior.max(axis=(0, 1)) - interior.min(axis=(0, 1))) > 8:
            return None
        hidden = np.zeros(observed.shape[:2], dtype=bool)
        hidden[y0:y1, x0:x1] = True
        # Both endpoints must agree with every observed visible pixel. Local
        # residuals reject small notation changes without whole-image dilution.
        residuals = []
        for reference in references:
            residual = np.abs(observed - reference).max(axis=2).astype(np.float32)
            residual[hidden] = 0
            maximum = float(cv2.blur(residual, (3, 3)).max())
            if maximum > 8:
                return None
            residuals.append(round(maximum, 3))
        hidden_intersection &= hidden
        evidence.append(dict(item, occluded_bbox=bbox, maximum_local_residual=residuals,
                             registration={'dx': 0, 'dy': 0, 'scale_x': 1., 'scale_y': 1.,
                                           'policy': 'held_window_native_coordinates'}))
    if not evidence or hidden_intersection.any():
        return None
    return evidence
