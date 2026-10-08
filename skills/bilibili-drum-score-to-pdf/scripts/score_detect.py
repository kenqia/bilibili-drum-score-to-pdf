"""Native white score ROI and complete staff-row geometry, adapted from main."""
import cv2
import numpy as np
from video_seek import ConversionError


def white_region(image):
    rgb = np.asarray(image.convert('RGB'))
    white = (rgb.min(axis=2) > 210).astype(np.uint8) * 255
    # Analysis mask only. The printable image is never eroded or redrawn.
    mask = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = [cv2.boundingRect(contour) for contour in contours]
    candidates = [box for box in candidates if box[2] > image.width * .45 and box[3] > image.height * .25]
    if not candidates:
        raise ConversionError('unsupported_layout', '未找到白底多行谱面。请提供支持布局的视频。')
    x, y, width, height = max(candidates, key=lambda box: box[2] * box[3])
    return [x, y, x + width, y + height]


def staff_lines(crop):
    gray = np.asarray(crop.convert('L'))
    ink = (gray < 150).astype(np.uint8)
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(25, crop.width // 4)), np.uint8))
    ys = np.where(horizontal.sum(axis=1) > crop.width * .4)[0]
    lines = []
    for y in ys:
        if not lines or y > lines[-1][-1] + 1:
            lines.append([int(y)])
        else:
            lines[-1].append(int(y))
    centers = [float(np.mean(line)) for line in lines]
    return centers


def staff_groups(crop):
    centers = staff_lines(crop)
    groups, index = [], 0
    while index + 4 < len(centers):
        candidate = centers[index:index + 5]
        gaps = np.diff(candidate)
        if min(gaps) >= 2 and max(gaps) <= min(gaps) * 1.25:
            groups.append({'top': candidate[0], 'bottom': candidate[-1], 'spacing': float(np.median(gaps))})
            index += 5
        else:
            index += 1
    return groups


def blank_cut(ink, low, high):
    """Cut only through whitespace between neighboring complete staffs."""
    low, high = max(0, int(low)), min(len(ink), int(high))
    occupied = ink[low:high].sum(axis=1) > 0
    blanks, start = [], None
    for offset, value in enumerate(np.append(occupied, True)):
        if not value and start is None:
            start = offset
        if value and start is not None:
            blanks.append((offset - start, low + start, low + offset))
            start = None
    if not blanks:
        raise ConversionError('unsupported_layout', '谱行之间没有安全裁剪空隙，无法保证保留完整记谱内容。')
    length, start, end = max(blanks)
    if length < 4:
        raise ConversionError('unsupported_layout', '谱行之间的空隙不足，无法保证谱行完整。')
    return (start + end) // 2


def analyze_frame(image):
    bbox = white_region(image)
    crop = image.crop(bbox)
    if crop.width < 700:
        raise ConversionError('low_resolution', '源谱面像素不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
    all_groups = staff_groups(crop)
    if not all_groups:
        raise ConversionError('unsupported_layout', '没有找到完整的五线谱行。请补充能显示整行的视频。')
    if min(group['spacing'] for group in all_groups) < 6:
        raise ConversionError('low_resolution', '源五线间距不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
    groups = [group for group in all_groups if group['top'] >= group['spacing'] * 6 and crop.height - group['bottom'] >= group['spacing'] * 5]
    if not groups:
        raise ConversionError('unsupported_layout', '谱行靠近画面边缘，无法确认符杆及标记完整。')
    lines = staff_lines(crop)
    partial_top = any(line < groups[0]['top'] - 1 for line in lines)
    partial_bottom = any(line > groups[-1]['bottom'] + 1 for line in lines)
    pixels = np.asarray(crop.convert('RGB'))
    # Bright colored notation also occupies space, even above the gray threshold.
    ink = (np.asarray(crop.convert('L')) < 180) | ((np.ptp(pixels, axis=2) > 20) & (pixels.min(axis=2) < 220))
    bounds = []
    for group in groups:
        above = [line for line in lines if line < group['top'] - 1]
        below = [line for line in lines if line > group['bottom'] + 1]
        top = blank_cut(ink, max(above) + group['spacing'] * 2 if above else max(0, group['top'] - group['spacing'] * 9), group['top'] - group['spacing'] * 3)
        if below:
            bottom = blank_cut(ink, group['bottom'] + group['spacing'] * 2, min(below) - group['spacing'] * 3)
        else:
            occupied = np.where(ink.sum(axis=1) > 0)[0]
            bottom = min(crop.height, int(occupied[-1]) + 12)
        bounds.append([top, bottom])
    header_ink = np.where(ink[:bounds[0][0]].sum(axis=1) > 0)[0]
    header_top = max(0, int(header_ink[0]) - 12) if len(header_ink) else bounds[0][0]
    return {'bbox': bbox, 'groups': groups, 'row_bounds': bounds,
            'partial_top': partial_top, 'partial_bottom': partial_bottom,
            'header_bbox': [bbox[0], bbox[1] + header_top, bbox[2], bbox[1] + bounds[0][0]]}
