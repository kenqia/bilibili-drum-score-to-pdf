"""Local observation packets and deterministic execution of saved visual decisions."""
import hashlib
import json
import platform
import math
import time
import copy
import os
from agent_sampling import plan, check_request, LIMITS
from agent_performance import ACTIVE, Performance, stage
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, __version__ as pillow_version
from video_seek import ConversionError, VideoReader, probe_video
from public_video import acquire, ACQUISITION_SECONDS, InputError, retryable_acquisition
from score_detect import analyze_frame
from cursor_detect import cursor_occluded, obstruction_detected
from agent_regions import native_rows
from agent_continuity import continuous_rows
from agent_segments import ordered_segments
from manifest import save_crop
from pdf_export import PRINTABLE_WIDTH_INCHES, write_pdf

VERSION = 1
MAX_JSON = 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    os.replace(temporary, path)


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('non-finite JSON number')
    return number


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def load_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ConversionError('invalid_decision', '缺少或过大的 JSON 记录。')
    try:
        return json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()), object_pairs_hook=unique_object, parse_float=finite_float)
    except (ValueError, OSError):
        raise ConversionError('invalid_decision', 'JSON 格式非法。') from None


def metrics():
    return dict(seek_count=0, decode_elapsed=0, decoded_reported_frames=0, peak_temp_disk=0)


def empty_output(output):
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ConversionError('existing_output', '结果目录已有内容，请选择新的空目录。')
    output.mkdir(parents=True, exist_ok=True)


def image_pixels(output, images):
    total = 0
    for record in images:
        with Image.open(output / record['path']) as image:
            total += image.width * image.height
    return total


def prepare(source, output, origin=None, timestamps=None, sampling=None, version=1, prior=None):
    total_began = time.monotonic()
    source = Path(source).resolve()
    with stage('source_verification'):
        metadata = probe_video(source)
    if metadata['width'] < 700:
        raise ConversionError('low_resolution', '原视频分辨率不足。')
    source_hash = digest(source)
    task_id = hashlib.sha256((source_hash + str(output.resolve())).encode()).hexdigest()[:24]
    observation = dict(schema_version=VERSION, task_id=task_id, source=dict(path=str(source), sha256=source_hash, **metadata),
                       frames=[], images=[], candidates=[], intervals=[], coordinate_space='native_pixels',
                       fixed_layout_only=False)
    if origin:
        observation['source']['origin'] = origin
    if timestamps is None:
        with stage('navigation'):
            timestamps, sampling = plan(source, metadata)
    count = metrics()
    initial_decode = sampling['used']['decode_seconds']
    count['decode_elapsed'] = initial_decode
    began = time.monotonic()
    reader = VideoReader(source, metadata, count)
    images = []
    try:
        if prior:
            for key in ('frames', 'images', 'candidates'):
                observation[key] = copy.deepcopy(prior[key])
            observation['images'] = [i for i in observation['images'] if i['kind'] not in ('comparison', 'batch_comparison')]
            images = [Image.open(output / f['path']).convert('RGB') for f in observation['frames']]
        for index, requested in enumerate(timestamps):
            with stage('native_decode'):
                record, image = reader.read_record(requested)
            if prior and any(f['pts'] == record['pts'] and f['time_base'] == record['time_base'] for f in observation['frames']):
                raise ConversionError('invalid_request', '请求重解码了已有 PTS，不能声称新增观察。')
            frame_id = f'frame-{index:03d}' if version == 1 else f'v{version}-frame-{index:03d}'
            filename = f'{frame_id}.png'
            image.save(output / filename)
            frame = dict(id=frame_id, path=filename, sha256=digest(output / filename),
                         width=image.width, height=image.height, requested_timestamp=requested, **record)
            observation['frames'].append(frame)
            observation['images'].append(dict(id=frame_id, path=filename, sha256=frame['sha256'], frame_id=frame_id,
                                              kind='native', bbox=[0, 0, image.width, image.height],
                                              mapping=dict(coordinate_space='native_pixels', scale=[1, 1], source_offset=[0, 0])))
            images.append(image)
            # Detectors propose navigation boxes; Agent decisions may use any valid native ROI.
            try:
                with stage('native_analysis'):
                    analysis = analyze_frame(image)
            except ConversionError as error:
                analysis = dict(bbox=[0, 0, image.width, image.height], row_bounds=[], groups=[],
                                header_bbox=[0, 0, 0, 0], proposal_error=error.code)
            with stage('image_generation'):
                for y in range(0, image.height, 280):
                    for x in range(0, image.width, 640):
                        tile_box = [x, y, min(x + 800, image.width), min(y + 360, image.height)]
                        tile_id = f'{frame_id}-native-{x}-{y}'
                        tile_path = f'{tile_id}.png'
                        image.crop(tile_box).save(output / tile_path)
                        observation['images'].append(dict(id=tile_id, path=tile_path, sha256=digest(output / tile_path),
                            frame_id=frame_id, kind='native_detail', bbox=tile_box,
                            mapping=dict(coordinate_space='native_pixels', scale=[1, 1], source_offset=[x, y])))
                frame['analysis'] = analysis
                for row, bounds in enumerate(analysis['row_bounds']):
                    bbox = [analysis['bbox'][0], analysis['bbox'][1] + bounds[0], analysis['bbox'][2], analysis['bbox'][1] + bounds[1]]
                    candidate_id = f'{frame_id}-row-{row:03d}'
                    detail = f'{candidate_id}.png'
                    image.crop(bbox).save(output / detail)
                    observation['images'].append(dict(id=candidate_id, path=detail, sha256=digest(output / detail),
                                                      frame_id=frame_id, kind='detail', bbox=bbox,
                                                      mapping=dict(coordinate_space='native_pixels', scale=[1, 1], source_offset=bbox[:2])))
                    group = analysis['groups'][row]
                    native = image.crop(bbox)
                    clean = not cursor_occluded(native, group['spacing']) and not obstruction_detected(native, analysis['bbox'][1] + group['top'] - bbox[1], group['spacing'])
                    observation['candidates'].append(dict(id=candidate_id, frame_id=frame_id, index=row, bbox=bbox, clean=clean,
                                                         coordinate_space='native_pixels', complete=not (analysis['partial_top'] or analysis['partial_bottom'])))
        paired = sorted(zip(observation['frames'], images), key=lambda pair: pair[0]['timestamp'])
        observation['frames'] = [f for f, _ in paired]
        images = [i for _, i in paired]
        with stage('image_generation'):
            montage = Image.new('RGB', (640 * min(3, len(images)), 510 * math.ceil(len(images) / 3)), 'white')
            panels = []
            for index, (frame, image) in enumerate(zip(observation['frames'], images)):
                scale = min(640 / image.width, 480 / image.height)
                size = [round(image.width * scale), round(image.height * scale)]
                montage.paste(image.resize(size), (640 * (index % 3), 30 + 510 * (index // 3)))
                ImageDraw.Draw(montage).text((640 * (index % 3) + 5, 5 + 510 * (index // 3)), f'{frame["id"]}  {frame["timestamp"]:.6f} s', fill='black')
                panels.append(dict(frame_id=frame['id'], scale=scale, offset=[640 * (index % 3), 30 + 510 * (index // 3)], size=size,
                                   source_bbox=[0, 0, image.width, image.height],
                                   mapping=dict(coordinate_space='comparison_pixels', scale=[size[0] / image.width, size[1] / image.height], source_offset=[0, 0], view_offset=[640 * (index % 3), 30 + 510 * (index // 3)])))
            comparison_path = 'comparison.png' if version == 1 else f'comparison-v{version}.png'
            montage.save(output / comparison_path)
            observation['images'].append(dict(id='comparison', kind='comparison', path=comparison_path,
                                              sha256=digest(output / comparison_path), panels=panels))
            observation['intervals'] = [dict(start=a['timestamp'], end=b['timestamp']) for a, b in zip(observation['frames'], observation['frames'][1:])]
            if not prior:
                sampling['used']['native_frames'] += len(timestamps)
            sampling['used']['decode_seconds'] = count['decode_elapsed']
            count['decode_elapsed'] -= initial_decode
            observation['sampling'] = sampling
            observation['observation_version'] = version
            observation['batches'] = [dict(id=f'batch-{i//2:03d}', frames=[f['id'] for f in observation['frames'][i:i+3]]) for i in range(0, max(1, len(images)-1), 2)]
            observation['metrics'] = {**count, 'analyzed_frames': len(timestamps), 'native_images': len(images),
                                      'detail_images': sum(i['kind'] in ('detail', 'native_detail') for i in observation['images']), 'comparison_images': 1,
                                      'image_pixels': image_pixels(output, observation['images']),
                                      'model_elapsed': None, 'model_tokens': None, 'thumbnail_checks': sampling['thumbnail_checks'],
                                      'thumbnail_elapsed': sampling['thumbnail_elapsed'], 'comparison_composed_frames': len(images),
                                      'supplement_requests': sampling['used']['requests'], 'prepare_elapsed': time.monotonic()-began,
                                      'total_elapsed': time.monotonic()-total_began,
                                      'native_processing_elapsed': time.monotonic()-began-count['decode_elapsed']}
            for start, batch in zip(range(0, max(1, len(images)-1), 2), observation['batches']):
                batch_id = f'comparison-v{version}-{batch["id"]}'
                batch_path = f'{batch_id}.png'
                context = Image.new('RGB', (640 * len(batch['frames']), 510), 'white')
                context_panels = []
                for position, panel in enumerate(panels[start:start+3]):
                    context.paste(montage.crop((panel['offset'][0], panel['offset'][1]-30,
                        panel['offset'][0]+640, panel['offset'][1]+480)), (position*640, 0))
                    adjusted = copy.deepcopy(panel)
                    adjusted['offset'] = [position*640, 30]
                    adjusted['mapping']['view_offset'] = adjusted['offset']
                    context_panels.append(adjusted)
                context.save(output / batch_path)
                observation['images'].append(dict(id=batch_id, kind='batch_comparison', path=batch_path,
                    sha256=digest(output / batch_path), panels=context_panels))
                batch['image_id'] = batch_id
            observation['metrics']['image_pixels'] = image_pixels(output, observation['images'])
            observation['metrics']['comparison_images'] += len(observation['batches'])
            observation['metrics']['comparison_composed_frames'] += sum(len(b['frames']) for b in observation['batches'])
        if len(json.dumps(observation, ensure_ascii=False, indent=2, allow_nan=False).encode()) > MAX_JSON - 4096:
            raise ConversionError('sampling_budget', '观察包达到可恢复 JSON 大小上限，请保留疑点。')
        previous = load_json(output / 'task.json') if (output / 'task.json').exists() else {}
        write_json(output / 'observation.next.json', observation)
        result = dict(schema_version=VERSION, task_id=task_id, observation_sha256=digest(output / 'observation.next.json'),
                      status='waiting', complete=False, phase='review', observation_version=version, rows=[], issues=[],
                      next_action='Read comparison and native detail images, then submit a visual decision.', metrics=observation['metrics'])
        result['decision_history'] = previous.get('decision_history', [])
        write_json(output / 'sampling.next.json', sampling)
        result['sampling_sha256'] = digest(output / 'sampling.next.json')
        result['sampling_usage'] = sampling['used']
        write_json(output / 'task.next.json', result)
        write_json(output / 'publication.json', {'observation_sha256': result['observation_sha256'], 'state_sha256': digest(output / 'task.next.json'), 'sampling_sha256': result['sampling_sha256']})
        recover_publication(output)
        return result
    finally:
        reader.close()


def recover_publication(task):
    journal = task / 'publication.json'
    if not journal.exists():
        return
    record = load_json(journal)
    if set(record) != {'observation_sha256', 'state_sha256', 'sampling_sha256'}:
        raise ConversionError('invalid_task', '观察发布记录非法。')
    for stem, key in [('observation', 'observation_sha256'), ('sampling', 'sampling_sha256'), ('task', 'state_sha256')]:
        pending = task / f'{stem}.next.json'
        current = task / f'{stem}.json'
        path = pending if pending.exists() else current
        if digest(path) != record[key]:
            raise ConversionError('source_mismatch', '中断发布记录已损坏。')
        if pending.exists():
            os.replace(pending, current)
    journal.unlink()


def checked_task(task):
    if task.is_symlink():
        raise ConversionError('invalid_task', '任务路径非法。')
    recover_publication(task)
    state = load_json(task / 'task.json')
    observation = load_json(task / 'observation.json')
    if not isinstance(state, dict) or not isinstance(observation, dict):
        raise ConversionError('invalid_task', '任务记录非法。')
    if type(state.get('schema_version')) is not int or state['schema_version'] != VERSION or type(observation.get('schema_version')) is not int or observation['schema_version'] != VERSION:
        raise ConversionError('invalid_task', '任务协议版本不受支持，不迁移旧任务。')
    history = state.get('decision_history', [])
    if not isinstance(history, list):
        raise ConversionError('invalid_task', '接受历史非法。')
    for index, entry in enumerate(history):
        if not isinstance(entry, dict) or not isinstance(entry.get('sha256'), str) or len(entry['sha256']) != 64 or any(c not in '0123456789abcdef' for c in entry['sha256']):
            raise ConversionError('invalid_task', '接受历史引用非法。')
        if entry.get('path') != f'accepted-{index:04d}-{entry.get("sha256")}.json' or digest(task / entry['path']) != entry['sha256']:
            raise ConversionError('source_mismatch', '接受决定历史已损坏。')
    if digest(task / 'observation.json') != state['observation_sha256'] or observation['task_id'] != state['task_id']:
        raise ConversionError('source_mismatch', '观察包已改变。')
    for image in observation['images']:
        path = task / image['path']
        if path.parent != task or path.is_symlink() or digest(path) != image['sha256']:
            raise ConversionError('source_mismatch', '观察图像已改变。')
    ledger_path = task / 'sampling.json'
    if state.get('sampling_sha256') and digest(ledger_path) != state['sampling_sha256']:
        raise ConversionError('invalid_request', '采样预算记录已改变。')
    ledger = load_json(ledger_path) if ledger_path.exists() else observation['sampling']
    used = ledger['used']
    if ledger['limits'] != LIMITS or set(used) != set(LIMITS) or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in used.values()) or any(type(used[k]) is not int for k in ('requests','native_frames','requested_frames')) or any(used[k] < observation['sampling']['used'][k] for k in used):
        raise ConversionError('invalid_request', '采样预算记录非法。')
    if digest(observation['source']['path']) != observation['source']['sha256']:
        raise ConversionError('source_mismatch', '原视频已改变。')
    return state, observation


def validate(decision, state, observation):
    fields = {'schema_version', 'task_id', 'observation_sha256', 'decision_id', 'model', 'prompt', 'presented_images',
              'visual_review', 'complete', 'evidence', 'selected_candidates', 'unresolved'}
    version = decision.get('schema_version') if isinstance(decision, dict) else None
    if version in (2, 3):
        fields = fields - {'selected_candidates'} | {'rows'}
    if version == 3:
        fields |= {'observations', 'transitions', 'coverage'}
    if version == 4:
        fields = fields - {'selected_candidates'} | {'segments','boundaries','coverage'}
    if not isinstance(decision, dict) or set(decision) != fields or type(version) is not int or version not in (1, 2, 3, 4):
        raise ConversionError('invalid_decision', '决定字段或版本非法。')
    if decision['task_id'] != state['task_id'] or decision['observation_sha256'] != state['observation_sha256']:
        raise ConversionError('invalid_decision', '决定不属于当前观察包。')
    if any(not isinstance(decision[k], str) or not decision[k].strip() or len(decision[k]) > 2000 for k in ('decision_id', 'evidence')):
        raise ConversionError('invalid_decision', '缺少简短观察依据或决定 ID。')
    model, prompt = decision['model'], decision['prompt']
    if not isinstance(model, dict) or set(model) != {'id', 'version'} or any(not isinstance(v, str) or not v for v in model.values()):
        raise ConversionError('invalid_decision', '模型标识必须明确；不可见版本使用 unknown。')
    if not isinstance(prompt, dict) or set(prompt) != {'version', 'text'} or any(not isinstance(v, str) or not v or len(v) > 16000 for v in prompt.values()):
        raise ConversionError('invalid_decision', '缺少公开任务提示词版本。')
    if type(decision['visual_review']) is not bool or type(decision['complete']) is not bool or not isinstance(decision['unresolved'], list):
        raise ConversionError('invalid_decision', '审阅或完整性状态非法。')
    known = {i['id'] for i in observation['images']}
    presented = decision['presented_images']
    if not isinstance(presented, list) or not all(isinstance(i, str) and i in known for i in presented) or len(set(presented)) != len(presented):
        raise ConversionError('invalid_decision', '图像呈交清单非法。')
    if version in (2, 3, 4):
        if 'comparison' not in presented or any(f['id'] not in presented for f in observation['frames']):
            raise ConversionError('missing_evidence', '必须查看相邻对照图与全部原帧。')
        if not decision['visual_review'] or not decision['complete'] or decision['unresolved']:
            raise ConversionError('review_required', '视觉审阅或完整性存在未决疑点。')
        if version in (3, 4):
            try:
                return (ordered_segments if version == 4 else continuous_rows)(decision, observation, presented)[0]
            except ConversionError as error:
                error.issues = [dict(reason=error.code, start=a['timestamp'], end=b['timestamp'],
                                     before_image=a['id'], after_image=b['id'],
                                     before_screenshot=a['path'], after_screenshot=b['path'])
                                for a, b in zip(observation['frames'], observation['frames'][1:])]
                raise
        return native_rows(decision, observation, presented)
    if any(f['analysis']['bbox'] != observation['frames'][0]['analysis']['bbox'] or f['analysis']['row_bounds'] != observation['frames'][0]['analysis']['row_bounds'] for f in observation['frames'][1:]):
        raise ConversionError('review_required', 'v1 选择协议只支持固定检测几何，请改用原生谱行决定。')
    selected = decision['selected_candidates']
    candidates = {c['id']: c for c in observation['candidates']}
    if not isinstance(selected, list) or not selected or not all(isinstance(i, str) and i in candidates for i in selected) or len(set(selected)) != len(selected):
        raise ConversionError('invalid_decision', '候选引用非法。')
    chosen = [candidates[i] for i in selected]
    if any(c['id'] not in presented or c['frame_id'] not in presented for c in chosen) or 'comparison' not in presented or any(f['id'] not in presented for f in observation['frames']):
        raise ConversionError('missing_evidence', '必须呈交对照图、所选原图和原生细节。')
    if not decision['visual_review'] or not decision['complete'] or decision['unresolved'] or any(not c['complete'] or not c['clean'] for c in chosen):
        raise ConversionError('review_required', '视觉审阅或完整性存在未决疑点。')
    indices = [c['index'] for c in chosen]
    if indices != list(range(len(observation['frames'][0]['analysis']['groups']))):
        raise ConversionError('review_required', '谱行缺失、重复或顺序非法。')
    for c in chosen:
        frame = next(f for f in observation['frames'] if f['id'] == c['frame_id'])
        bbox = c['bbox']
        if c['coordinate_space'] != 'native_pixels' or len(bbox) != 4 or any(type(v) is not int for v in bbox) or not (0 <= bbox[0] < bbox[2] <= frame['width'] and 0 <= bbox[1] < bbox[3] <= frame['height']):
            raise ConversionError('invalid_decision', '候选坐标非法。')
    return chosen


def submit(task, path):
    with stage('source_verification'):
        state, observation = checked_task(task)
    value = load_json(path)
    batch = isinstance(value, dict) and type(value.get('schema_version')) is int and value['schema_version'] == 5
    decision = value.get('decision') if batch else value
    history = state.get('decision_history', [])
    if not isinstance(decision, dict) or decision.get('task_id') != state['task_id'] or decision.get('observation_sha256') != state['observation_sha256']:
        raise ConversionError('invalid_decision', '决定不属于当前观察包。')
    decision_id = value.get('decision_id') if isinstance(value, dict) else None
    if not isinstance(decision_id, str) or not decision_id.strip() or len(decision_id) > 2000:
        raise ConversionError('invalid_decision', '缺少决定 ID。')
    for entry in history:
        if entry['decision_id'] == decision_id:
            if entry['observation_sha256'] != state['observation_sha256']:
                raise ConversionError('invalid_decision', '旧包决定不能在新观察版本继续。')
            if load_json(task / entry['path']) != value:
                raise ConversionError('existing_decision', '同一决定 ID 的内容不同。')
            return state
    reviewed = [f['id'] for f in observation['frames']]
    revision = None
    if batch:
        if set(value) != {'schema_version', 'decision_id', 'reviewed_frames', 'revision_of', 'decision'} or not isinstance(decision, dict) or type(decision.get('schema_version')) is not int or decision.get('schema_version') not in (1,2,3,4):
            raise ConversionError('invalid_decision', '批次须封装已支持的决定协议。')
        reviewed = value['reviewed_frames']
        all_frames = [f['id'] for f in observation['frames']]
        if not isinstance(reviewed, list) or not reviewed or reviewed != all_frames[:len(reviewed)]:
            raise ConversionError('invalid_decision', '批次必须是从首帧开始的连续已审前缀。')
        if len(reviewed) < len(all_frames) and decision['schema_version'] not in (3,4):
            raise ConversionError('invalid_decision', '固定协议不能用于部分进度。')
        revision = value['revision_of']
        if revision is not None and (not history or revision != history[-1]['decision_id']):
            raise ConversionError('existing_decision', '修订必须明确引用最新已接受决定。')
    if history:
        baseline = load_json(task / history[0]['path'])
        baseline = baseline.get('decision', baseline)
        if not isinstance(decision, dict) or decision.get('model') != baseline['model'] or decision.get('schema_version') != baseline['schema_version']:
            raise ConversionError('invalid_decision', '不能混用模型标识或决定协议，请创建新任务。')
    previous_frames = state.get('reviewed_frames', [])
    if previous_frames and revision is None:
        if reviewed[:len(previous_frames)] != previous_frames or len(reviewed) <= len(previous_frames):
            raise ConversionError('existing_decision', '继续批次必须扩展已审前缀，修改请显式修订。')
        previous = load_json(task / history[-1]['path'])
        previous = previous.get('decision', previous)
        for key in ('rows', 'observations', 'transitions', 'boundaries'):
            if key in previous and decision.get(key, [])[:len(previous[key])] != previous[key]:
                raise ConversionError('existing_decision', '已接受身份或裁剪改变，请显式修订并重新审计。')
        if 'segments' in previous:
            old_segments, new_segments = previous['segments'], decision.get('segments')
            if not isinstance(new_segments, list) or len(new_segments) < len(old_segments) or new_segments[:len(old_segments)-1] != old_segments[:-1]:
                raise ConversionError('existing_decision', '已接受谱面段改变，请显式修订并重新审计。')
            old_last, new_last = old_segments[-1], new_segments[len(old_segments)-1]
            if not isinstance(new_last, dict) or set(new_last) != set(old_last):
                raise ConversionError('existing_decision', '已接受谱面段字段改变，请显式修订并重新审计。')
            for key, accepted in old_last.items():
                proposed = new_last[key]
                if key in ('frames', 'rows', 'observations', 'transitions'):
                    unchanged = isinstance(proposed, list) and proposed[:len(accepted)] == accepted
                else:
                    unchanged = proposed == accepted
                if not unchanged:
                    raise ConversionError('existing_decision', '已接受身份或裁剪改变，请显式修订并重新审计。')
    partial = copy.deepcopy(observation)
    partial['frames'] = [f for f in observation['frames'] if f['id'] in reviewed]
    allowed = {i['id'] for i in observation['images'] if i.get('frame_id') in reviewed or i['kind'] == 'comparison' or (i['kind'] == 'batch_comparison' and all(p['frame_id'] in reviewed for p in i['panels']))}
    if not isinstance(decision, dict) or any(i not in allowed for i in decision.get('presented_images', [])):
        raise ConversionError('invalid_decision', '批次不能引用未审尾部。')
    with stage('decision_validation'):
        validate(decision, state, partial)
    complete = len(reviewed) == len(observation['frames'])
    staged = task / 'accepted.next.json'
    write_json(staged, value)
    record_hash = digest(staged)
    entry = dict(path=f'accepted-{len(history):04d}-{record_hash}.json', decision_id=decision_id, observation_sha256=state['observation_sha256'],
                 observation_version=state['observation_version'], revision_of=revision)
    os.replace(staged, task / entry['path'])
    entry['sha256'] = record_hash
    state.update(decision_history=history+[entry], reviewed_frames=reviewed, phase='accepted' if complete else 'batch_accepted',
                 complete=complete, status='waiting', issues=[] if complete else [{'reason':'unreviewed_tail','frames':[f['id'] for f in observation['frames'][len(reviewed):]]}],
                 next_action='Export to a new empty directory.' if complete else 'Review the next overlapping batch and submit the cumulative prefix.')
    write_json(task / 'task.json', state)
    if complete:
        write_json(task / 'decision.json', decision)
    return state


def export(task, output):
    with stage('source_verification'):
        state, observation = checked_task(task)
    if state.get('decision_history'):
        if state.get('phase') != 'accepted' or not state.get('complete'):
            raise ConversionError('review_required', '仍有未审尾部或观察包已更新。')
        record = load_json(task / state['decision_history'][-1]['path'])
        decision = record.get('decision', record)
    else:
        decision = load_json(task / 'decision.json')
    with stage('decision_validation'):
        chosen = validate(decision, state, observation)
    count = metrics()
    reader = VideoReader(observation['source']['path'], observation['source'], count)
    rows, header = [], None
    try:
        for frame in observation['frames']:
            with stage('source_redecode'):
                actual, image = reader.read_record(frame['requested_timestamp'])
            path = output / frame['path']
            image.save(path)
            if actual != {k: frame[k] for k in ('timestamp', 'pts', 'time_base')} or image.size != (frame['width'], frame['height']) or digest(path) != frame['sha256']:
                raise ConversionError('source_mismatch', '重新解码的原帧、PTS 或尺寸不一致。')
        for c in chosen:
            frame = next(f for f in observation['frames'] if f['id'] == c['frame_id'])
            dpi = (c['bbox'][2] - c['bbox'][0]) / PRINTABLE_WIDTH_INCHES
            if dpi < 150:
                raise ConversionError('low_resolution', '谱行不足 150 effective DPI。')
            row = save_crop(output, frame['path'], c['bbox'], f'row-{c["index"]:03d}')
            row.update(id=f'row{c["index"]}', index=c['index'], timestamp=frame['timestamp'], pts=frame['pts'], time_base=frame['time_base'],
                       selected_candidate=c, quality={'effective_dpi': round(dpi, 3), 'complete': True})
            if decision['schema_version'] in (3,4):
                row.update(**{k: c[k] for k in ('instance_id', 'observation_id', 'global_y', 'scroll_offset')})
            if decision['schema_version'] == 4:
                row['segment_id'] = c['segment_id']
            rows.append(row)
        extras = []
        first = observation['frames'][0]
        bbox = first['analysis']['header_bbox']
        if decision['schema_version'] != 4 and bbox[3] > bbox[1]:
            header = save_crop(output, first['path'], bbox, 'header')
            header.update(timestamp=first['timestamp'], pts=first['pts'], time_base=first['time_base'])
        if decision['schema_version'] == 4:
            _, segment_audit, regions = ordered_segments(decision, observation, decision['presented_images'])
            for index,c in enumerate(regions):
                frame = next(f for f in observation['frames'] if f['id'] == c['frame_id'])
                if (c['bbox'][2]-c['bbox'][0])/PRINTABLE_WIDTH_INCHES < 150:
                    raise ConversionError('low_resolution', '行外区域不足 150 effective DPI。')
                extra = save_crop(output,frame['path'],c['bbox'],f'extra-{index:03d}')
                extra.update(segment_id=c['segment_id'],kind=c['kind'],placement=c['placement'],timestamp=frame['timestamp'],pts=frame['pts'],time_base=frame['time_base'],selected_region=c)
                extras.append(extra)
            blocks=[]
            for segment in decision['segments']:
                blocks.extend(e for e in extras if e['segment_id']==segment['id'] and e['placement']=='before_rows')
                blocks.extend(r for r in rows if r['segment_id']==segment['id'])
                blocks.extend(e for e in extras if e['segment_id']==segment['id'] and e['placement']=='after_rows')
            with stage('pdf_export'):
                pages=write_pdf(output,None,blocks)
        else:
            with stage('pdf_export'):
                pages = write_pdf(output, header, rows)
        try:
            revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            revision = 'unknown'
        result = dict(schema_version=VERSION, status='success', complete=True, phase='export', task_id=state['task_id'],
                      source=observation['source'], observation_sha256=state['observation_sha256'], rows=rows, header=header,
                      issues=[], page_count=pages, pdf='score.pdf', decision=decision, script_revision=revision,
                      environment={'python': platform.python_version(), 'pillow': pillow_version},
                      skill_sha256=digest(Path(__file__).parents[1] / 'SKILL.md'),
                      presented_images=[i for i in observation['images'] if i['id'] in decision['presented_images']],
                      prompt_sha256=hashlib.sha256(decision['prompt']['text'].encode()).hexdigest(), metrics=count)
        if decision['schema_version'] == 4:
            result.update(coverage=segment_audit,extras=extras)
        elif decision['schema_version'] == 3:
            result['coverage'] = continuous_rows(decision, observation, decision['presented_images'])[1]
        else:
            result['coverage'] = {'scope': 'fixed_layout_trial', 'hidden_content_proven_absent': False}
        result['decision_history'] = state.get('decision_history', [])
        result['metrics']['presented_image_pixels'] = image_pixels(task, result['presented_images'])
        result['metrics']['model_elapsed'] = None
        result['metrics']['model_tokens'] = None
        write_json(output / 'decision.json', decision)
        return result
    finally:
        reader.close()



def supplement(task, path):
    with stage('source_verification'):
        state, observation = checked_task(task)
    request = load_json(path)
    timestamps = check_request(request, state, observation)
    sampling = copy.deepcopy(observation['sampling'])
    # Charge accepted requests before decoding, so interrupted requests cannot reset the budget.
    ledger_path = task / 'sampling.json'
    if ledger_path.exists():
        ledger = load_json(ledger_path)
        sampling['used'] = ledger['used']
        sampling['request_ids'] = ledger['request_ids']
        check_request(request, state, {**observation, 'sampling': sampling})
    sampling['used']['requests'] += 1
    sampling['used']['requested_frames'] += len(timestamps)
    sampling['request_ids'].append(request['request_id'])
    sampling['used']['native_frames'] += len(timestamps)
    reserved = copy.deepcopy(sampling)
    reserved['used']['decode_seconds'] += min(60 * len(timestamps), max(0, sampling['limits']['decode_seconds'] - sampling['used']['decode_seconds']))
    write_json(ledger_path, reserved)
    state.update(sampling_sha256=digest(ledger_path), sampling_usage=reserved['used'], phase='supplement_pending', complete=False,
                 issues=[request['issue']], next_action='Inspect the unresolved sampling request, then supplement or explicitly revise the decision.')
    write_json(task / 'task.json', state)
    version = state.get('observation_version', 1)
    archive = task / f'observation-v{version}.json'
    if not archive.exists():
        archive.write_bytes((task / 'observation.json').read_bytes())
    decision = task / 'decision.json'
    result = prepare(observation['source']['path'], task, origin=observation['source'].get('origin'),
                     timestamps=timestamps, sampling=sampling, version=version+1, prior=observation)
    if decision.exists():
        decision.rename(task / f'decision-v{version}.json')
    write_json(task / f'request-{version+1}.json', request)
    return result


def run(operation, source=None, task=None, decision=None, output=None, acquisition_timeout=ACQUISITION_SECONDS):
    target = Path(output) if output and operation in ('prepare', 'export', 'replay') else None
    performance = None
    token = None
    try:
        if operation == 'report':
            state, observation = checked_task(Path(task))
            recorder = Performance(Path(task), load_json, write_json)
            recorder.metadata(observation, state)
            return dict(status='success' if recorder.data['task_status'] == 'success' else 'waiting', complete=recorder.data['task_status'] == 'success', phase='report', performance=recorder.report())
        if operation in ('prepare', 'export', 'replay'):
            if not target:
                raise ConversionError('invalid_input', '需要新的结果目录。')
            retry = operation == 'prepare' and retryable_acquisition(target)
            if retry:
                performance = Performance(target, load_json, write_json, embedded=True)
                (target / 'manifest.json').unlink()
            empty_output(target)
            if operation == 'prepare':
                performance = performance or Performance(target, load_json, write_json, embedded=bool(source and '://' in str(source)))
        if operation != 'prepare' and task and Path(task).is_dir() and not Path(task).is_symlink():
            performance = Performance(Path(task), load_json, write_json)
        if performance:
            performance.start(operation)
            token = ACTIVE.set(performance)
        if operation == 'prepare':
            origin = None
            if source and '://' in str(source):
                with stage('anonymous_acquisition'):
                    source, origin = acquire(source, target, timeout=acquisition_timeout)
            performance.embedded = False
            performance.save()
            result = prepare(source, target, origin=origin)
        elif operation == 'supplement':
            result = supplement(Path(task), decision)
        elif operation == 'resume':
            result, _ = checked_task(Path(task))
        elif operation == 'submit':
            result = submit(Path(task), decision)
        else:
            result = export(Path(task), target)
    except InputError as error:
        result = dict(schema_version=VERSION, status='failed', complete=False, phase='acquisition', rows=[], issues=[],
                      error={'code': error.code, 'message': str(error)})
        if error.origin:
            result['origin'] = error.origin
        if hasattr(error, 'diagnostics'):
            result['error'].update(error.diagnostics)
        if hasattr(error, 'http_status'):
            result['error']['http_status'] = error.http_status
    except KeyboardInterrupt:
        result = dict(status='failed', complete=False, phase=operation, error={'code': 'interrupted', 'message': '任务已中断，请保留观察包并使用新的结果目录。'})
    except (ConversionError, OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        code = error.code if isinstance(error, ConversionError) else 'invalid_input'
        result = dict(status='waiting' if code in ('unsupported_layout', 'review_required', 'missing_evidence', 'sampling_budget') else 'failed',
                      complete=False, phase=operation, rows=[], issues=[], error={'code': code, 'message': str(error) if isinstance(error, ConversionError) else '记录或输入不可用。'})
        result['issues'] = getattr(error, 'issues', [])
        if operation in ('submit', 'supplement') and result['status'] == 'waiting':
            try:
                saved, _ = checked_task(Path(task))
                saved.update(complete=False, phase='review', issues=result['issues'] or [result['error']], next_action='Resolve the saved review issues before export.')
                write_json(Path(task) / 'task.json', saved)
            except (ConversionError, OSError, ValueError, TypeError, KeyError):
                pass
    if performance:
        if (performance.directory / 'observation.json').exists() and (performance.directory / 'task.json').exists():
            try:
                performance.metadata(load_json(performance.directory / 'observation.json'), load_json(performance.directory / 'task.json'))
            except (ConversionError, OSError, ValueError, TypeError, KeyError):
                pass
        if target and result.get('status') == 'success' and operation in ('export','replay'):
            with stage('delivery_publication'):
                write_json(target / 'manifest.json', result)
        performance.finish(result)
        result['performance'] = performance.report()
        if performance.embedded:
            result['performance_ledger'] = performance.data
        if token is not None:
            ACTIVE.reset(token)
    if target and target.exists() and result.get('error', {}).get('code') != 'existing_output':
        write_json(target / 'manifest.json', result)
    return result
