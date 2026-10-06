"""Restore the pixels of white multi-staff score windows, without recognizing notes."""
from pathlib import Path
import json
import re
import subprocess
import tempfile
import time

import cv2
import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas


class ConversionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def probe_video(source):
    try:
        process = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration', '-of', 'json', str(source)], capture_output=True, timeout=30, check=True)
        data = json.loads(process.stdout)
        stream = data['streams'][0]
        return {'width': stream['width'], 'height': stream['height'], 'duration': float(data['format']['duration'])}
    except (subprocess.SubprocessError, ValueError, KeyError, IndexError, OSError):
        raise ConversionError('unreadable_input', '无法读取本地视频。请提供可播放的视频文件。') from None


def sample_video(source, directory, interval=0.5):
    """Decode real frames with ffmpeg, retaining their source PTS in seconds."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    duration = probe_video(source)['duration']
    selector = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{interval})+gte(t,{max(0, duration - .05)})',showinfo"
    try:
        process = subprocess.run(['ffmpeg', '-v', 'info', '-nostdin', '-i', str(source), '-vf', selector, '-vsync', '0', '-start_number', '0', str(directory / 'frame-%06d.png')], capture_output=True, check=True, timeout=600)
    except (subprocess.SubprocessError, OSError):
        raise ConversionError('decode_failed', '视频解码失败。请提供可播放的本地视频。') from None
    timestamps = [float(value) for value in re.findall(r'\bpts_time:([0-9.eE+-]+)', process.stderr.decode('utf-8', errors='replace'))]
    files = sorted(directory.glob('frame-*.png'))
    if len(timestamps) != len(files):
        raise ConversionError('decode_failed', '无法建立解码画面与视频时间的对应记录。')
    sampled = list(zip(timestamps, files))
    # The duration need not coincide with a frame PTS. Decode the last second
    # separately so low frame rates and variable frame rates retain the real end.
    seek_start = max(0, duration - 1)
    try:
        tail = subprocess.run(['ffmpeg', '-v', 'info', '-nostdin', '-ss', str(seek_start), '-i', str(source), '-vf', f'setpts=PTS+{seek_start}/TB,showinfo', '-vsync', '0', '-start_number', '0', str(directory / 'tail-%06d.png')], capture_output=True, check=True, timeout=60)
        tail_times = [float(value) for value in re.findall(r'\bpts_time:([0-9.eE+-]+)', tail.stderr.decode('utf-8', errors='replace'))]
        tail_files = sorted(directory.glob('tail-*.png'))
        if not tail_times or len(tail_times) != len(tail_files):
            raise ConversionError('decode_failed', '无法核查视频最后一帧。')
        if not sampled or tail_times[-1] > sampled[-1][0]:
            sampled.append((tail_times[-1], tail_files[-1]))
    except (subprocess.SubprocessError, OSError):
        raise ConversionError('decode_failed', '视频末尾解码失败，无法确认结尾。') from None
    return sampled


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
        raise ConversionError('incomplete_rows', '谱行之间没有安全裁剪空隙，无法保证保留完整记谱内容。')
    length, start, end = max(blanks)
    if length < 4:
        raise ConversionError('incomplete_rows', '谱行之间的空隙不足，无法保证谱行完整。')
    return (start + end) // 2


def analyze_frame(image, allow_partial=False):
    bbox = white_region(image)
    crop = image.crop(bbox)
    if crop.width < 700:
        raise ConversionError('low_resolution', '源谱面像素不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
    all_groups = staff_groups(crop)
    if not all_groups:
        raise ConversionError('incomplete_rows', '没有找到完整的五线谱行。请补充能显示整行的视频。')
    if min(group['spacing'] for group in all_groups) < 6:
        raise ConversionError('low_resolution', '源五线间距不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
    groups = [group for group in all_groups if group['top'] >= group['spacing'] * 3 and crop.height - group['bottom'] >= group['spacing'] * 5]
    if not groups:
        raise ConversionError('incomplete_rows', '谱行靠近画面边缘，无法确认符杆及标记完整。')
    lines = staff_lines(crop)
    partial_top = any(line < groups[0]['top'] - 1 for line in lines)
    partial_bottom = any(line > groups[-1]['bottom'] + 1 for line in lines)
    if not allow_partial and (partial_top or partial_bottom):
        raise ConversionError('incomplete_rows', '画面边缘包含未恢复的残行。')
    ink = np.asarray(crop.convert('L')) < 180
    bounds = []
    for group in groups:
        above = [line for line in lines if line < group['top'] - 1]
        below = [line for line in lines if line > group['bottom'] + 1]
        top = blank_cut(ink, max(above) + group['spacing'] * 2 if above else 0, group['top'] - group['spacing'] * 3)
        if below:
            bottom = blank_cut(ink, group['bottom'] + group['spacing'] * 2, min(below) - group['spacing'] * 3)
        else:
            occupied = np.where(ink.sum(axis=1) > 0)[0]
            bottom = min(crop.height, int(occupied[-1]) + 12)
        bounds.append([top, bottom])
    gray = np.asarray(crop.convert('L'))
    return {'bbox': bbox, 'groups': groups, 'row_bounds': bounds, 'cuts': [bounds[0][0]] + [bound[1] for bound in bounds], 'partial_top': partial_top, 'partial_bottom': partial_bottom, 'sharpness': float(cv2.Laplacian(gray, cv2.CV_64F).var())}


def extract_rows(source, output, metadata, decisions=None):
    from ordered_score import restore_rows
    return restore_rows(source, output, metadata, decisions)


def write_pdf(output, header, rows, gaps=None):
    """Place each row as one image, preserving aspect ratio and page boundaries."""
    output = Path(output)
    canvas = Canvas(str(output / 'score.pdf'), pagesize=A4, pageCompression=1)
    page_width, page_height = A4
    margin, gap = 36, 12
    position, page = page_height - margin, 1
    blocks = [header] if header else []
    gaps = gaps or []
    for index in range(len(rows) + 1):
        here = [gap for gap in gaps if gap['position'] == index]
        blocks.extend({'missing_marker': f"MISSING CONTENT: {gap['id']} at {gap['timestamp']:.3f}s", 'gap': gap} for gap in here)
        if index < len(rows) and not any(gap.get('replace_row') for gap in here):
            blocks.append(rows[index])
    if gaps:
        blocks.append({'missing_marker': 'LIMITATIONS: user accepted missing score content. See manifest.json for evidence.'})
    for block in blocks:
        if 'missing_marker' in block:
            if position - 36 < margin:
                canvas.showPage()
                page += 1
                position = page_height - margin
            canvas.setFont('Helvetica', 9)
            canvas.rect(margin, position - 30, page_width - margin * 2, 30)
            canvas.drawString(margin + 6, position - 18, block['missing_marker'])
            if 'gap' in block:
                block['gap'].update(page=page, pdf_bbox=[margin, position - 30, page_width - margin, position])
            position -= 36 + gap
            continue
        with Image.open(output / block['image']) as image:
            width = page_width - margin * 2
            height = image.height * width / image.width
        if height > page_height - margin * 2:
            raise ConversionError('row_too_tall', '完整谱行无法以当前比例放入 A4，需人工核对布局。')
        if position - height < margin:
            canvas.showPage()
            page += 1
            position = page_height - margin
        canvas.drawImage(str(output / block['image']), margin, position - height, width=width, height=height)
        block['page'] = page
        block['pdf_bbox'] = [margin, position - height, margin + width, position]
        position -= height + gap
    canvas.save()
    return page


def convert(source, output, decisions=None):
    start = time.monotonic()
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {'schema_version': 1, 'status': 'failed', 'complete': False, 'issues': [], 'rows': [], 'header': None}
    try:
        metadata = probe_video(source)
        result['source'] = {'kind': 'local', 'name': source.name, **metadata}
        if metadata['width'] < 700:
            raise ConversionError('low_resolution', '源视频宽度不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
        header, rows, evidence = extract_rows(source, output, metadata, decisions)
        result.update(evidence)
        pages = write_pdf(output, header, rows, result.get('gaps'))
        result.update(status='success', complete=not result.get('gaps'), header=header, rows=rows, page_count=pages, pdf='score.pdf')
    except ConversionError as error:
        result['error'] = {'code': error.code, 'message': str(error)}
        if hasattr(error, 'issues'):
            result.update(status='waiting', issues=error.issues)
        if hasattr(error, 'progress'):
            result.update(error.progress)
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    result['confirmation_count'] = 0
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result
