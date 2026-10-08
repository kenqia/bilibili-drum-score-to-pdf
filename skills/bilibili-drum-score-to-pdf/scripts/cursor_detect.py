"""Candidate usability only. Detection never alters row identity or output pixels."""
import cv2
import numpy as np


def cursor_occluded(image, spacing):
    pixels = np.asarray(image.convert('RGB')).astype(np.int16)
    colored = ((pixels.max(axis=2) - pixels.min(axis=2) > 12)
               & (pixels.max(axis=2) > 140)).astype(np.uint8)
    joined = cv2.morphologyEx(colored, cv2.MORPH_CLOSE, np.ones((max(3, round(spacing)), 3), np.uint8))
    vertical = cv2.morphologyEx(joined, cv2.MORPH_OPEN,
                                np.ones((max(9, round(spacing * 4)), 1), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(vertical, 8)
    return any(2 <= w <= image.width * .12 and h >= spacing * 4 and h >= w * 2.2
               for x, y, w, h, area in stats[1:])


def obstruction_detected(image, staff_y, spacing):
    """Veto broad breaks in a complete staff; arbitrary overlays remain unsupported."""
    gray = np.asarray(image.convert('L'))
    support = []
    for line in range(5):
        y = round(staff_y + line * spacing)
        band = gray[max(0, y - 2):min(image.height, y + 3)]
        support.append(float((band.min(axis=0) < 150).mean()) if len(band) else 0)
    return min(support) < .65 or min(support) < max(support) * .8


def stationary_overlays(old_image, new_image, spacing):
    """Stationary textured screen blocks during staff translation veto candidates."""
    old = np.asarray(old_image.convert('L'), dtype=np.float32)
    new = np.asarray(new_image.convert('L'), dtype=np.float32)
    if old.shape != new.shape:
        return []
    old -= cv2.GaussianBlur(old, (0, 0), 2)
    new -= cv2.GaussianBlur(new, (0, 0), 2)
    tile_x, tile_y = round(spacing * 4), round(spacing * 2)
    boxes = []
    for y in range(0, len(old), tile_y):
        for x in range(0, old.shape[1], tile_x):
            a, b = old[y:y + tile_y, x:x + tile_x], new[y:y + tile_y, x:x + tile_x]
            energy = float(np.sqrt(np.mean(a * a) * np.mean(b * b)))
            if energy > 1 and float(np.mean(a * b)) / energy > .98:
                boxes.append([x, y, min(old.shape[1], x + tile_x), min(len(old), y + tile_y)])
    return boxes
