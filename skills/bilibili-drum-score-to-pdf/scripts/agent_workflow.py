"""Local observation packets and deterministic execution of saved visual decisions."""
import hashlib
import json
import platform
import math
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, __version__ as pillow_version
from video_seek import ConversionError, VideoReader, probe_video
from score_detect import analyze_frame
from cursor_detect import cursor_occluded, obstruction_detected
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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


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


def prepare(source, output):
    source = Path(source).resolve()
    metadata = probe_video(source)
    if metadata['width'] < 700:
        raise ConversionError('low_resolution', '原视频分辨率不足。')
    source_hash = digest(source)
    task_id = hashlib.sha256((source_hash + str(output.resolve())).encode()).hexdigest()[:24]
    observation = dict(schema_version=VERSION, task_id=task_id, source=dict(path=str(source), sha256=source_hash, **metadata),
                       frames=[], images=[], candidates=[], intervals=[], coordinate_space='native_pixels',
                       fixed_layout_only=True)
    count = metrics()
    reader = VideoReader(source, metadata, count)
    images = []
    try:
        for index, requested in enumerate([0, metadata['duration'] / 2, None]):
            record, image = reader.read_record(requested)
            frame_id = f'frame-{index:03d}'
            filename = f'{frame_id}.png'
            image.save(output / filename)
            frame = dict(id=frame_id, path=filename, sha256=digest(output / filename),
                         width=image.width, height=image.height, requested_timestamp=requested, **record)
            observation['frames'].append(frame)
            observation['images'].append(dict(id=frame_id, path=filename, sha256=frame['sha256'], frame_id=frame_id,
                                              kind='native', bbox=[0, 0, image.width, image.height]))
            images.append(image)
            analysis = analyze_frame(image)
            frame['analysis'] = analysis
            for row, bounds in enumerate(analysis['row_bounds']):
                bbox = [analysis['bbox'][0], analysis['bbox'][1] + bounds[0], analysis['bbox'][2], analysis['bbox'][1] + bounds[1]]
                candidate_id = f'{frame_id}-row-{row:03d}'
                detail = f'{candidate_id}.png'
                image.crop(bbox).save(output / detail)
                observation['images'].append(dict(id=candidate_id, path=detail, sha256=digest(output / detail),
                                                  frame_id=frame_id, kind='detail', bbox=bbox))
                group = analysis['groups'][row]
                native = image.crop(bbox)
                clean = not cursor_occluded(native, group['spacing']) and not obstruction_detected(native, analysis['bbox'][1] + group['top'] - bbox[1], group['spacing'])
                observation['candidates'].append(dict(id=candidate_id, frame_id=frame_id, index=row, bbox=bbox, clean=clean,
                                                     coordinate_space='native_pixels', complete=not (analysis['partial_top'] or analysis['partial_bottom'])))
        montage = Image.new('RGB', (640 * len(images), 510), 'white')
        panels = []
        for index, (frame, image) in enumerate(zip(observation['frames'], images)):
            scale = min(640 / image.width, 480 / image.height)
            size = [round(image.width * scale), round(image.height * scale)]
            montage.paste(image.resize(size), (640 * index, 30))
            ImageDraw.Draw(montage).text((640 * index + 5, 5), f'{frame["id"]}  {frame["timestamp"]:.6f} s', fill='black')
            panels.append(dict(frame_id=frame['id'], scale=scale, offset=[640 * index, 30], size=size))
        montage.save(output / 'comparison.png')
        observation['images'].append(dict(id='comparison', kind='comparison', path='comparison.png',
                                          sha256=digest(output / 'comparison.png'), panels=panels))
        if any(f['analysis']['bbox'] != observation['frames'][0]['analysis']['bbox'] or f['analysis']['row_bounds'] != observation['frames'][0]['analysis']['row_bounds'] for f in observation['frames'][1:]):
            raise ConversionError('review_required', '当前流程只支持固定谱面，观察到几何变化。')
        observation['intervals'] = [dict(start=a['timestamp'], end=b['timestamp']) for a, b in zip(observation['frames'], observation['frames'][1:])]
        observation['metrics'] = {**count, 'analyzed_frames': len(images), 'native_images': len(images),
                                  'detail_images': len(observation['candidates']), 'comparison_images': 1,
                                  'image_pixels': image_pixels(output, observation['images']),
                                  'model_elapsed': None, 'model_tokens': None}
        write_json(output / 'observation.json', observation)
        result = dict(schema_version=VERSION, task_id=task_id, observation_sha256=digest(output / 'observation.json'),
                      status='waiting', complete=False, phase='review', rows=[], issues=[],
                      next_action='Read comparison and native detail images, then submit a visual decision.', metrics=observation['metrics'])
        write_json(output / 'task.json', result)
        return result
    finally:
        reader.close()


def checked_task(task):
    if task.is_symlink():
        raise ConversionError('invalid_task', '任务路径非法。')
    state = load_json(task / 'task.json')
    observation = load_json(task / 'observation.json')
    if digest(task / 'observation.json') != state['observation_sha256'] or observation['task_id'] != state['task_id']:
        raise ConversionError('source_mismatch', '观察包已改变。')
    for image in observation['images']:
        path = task / image['path']
        if path.parent != task or path.is_symlink() or digest(path) != image['sha256']:
            raise ConversionError('source_mismatch', '观察图像已改变。')
    if digest(observation['source']['path']) != observation['source']['sha256']:
        raise ConversionError('source_mismatch', '原视频已改变。')
    return state, observation


def validate(decision, state, observation):
    fields = {'schema_version', 'task_id', 'observation_sha256', 'decision_id', 'model', 'prompt', 'presented_images',
              'visual_review', 'complete', 'evidence', 'selected_candidates', 'unresolved'}
    if not isinstance(decision, dict) or set(decision) != fields or type(decision['schema_version']) is not int or decision['schema_version'] != VERSION:
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
    state, observation = checked_task(task)
    decision = load_json(path)
    validate(decision, state, observation)
    record = task / 'decision.json'
    if record.exists():
        if load_json(record) != decision:
            raise ConversionError('existing_decision', '已有决定，请保留原任务；修订流程尚未启用。')
    else:
        write_json(record, decision)
    return {**state, 'phase': 'accepted', 'next_action': 'Export to a new empty directory.'}


def export(task, output):
    state, observation = checked_task(task)
    decision = load_json(task / 'decision.json')
    chosen = validate(decision, state, observation)
    count = metrics()
    reader = VideoReader(observation['source']['path'], observation['source'], count)
    rows, header = [], None
    try:
        for frame in observation['frames']:
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
            rows.append(row)
        first = observation['frames'][0]
        bbox = first['analysis']['header_bbox']
        if bbox[3] > bbox[1]:
            header = save_crop(output, first['path'], bbox, 'header')
            header.update(timestamp=first['timestamp'], pts=first['pts'], time_base=first['time_base'])
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
        write_json(output / 'decision.json', decision)
        return result
    finally:
        reader.close()


def run(operation, source=None, task=None, decision=None, output=None):
    target = Path(output) if output and operation in ('prepare', 'export', 'replay') else None
    try:
        if operation in ('prepare', 'export', 'replay'):
            if not target:
                raise ConversionError('invalid_input', '需要新的结果目录。')
            empty_output(target)
        if operation == 'prepare':
            result = prepare(source, target)
        elif operation == 'submit':
            result = submit(Path(task), decision)
        else:
            result = export(Path(task), target)
    except KeyboardInterrupt:
        result = dict(status='failed', complete=False, phase=operation, error={'code': 'interrupted', 'message': '任务已中断，请保留观察包并使用新的结果目录。'})
    except (ConversionError, OSError, ValueError, TypeError, KeyError) as error:
        code = error.code if isinstance(error, ConversionError) else 'invalid_input'
        result = dict(status='waiting' if code in ('unsupported_layout', 'review_required', 'missing_evidence') else 'failed',
                      complete=False, phase=operation, rows=[], issues=[], error={'code': code, 'message': str(error) if isinstance(error, ConversionError) else '记录或输入不可用。'})
    if target and target.exists() and result.get('error', {}).get('code') != 'existing_output':
        write_json(target / 'manifest.json', result)
    return result
