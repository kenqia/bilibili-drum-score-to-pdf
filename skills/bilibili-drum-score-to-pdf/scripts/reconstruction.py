"""Agent-selected source systems to a geometric vector facsimile.

No music recognition and no hidden-symbol recovery. Public functions are the
local workflow boundary; visual assertions belong to the calling Agent.
"""
import json
import math
from pathlib import Path
import uuid

import cv2
import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from video_seek import ConversionError, VideoReader, probe_video
from delivery_layout import pdf_name
from score_task import ReconstructionError, digest, write_path, load, review_pdf
from score_task import save, artifact
import score_task

ROUGH_PIXELS = 80_000_000

def prepare(source, task):
    """Probe a local video, or resume an intact task for the same source."""
    source, task = Path(source).resolve(), Path(task)
    write_path(task,'record.json')
    write_path(task,'record.tmp')
    if not source.is_file():
        raise ConversionError('invalid_input', '本地视频不存在。')
    if (task / 'record.json').exists():
        record = load(task)
        if record['source']['path'] != str(source):
            raise ReconstructionError('已有任务对应另一视频。')
        return record
    if task.exists() and any(task.iterdir()):
        raise ReconstructionError('目标目录已有用户文件；请选择新的任务目录。')
    metadata = probe_video(source)
    task.mkdir(parents=True, exist_ok=True)
    record = {'schema': 'score-reconstruction/1', 'source': {'path': str(source),
              'sha256': digest(source), **metadata}, 'captures': [], 'regions': [],
              'status': 'needs_source_review', 'metrics': {'seek_count': 0,
              'decode_elapsed': 0, 'decoded_reported_frames': 0, 'peak_temp_disk': 0,
              'presented_capture_ids': [], 'model_cost': None}}
    save(task, record)
    return record


def capture(task, seconds):
    """Save or promote one verified native frame without duplicate decoding."""
    from native_cache import capture as cached_capture
    return cached_capture(task, seconds)


def assemble(task, title, regions, review):
    """Select local source systems through the shared task lifecycle."""
    return score_task.assemble(task, title, regions, review)


def build_selection(task, regions, captures):
    """Build validated crops and rough chunks without changing task state."""
    blocks, pending = [], []
    revision = uuid.uuid4().hex
    for index, selection in enumerate(regions):
        capture_id = selection['capture']
        source = captures[capture_id]
        with Image.open(artifact(task, source)) as image:
            box = selection['bbox']
            if len(box) != 4 or any(type(v) is not int for v in box) or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                raise ReconstructionError('裁剪范围越界。')
            crop = image.crop(box).convert('RGB')
        kind = selection.get('kind', 'system')
        if kind not in ('header', 'system'):
            raise ReconstructionError('标题只能放在首行。')
        if kind == 'system':
            top, spacing = selection.get('staff_top'), selection.get('staff_spacing')
            if not isinstance(top, (int, float)) or not isinstance(spacing, (int, float)) or not math.isfinite(top) or not math.isfinite(spacing) or not (spacing > 0 and 0 <= top < top + 4 * spacing < crop.height):
                raise ReconstructionError('五线位置需要 Agent 确认。')
        path = write_path(task, Path('regions') / revision / f'region-{index+1:04d}.png')
        pending.append((path, capture_id, box))
        blocks.append({**selection, 'kind': kind, 'path': str(path.relative_to(task)),
                       'source_sha256': source['sha256'], 'pts': source['pts'],
                       'time_base': source['time_base'], 'width': crop.width, 'height': crop.height})
        crop.close()
    if not any(item['kind'] == 'system' for item in blocks):
        raise ReconstructionError('没有完整谱行。')
    width = max(item['width'] for item in blocks)
    batches, batch, height = [], [], 0
    for item in blocks:
        if width * item['height'] > ROUGH_PIXELS:
            raise ReconstructionError('单个完整谱行超出粗拼内存范围。')
        if batch and width * (height + item['height']) > ROUGH_PIXELS:
            batches.append(batch)
            batch, height = [], 0
        batch.append(item)
        height += item['height']
    batches.append(batch)
    for item, (path, capture_id, box) in zip(blocks, pending):
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(artifact(task, captures[capture_id])) as image:
            crop = image.crop(box).convert('RGB')
            crop.save(path)
            crop.close()
        item['sha256'] = digest(path)
    chunks = []
    for number, batch in enumerate(batches, 1):
        rough = Image.new('RGB', (width, sum(item['height'] for item in batch)), 'white')
        cursor = 0
        for item in batch:
            with Image.open(Path(task) / item['path']) as image:
                rough.paste(image, (0, cursor))
            cursor += item['height']
        path = write_path(task, f'rough-{revision}-{number}.png')
        rough.save(path)
        rough.close()
        chunks.append({'path': path.name, 'sha256': digest(path),
                       'inputs': [item['sha256'] for item in batch]})
    return {'regions': blocks, 'rough': chunks[0], 'rough_chunks': chunks}


def ink_mask(image):
    """Preserve dark or saturated notation, ignore light highlight backgrounds."""
    rgb = np.asarray(image.convert('RGB'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    red, green, blue = cv2.split(rgb)
    maximum = cv2.max(cv2.max(red, green), blue)
    minimum = cv2.min(cv2.min(red, green), blue)
    # OpenCV treats a 1x1 operand as a scalar, making compare(array, int)
    # ambiguous. Array thresholds retain the same rule for every crop size.
    saturated = ((maximum - minimum) > 45) & (minimum < 150)
    return np.where((gray < 165) | saturated, 255, 0).astype(np.uint8)



def trace_region(task, item):
    with Image.open(artifact(task, item)) as image:
        mask = ink_mask(image)
    outlines, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    paths = [cv2.approxPolyDP(outline, .25, True)[:, 0].tolist() for outline in outlines if len(outline) >= 3]
    paths = [points for points in paths if len(points) >= 3]
    lines = []
    if item['kind'] == 'system':
        horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((1, max(10, item['width'] // 12)), np.uint8))
        for line in range(5):
            y = item['staff_top'] + line * item['staff_spacing']
            band = horizontal[max(0, round(y)-2):min(mask.shape[0], round(y)+3)]
            xs = np.where(band.any(axis=0))[0]
            if not len(xs):
                raise ReconstructionError('五线边界不可确认；需要局部补采，不能恢复隐藏记号。')
            lines.append([int(xs[0]), y, int(xs[-1])])
    return {'paths': paths, 'lines': lines, 'width': item['width'], 'height': item['height']}


def paginate(blocks, margin=24, minimum_gap=6):
    """Use a common scale and split only between complete systems."""
    width, height = A4
    scale = (width - 2 * margin) / max(block['width'] for block in blocks)
    pages, current, occupied = [], [], 0
    for index, block in enumerate(blocks):
        size = block['height'] * scale
        if size > height - 2 * margin:
            raise ReconstructionError('单个谱行超过 A4 可打印高度。')
        extra = size + (minimum_gap if current else 0)
        if current and occupied + extra > height - 2 * margin:
            pages.append(current)
            current, occupied = [], 0
        current.append(index)
        occupied += size + (minimum_gap if len(current) > 1 else 0)
    if current:
        pages.append(current)
    if len(pages[0]) == 1 and blocks[0].get('kind') == 'header':
        raise ReconstructionError('标题占据整页，需要重新裁剪或布局。')
    def occupied_height(batch):
        return sum(blocks[i]['height'] * scale for i in batch) + minimum_gap * (len(batch) - 1)
    # Keep the greedy minimum page count, then balance neighboring pages using
    # complete systems. Each move strictly decreases squared occupied heights.
    changed = True
    while changed:
        changed = False
        for left, right in zip(pages, pages[1:]):
            if len(left) <= 1 or (blocks[left[0]].get('kind') == 'header' and len(left) <= 2):
                continue
            before = abs(occupied_height(left) - occupied_height(right))
            moved = left[-1]
            next_left, next_right = left[:-1], [moved] + right
            if occupied_height(next_right) <= height - 2 * margin and abs(occupied_height(next_left) - occupied_height(next_right)) < before:
                left.pop()
                right.insert(0, moved)
                changed = True
    placements = []
    for number, batch in enumerate(pages, 1):
        used = sum(blocks[i]['height'] * scale for i in batch)
        gap = (height - 2 * margin - used) / (len(batch) - 1) if len(batch) > 1 else 0
        # Sparse pages keep modest gaps and centered content instead of stretching.
        gap = min(gap, max(36, minimum_gap))
        top = height - margin - max(0, (height - 2 * margin - used - gap * (len(batch)-1)) / 2)
        for index in batch:
            size = blocks[index]['height'] * scale
            placements.append({'page': number, 'region': index, 'scale': scale,
                               'bbox': [margin, top-size, margin+blocks[index]['width']*scale, top]})
            top -= size + gap
    return placements, len(pages)


def draw_vector(canvas, vector):
    """Draw traced notation and staff lines in the caller's coordinate space."""
    path = canvas.beginPath()
    for points in vector['paths']:
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.close()
    canvas.drawPath(path, fill=1, stroke=0, fillMode=0)
    canvas.setLineWidth(1.1)
    for x1, y, x2 in vector['lines']:
        canvas.line(x1, y, x2, y)


def export_vector(task):
    """Export through the shared task lifecycle and existing renderer."""
    return score_task.export(task, _render_vector)


def _render_vector(task, record):
    vectors = [trace_region(task, item) for item in record['regions']]
    options = record.get('layout', {})
    placements, page_count = paginate(record['regions'], margin=options.get('margin', 24), minimum_gap=options.get('minimum_gap', 6))
    exports = write_path(task, 'exports')
    if exports.is_symlink():
        raise ReconstructionError('导出目录不能指向任务外部或已有用户目录。')
    exports.mkdir(exist_ok=True)
    revision = exports / uuid.uuid4().hex
    revision.mkdir()
    pdf_path = revision / pdf_name(record['title'])
    filename = str(pdf_path.relative_to(task))
    canvas = Canvas(str(pdf_path), pagesize=A4, invariant=1)
    canvas.setTitle(record['title'])
    for page in range(1, page_count + 1):
        for placement in (p for p in placements if p['page'] == page):
            vector = vectors[placement['region']]
            canvas.saveState()
            canvas.translate(placement['bbox'][0], placement['bbox'][3])
            canvas.scale(placement['scale'], -placement['scale'])
            draw_vector(canvas, vector)
            canvas.restoreState()
        canvas.showPage()
    canvas.save()
    vector_path = revision / 'vector.json'
    vector_path.write_text(json.dumps({'inputs': [r['sha256'] for r in record['regions']], 'regions': vectors}))
    output = {'pdf': filename, 'sha256': digest(Path(task) / filename),
              'page_count': page_count, 'placements': placements,
              'method': 'geometric_contours_and_staff_lines', 'semantic_transcription': False,
              'hidden_symbol_recovery': False, 'status': 'needs_pdf_review',
              'vector': {'path': str(vector_path.relative_to(task)), 'sha256': digest(vector_path)}}
    return score_task.finalize_output(task, output, [{**r, 'source_region': i} for i, r in enumerate(record['regions'])], options, record)
