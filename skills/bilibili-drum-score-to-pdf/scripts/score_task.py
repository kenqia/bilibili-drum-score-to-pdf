"""Score reconstruction task integrity and atomic publication.

Both supported entry points share this module. Visual review assertions remain
with the Agent; this module validates their references and persists decisions.
"""
import copy
import hashlib
import json
import math
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
    if path.exists():
        previous = json.loads(path.read_text())
        history = previous.get('generation_history', {}).copy()
        history.update(record.get('generation_history', {}))
        for page in previous.get('redraw_pages', []):
            key = page.get('input_identity') or input_identity(previous, page['regions'])
            history[key] = copy.deepcopy(page)
        record['generation_history'] = history
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
    for name in ('record.json','record.tmp','captures','regions','navigation','native-cache','redraw','exports'):
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
        for preview in record['output'].get('previews', []):
            artifact(task, preview)
        artifact(task, record['output']['vector'])
        artifact(task, {'path': record['output']['pdf'], 'sha256': record['output']['sha256']})
    for reference in record.get('overview',{}).get('panels',[]):
        artifact(task,reference)
    for reference in record.get('overview',{}).get('candidates',[]):
        artifact(task,reference)
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


def input_identity(record, indices):
    captures = {c['id']: c for c in record['captures']}
    members = []
    for index in indices:
        region = record['regions'][index]
        shot = captures[region['capture']]
        geometry = {key: float(region[key]) if region.get(key) is not None else None for key in ('staff_top','staff_spacing')}
        members.append({'source': record['source']['sha256'], 'capture': shot['sha256'],
            'pts': shot.get('pts'), 'time_base': shot.get('time_base'),
            **{key: region.get(key) for key in ('position','bbox','sha256','kind','width','height')}, **geometry})
    return hashlib.sha256(json.dumps(members, sort_keys=True).encode()).hexdigest()


def invalidate_output(record, reason):
    if record.get('output'):
        record.setdefault('output_history', []).append({'reason': reason, 'output': record.pop('output')})


def invalidate_selection(record):
    if record.get('redraw_pages'):
        record['generation_group_sizes'] = [len(p['regions']) for p in record['redraw_pages']]
    record['redraw_pages'] = []
    invalidate_output(record, 'source_revision')


def review_pdf(task, pages, notes, output_revision=None):
    """Record actual Agent inspection; callers must view rendered pages first."""
    record = load(task)
    output = record.get('output')
    if output_revision is not None and (not output or output_revision != output['sha256']):
        raise ReconstructionError('终稿审阅版本已过期。')
    if not output or sorted(pages) != list(range(1, output['page_count'] + 1)) or not notes:
        raise ReconstructionError('必须实际审阅最终每页 PDF。')
    output.update(status='reviewed', review={'pages': pages, 'notes': notes, 'output_revision': output['sha256'], 'preview_hashes': [p['sha256'] for p in output.get('previews', [])]})
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
        from automatic_score import freeze
        freeze(previous, 'agent')
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
    invalidate_selection(previous)
    previous['metrics']['presented_capture_ids'] = list(dict.fromkeys(viewed))
    from automatic_score import freeze
    freeze(previous, 'agent')
    save(task, previous)
    return previous


def redraw_inputs(task, groups=None):
    from reconstruction import ROUGH_PIXELS

    record = load(task)
    from automatic_score import require_frozen
    require_frozen(record)
    if record.get('source_review',{}).get('complete') is not True or record['source_review'].get('unresolved'):
        raise ReconstructionError('原图完整性尚未确认。')
    if record.get('redraw_pages') and (groups is None or groups == [p['regions'] for p in record['redraw_pages']]):
        return record['redraw_pages']
    if not record.get('redraw_pages') and record['status'] != 'ready_to_redraw':
        raise ReconstructionError('原图接续或完整性未确认。')
    if groups is None and record.get('generation_group_sizes') and sum(record['generation_group_sizes']) == len(record['regions']):
        groups, offset = [], 0
        for size in record['generation_group_sizes']:
            groups.append(list(range(offset, offset + size)))
            offset += size
    if groups is None:
        groups, group = [], []
        for index, block in enumerate(record['regions']):
            proposed = group + [index]
            blocks = [record['regions'][i] for i in proposed]
            width = max(b['width'] for b in blocks)
            height = sum(b['height'] for b in blocks)
            effective_scale = min(1, 4096 / max(width, height))
            systems = [b for b in blocks if b['kind'] == 'system']
            symbol_resolution = min((b['staff_spacing'] * effective_scale
                for b in systems), default=4)
            if group and (len(systems) > 8 or width * height > ROUGH_PIXELS or
                          symbol_resolution < 4):
                groups.append(group)
                group = []
            group.append(index)
        if group:
            groups.append(group)
    if not groups or any(not group for group in groups) or [i for group in groups for i in group] != list(range(len(record['regions']))):
        raise ReconstructionError('重绘分块必须按完整谱行顺序覆盖全部材料。')
    if any(max(record['regions'][i]['width'] for i in group) * sum(record['regions'][i]['height'] for i in group) > ROUGH_PIXELS for group in groups):
        raise ReconstructionError('重绘分组超出内存像素限制；拆分完整谱行。')
    directory = write_path(task, Path('redraw') / uuid.uuid4().hex)
    directory.mkdir(parents=True)
    pages = []
    for number, indices in enumerate(groups, 1):
        identity = input_identity(record, indices)
        historical = next((p for p in record.get('redraw_pages', []) if p.get('input_identity') == identity), None) or record.get('generation_history', {}).get(identity)
        if historical:
            restored = copy.deepcopy(historical)
            artifact(task, restored['input'])
            for attempt in restored.get('attempts', []):
                if attempt.get('output'):
                    artifact(task, attempt['output'])
            if restored.get('output'):
                artifact(task, restored['output'])
            restored.update(id=f'page-{number}', regions=indices, freeze_id=record['freeze']['id'], input_identity=identity)
            for row, index in zip(restored.get('row_materials', []), indices):
                row['source_region'] = index
                row['source'] = {key: record['regions'][index].get(key) for key in ('capture','position','pts','time_base','source_sha256','sha256')}
            pages.append(restored)
            continue
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
        pages.append({'input_identity': identity, 'id': f'page-{number}', 'freeze_id': record['freeze']['id'], 'regions': indices, 'input': {'path': str(path.relative_to(task)), 'sha256': digest(path), 'inputs': [b['sha256'] for b in blocks]}, 'source_boundaries': boundaries, 'status': 'needs_generation', 'corrections_used': 0, 'attempts': []})
    if record.get('redraw_pages') and groups != [p['regions'] for p in record['redraw_pages']]:
        invalidate_output(record, 'generation_regrouping')
        record['status'] = 'ready_to_redraw'
    record['generation_group_sizes'] = [len(group) for group in groups]
    record['redraw_pages'] = pages
    save(task, record)
    return pages


def _page(record, identifier):
    for page in record.get('redraw_pages', []):
        if page['id'] == identifier:
            return page
    raise ReconstructionError('重绘页引用无效。')


def begin_redraw(task, identifier, viewed_notes=None, correction=False):
    """Persist BEFORE invoking host tool; interrupted calls cannot reset budget."""
    record = load(task)
    from automatic_score import require_frozen
    require_frozen(record)
    page = _page(record, identifier)
    if record.get('source_review', {}).get('complete') is not True or record['source_review'].get('unresolved'):
        raise ReconstructionError('原图完整性尚未确认，禁止宿主调用。')
    program_approved=record['freeze']['producer']=='program'
    if (not viewed_notes and not program_approved) or (correction and (page['status'] != 'needs_correction' or page['corrections_used'] >= 1)) or (not correction and page['status'] != 'needs_generation'):
        raise ReconstructionError('实际粗拼审阅或重绘次数无效。')
    if correction:
        page['corrections_used'] += 1
    attempt = {'request': uuid.uuid4().hex, 'kind': 'correction' if correction else 'initial', 'input_sha256': page['input']['sha256'], 'notes': viewed_notes, 'status': 'calling', 'cost': None}
    attempt['approval']={'producer':'program' if program_approved else 'agent',
        'freeze_id':record['freeze']['id']}
    page['attempts'].append(attempt)
    page['status'] = 'calling'
    save(task, record)
    return {**attempt, 'input': str(artifact(task, page['input'])), 'previous_output': str(artifact(task, page['output'])) if page.get('output') else None}


def finish_redraw(task, identifier, request, output, tool, receipt):
    """Host passes newly generated local output and real invocation receipt."""
    record = load(task)
    from automatic_score import require_frozen
    require_frozen(record)
    page = _page(record, identifier)
    if not page.get('attempts'):
        raise ReconstructionError('尚未启动宿主调用。')
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


def fail_redraw(task, identifier, notes, outcome='failed'):
    """Unavailable, failed or uncertain interrupted calls route to vector."""
    record = load(task)
    from automatic_score import require_frozen
    require_frozen(record)
    page = _page(record, identifier)
    if outcome not in ('failed', 'unavailable', 'unknown') or not notes or page['status'] == 'accepted':
        raise ReconstructionError('需要失败记录，且不能降级已接受重绘。')
    if page['attempts'] and page['attempts'][-1]['status'] == 'calling':
        page['attempts'][-1].update(status=outcome, reason=notes)
    page.update(status='vector', fallback_reason=notes)
    save(task, record)
    return page


def review_redraw(task, identifier, accepted, notes, boundaries=None):
    """Actual image review supplies complete system boundaries on accepted output."""
    record = load(task)
    from automatic_score import require_frozen
    require_frozen(record)
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
        page['row_materials'] = [
            {'source_region': index, 'kind': record['regions'][index]['kind'],
             'image': page['output'], 'crop_bbox': box,
             'source': {key: record['regions'][index].get(key) for key in
                ('capture', 'position', 'pts', 'time_base', 'source_sha256', 'sha256')},
             'source_width': record['regions'][index]['width']}
            for index, box in zip(page['regions'], boxes)]
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
    from automatic_score import require_frozen
    require_frozen(record)
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
    page.pop('row_materials', None)
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
    from automatic_score import require_frozen
    require_frozen(record)
    output = record.get('output')
    if host_redraw:
        if output and output.get('layout_version') == 2 and output.get('previews') and output.get('checks', {}).get('status') == 'passed':
            return output
        pages = record.get('redraw_pages', [])
        if not pages or any(p['status'] not in ('accepted', 'vector') for p in pages):
            raise ReconstructionError('先完成每页重绘审阅或自动兜底。')
    else:
        if output:
            return output
        if record['status'] != 'ready_to_redraw':
            raise ReconstructionError('原图尚未确认完整，或仍有未决内容。')
    if output:
        invalidate_output(record, 'preview_layout_upgrade')
    output = render(task, record)
    record.update(output=output, status='needs_pdf_review')
    save(task, record)
    return output


def generation_materials(task):
    """Ordered complete rows from accepted groups and geometric fallback."""
    record = load(task)
    from automatic_score import require_frozen
    require_frozen(record)
    rows = []
    pages = record.get('redraw_pages', [])
    if not pages or any(p['status'] not in ('accepted', 'vector') for p in pages):
        raise ReconstructionError('先完成全部组审阅或矢量兜底。')
    for page in pages:
        for offset, index in enumerate(page['regions']):
            region = record['regions'][index]
            row = {'source_region': index, 'group': page['id'], 'kind': region['kind'],
                'source_width': region['width'], 'source': {key: region.get(key)
                for key in ('capture', 'position', 'pts', 'time_base', 'source_sha256', 'sha256')}}
            if page['status'] == 'accepted':
                row.update(image=page['output'], crop_bbox=page['boundaries'][offset],
                    route='imagegen')
            else:
                row.update(region=region, route='vector',
                    method='contour_trace_with_staff_repair', music_recognition=False)
            rows.append(row)
    return rows


def layout(task, margin=24, minimum_gap=6, target_pages=None):
    record = load(task)
    if (type(margin) not in (int,float) or not math.isfinite(margin) or not 0 <= margin <= 144 or
            type(minimum_gap) not in (int,float) or not math.isfinite(minimum_gap) or not 0 <= minimum_gap <= 144 or
            (target_pages is not None and (type(target_pages) is not int or not 1 <= target_pages <= 512))):
        raise ReconstructionError('布局需要有限边距、行距及可选正整数页数目标。')
    value = {'margin': margin, 'minimum_gap': minimum_gap, 'target_pages': target_pages}
    if value != record.get('layout'):
        invalidate_output(record, 'layout_revision')
        record['layout'] = value
        record['status'] = 'ready_to_redraw'
        save(task, record)
    return {'layout': value, 'status': record['status'], 'generation_groups': record.get('redraw_pages', [])}
