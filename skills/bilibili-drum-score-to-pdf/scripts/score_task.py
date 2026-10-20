"""Score reconstruction task integrity and atomic publication.

Both supported entry points share this module. Visual review assertions remain
with the Agent; this module validates their references and persists decisions.
"""
import copy
import hashlib
from functools import lru_cache
import json
import math
from pathlib import Path
import uuid
from PIL import Image


class ReconstructionError(ValueError):
    def __init__(self, message, code='invalid_state', field=None, action=None):
        super().__init__(message)
        self.code, self.field, self.action = code, field, action


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
        previous = json.loads(path.read_text(encoding='utf-8'))
        history = previous.get('generation_history', {}).copy()
        history.update(record.get('generation_history', {}))
        current = {p.get('input_identity') for p in record.get('redraw_pages', [])}
        for page in previous.get('redraw_pages', []):
            page = copy.deepcopy(page)
            key = page.get('input_identity') or input_identity(previous, page['regions'])
            if page.get('status') == 'prepared' and page.get('input_identity') not in current:
                size = len(page['regions'])
                still_selected = any(input_identity(record, list(range(start, start + size))) ==
                                     page.get('input_identity')
                                     for start in range(len(record.get('regions', [])) - size + 1))
                if still_selected:
                    history[key] = page
                    continue
                attempt = page['attempts'][-1]
                attempt.update(status='cancelled', reason='input_selection_changed_before_dispatch')
                page['status'] = 'vector' if attempt['kind'] == 'correction' else 'needs_generation'
            history[key] = page
        record['generation_history'] = history
    temporary = write_path(task, 'record.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def artifact(task, reference):
    base = Path(task).resolve()
    path = (base / reference['path']).resolve()
    if not path.is_relative_to(base) or not path.is_file() or digest(path) != reference['sha256']:
        raise ReconstructionError('来源或派生产物损坏，停止导出。')
    return path


def load(task):
    for name in ('record.json','record.tmp','captures','regions','navigation','native-cache','redraw','exports','longshot'):
        write_path(task,name)
    try:
        record = json.loads((Path(task) / 'record.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        raise ReconstructionError('无法读取当前任务记录。', code='invalid_state', action='prepare or resume a current task') from None
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
    if record.get('longshot'):
        stitched = record['longshot']
        for reference in [stitched['image'], stitched['samples'], *stitched['endpoints']]:
            artifact(task, reference)
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



def _fingerprint(record):
    material = {'source': record['source']['sha256'], 'regions': record['regions'],
        'rough_chunks': record.get('rough_chunks'), 'review': record.get('source_review'),
        'checks': record.get('program_checks'),
        'overview_candidates': [c['sha256'] for c in record.get('overview',{}).get('candidates',[])]}
    if record.get('longshot'):
        material['longshot'] = record['longshot']
    if record.get('agent_review_contract'):
        material['agent_review_contract'] = record['agent_review_contract']
        material['source_issue_history'] = record.get('source_issue_history', [])
        if 'legacy_source_approval' in record:
            material['legacy_source_approval'] = record['legacy_source_approval']
    if 'row_manifest' in record:
        material['row_manifest'] = record['row_manifest']
    if 'continuity_reviews' in record:
        material['continuity_reviews'] = record['continuity_reviews']
    if 'row_anchor_reviews' in record:
        material['row_anchor_reviews'] = record['row_anchor_reviews']
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def freeze(record, producer):
    material_digest=hashlib.sha256(json.dumps(record['regions'],sort_keys=True).encode()).hexdigest()
    previous=record.get('freeze',{})
    identifier=previous['id'] if previous.get('material_digest')==material_digest else uuid.uuid4().hex
    record['freeze'] = {'id': identifier, 'producer': producer, 'material_digest':material_digest,
        'fingerprint': _fingerprint(record), 'source_sha256': record['source']['sha256']}
    return record['freeze']

def require_frozen(record):
    frozen = record.get('freeze', {})
    from longshot import is_longshot
    stitched = is_longshot(record)
    if (frozen.get('producer') != ('longshot' if stitched else 'agent') or frozen.get('fingerprint') != _fingerprint(record)
            or record.get('source_review', {}).get('complete') is not True
            or record['source_review'].get('unresolved')):
        raise ReconstructionError('来源尚未审阅或选行已改变；查看 stage 后重新确认。',
                                  code='source_review_required', action='stage')
    if stitched:
        if (record['longshot'].get('review') or {}).get('accepted') is not True:
            raise ReconstructionError('需要先整体查看长截图。', code='source_review_required')
    elif record.get('agent_review_contract'):
        from agent_source_review import validate
        validate(record, record['regions'], record['source_review'], same=True)


def input_identity(record, indices):
    captures = {c['id']: c for c in record['captures']}
    members = []
    for index in indices:
        region = record['regions'][index]
        shot = record['longshot']['image'] if region.get('source_kind') == 'longshot' else captures[region['capture']]
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
    if not output_revision:
        raise ReconstructionError('必须显式提交实际查看的 output_revision；导出并查看当前全部预览后再审阅。')
    if not output or output_revision != output.get('output_revision'):
        raise ReconstructionError('终稿审阅版本已过期。')
    if not output or sorted(pages) != list(range(1, output['page_count'] + 1)) or not notes:
        raise ReconstructionError('必须实际审阅最终每页 PDF。')
    require_output_previews(task, output, record)
    output.update(status='reviewed', review={'pages': sorted(pages), 'notes': notes, 'output_revision': output['output_revision'], 'preview_hashes': [p['sha256'] for p in output.get('previews', [])]})
    record['status'] = 'reviewed'
    save(task, record)
    return output


def assemble(task, title, regions, review, *, positioned=False):
    """Agent specifies original score positions and actual continuity evidence.

    Same position is overlap, distinct positions retain later repeated music.
    Position labels are Agent statements, never inferred from pixel equality.
    """
    if (not isinstance(title, str) or not title.strip() or not isinstance(review, dict) or
            not isinstance(regions, list) or any(not isinstance(r, dict) for r in regions) or
            not isinstance(review.get('notes'), str) or not review['notes'].strip()):
        raise ReconstructionError('需要实际确认的谱名和原图审阅记录。')
    previous = load(task)
    # Explicit manual selection uses the manual contract, even on a task that
    # was initially prepared for automatic longshot stitching.
    previous.pop('longshot', None)
    previous.pop('workflow', None)
    if positioned or previous.get('agent_review_contract'):
        if not review.get('continuity') or not review.get('first_last'):
            raise ReconstructionError('需要接续和首尾实际审阅记录。')
        unique, seen = [], set()
        for region in regions:
            position = region.get('position')
            if not isinstance(position, str) or not position:
                raise ReconstructionError('每个原谱位置需要明确标签。')
            if position in seen and previous.get('agent_review_contract'):
                preferred = next(r for r in unique if r['position'] == position)
                if any(preferred.get(k) != region.get(k) for k in ('capture', 'bbox', 'kind', 'staff_top', 'staff_spacing')):
                    raise ReconstructionError('同位置有不同来源；请只提交 Agent 选定的来源，或使用 revise-selection。',
                                              code='invalid_request', field='regions.position')
            if position not in seen:
                unique.append(region)
                seen.add(position)
    else:
        unique = regions
    if not unique:
        raise ReconstructionError('选择或审阅引用无效。')
    fields = ('capture', 'bbox', 'kind', 'staff_top', 'staff_spacing', 'position')
    def selection_key(region):
        return [region.get(field, 'system' if field == 'kind' else None) for field in fields]
    same = (title.strip() == previous.get('title') and
            [selection_key(r) for r in unique] == [selection_key(r) for r in previous['regions']])
    from agent_source_review import validate
    review, active_contract = validate(previous, unique, review, same=same, upgrade=True, title=title.strip())
    if active_contract:
        from agent_source_review import CONTRACT
        previous['agent_review_contract'] = CONTRACT
    viewed = review.get('viewed_captures', [])
    captures = {c['id'] for c in previous['captures']}
    if not review.get('notes') or not set(viewed).issubset(captures) or any(r['capture'] not in viewed for r in unique):
        raise ReconstructionError('每个选行必须引用实际审阅过的原截图。')
    if same:
        # Re-confirming identical valid source material is recovery, not a new
        # request. Preserve accepted outputs and persisted correction budgets.
        previous['source_review'] = review
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
    freeze(previous, 'agent')
    save(task, previous)
    return previous


def redraw_inputs(task, groups=None):
    from reconstruction import ROUGH_PIXELS

    record = load(task)
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
    # Exact historic identities retain their attempts and spent budgets. New
    # memberships must satisfy the same resolution limits as default grouping.
    for indices in groups:
        identity = input_identity(record, indices)
        historical = next((p for p in record.get('redraw_pages', []) if p.get('input_identity') == identity), None) or record.get('generation_history', {}).get(identity)
        if historical:
            continue
        blocks = [record['regions'][i] for i in indices]
        scale = min(1, 4096 / max(max(b['width'] for b in blocks), sum(b['height'] for b in blocks)))
        systems = [b for b in blocks if b['kind'] == 'system']
        if len(systems) > 8 or (not record.get('longshot') and any(b['staff_spacing'] * scale < 4 for b in systems)):
            raise ReconstructionError('新重绘组超过八条完整谱行或小符号有效分辨率不足；拆分完整行，单行不足时补采更清晰来源。')
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


def _crop_checks(task, record):
    if record.get('longshot'):
        # The complete longshot is the source. Pixel-level edge ambiguity is
        # covered by its overall review, never an automatic rejection gate.
        image = record['longshot']['image']
        boxes = [r['bbox'] for r in record['regions']]
        valid = (bool(boxes) and boxes[0][1] == 0 and boxes[-1][3] == image['height'] and
                 all(0 <= a[1] < a[3] <= image['height'] and a[0] == 0 and a[2] == image['width'] for a in boxes) and
                 all(a[3] == b[1] for a, b in zip(boxes, boxes[1:])))
        return {'producer': 'program', 'status': 'passed' if valid else 'blocked',
                'issues': [] if valid else [{'code': 'longshot_cut_coverage'}],
                'scope': 'complete longshot coverage; no symbol-by-symbol check'}
    import cv2
    import numpy as np
    from reconstruction import ink_mask

    issues = []
    captures = {shot['id']: shot for shot in record['captures']}

    @lru_cache(maxsize=1)
    def native_mask(identifier):
        with Image.open(artifact(task, captures[identifier])) as image:
            return ink_mask(image) > 0

    for index, region in enumerate(record['regions']):
        identifier = region['capture']
        mask = native_mask(identifier)
        left, top, right, bottom = region['bbox']
        edges = []
        for name, inside, outside in (('top', top, top - 1), ('bottom', bottom - 1, bottom)):
            ink = mask[inside, left:right]
            # Header envelopes are intentionally tight around complete text.
            if region['kind'] != 'system' and 0 <= outside < mask.shape[0]:
                ink = ink & mask[outside, left:right]
            if np.any(ink):
                edges.append(name)
        patch = mask[top:bottom, left:right]
        if region['kind'] == 'system':
            horizontal = cv2.morphologyEx(patch.astype(np.uint8), cv2.MORPH_OPEN,
                                         np.ones((1, max(24, patch.shape[1] // 4)), np.uint8))
            staff = np.zeros_like(patch)
            for line in range(5):
                y = round(region['staff_top'] + line * region['staff_spacing'])
                low, high = max(0, y - 2), min(len(staff), y + 3)
                staff[low:high] = horizontal[low:high] > 0
            patch = patch & ~staff
        for name, inside, outside in (('left', 0, left - 1), ('right', -1, right)):
            ink = patch[:, inside]
            if region['kind'] != 'system' and 0 <= outside < mask.shape[1]:
                ink = ink & mask[top:bottom, outside]
            if np.any(ink):
                edges.append(name)
        if edges:
            issues.append({'code': 'crop_edge', 'region': index, 'capture': identifier,
                           'bbox': region['bbox'], 'edges': edges})
    return {'producer': 'program', 'status': 'blocked' if issues else 'passed',
            'issues': issues, 'scope': 'system ink touching crop boundaries; not music proofreading'}


def crop_checks(task):
    """Inspect selected crop boundaries before a host request is reserved."""
    return _crop_checks(task, load(task))


def _require_safe_crops(task, record):
    if _crop_checks(task, record)['status'] != 'passed':
        raise ReconstructionError('裁剪边缘穿过可见记号；运行 crop-checks 并修正后再调用或导出。')


def _reserve_redraw(record, page, viewed_notes, correction, reserve):
    if (not isinstance(viewed_notes, str) or not viewed_notes.strip()) or (correction and (
            page['status'] != 'needs_correction' or page['corrections_used'] >= 1)) or (
            not correction and page['status'] != 'needs_generation'):
        raise ReconstructionError('实际粗拼审阅或重绘次数无效。')
    if correction:
        page['corrections_used'] += 1
    attempt = {'request': uuid.uuid4().hex, 'kind': 'correction' if correction else 'initial',
               'input_sha256': page['input']['sha256'], 'notes': viewed_notes,
               'status': 'prepared' if reserve else 'calling', 'cost': None,
               'approval': {'producer': 'agent',
                            'freeze_id': record['freeze']['id']}}
    if record.get('longshot'):
        from longshot import PROMPT
        attempt['prompt'] = PROMPT
    page['attempts'].append(attempt)
    page['status'] = attempt['status']
    return attempt


def _host_request(task, page):
    return {**page['attempts'][-1], 'input': str(artifact(task, page['input'])),
            'previous_output': str(artifact(task, page['output'])) if page.get('output') else None}


def begin_redraw(task, identifier, viewed_notes=None, correction=False, reserve=False):
    """Legacy calls are conservatively dispatched; reserve=True prepares only."""
    record = load(task)
    require_frozen(record)
    _require_safe_crops(task, record)
    page = _page(record, identifier)
    if type(correction) is not bool or type(reserve) is not bool:
        raise ReconstructionError('修正与预留参数必须是布尔值。')
    _reserve_redraw(record, page, viewed_notes, correction, reserve)
    save(task, record)
    return _host_request(task, page)


def redraw_requests(task, viewed_notes=None):
    """Return one ordered handoff for every group, including resumed requests."""
    redraw_inputs(task)
    record = load(task)
    if not viewed_notes and record.get('longshot'):
        viewed_notes = (record['longshot'].get('review') or {}).get('notes')
    _require_safe_crops(task, record)
    handoffs = []
    changed = False
    for page in record['redraw_pages']:
        if page['status'] == 'needs_generation' and viewed_notes:
            _reserve_redraw(record, page, viewed_notes, False, True)
            changed = True
        status = page['status']
        action = {'prepared': 'ready_to_dispatch', 'calling': 'recover_existing_call',
                  'needs_generation': 'needs_input_review'}.get(status, status)
        handoff = {'group': page['id'], 'status': action,
                   'input_identity': page['input_identity'],
                   'input': str(artifact(task, page['input']))}
        if status in ('prepared', 'calling'):
            handoff['request'] = _host_request(task, page)
        if page.get('output'):
            handoff['output'] = page['output']
        handoffs.append(handoff)
    requests = [h['request'] for h in handoffs if 'request' in h]
    if len({r['request'] for r in requests}) != len(requests):
        raise ReconstructionError('批量请求的 request ID 重复。')
    for page in record['redraw_pages']:
        if page['status'] in ('prepared', 'calling') and (
                page['attempts'][-1]['input_sha256'] != page['input']['sha256'] or
                page['attempts'][-1]['status'] != page['status']):
            raise ReconstructionError('请求状态或输入 hash 不一致。')
    if len({h['group'] for h in handoffs}) != len(record['redraw_pages']):
        raise ReconstructionError('批量请求的组 ID 重复。')
    if changed:
        save(task, record)
    return {'group_count': len(record['redraw_pages']), 'handoffs': handoffs}


def dispatch_redraw(task, identifier, request):
    """Persist before the host call; interruption now means result unknown."""
    record = load(task)
    require_frozen(record)
    _require_safe_crops(task, record)
    page = _page(record, identifier)
    if page['status'] != 'prepared' or page['attempts'][-1]['request'] != request:
        raise ReconstructionError('只能提交当前预留请求；已提交或结果未知时先恢复。')
    page['attempts'][-1]['status'] = 'calling'
    page['status'] = 'calling'
    save(task, record)
    return _host_request(task, page)


def cancel_redraw(task, identifier, request, notes):
    """Cancel only a known unsubmitted reservation; spent correction stays spent."""
    record = load(task)
    require_frozen(record)
    page = _page(record, identifier)
    if (page['status'] != 'prepared' or not isinstance(notes, str) or not notes.strip()
            or page['attempts'][-1]['request'] != request):
        raise ReconstructionError('只能作废当前尚未提交的预留请求，且必须记录原因。')
    attempt = page['attempts'][-1]
    attempt.update(status='cancelled', reason=notes)
    page['status'] = 'vector' if attempt['kind'] == 'correction' else 'needs_generation'
    if attempt['kind'] == 'correction':
        page['fallback_reason'] = notes
    save(task, record)
    return page



def finish_redraw(task, identifier, request, output, tool, receipt):
    """Host passes newly generated local output and real invocation receipt."""
    record = load(task)
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
    require_frozen(record)
    page = _page(record, identifier)
    if outcome not in ('failed', 'unavailable', 'unknown') or not notes or page['status'] == 'accepted':
        raise ReconstructionError('需要失败记录，且不能降级已接受重绘。')
    if page['attempts'] and page['attempts'][-1]['status'] in ('prepared', 'calling'):
        page['attempts'][-1].update(status=outcome, reason=notes)
    page.update(status='vector', fallback_reason=notes, fallback_outcome=outcome)
    save(task, record)
    return page


def review_redraw(task, identifier, accepted, notes, boundaries=None):
    """Actual image review supplies complete system boundaries on accepted output."""
    record = load(task)
    require_frozen(record)
    page = _page(record, identifier)
    if page['status'] != 'needs_image_review' or type(accepted) is not bool or not notes:
        raise ReconstructionError('需要实际重绘图审阅。')
    if accepted:
        with Image.open(artifact(task, page['output'])) as image:
            if boundaries is None and record.get('longshot'):
                from longshot import redraw_boxes
                boundaries = redraw_boxes(image, [record['regions'][i] for i in page['regions']])
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
    require_frozen(record)
    _require_safe_crops(task, record)
    output = record.get('output')
    if output:
        try:
            require_output_previews(task, output, record)
        except ReconstructionError:
            pass
        else:
            return output
    if host_redraw:
        pages = record.get('redraw_pages', [])
        if not pages or any(p['status'] not in ('accepted', 'vector') for p in pages):
            raise ReconstructionError('先完成每页重绘审阅或自动兜底。')
    else:
        if not output and record['status'] != 'ready_to_redraw':
            raise ReconstructionError('原图尚未确认完整，或仍有未决内容。')
    if output:
        invalidate_output(record, 'preview_layout_upgrade')
    output = render(task, record)
    require_output_previews(task, output, record)
    record.update(output=output, status='needs_pdf_review')
    save(task, record)
    return output


def generation_materials(task):
    """Ordered complete rows from accepted groups and geometric fallback."""
    record = load(task)
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


def _preview_and_check(task, output, blocks, options):
    import subprocess
    import math
    from reportlab.lib.pagesizes import A4
    directory = Path(task) / Path(output['pdf']).parent
    previews = []
    if output['page_count'] > 512:
        raise ReconstructionError('PDF 页面数超过预览资源限制。')
    for number in range(1, output['page_count'] + 1):
        prefix = write_path(task, directory.relative_to(task) / f'preview-{number}')
        subprocess.run(['pdftoppm','-f',str(number),'-l',str(number),'-scale-to','1200',
            '-png','-singlefile',str(Path(task)/output['pdf']),str(prefix)],
            check=True, capture_output=True, timeout=30)
        path = prefix.with_suffix('.png')
        with Image.open(path) as image:
            dimensions = list(image.size)
            image.verify()
        previews.append({'page':number,'path':str(path.relative_to(task)),'sha256':digest(path),'dimensions':dimensions})
    issues, warnings = [], []
    placements = output['placements']
    indices = [p['region'] for p in placements]
    if sorted(indices) != list(range(len(blocks))):
        issues.append({'code':'omitted_or_duplicate_position'})
    margin = options.get('margin',24)
    for placement in placements:
        box = placement['bbox']
        block = blocks[placement['region']]
        if not math.isfinite(placement['scale']) or placement['scale'] <= 0 or any(not math.isfinite(v) for v in box):
            issues.append({'code':'invalid_geometry','region':placement['region']})
        if box[0] < margin-0.01 or box[1] < margin-0.01 or box[2] > A4[0]-margin+0.01 or box[3] > A4[1]-margin+0.01:
            issues.append({'code':'print_boundary','region':placement['region']})
        if abs((box[2]-box[0])/block['width']-(box[3]-box[1])/block['height']) > 0.00001:
            issues.append({'code':'nonuniform_scale','region':placement['region']})
    for number in range(1,output['page_count']+1):
        page = [p for p in placements if p['page']==number]
        for a,b in zip(page,page[1:]):
            if a['bbox'][1] < b['bbox'][3]-0.01:
                issues.append({'code':'overlap','page':number})
        used = sum(p['bbox'][3]-p['bbox'][1] for p in page)
        if used < (A4[1]-2*margin)*0.25:
            warnings.append({'code':'sparse_page','page':number,'occupied_height':used})
    if issues:
        raise ReconstructionError('PDF 自动几何检查未通过。')
    return previews, {'producer':'program','status':'passed','issues':issues,'warnings':warnings,
        'scope':'placement geometry only; not music proofreading',
        'ordered_source_regions':[b['source_region'] for b in blocks]}


def finalize_output(task, output, blocks, options, record):
    """Create ordered previews and geometry evidence for every public renderer."""
    if record.get('longshot'):
        from longshot import NOTICE
        output.update(notice=NOTICE, reliable=False)
    output['previews'], output['checks'] = _preview_and_check(task, output, blocks, options)
    target = options.get('target_pages')
    count = output['page_count']
    output['layout_version'] = 2
    output['output_revision'] = Path(output['pdf']).parent.name
    output['freeze_id'] = record['freeze']['id']
    output['layout_options'] = options
    output['layout'] = {**options, 'actual_pages': count, 'target_met': target is None or count == target,
        'explanation': ('完整行与共同可读比例需要更多页面。' if count > target else '按完整行自然分页；页数目标为建议，不增加空白页。') if target and count != target else None}
    return output


def require_output_previews(task, output, record):
    if (not output or not output.get('output_revision') or
            output['output_revision'] != Path(output['pdf']).parent.name or
            output.get('freeze_id') != record.get('freeze', {}).get('id') or
            output.get('layout_options') != record.get('layout', {}) or
            output.get('layout_version') != 2 or
            output.get('checks', {}).get('status') != 'passed' or
            output.get('checks', {}).get('issues') != [] or
            output.get('checks', {}).get('ordered_source_regions') != list(range(len(record['regions']))) or
            [p.get('page') for p in output.get('previews', [])] != list(range(1, output['page_count'] + 1))):
        raise ReconstructionError('终稿缺少有效的全部有序预览与检查；重新导出并查看当前全部页面。')
    if output.get('status') == 'reviewed':
        review = output.get('review', {})
        if (review.get('output_revision') != output['output_revision'] or
                review.get('pages') != list(range(1, output['page_count'] + 1)) or
                review.get('preview_hashes') != [p['sha256'] for p in output['previews']]):
            raise ReconstructionError('终稿审核未绑定当前版本与全部预览；重新导出并实际审阅。')
    for preview in output['previews']:
        artifact(task, preview)
