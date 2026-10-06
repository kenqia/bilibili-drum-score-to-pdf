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
    return list(zip(timestamps, files))


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


def staff_groups(crop):
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


def analyze_frame(image):
    bbox = white_region(image)
    crop = image.crop(bbox)
    if crop.width < 700:
        raise ConversionError('low_resolution', '源谱面像素不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
    groups = staff_groups(crop)
    if not groups:
        raise ConversionError('incomplete_rows', '没有找到完整的五线谱行。请补充能显示整行的视频。')
    if min(group['spacing'] for group in groups) < 6:
        raise ConversionError('low_resolution', '源谱面像素或五线间距不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
    ink = np.asarray(crop.convert('L')) < 180
    cuts = [blank_cut(ink, 0, groups[0]['top'] - groups[0]['spacing'] * 3)]
    for left, right in zip(groups, groups[1:]):
        cuts.append(blank_cut(ink, left['bottom'] + left['spacing'] * 2, right['top'] - right['spacing'] * 3))
    # Keep all lower annotations. No fixed crop at the fifth staff line.
    occupied = np.where(ink.sum(axis=1) > 0)[0]
    last = min(crop.height, int(occupied[-1]) + 12)
    cuts.append(last)
    for group, top, bottom in zip(groups, cuts, cuts[1:]):
        if group['top'] - top < group['spacing'] * 2 or bottom - group['bottom'] < group['spacing'] * 2:
            raise ConversionError('incomplete_rows', '谱行靠近画面边缘，无法确认符杆及标记完整。请补充包含整行的视频。')
    gray = np.asarray(crop.convert('L'))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {'bbox': bbox, 'groups': groups, 'cuts': cuts, 'sharpness': sharpness}


def extract_fixed_rows(source, output, metadata):
    output = Path(output)
    candidates, failures = [], []
    first_region = None
    with tempfile.TemporaryDirectory(prefix='drum-score-') as scratch:
        for timestamp, file in sample_video(source, scratch):
            with Image.open(file) as image:
                try:
                    analysis = analyze_frame(image)
                    region = image.crop(analysis['bbox']).convert('L')
                    pixels = np.asarray(region)
                    if first_region is None:
                        first_region = (pixels.copy(), timestamp, image.copy())
                    reference, first_time, first_image = first_region
                    changed = pixels.shape != reference.shape
                    if not changed:
                        changed = float((np.abs(pixels.astype(float) - reference.astype(float)) > 50).mean()) > .001
                    if changed:
                        images = output / 'images'
                        images.mkdir(parents=True, exist_ok=True)
                        first_image.save(images / 'window-first.png')
                        image.save(images / 'window-changed.png')
                        error = ConversionError('dynamic_layout', '谱面随时间变化，当前固定谱面切片不能保证整曲覆盖。需要继续进行纵向谱行恢复。')
                        error.issues = [{'id': 'layout-001', 'kind': 'dynamic_layout', 'question': str(error), 'timestamp': timestamp, 'image': 'images/window-changed.png', 'reference_timestamp': first_time, 'reference_image': 'images/window-first.png'}]
                        raise error
                    candidates.append((analysis['sharpness'], timestamp, file, analysis))
                except ConversionError as error:
                    if error.code == 'dynamic_layout':
                        raise
                    failures.append(error)
        if not candidates:
            if failures:
                raise failures[0]
            raise ConversionError('decode_failed', '视频中没有可读取的画面。')
        _, timestamp, file, analysis = max(candidates, key=lambda item: (item[0], -item[1]))
        with Image.open(file) as image:
            region = image.crop(analysis['bbox']).convert('L')
            images = output / 'images'
            images.mkdir(parents=True, exist_ok=True)
            cuts, bbox = analysis['cuts'], analysis['bbox']
            header = None
            if (np.asarray(region.crop((0, 0, region.width, cuts[0]))) < 180).any():
                region.crop((0, 0, region.width, cuts[0])).save(images / 'header.png')
                header = {'image': 'images/header.png', 'timestamp': timestamp, 'bbox': [bbox[0], bbox[1], bbox[2], bbox[1] + cuts[0]]}
            rows = []
            for index, (top, bottom) in enumerate(zip(cuts, cuts[1:]), 1):
                name = f'images/row-{index:04d}.png'
                region.crop((0, top, region.width, bottom)).save(output / name)
                rows.append({'id': f'row-{index:04d}', 'image': name, 'timestamp': timestamp, 'bbox': [bbox[0], bbox[1] + top, bbox[2], bbox[1] + bottom]})
            return header, rows


def write_pdf(output, header, rows):
    """Place each row as one image, preserving aspect ratio and page boundaries."""
    output = Path(output)
    canvas = Canvas(str(output / 'score.pdf'), pagesize=A4, pageCompression=1)
    page_width, page_height = A4
    margin, gap = 36, 12
    position, page = page_height - margin, 1
    blocks = ([header] if header else []) + rows
    for block in blocks:
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


def convert(source, output):
    start = time.monotonic()
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {'schema_version': 1, 'status': 'failed', 'complete': False, 'issues': [], 'rows': [], 'header': None}
    try:
        metadata = probe_video(source)
        result['source'] = {'kind': 'local', 'name': source.name, **metadata}
        if metadata['width'] < 700:
            raise ConversionError('low_resolution', '源视频宽度不足，放大不能恢复音符细节。请提供更清晰的本地视频。')
        header, rows = extract_fixed_rows(source, output, metadata)
        pages = write_pdf(output, header, rows)
        result.update(status='success', complete=True, header=header, rows=rows, page_count=pages, pdf='score.pdf')
    except ConversionError as error:
        result['error'] = {'code': error.code, 'message': str(error)}
        if hasattr(error, 'issues'):
            result.update(status='waiting', issues=error.issues)
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    result['confirmation_count'] = 0
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result
