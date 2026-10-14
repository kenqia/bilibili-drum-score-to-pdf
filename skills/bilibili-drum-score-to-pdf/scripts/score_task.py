"""Score reconstruction task integrity and atomic publication.

Both supported entry points share this module. Visual review assertions remain
with the Agent; this module validates their references and persists decisions.
"""
import hashlib
import json
from pathlib import Path
import uuid
from PIL import Image


class ReconstructionError(ValueError):
    pass


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def write_path(task, relative):
    """Validate every existing write component before touching the filesystem."""
    root=Path(task)
    if root.is_symlink():
        raise ReconstructionError('任务目录不能是符号链接。')
    suffix=Path(relative)
    if suffix.is_absolute() or '..' in suffix.parts:
        raise ReconstructionError('写入路径必须位于任务内。')
    candidate=root
    for part in suffix.parts:
        candidate=candidate/part
        if candidate.is_symlink():
            raise ReconstructionError('任务写入路径不能包含符号链接。')
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ReconstructionError('写入路径必须位于任务内。')
    return candidate


def save(task, record):
    path = write_path(task, 'record.json')
    temporary = write_path(task, 'record.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    temporary.replace(path)


def artifact(task, reference):
    base = Path(task).resolve()
    path = (base / reference['path']).resolve()
    if not path.is_relative_to(base) or not path.is_file() or digest(path) != reference['sha256']:
        raise ReconstructionError('来源或派生产物损坏，停止导出。')
    return path


def load(task):
    for name in ('record.json','record.tmp','captures','regions','navigation','redraw','exports'):
        write_path(task,name)
    record = json.loads((Path(task) / 'record.json').read_text())
    if record.get('schema') != 'score-reconstruction/1':
        raise ReconstructionError('不是当前重构任务。')
    source = Path(record['source']['path'])
    if not source.is_file() or digest(source) != record['source']['sha256']:
        raise ReconstructionError('原视频损坏或改变，停止任务。')
    for item in record['captures'] + record.get('regions', []):
        artifact(task, item)
    if record.get('rough'):
        artifact(task, record['rough'])
    for chunk in record.get('rough_chunks', []):
        artifact(task, chunk)
    if record.get('output'):
        artifact(task, record['output']['vector'])
        artifact(task, {'path': record['output']['pdf'], 'sha256': record['output']['sha256']})
    for reference in record.get('probes', []):
        artifact(task, reference)
    for page in record.get('redraw_pages', []):
        artifact(task, page['input'])
        if page.get('output'):
            artifact(task, page['output'])
        for attempt in page.get('attempts', []):
            if attempt.get('output'):
                artifact(task, attempt['output'])
    return record


def review_pdf(task, pages, notes):
    """Record actual Agent inspection; callers must view rendered pages first."""
    record = load(task)
    output = record.get('output')
    if not output or sorted(pages) != list(range(1, output['page_count'] + 1)) or not notes:
        raise ReconstructionError('必须实际审阅最终每页 PDF。')
    output.update(status='reviewed', review={'pages': pages, 'notes': notes})
    record['status'] = 'reviewed'
    save(task, record)
    return output


def assemble(task, title, regions, review, *, positioned=False):
    """Agent specifies original score positions and actual continuity evidence.

    Same position is overlap, distinct positions retain later repeated music.
    Position labels are Agent statements, never inferred from pixel equality.
    """
    if not title or not title.strip() or not review.get('notes'):
        raise ReconstructionError('需要实际确认的谱名和原图审阅记录。')
    if positioned:
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
    else:
        unique = regions
    if not unique:
        raise ReconstructionError('选择或审阅引用无效。')
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
    if same:
        # Re-confirming identical valid source material is recovery, not a new
        # request. Preserve accepted outputs and persisted correction budgets.
        previous['source_review'] = review
        if review.get('complete') is not True or review.get('unresolved'):
            if previous.get('output'):
                previous.setdefault('source_review_withdrawals',[]).append({'review':review,'output':previous.pop('output')})
            previous['status'] = 'needs_source_review'
        elif previous['status'] == 'needs_source_review':
            previous['status'] = 'ready_to_redraw'
        save(task, previous)
        return previous
    # Geometry prepares versioned files; no record is published until both the
    # new selection and all dependent invalidation decisions are ready.
    from reconstruction import build_selection
    materials = build_selection(task, unique, {c['id']: c for c in previous['captures']})
    previous.update(**materials, title=title.strip(), source_review=review,
        status='ready_to_redraw' if review.get('complete') is True and not review.get('unresolved') else 'needs_source_review')
    previous.pop('output', None)
    if positioned or 'redraw_pages' in previous:
        previous['redraw_pages'] = []
    previous['metrics']['presented_capture_ids'] = list(dict.fromkeys(viewed))
    save(task, previous)
    return previous


def redraw_inputs(task, groups=None):
    from reconstruction import paginate, ROUGH_PIXELS

    record = load(task)
    if record.get('source_review',{}).get('complete') is not True or record['source_review'].get('unresolved'):
        raise ReconstructionError('原图完整性尚未确认。')
    if record.get('redraw_pages'):
        return record['redraw_pages']
    if record['status'] != 'ready_to_redraw':
        raise ReconstructionError('原图接续或完整性未确认。')
    placements, count = paginate(record['regions'])
    if groups is None:
        groups=[]
        for number in range(1,count+1):
            group=[]
            for i in [p['region'] for p in placements if p['page']==number]:
                proposed=group+[i]
                if group and max(record['regions'][j]['width'] for j in proposed)*sum(record['regions'][j]['height'] for j in proposed)>ROUGH_PIXELS:
                    groups.append(group)
                    group=[]
                group.append(i)
            if group:groups.append(group)
    if not groups or any(not group for group in groups) or [i for group in groups for i in group] != list(range(len(record['regions']))):
        raise ReconstructionError('重绘分块必须按完整谱行顺序覆盖全部材料。')
    if any(max(record['regions'][i]['width'] for i in group) * sum(record['regions'][i]['height'] for i in group) > ROUGH_PIXELS for group in groups):
        raise ReconstructionError('重绘分组超出内存像素限制；拆分完整谱行。')
    directory = write_path(task, Path('redraw') / uuid.uuid4().hex)
    directory.mkdir(parents=True)
    pages = []
    for number, indices in enumerate(groups, 1):
        blocks = [record['regions'][i] for i in indices]
        width, height = max(b['width'] for b in blocks), sum(b['height'] for b in blocks)
        image = Image.new('RGB', (width, height), 'white')
        y, boundaries = 0, []
        for block in blocks:
            with Image.open(artifact(task, block)) as crop:
                image.paste(crop, (0, y))
            boundaries.append([0, y, block['width'], y + block['height']])
            y += block['height']
        path = write_path(task, directory.relative_to(task) / f'input-{number}.png')
        image.save(path)
        pages.append({'id': f'page-{number}', 'regions': indices, 'input': {'path': str(path.relative_to(task)), 'sha256': digest(path), 'inputs': [b['sha256'] for b in blocks]}, 'source_boundaries': boundaries, 'status': 'needs_generation', 'corrections_used': 0, 'attempts': []})
    record['redraw_pages'] = pages
    save(task, record)
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
    save(task, record)
    return {**attempt, 'input': str(artifact(task, page['input'])), 'previous_output': str(artifact(task, page['output'])) if page.get('output') else None}


def finish_redraw(task, identifier, request, output, tool, receipt):
    """Host passes newly generated local output and real invocation receipt."""
    record = load(task)
    page = _page(record, identifier)
    attempt = page['attempts'][-1]
    if page['status'] != 'calling' or attempt['request'] != request or tool != 'host-imagegen' or not receipt:
        raise ReconstructionError('宿主工具调用来源无效。')
    with Image.open(output) as image:
        image.verify()
    path = write_path(task, Path('redraw') / (request + '.png'))
    # Copy byte-for-byte. A receipt is an assertion, not proof of a tool call.
    path.write_bytes(Path(output).read_bytes())
    page['output'] = {'path': str(path.relative_to(task)), 'sha256': digest(path), 'input_sha256': page['input']['sha256']}
    attempt.update(status='returned', tool=tool, receipt=receipt, output=page['output'])
    page['status'] = 'needs_image_review'
    save(task, record)
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
    save(task, record)
    return page


def review_redraw(task, identifier, accepted, notes, boundaries=None):
    """Actual image review supplies complete system boundaries on accepted output."""
    record = load(task)
    page = _page(record, identifier)
    if page['status'] != 'needs_image_review' or type(accepted) is not bool or not notes:
        raise ReconstructionError('需要实际重绘图审阅。')
    if accepted:
        with Image.open(artifact(task, page['output'])) as image:
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
    save(task, record)
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
    save(task, record)
    return page


def export(task, render, *, host_redraw=False):
    """Validate export readiness, render materials, then publish once.

    The two existing renderers return files and placements. Task state and PDF
    approval are owned here, independent of vector or host-image geometry.
    """
    record = load(task)
    if record.get('source_review', {}).get('complete') is not True or record['source_review'].get('unresolved'):
        raise ReconstructionError('原图完整性尚未确认，停止导出。')
    output = record.get('output')
    if host_redraw:
        if output and output.get('layout_version') == 2:
            return output
        pages = record.get('redraw_pages', [])
        if not pages or any(p['status'] not in ('accepted', 'vector') for p in pages):
            raise ReconstructionError('先完成每页重绘审阅或自动兜底。')
    else:
        if output:
            return output
        if record['status'] != 'ready_to_redraw':
            raise ReconstructionError('原图尚未确认完整，或仍有未决内容。')
    output = render(task, record)
    record.update(output=output, status='needs_pdf_review')
    save(task, record)
    return output
