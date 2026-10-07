"""Assess real row observations and preserve pixels as printable grayscale."""
import importlib.metadata
import cv2
import numpy as np
from reportlab.lib.pagesizes import A4

PRINTABLE_WIDTH_INCHES = (A4[0] - 72) / 72
MIN_PRINT_DPI = 150.0
HIGH_QUALITY_DPI = 200.0


def print_quality_band(dpi):
    if dpi is None or dpi < MIN_PRINT_DPI:
        return 'low_print_resolution'
    return 'high_quality_candidate' if dpi >= HIGH_QUALITY_DPI else 'printable_candidate'


def cursor_regions(image, spacing):
    pixels = np.asarray(image.convert('RGB'))
    signed = pixels.astype(np.int16)
    colored = ((signed[:, :, 2] - signed[:, :, 0] > 12) & (signed[:, :, 2] >= signed[:, :, 1])).astype(np.uint8)
    joined = cv2.morphologyEx(colored, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # Separate a vertical playback core from an attached horizontal blue line.
    vertical = cv2.morphologyEx(joined, cv2.MORPH_OPEN,
                                np.ones((max(9, int(round(spacing * 4))), 1), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(vertical, 8)
    boxes, ignored = [], np.zeros(colored.shape, dtype=bool)
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if 2 <= width <= image.width * .12 and height >= spacing * 4 and height >= width * 2.2 and area / (width * height) >= .35:
            # Include only a four-pixel codec fringe around the detected core.
            # These pixels stay unknown until complementary real observations.
            box = [max(0, int(x) - 4), max(0, int(y) - 4),
                   min(image.width, int(x + width) + 4), min(image.height, int(y + height) + 4)]
            boxes.append(box)
            ignored[box[1]:box[3], box[0]:box[2]] = True
    if boxes:
        # At 236 seconds a just-played stacked note remains blue behind the
        # moving core. Treat only a small nearby component as unknown, so
        # stationary complementary observations must expose it again. The
        # native long blue rest line is too wide to enter this mask.
        _, _, blue_marks, _ = cv2.connectedComponentsWithStats(colored, 8)
        for x, y, width, height, area in blue_marks[1:]:
            if area < 3 or width > spacing * 2 or height > spacing * 3:
                continue
            if any(b[0] - spacing * 4 <= x + width <= b[0]
                   and y < b[3] and y + height > b[1] for b in boxes):
                ignored[max(0, y - 4):min(image.height, y + height + 4),
                        max(0, x - 4):min(image.width, x + width + 4)] = True
        # The live player also colors the struck note green; its head can
        # protrude beyond the blue stripe. Only a small green component that
        # touches an established cursor core is unavailable observation.
        green = ((signed[:, :, 1] - signed[:, :, 0] > 12)
                 & (signed[:, :, 1] > signed[:, :, 2])).astype(np.uint8)
        _, _, marks, _ = cv2.connectedComponentsWithStats(green, 8)
        for x, y, width, height, area in marks[1:]:
            if area < 3 or width > spacing * 2 or height > spacing * 2:
                continue
            if any(x < b[2] and x + width > b[0] and y < b[3] and y + height > b[1] for b in boxes):
                ignored[max(0, y - 2):min(image.height, y + height + 2),
                        max(0, x - 2):min(image.width, x + width + 2)] = True
    return boxes, ignored


def assess(image, spacing):
    boxes, _ = cursor_regions(image, spacing)
    gray = np.asarray(image.convert('L'))
    effective_dpi = image.width / PRINTABLE_WIDTH_INCHES
    band = print_quality_band(effective_dpi)
    return {'cursor_occluded': bool(boxes), 'cursor_boxes': boxes, 'sharpness': float(cv2.Laplacian(gray, cv2.CV_64F).var()), 'native_width': image.width, 'staff_spacing': spacing, 'effective_dpi': round(effective_dpi, 3), 'print_quality': band}


def printable(image):
    # Preserve every observed pixel through luminance conversion. No erosion,
    # whitening, thresholding, inpainting, enlargement or guessed notation.
    return image.convert('L')


def quality_report(metadata, rows):
    dpis = [row['quality']['native_width'] / PRINTABLE_WIDTH_INCHES for row in rows if row.get('quality', {}).get('native_width') is not None]
    minimum = min(dpis) if dpis else None
    return {'source_width': metadata['width'], 'source_height': metadata['height'], 'policy': 'whole_clean_observed_row_then_supported_boundary_then_highest_sharpness', 'pixel_mapping': 'grayscale_without_erasing_or_drawing', 'unrecovered_rows': [row['id'] for row in rows if row.get('quality', {}).get('cursor_occluded') or row.get('cursor_content_unproven')], 'effective_dpi': {'minimum': round(minimum, 3) if minimum is not None else None, 'printable_width_inches': round(PRINTABLE_WIDTH_INCHES, 3), 'minimum_required': MIN_PRINT_DPI, 'high_quality_target': HIGH_QUALITY_DPI, 'status': print_quality_band(minimum)}, 'tools': {name: importlib.metadata.version(name) for name in ['pillow', 'numpy', 'opencv-python-headless', 'reportlab']}, 'limits': ['Native pixels and staff spacing are heuristics; final print readability needs visual review.']}

def validate_print_quality(rows):
    if any(row.get('quality', {}).get('native_width', 0) / PRINTABLE_WIDTH_INCHES < MIN_PRINT_DPI for row in rows):
        raise ValueError(f'谱行原生像素不足以达到 {MIN_PRINT_DPI:.0f} DPI。请提供更清晰的本地视频。')
