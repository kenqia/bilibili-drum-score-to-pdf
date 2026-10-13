"""Agent-selected source systems to a geometric vector facsimile.

No music recognition and no hidden-symbol recovery. Public functions are the
local workflow boundary; visual assertions belong to the calling Agent.
"""
import hashlib
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

ROUGH_PIXELS = 80_000_000

class ReconstructionError(ValueError):
    pass


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def _save(task, record):
    path = Path(task) / 'record.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    temporary.replace(path)


def _artifact(task, reference):
    base = Path(task).resolve()
    path = (base / reference['path']).resolve()
    if not path.is_relative_to(base) or not path.is_file() or digest(path) != reference['sha256']:
        raise ReconstructionError('来源或派生产物损坏，停止导出。')
    return path


def load(task):
    record = json.loads((Path(task) / 'record.json').read_text())
    if record.get('schema') != 'score-reconstruction/1':
        raise ReconstructionError('不是当前重构任务。')
    source = Path(record['source']['path'])
    if not source.is_file() or digest(source) != record['source']['sha256']:
        raise ReconstructionError('原视频损坏或改变，停止任务。')
    for item in record['captures'] + record.get('regions', []):
        _artifact(task, item)
    if record.get('rough'):
        _artifact(task, record['rough'])
    for chunk in record.get('rough_chunks', []):
        _artifact(task, chunk)
    if record.get('output'):
        _artifact(task, record['output']['vector'])
        _artifact(task, {'path': record['output']['pdf'], 'sha256': record['output']['sha256']})
    return record


def prepare(source, task):
    """Probe a local video, or resume an intact task for the same source."""
    source, task = Path(source).resolve(), Path(task)
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
    _save(task, record)
    return record


def capture(task, seconds):
    """Save one native frame with actual PTS. Saving is not visual review."""
    record = load(task)
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 <= seconds < record['source']['duration']:
        raise ReconstructionError('取帧时间必须在视频范围内。')
    for shot in record['captures']:
        if shot['requested_seconds'] == seconds:
            return shot
    reader = VideoReader(record['source']['path'], record['source'], record['metrics'])
    try:
        pts, picture = reader.read_record(seconds)
    except ConversionError as error:
        record['last_decode_error'] = error.code
        raise
    finally:
        reader.close()
        _save(task, record)
    identifier = f'capture-{len(record["captures"])+1:04d}'
    directory = Path(task) / 'captures'
    directory.mkdir(exist_ok=True)
    path = directory / f'{identifier}.png'
    picture.save(path)
    shot = {'id': identifier, 'path': str(path.relative_to(task)), 'sha256': digest(path),
            'requested_seconds': seconds, **pts}
    record['captures'].append(shot)
    _save(task, record)
    return shot


def assemble(task, title, regions, review):
    """Persist the Agent's ordered full systems and optional header crop.

    Repeated music at later positions stays as another region. The Agent omits
    only overlap at the same score position and states completeness explicitly.
    """
    record = _assemble(task, title, regions, review, load(task))
    _save(task, record)
    return record


def _assemble(task, title, regions, review, record):
    """Prepare validated artifacts without publishing the task record."""
    if not title or not title.strip() or not review.get('notes'):
        raise ReconstructionError('需要实际确认的谱名和原图审阅记录。')
    viewed = review.get('viewed_captures', [])
    captures = {item['id']: item for item in record['captures']}
    if not regions or not set(viewed).issubset(captures):
        raise ReconstructionError('选择或审阅引用无效。')
    blocks, pending = [], []
    revision = uuid.uuid4().hex
    for index, selection in enumerate(regions):
        capture_id = selection['capture']
        if capture_id not in captures or capture_id not in viewed:
            raise ReconstructionError('每个选行来源必须由 Agent 实际查看。')
        source = captures[capture_id]
        with Image.open(_artifact(task, source)) as image:
            box = selection['bbox']
            if len(box) != 4 or any(type(v) is not int for v in box) or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                raise ReconstructionError('裁剪范围越界。')
            crop = image.crop(box).convert('RGB')
        kind = selection.get('kind', 'system')
        if kind not in ('header', 'system') or (kind == 'header' and index != 0):
            raise ReconstructionError('标题只能放在首行。')
        if kind == 'system':
            top, spacing = selection.get('staff_top'), selection.get('staff_spacing')
            if not isinstance(top, (int, float)) or not isinstance(spacing, (int, float)) or not math.isfinite(top) or not math.isfinite(spacing) or not (spacing > 0 and 0 <= top < top + 4 * spacing < crop.height):
                raise ReconstructionError('五线位置需要 Agent 确认。')
        path = Path(task) / 'regions' / revision / f'region-{index+1:04d}.png'
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
        with Image.open(_artifact(task, captures[capture_id])) as image:
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
        path = Path(task) / f'rough-{revision}-{number}.png'
        rough.save(path)
        rough.close()
        chunks.append({'path': path.name, 'sha256': digest(path),
                       'inputs': [item['sha256'] for item in batch]})
    record.update(title=title.strip(), regions=blocks, source_review=review,
                  rough=chunks[0], rough_chunks=chunks,
                  status='ready_to_redraw' if review.get('complete') is True and not review.get('unresolved') else 'needs_source_review')
    record.pop('output', None)
    record['metrics']['presented_capture_ids'] = list(dict.fromkeys(viewed))
    return record


def ink_mask(image):
    """Preserve dark or saturated notation, ignore light highlight backgrounds."""
    rgb = np.asarray(image.convert('RGB')).astype(np.int16)
    gray = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    notation = (rgb.max(2) - rgb.min(2) > 45) & (rgb.min(2) < 150)
    return ((gray < 165) | notation).astype(np.uint8) * 255


def trace_region(task, item):
    with Image.open(_artifact(task, item)) as image:
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
        gap = min(gap, 36)
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
    record = load(task)
    if record.get('output'):
        return record['output']
    if record['status'] != 'ready_to_redraw':
        raise ReconstructionError('原图尚未确认完整，或仍有未决内容。')
    vectors = [trace_region(task, item) for item in record['regions']]
    placements, page_count = paginate(record['regions'])
    exports = Path(task) / 'exports'
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
    record.update(output=output, status='needs_pdf_review')
    _save(task, record)
    return output


def review_pdf(task, pages, notes):
    """Record actual Agent inspection; callers must view rendered pages first."""
    record = load(task)
    output = record.get('output')
    if not output or sorted(pages) != list(range(1, output['page_count'] + 1)) or not notes:
        raise ReconstructionError('必须实际审阅最终每页 PDF。')
    output.update(status='reviewed', review={'pages': pages, 'notes': notes})
    record['status'] = 'reviewed'
    _save(task, record)
    return output
