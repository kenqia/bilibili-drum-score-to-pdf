"""Assess real row observations and preserve pixels as printable grayscale."""
import importlib.metadata
import cv2
import numpy as np
from reportlab.lib.pagesizes import A4


def cursor_regions(image, spacing):
    pixels = np.asarray(image.convert('RGB'))
    signed = pixels.astype(np.int16)
    colored = ((signed[:, :, 2] - signed[:, :, 0] > 12) & (signed[:, :, 2] >= signed[:, :, 1])).astype(np.uint8)
    joined = cv2.morphologyEx(colored, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    boxes, ignored = [], np.zeros(colored.shape, dtype=bool)
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if 2 <= width <= image.width * .12 and height >= max(spacing * 4, image.height * .3) and height >= width * 2.2 and area / (width * height) >= .35:
            box = [int(x), int(y), int(x + width), int(y + height)]
            boxes.append(box)
            ignored[y:y + height, x:x + width] = True
    return boxes, ignored


def assess(image, spacing):
    boxes, _ = cursor_regions(image, spacing)
    gray = np.asarray(image.convert('L'))
    return {'cursor_occluded': bool(boxes), 'cursor_boxes': boxes, 'sharpness': float(cv2.Laplacian(gray, cv2.CV_64F).var()), 'native_width': image.width, 'staff_spacing': spacing, 'effective_dpi': round(image.width / ((A4[0] - 72) / 72), 1)}


def printable(image):
    # Preserve every observed pixel through luminance conversion. No erosion,
    # whitening, thresholding, inpainting, enlargement or guessed notation.
    return image.convert('L')


def quality_report(metadata, rows):
    return {'source_width': metadata['width'], 'source_height': metadata['height'], 'policy': 'whole_clean_observed_row_then_highest_sharpness', 'pixel_mapping': 'grayscale_without_erasing_or_drawing', 'unrecovered_rows': [row['id'] for row in rows if row.get('quality', {}).get('cursor_occluded')], 'tools': {name: importlib.metadata.version(name) for name in ['pillow', 'numpy', 'opencv-python-headless', 'reportlab']}, 'limits': ['Native pixels and staff spacing are heuristics; final print readability needs visual review.']}
