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
from video_seek import VideoReader

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
    record.update(probes=[], redraw_pages=[])
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


def row_manifest(task):
    """Read the verified row inventory, never metadata-only approval."""
    record = load(task)
    return record.get('row_manifest', {'version': 'score-rows/1', 'rows': [],
        'source_sha256': record['source']['sha256'], 'continuity_complete': False,
        'unresolved': [{'code': 'no_row_observations'}]})


def review_continuity(task, previous_capture, capture, previous_bars, bars,
                      viewed_captures, complete_rows, first_last, notes):
    """Record an Agent's actual numbered join; this is not program OCR."""
    record = load(task)
    shots = {shot['id']: shot for shot in record['captures']}
    if (previous_capture not in shots or capture not in shots or
            not isinstance(viewed_captures, list) or
            not {previous_capture, capture}.issubset(viewed_captures) or
            not set(viewed_captures).issubset(shots) or complete_rows is not True or
            not isinstance(first_last, str) or not first_last.strip() or
            not isinstance(notes, str) or not notes.strip()):
        raise ReconstructionError('需要实际查看的两张来源、完整谱行和首尾接续依据。')
    for limits in (previous_bars, bars):
        if (not isinstance(limits, list) or len(limits) != 2 or
                any(type(value) is not int or value < 1 for value in limits) or limits[0] > limits[1]):
            raise ReconstructionError('小节范围必须为已实际读取的正整数起止。')
    if (bars[0] != previous_bars[1] + 1 or
            shots[previous_capture]['timestamp'] >= shots[capture]['timestamp']):
        raise ReconstructionError('小节或来源顺序不连续；请局部回查。')
    evidence = {'producer': 'agent', 'method': 'numbered_complete_rows_and_boundary_marks',
        'source_sha256': record['source']['sha256'], 'previous_capture': previous_capture,
        'capture': capture, 'previous_sha256': shots[previous_capture]['sha256'],
        'sha256': shots[capture]['sha256'], 'previous_bars': previous_bars, 'bars': bars,
        'viewed_captures': viewed_captures, 'complete_rows': True,
        'first_last': first_last.strip(), 'notes': notes.strip()}
    reviews = record.setdefault('continuity_reviews', [])
    if evidence not in reviews:
        reviews.append(evidence)
        record.pop('freeze', None)
    score_task.save(task, record)
    return evidence


def present(task, identifiers, notes):
    """Receipt of images actually shown, distinct from retained or decoded frames."""
    record = load(task)
    known = {r['id'] for r in record['captures'] + record.get('probes', [])}
    if not notes or not set(identifiers).issubset(known):
        raise ReconstructionError('呈交图像引用或实际看图记录无效。')
    record.setdefault('presentations', []).append({'images': identifiers, 'notes': notes})
    record['metrics']['presented_images'] = sum(len(item['images']) for item in record['presentations'])
    score_task.save(task, record)
    return record


def assemble(task, title, regions, review):
    """Select ordered original positions through the shared task lifecycle."""
    return score_task.assemble(task, title, regions, review, positioned=True)

def export(task):
    """Export through the shared task lifecycle and existing renderer."""
    return score_task.export(task, _render_pdf, host_redraw=True)


def _render_pdf(task, record):
    pages = record['redraw_pages']
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
    layout_options = record.get('layout', {})
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
        'source_review':record.get('source_review'), 'program_checks':record.get('program_checks'), 'layout':layout_options}))
    output = {'pdf': str(pdf.relative_to(task)), 'sha256': score_task.digest(pdf), 'page_count': count, 'placements': placements, 'routes': routes, 'method': 'reviewed_host_images_and_vector_fallback', 'layout_version': 2, 'status': 'needs_pdf_review', 'vector': {'path': str(manifest.relative_to(task)), 'sha256': score_task.digest(manifest)}}
    return score_task.finalize_output(task, output, blocks, layout_options, record)

from automatic_score import overview, resample, auto_freeze, revise_crop, scan_status


from score_task import layout



def stage(task, title=None, mode='sparse', max_observations=128):
    """Advance automatic work to the next genuine host or visual decision."""
    import automatic_score as automatic
    if mode not in ('sparse', 'strict'):
        raise ReconstructionError('导航模式必须为 sparse 或 strict。')
    if type(max_observations) is not int or not 1 <= max_observations <= 8192:
        raise ReconstructionError('单次导航预算必须为 1–8192 的整数。')
    record = load(task)
    artifacts = {}
    survey = record.get('overview', {})
    if mode == 'strict' and (survey.get('mode') == 'sparse' or not survey.get('scan', {}).get('complete') or
                            survey.get('scan', {}).get('policy_version') != automatic.SCAN_POLICY_VERSION):
        if survey:
            survey['mode'] = 'strict'
        record.pop('freeze', None)
        score_task.save(task, record)
        survey = overview(task)
        record = load(task)
    try:
        automatic.require_frozen(record)
        already_frozen = True
    except ReconstructionError:
        already_frozen = False
    if not already_frozen:
        if mode == 'sparse':
            import sparse_navigation
            sparse_navigation.collect(task, max_observations)
            survey = load(task)['overview']
        elif not survey.get('scan', {}).get('complete'):
            survey = overview(task)
    artifacts['overview'] = survey.get('panels', [])
    record = load(task)
    try:
        automatic.require_frozen(record)
    except ReconstructionError:
        result = auto_freeze(task, title)
        if result['status'] != 'frozen':
            current = load(task)
            return {'phase':'source','status':'pending' if current.get('navigation', {}).get('status') == 'pending' else 'blocked','artifacts':{**artifacts,
                'rough':result.get('rough'),'regions':result.get('regions')},
                'checks':result['checks'],'unresolved':result['checks'].get('unresolved',[]),
                'navigation': current.get('navigation'), 'row_manifest': current.get('row_manifest'),
                'scan_progress':record.get('overview', {}).get('scan', {}).get('progress', {}),
                'next':{'operations':['stage','row-manifest','review-continuity','resample','revise-crop','auto-freeze','assemble'], 'instruction':result.get('resume')}}
    checks = crop_checks(task)
    if checks['status'] != 'passed':
        return {'phase': 'source', 'status': 'blocked', 'artifacts': artifacts,
                'checks': checks, 'unresolved': checks['issues'],
                'next': {'operations': ['crop-checks', 'revise-crop', 'assemble']}}
    batch = redraw_requests(task)
    record = load(task)
    if record.get('output'):
        try:
            score_task.require_output_previews(task, record['output'], record)
        except ReconstructionError:
            export(task)
            record = load(task)
        output = record['output']
        return {'phase':'complete' if output['status']=='reviewed' else 'pdf_review',
            'status':'complete' if output['status']=='reviewed' else 'pending',
            'artifacts':{**artifacts,'output':output},'checks':output.get('checks',{}),'unresolved':[],
            'next':None if output['status']=='reviewed' else {'operation':'review-pdf',
                'pages':list(range(1,output['page_count']+1)),'output_revision':output['output_revision'],
                'instruction':'实际查看全部有序预览并记录标题、顺序、首尾和关键记号。'}}
    handoffs = [h for h in batch['handoffs'] if h['status'] not in ('accepted', 'vector')]
    if handoffs:
        return {'phase':'generation','status':'pending','artifacts':artifacts,'checks':record.get('program_checks',{}),
            'unresolved':[],'handoffs':handoffs,'next':{'operations':['redraw-requests','dispatch-redraw','cancel-redraw','finish-redraw','review-redraw','fail-redraw'],
                'instruction':'宿主执行或实际视觉审阅尚未完成；未知调用先恢复，不重新发送。'}}
    export(task)
    return stage(task,title)
