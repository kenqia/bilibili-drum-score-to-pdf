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
import score_task
from public_video import acquire, video_origin, ACQUISITION_SECONDS, retryable_acquisition

from score_task import (ReconstructionError, load, review_pdf, redraw_inputs,
                        begin_redraw, finish_redraw, fail_redraw, review_redraw,
                        reject_accepted_redraw, generation_materials, crop_checks,
                        redraw_requests, dispatch_redraw, cancel_redraw)


def prepare(source, task, acquisition_timeout=ACQUISITION_SECONDS):
    """Same local/anonymous URL entry; resumes without downloading twice."""
    task = Path(task)
    if task.is_symlink():
        raise ReconstructionError('目标目录不能是符号链接。')
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
    retry = task.exists() and retryable_acquisition(task)
    if task.exists() and any(task.iterdir()) and not retry:
        raise ReconstructionError('目标目录已有用户文件。')
    origin = None
    if '://' in str(source):
        origin = video_origin(str(source))
        destination = task.parent / (task.name + '-source-' + uuid.uuid4().hex)
        try:
            source, origin = acquire(str(source), destination, timeout=acquisition_timeout)
        except BaseException:
            if retryable_acquisition(destination):
                (destination / 'manifest.json').unlink()
                destination.rmdir()
            raise
    if retry:
        local.probe_video(source)
        (task / 'manifest.json').unlink()
    record = local.prepare(source, task)
    if origin:
        record['origin'] = origin
    from agent_source_review import CONTRACT
    import host_check
    record.update(probes=[], redraw_pages=[], agent_review_contract=CONTRACT, workflow='longshot/1', pdf_route='original',
                  environment=host_check.check([]))
    record['metrics'].update(navigation_probes=0, native_retained=0, presented_images=0)
    score_task.save(task, record)
    return record


def navigate(task, seconds, width=480):
    """Low-resolution probe; Agent decides its next time, never a fixed cadence."""
    record = load(task)
    if type(width) is not int or not 64 <= width <= 960 or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 <= seconds < record['source']['duration']:
        raise ReconstructionError('导航时间或宽度无效。')
    import native_cache
    entry = native_cache.native(task, record, seconds)
    for probe in record.get('probes', []):
        if probe['requested_seconds'] == seconds and probe['requested_width'] == width:
            native_cache.evict(task, record)
            score_task.save(task, record)
            return probe
    pts = {key: entry[key] for key in ('timestamp', 'pts', 'time_base')}
    with Image.open(score_task.artifact(task, entry)) as source:
        image = source.convert('RGB')
    image.thumbnail((width, max(1, round(width * image.height / image.width))))
    directory = score_task.write_path(task, 'navigation')
    directory.mkdir(exist_ok=True)
    identifier = 'probe-' + uuid.uuid4().hex
    path = score_task.write_path(task, Path('navigation') / (identifier + '.png'))
    image.save(path)
    image.close()
    probe = {'id': identifier, 'path': str(path.relative_to(task)), 'sha256': score_task.digest(path), 'requested_seconds': seconds, 'requested_width': width, 'native_candidate': entry['id'], 'width': image.width, 'height': image.height, **pts}
    record.setdefault('probes', []).append(probe)
    record['metrics']['navigation_probes'] = len(record['probes'])
    native_cache.evict(task, record)
    score_task.save(task, record)
    return probe


def capture(task, seconds):
    shot = local.capture(task, seconds)
    record = load(task)
    record['metrics']['native_retained'] = len(record['captures'])
    score_task.save(task, record)
    return shot


def promote(task, identifier):
    record = load(task)
    for probe in record.get('probes', []):
        if probe['id'] == identifier:
            import native_cache
            return native_cache.capture(task, probe['requested_seconds'], expected=probe)
    raise ReconstructionError('导航候选引用无效。')


def cache_report(task):
    import native_cache
    return native_cache.report(load(task))


def cache_limits(task, max_entries=64, max_bytes=268435456):
    import native_cache
    if type(max_entries) is not int or type(max_bytes) is not int or max_entries < 1 or max_bytes < 1:
        raise ReconstructionError('缓存限制必须为正整数。')
    record = load(task)
    native_cache.state(record).update(max_entries=max_entries, max_bytes=max_bytes)
    native_cache.evict(task, record)
    score_task.save(task, record)
    return native_cache.report(record)


def present(task, identifiers, notes):
    """Receipt of images actually shown, distinct from retained or decoded frames."""
    record = load(task)
    known = {r['id'] for r in record['captures'] + record.get('probes', [])}
    if (not isinstance(notes, str) or not notes.strip() or not isinstance(identifiers, list) or
            not identifiers or any(not isinstance(i, str) for i in identifiers) or not set(identifiers).issubset(known)):
        raise ReconstructionError('呈交图像引用或实际看图记录无效。')
    record.setdefault('presentations', []).append({'images': identifiers, 'notes': notes})
    record['metrics']['presented_images'] = sum(len(item['images']) for item in record['presentations'])
    score_task.save(task, record)
    return record


def assemble(task, title, regions, review):
    """Select ordered original positions through the shared task lifecycle."""
    return score_task.assemble(task, title, regions, review, positioned=True)


def revise_selection(task, changes, review=None):
    """Patch explicit positions and merge unaffected evidence atomically via assemble."""
    from agent_source_review import merge_review
    import copy
    record = load(task)
    if not isinstance(changes, list) or not isinstance(review, (dict, type(None))):
        raise ReconstructionError('changes 必须为列表，review 必须为对象。', code='invalid_request', field='changes')
    regions = copy.deepcopy(record['regions'])
    if not regions or any(not r.get('position') for r in regions):
        raise ReconstructionError('局部修订需要已有明确原谱位置；先使用 assemble。')
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or change.get('position') in seen:
            raise ReconstructionError('局部修订必须为对象，同位置每次只修改一次。', code='invalid_request', field='changes')
        position, region = change.get('position'), change.get('region')
        if not isinstance(position, str) or not position or not isinstance(region, dict):
            raise ReconstructionError('局部修订需要 position 和完整 region。', code='invalid_request', field='changes')
        seen.add(position)
        index = next((i for i, r in enumerate(regions) if r['position'] == position), None)
        replacement = {**region, 'position': position}
        if index is not None:
            if change.get('after') is not None:
                raise ReconstructionError('替换来源不改变原谱顺序。', code='invalid_request', field='changes.after')
            regions[index] = replacement
        else:
            after = change.get('after')
            preceding = next((i for i, r in enumerate(regions) if r['position'] == after), None)
            if preceding is None:
                raise ReconstructionError('插入来源需要已存在的 after 位置。', code='invalid_request', field='changes.after')
            regions.insert(preceding + 1, replacement)
    patch = review if review is not None else {'complete': False, 'unresolved': ['局部来源已修改，等待实际审阅。']}
    merged = merge_review(record, regions, patch)
    return assemble(task, record['title'], regions, merged)


def export(task):
    """Export through the shared task lifecycle and existing renderer."""
    route = score_task.delivery_route(load(task))
    return score_task.export(task, _render_pdf, host_redraw=route == 'redraw', render_route=route)


def _render_pdf(task, record):
    pages = record['redraw_pages']
    blocks, vectors, routes = [], [], []
    route = score_task.delivery_route(record)
    if route == 'vector':
        routes = [route]
        for index, original in enumerate(record['regions']):
            blocks.append({**original, 'source_region': index})
            vectors.append(local.trace_region(task, original))
        pages = []
    for page in (pages if route == 'redraw' else []):
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
    layout_options = record.get('layout', {})
    if route == 'original':
        from longshot import _continuous_pages
        if ('page_breaks' in layout_options and
                layout_options.get('page_breaks_source_sha256') != record['longshot']['image']['sha256']):
            raise ReconstructionError('分页切口属于旧长图；重新查看并调用layout。', action='layout')
        blocks, placements = _continuous_pages(task, record, margin=layout_options.get('margin', 24),
                                              page_breaks=layout_options.get('page_breaks'))
        vectors, routes = [None] * len(blocks), [route]
        count = len(blocks)
    else:
        placements, count = local.paginate(blocks, margin=layout_options.get('margin',24), minimum_gap=layout_options.get('minimum_gap',6))
    if (Path(task) / 'exports').is_symlink():
        raise ReconstructionError('导出目录不能指向任务外。')
    revision = score_task.write_path(task, Path('exports') / uuid.uuid4().hex)
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
                with Image.open(score_task.artifact(task, block['image'])) as image:
                    canvas.drawImage(str(score_task.artifact(task, block['image'])), -box[0] * native_scale, -(image.height - box[1]) * native_scale, width=image.width * native_scale, height=image.height * native_scale)
            else:
                canvas.scale(scale, -scale)
                local.draw_vector(canvas, vector)
            canvas.restoreState()
        canvas.showPage()
    canvas.save()
    manifest = revision / 'materials.json'
    import json
    manifest.write_text(json.dumps({'blocks': blocks, 'vectors': vectors, 'inputs': [r['sha256'] for r in record['regions']],
        'source_review':record.get('source_review'), 'program_checks':record.get('program_checks'), 'layout':layout_options,
        'render_route': route, 'watermark_cleanup': record.get('watermark_cleanup') if route == 'original' else None}))
    output = {'pdf': str(pdf.relative_to(task)), 'sha256': score_task.digest(pdf), 'page_count': count, 'placements': placements, 'routes': routes, 'render_route': route, 'method': 'original_continuous_pages' if route == 'original' else 'reviewed_host_images_and_vector_fallback', 'layout_version': 2, 'status': 'needs_pdf_review', 'vector': {'path': str(manifest.relative_to(task)), 'sha256': score_task.digest(manifest)}}
    if route == 'original':
        output['print_source_sha256'] = blocks[0]['image']['sha256']
        output['page_strips'] = [{'page': i + 1, 'bbox': b['crop_bbox'], 'source_regions': b['source_regions']}
                                 for i, b in enumerate(blocks)]
    return score_task.finalize_output(task, output, blocks, layout_options, record)


from score_task import layout, set_pdf_route as pdf_route
from longshot import stitch, review_longshot, clean_watermark, repair_longshot


def stage(task):
    """Advance to the next source, host-generation or final-page review."""
    record = load(task)
    if record.get('workflow') == 'longshot/1':
        import longshot
        if not record.get('longshot') and not record['regions'] and not record['captures']:
            longshot.stitch(task)
            record = load(task)
        if longshot.is_longshot(record) and not (record['longshot'].get('review') or {}).get('accepted'):
            return longshot.handoff(record)
    artifacts = {}
    try:
        score_task.require_frozen(record)
    except ReconstructionError:
        from agent_source_review import source_handoff
        return source_handoff(record)
    checks = crop_checks(task)
    if checks['status'] != 'passed':
        return {'phase': 'source', 'status': 'blocked', 'artifacts': artifacts,
                'checks': checks, 'unresolved': checks['issues'],
                'next': {'operations': ['crop-checks', 'revise-crop', 'revise-selection', 'assemble'],
                         'operation': 'revise-crop', 'required_fields': ['index', 'bbox']}}
    route = score_task.delivery_route(record)
    calling = any(p['status'] == 'calling' for p in record.get('redraw_pages', []))
    batch = redraw_requests(task) if route == 'redraw' or calling else {'handoffs': []}
    record = load(task)
    handoffs = [h for h in batch['handoffs'] if h['status'] not in ('accepted', 'vector')]
    if handoffs:
        return {'phase':'generation','status':'pending','artifacts':artifacts,'checks':record.get('program_checks',{}),
            'unresolved':[],'handoffs':handoffs,'next':{'operations':['redraw-requests','dispatch-redraw','cancel-redraw','finish-redraw','review-redraw','fail-redraw'],
                'instruction':'宿主执行或实际视觉审阅尚未完成；未知调用先恢复，不重新发送。'}}
    if record.get('output'):
        try:
            score_task.require_output_previews(task, record['output'], record)
            if score_task.output_route(record['output']) != route:
                raise ReconstructionError('输出路线已改变。')
        except ReconstructionError:
            export(task)
            record = load(task)
        output = record['output']
        return {'phase':'complete' if output['status']=='reviewed' else 'pdf_review',
            'status':'complete' if output['status']=='reviewed' else 'pending',
            'artifacts':{**artifacts,'output':output},'checks':output.get('checks',{}),'unresolved':[],
            'next':None if output['status']=='reviewed' else {'operation':'review-pdf',
                'pages':list(range(1,output['page_count']+1)),'output_revision':output['output_revision'],
                'instruction':('实际查看全部有序预览、打印字号及每个分页切口两侧，核对渐强、圆圈、重音等与所属谱行的关系；紧凑版需确认稍小的音符仍可读。有疑问用layout(page_breaks)按原尺寸把相关行留在同页，再重新导出。' if route == 'original' else '实际查看全部有序预览并记录标题、顺序、首尾和关键记号。')}}
    export(task)
    return stage(task)


def revise_crop(task, index, bbox):
    record = load(task)
    if type(index) is not int or not 0 <= index < len(record['regions']):
        raise ReconstructionError('裁剪引用无效。', code='invalid_request', field='index')
    regions = [{**r, 'position': r.get('position') or str(i)}
               for i, r in enumerate(record['regions'])]
    region = regions[index]
    if (region['kind'] == 'system' and isinstance(bbox, list) and len(bbox) == 4
            and all(type(v) is int for v in bbox)):
        region['staff_top'] += region['bbox'][1] - bbox[1]
    region['bbox'] = bbox
    review = {**record['source_review'], 'complete': False,
              'unresolved': ['局部裁剪已修改，等待实际审阅。']}
    return score_task.assemble(task, record['title'], regions, review, positioned=True)
