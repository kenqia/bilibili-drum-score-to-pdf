"""Agent-led reconstruction, navigation and host image generation receipts.

The host executes image generation; this module persists its requests/results.
No model credentials or vision decisions are implemented here.
"""
from pathlib import Path
import math
import uuid
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
import reconstruction as local
from public_video import acquire, video_origin, ACQUISITION_SECONDS
from video_seek import VideoReader

ReconstructionError = local.ReconstructionError


def load(task):
    record = local.load(task)
    for reference in record.get('probes', []):
        local._artifact(task, reference)
    for page in record.get('redraw_pages', []):
        local._artifact(task, page['input'])
        if page.get('output'):
            local._artifact(task, page['output'])
        for attempt in page.get('attempts', []):
            if attempt.get('output'):
                local._artifact(task, attempt['output'])
    return record


def prepare(source, task, acquisition_timeout=ACQUISITION_SECONDS):
    """Same local/anonymous URL entry; resumes without downloading twice."""
    task = Path(task)
    if (task / 'record.json').exists():
        record = load(task)
        candidate = str(source)
        if candidate.startswith(('http://', 'https://')):
            candidate = video_origin(candidate)['url']
        else:
            candidate = str(Path(candidate).resolve())
        if candidate not in (record['source']['path'], record.get('origin', {}).get('url')):
            raise ReconstructionError('已有任务对应另一来源。')
        return record
    if task.exists() and any(task.iterdir()):
        raise ReconstructionError('目标目录已有用户文件。')
    origin = None
    if str(source).startswith(('http://', 'https://')):
        origin = video_origin(str(source))
        destination = task.parent / (task.name + '-source-' + uuid.uuid4().hex)
        source, origin = acquire(str(source), destination, timeout=acquisition_timeout)
    record = local.prepare(source, task)
    if origin:
        record['origin'] = origin
    record.update(probes=[], redraw_pages=[])
    record['metrics'].update(navigation_probes=0, native_retained=0, presented_images=0)
    local._save(task, record)
    return record


def navigate(task, seconds, width=480):
    """Low-resolution probe; Agent decides its next time, never a fixed cadence."""
    record = load(task)
    if type(width) is not int or not 64 <= width <= 960 or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 <= seconds < record['source']['duration']:
        raise ReconstructionError('导航时间或宽度无效。')
    for probe in record.get('probes', []):
        if probe['requested_seconds'] == seconds and probe['requested_width'] == width:
            return probe
    reader = VideoReader(record['source']['path'], record['source'], record['metrics'])
    try:
        pts, image = reader.read_record(seconds)
    finally:
        reader.close()
        local._save(task, record)
    image.thumbnail((width, max(1, round(width * image.height / image.width))))
    directory = Path(task) / 'navigation'
    directory.mkdir(exist_ok=True)
    identifier = 'probe-' + uuid.uuid4().hex
    path = directory / (identifier + '.png')
    image.save(path)
    probe = {'id': identifier, 'path': str(path.relative_to(task)), 'sha256': local.digest(path), 'requested_seconds': seconds, 'requested_width': width, 'width': image.width, 'height': image.height, **pts}
    record.setdefault('probes', []).append(probe)
    record['metrics']['navigation_probes'] = len(record['probes'])
    local._save(task, record)
    return probe


def capture(task, seconds):
    shot = local.capture(task, seconds)
    record = load(task)
    record['metrics']['native_retained'] = len(record['captures'])
    local._save(task, record)
    return shot


def present(task, identifiers, notes):
    """Receipt of images actually shown, distinct from retained or decoded frames."""
    record = load(task)
    known = {r['id'] for r in record['captures'] + record.get('probes', [])}
    if not notes or not set(identifiers).issubset(known):
        raise ReconstructionError('呈交图像引用或实际看图记录无效。')
    record.setdefault('presentations', []).append({'images': identifiers, 'notes': notes})
    record['metrics']['presented_images'] = sum(len(item['images']) for item in record['presentations'])
    local._save(task, record)
    return record


def assemble(task, title, regions, review):
    """Agent specifies original score positions and actual continuity evidence.

    Same position is overlap, distinct positions retain later repeated music.
    Position labels are Agent statements, never inferred from pixel equality.
    """
    if not review.get('continuity') or not review.get('first_last'):
        raise ReconstructionError('需要接续和首尾实际审阅记录。')
    unique, seen = [], set()
    for region in regions:
        position = region.get('position')
        if not isinstance(position, str) or not position:
            raise ReconstructionError('每个原谱位置需要明确标签。')
        if position not in seen:
            unique.append(region)
            seen.add(position)
    previous = load(task)
    fields = ('capture', 'bbox', 'kind', 'staff_top', 'staff_spacing', 'position')
    def selection_key(region):
        return [region.get(field, 'system' if field == 'kind' else None) for field in fields]
    same = (title.strip() == previous.get('title') and
            [selection_key(r) for r in unique] == [selection_key(r) for r in previous['regions']])
    viewed = review.get('viewed_captures', [])
    captures = {c['id'] for c in previous['captures']}
    if not review.get('notes') or not set(viewed).issubset(captures) or any(r['capture'] not in viewed for r in unique):
        raise ReconstructionError('每个选行必须引用实际审阅过的原截图。')
    if same and review.get('complete') is True and not review.get('unresolved'):
        # Re-confirming identical valid source material is recovery, not a new
        # request. Preserve accepted outputs and persisted correction budgets.
        previous['source_review'] = review
        local._save(task, previous)
        return previous
    record = local._assemble(task, title, unique, review, previous)
    record['redraw_pages'] = []
    local._save(task, record)
    return record


def redraw_inputs(task, groups=None):
    record = load(task)
    if record.get('redraw_pages'):
        return record['redraw_pages']
    if record['status'] != 'ready_to_redraw':
        raise ReconstructionError('原图接续或完整性未确认。')
    placements, count = local.paginate(record['regions'])
    if groups is None:
        groups = [[p['region'] for p in placements if p['page'] == number] for number in range(1, count + 1)]
    if not groups or any(not group for group in groups) or [i for group in groups for i in group] != list(range(len(record['regions']))):
        raise ReconstructionError('重绘分块必须按完整谱行顺序覆盖全部材料。')
    directory = Path(task) / 'redraw' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    pages = []
    for number, indices in enumerate(groups, 1):
        blocks = [record['regions'][i] for i in indices]
        width, height = max(b['width'] for b in blocks), sum(b['height'] for b in blocks)
        image = Image.new('RGB', (width, height), 'white')
        y, boundaries = 0, []
        for block in blocks:
            with Image.open(local._artifact(task, block)) as crop:
                image.paste(crop, (0, y))
            boundaries.append([0, y, block['width'], y + block['height']])
            y += block['height']
        path = directory / f'input-{number}.png'
        image.save(path)
        pages.append({'id': f'page-{number}', 'regions': indices, 'input': {'path': str(path.relative_to(task)), 'sha256': local.digest(path), 'inputs': [b['sha256'] for b in blocks]}, 'source_boundaries': boundaries, 'status': 'needs_generation', 'corrections_used': 0, 'attempts': []})
    record['redraw_pages'] = pages
    local._save(task, record)
    return pages


def _page(record, identifier):
    for page in record.get('redraw_pages', []):
        if page['id'] == identifier:
            return page
    raise ReconstructionError('重绘页引用无效。')


def begin_redraw(task, identifier, viewed_notes, correction=False):
    """Persist BEFORE invoking host tool; interrupted calls cannot reset budget."""
    record = load(task)
    page = _page(record, identifier)
    if not viewed_notes or (correction and (page['status'] != 'needs_correction' or page['corrections_used'] >= 1)) or (not correction and page['status'] != 'needs_generation'):
        raise ReconstructionError('实际粗拼审阅或重绘次数无效。')
    if correction:
        page['corrections_used'] += 1
    attempt = {'request': uuid.uuid4().hex, 'kind': 'correction' if correction else 'initial', 'input_sha256': page['input']['sha256'], 'notes': viewed_notes, 'status': 'calling'}
    page['attempts'].append(attempt)
    page['status'] = 'calling'
    local._save(task, record)
    return {**attempt, 'input': str(local._artifact(task, page['input'])), 'previous_output': str(local._artifact(task, page['output'])) if page.get('output') else None}


def finish_redraw(task, identifier, request, output, tool, receipt):
    """Host passes newly generated local output and real invocation receipt."""
    record = load(task)
    page = _page(record, identifier)
    attempt = page['attempts'][-1]
    if page['status'] != 'calling' or attempt['request'] != request or tool != 'host-imagegen' or not receipt:
        raise ReconstructionError('宿主工具调用来源无效。')
    with Image.open(output) as image:
        image.verify()
    path = Path(task) / 'redraw' / (request + '.png')
    # Copy byte-for-byte. A receipt is an assertion, not proof of a tool call.
    path.write_bytes(Path(output).read_bytes())
    page['output'] = {'path': str(path.relative_to(task)), 'sha256': local.digest(path), 'input_sha256': page['input']['sha256']}
    attempt.update(status='returned', tool=tool, receipt=receipt, output=page['output'])
    page['status'] = 'needs_image_review'
    local._save(task, record)
    return page


def fail_redraw(task, identifier, notes):
    """Unavailable, failed or uncertain interrupted calls route to vector."""
    record = load(task)
    page = _page(record, identifier)
    if not notes or page['status'] == 'accepted':
        raise ReconstructionError('需要失败记录，且不能降级已接受重绘。')
    if page['attempts'] and page['attempts'][-1]['status'] == 'calling':
        page['attempts'][-1].update(status='failed', reason=notes)
    page.update(status='vector', fallback_reason=notes)
    local._save(task, record)
    return page


def review_redraw(task, identifier, accepted, notes, boundaries=None):
    """Actual image review supplies complete system boundaries on accepted output."""
    record = load(task)
    page = _page(record, identifier)
    if page['status'] != 'needs_image_review' or type(accepted) is not bool or not notes:
        raise ReconstructionError('需要实际重绘图审阅。')
    if accepted:
        with Image.open(local._artifact(task, page['output'])) as image:
            boxes = boundaries or []
            if len(boxes) != len(page['regions']):
                raise ReconstructionError('必须确认每个完整谱行边界。')
            previous = 0
            for box in boxes:
                if len(box) != 4 or any(type(v) is not int for v in box) or not (0 <= box[0] < box[2] <= image.width and previous <= box[1] < box[3] <= image.height):
                    raise ReconstructionError('重绘边界越界或重叠。')
                previous = box[3]
        page.update(status='accepted', boundaries=boxes)
    else:
        page['status'] = 'needs_correction' if page['corrections_used'] == 0 else 'vector'
    page.setdefault('reviews', []).append({'accepted': accepted, 'notes': notes})
    local._save(task, record)
    return page


def reject_accepted_redraw(task, identifier, notes):
    """Withdraw an accepted image after an actual later notation error review.

    Keep generated attempts, review history and exported files for audit. This
    explicit action invalidates PDF approval without refunding correction calls.
    """
    record = load(task)
    page = _page(record, identifier)
    if page['status'] != 'accepted' or not isinstance(notes, str) or not notes.strip():
        raise ReconstructionError('需要已接受重绘的具体后续错误审阅。')
    rejection = {'notes': notes, 'output': page['output'],
                 'corrections_used': page['corrections_used']}
    if record.get('output'):
        rejection['pdf'] = record.pop('output')
    page.setdefault('rejections', []).append(rejection)
    page['status'] = 'needs_correction' if page['corrections_used'] == 0 else 'vector'
    page.pop('boundaries', None)
    record['status'] = 'needs_redraw_review'
    local._save(task, record)
    return page


def export(task):
    """Reflow complete generated systems and unchanged vector paths together."""
    record = load(task)
    if record.get('output', {}).get('layout_version') == 2:
        return record['output']
    pages = record.get('redraw_pages', [])
    if not pages or any(p['status'] not in ('accepted', 'vector') for p in pages):
        raise ReconstructionError('先完成每页重绘审阅或自动兜底。')
    blocks, vectors, routes = [], [], []
    for page in pages:
        routes.append('imagegen' if page['status'] == 'accepted' else 'vector')
        for offset, index in enumerate(page['regions']):
            original = record['regions'][index]
            if page['status'] == 'accepted':
                box = page['boundaries'][offset]
                blocks.append({'kind': original['kind'], 'width': original['width'], 'height': (box[3] - box[1]) * original['width'] / (box[2] - box[0]), 'image': page['output'], 'crop_bbox': box, 'source_region': index})
                vectors.append(None)
            else:
                blocks.append({**original, 'source_region': index})
                vectors.append(local.trace_region(task, original))
    placements, count = local.paginate(blocks)
    if (Path(task) / 'exports').is_symlink():
        raise ReconstructionError('导出目录不能指向任务外。')
    revision = Path(task) / 'exports' / uuid.uuid4().hex
    revision.mkdir(parents=True)
    pdf = revision / local.pdf_name(record['title'])
    canvas = Canvas(str(pdf), pagesize=A4, invariant=1)
    canvas.setTitle(record['title'])
    for number in range(1, count + 1):
        for placement in (p for p in placements if p['page'] == number):
            index = placement['region']
            block, vector = blocks[index], vectors[index]
            canvas.saveState()
            canvas.translate(placement['bbox'][0], placement['bbox'][3])
            scale = placement['scale']
            if vector is None:
                # PDF clipping preserves native output bytes and avoids pixel resampling.
                box = block['crop_bbox']
                native_scale = scale * block['width'] / (box[2] - box[0])
                clip = canvas.beginPath()
                clip.rect(0, -block['height'] * scale, block['width'] * scale, block['height'] * scale)
                canvas.clipPath(clip, stroke=0)
                with Image.open(local._artifact(task, block['image'])) as image:
                    canvas.drawImage(str(local._artifact(task, block['image'])), -box[0] * native_scale, -(image.height - box[1]) * native_scale, width=image.width * native_scale, height=image.height * native_scale)
            else:
                canvas.scale(scale, -scale)
                local.draw_vector(canvas, vector)
            canvas.restoreState()
        canvas.showPage()
    canvas.save()
    manifest = revision / 'materials.json'
    import json
    manifest.write_text(json.dumps({'blocks': blocks, 'vectors': vectors, 'inputs': [r['sha256'] for r in record['regions']]}))
    output = {'pdf': str(pdf.relative_to(task)), 'sha256': local.digest(pdf), 'page_count': count, 'placements': placements, 'routes': routes, 'method': 'reviewed_host_images_and_vector_fallback', 'layout_version': 2, 'status': 'needs_pdf_review', 'vector': {'path': str(manifest.relative_to(task)), 'sha256': local.digest(manifest)}}
    record.update(output=output, status='needs_pdf_review')
    local._save(task, record)
    return output


def review_pdf(task, pages, notes):
    """Validate all workflow references before recording final PDF approval."""
    load(task)
    return local.review_pdf(task, pages, notes)
