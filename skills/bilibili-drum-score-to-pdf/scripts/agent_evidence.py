"""Materialize single-frame native regions without rebuilding ordinary review."""
import copy
import hashlib
import json
import os
from PIL import Image
from agent_performance import ACTIVE, stage
from agent_regions import box
from video_seek import ConversionError

MAX_REGIONS = 128


def invalid(message):
    raise ConversionError('invalid_request', message)


def materialize(task, path):
    # Imported at the public operation boundary to keep workflow wiring small.
    from agent_workflow import checked_task, load_json, write_json, digest, recover_publication, image_pixels, MAX_JSON
    with stage('source_verification'):
        state, observation = checked_task(task)
    request = load_json(path)
    fields = {'schema_version', 'task_id', 'observation_sha256', 'observation_version',
              'source_sha256', 'request_id', 'reason', 'regions'}
    if not isinstance(request, dict) or set(request) != fields or type(request['schema_version']) is not int or request['schema_version'] != 1:
        invalid('原生证据请求字段或版本非法。')
    if any(not isinstance(request[k], str) or not request[k].strip() or len(request[k]) > 2000 for k in ('request_id', 'reason')):
        invalid('请求须有 ID 与明确疑点原因。')
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    updates = observation.get('evidence_updates', [])
    for update in updates:
        if update['request_id'] == request['request_id']:
            if update['request_sha256'] != fingerprint:
                invalid('相同请求 ID 的内容不同。')
            return state | dict(materialized_images=update['image_ids'], metrics={'generated_images': 0, 'cache_hits': len(update['image_ids'])})
    if (request['task_id'] != state['task_id'] or request['observation_sha256'] != state['observation_sha256']
            or type(request['observation_version']) is not int or request['observation_version'] != state['observation_version']
            or request['source_sha256'] != observation['source']['sha256']):
        invalid('请求不属于当前任务、来源或观察版本。')
    regions = request['regions']
    if not isinstance(regions, list) or not regions or len(regions) > MAX_REGIONS:
        invalid('请求须包含 1 至 128 个原生矩形。')
    frames = {f['id']: f for f in observation['frames']}
    version = state['observation_version']
    destinations = [f'observation-v{version}.json', f'evidence-request-{version+1}.json',
                    'observation.next.json', 'sampling.next.json', 'task.next.json', 'publication.json']
    for filename in destinations:
        if (task / filename).is_symlink() or (task / (filename + '.tmp')).is_symlink():
            raise ConversionError('source_mismatch', '证据更新路径不能是符号链接。')
    resolved = []
    for region in regions:
        if not isinstance(region, dict) or set(region) != {'frame_id', 'frame_sha256', 'pts', 'time_base', 'bbox'} or not isinstance(region['frame_id'], str) or region['frame_id'] not in frames:
            invalid('请求原帧引用或字段非法。')
        frame = frames[region['frame_id']]
        if (region['frame_sha256'] != frame['sha256'] or type(region['pts']) is not int
                or region['pts'] != frame['pts'] or region['time_base'] != frame['time_base']):
            invalid('请求原帧 hash、实际 PTS 或 time_base 不匹配。')
        try:
            box(region['bbox'], frame)
        except ConversionError:
            invalid('原生矩形越界、为空或不是整数坐标。')
        resolved.append((frame, region['bbox']))
    new = copy.deepcopy(observation)
    ids, generated = [], 0
    costs = dict(generated_images=0, cache_hits=0, generated_evidence=[])
    recorder = ACTIVE.get()

    def save_cost():
        if recorder:
            recorder.operation['metrics'] = copy.deepcopy(costs)
            recorder.save()

    save_cost()
    with stage('image_generation'):
        for frame, bbox in resolved:
            cached = next((i for i in new['images'] if i.get('frame_id') == frame['id']
                           and i['kind'] in ('native_detail', 'detail') and i['bbox'] == bbox), None)
            if cached:
                ids.append(cached['id'])
                costs['cache_hits'] += 1
                save_cost()
                continue
            key = hashlib.sha256(json.dumps([observation['source']['sha256'], frame['sha256'], frame['pts'], frame['time_base'], bbox]).encode()).hexdigest()
            image_id = f'roi-{key}'
            filename = f'{image_id}.png'
            with Image.open(task / frame['path']) as original:
                if original.size != (frame['width'], frame['height']):
                    raise ConversionError('source_mismatch', '保存原帧尺寸不匹配。')
                crop = original.convert('RGB').crop(bbox)
                destination = task / filename
                if destination.is_symlink():
                    raise ConversionError('source_mismatch', '原生证据路径非法。')
                if destination.exists():
                    with Image.open(destination) as existing:
                        if existing.mode != crop.mode or existing.size != crop.size or existing.tobytes() != crop.tobytes():
                            raise ConversionError('source_mismatch', '未发布原生证据已改变。')
                    costs['cache_hits'] += 1
                else:
                    temporary = destination.with_suffix('.next.png')
                    if temporary.is_symlink():
                        raise ConversionError('source_mismatch', '原生证据暂存路径非法。')
                    crop.save(temporary)
                    os.replace(temporary, destination)
                    generated += 1
                    costs['generated_images'] += 1
            evidence = dict(id=image_id, path=filename, sha256=digest(destination),
                frame_id=frame['id'], frame_sha256=frame['sha256'], source_sha256=observation['source']['sha256'],
                pts=frame['pts'], time_base=frame['time_base'], timestamp=frame['timestamp'],
                kind='native_detail', bbox=bbox, mapping=dict(coordinate_space='native_pixels', scale=[1, 1], source_offset=bbox[:2]))
            if len(costs['generated_evidence']) < costs['generated_images']:
                costs['generated_evidence'].append(evidence)
            save_cost()
            new['images'].append(evidence)
            ids.append(image_id)
    new['observation_version'] = version + 1
    new.setdefault('evidence_updates', []).append(dict(request_id=request['request_id'], request_sha256=fingerprint,
        request=request, from_observation_sha256=state['observation_sha256'], observation_version=version+1,
        image_ids=ids, generated_images=generated))
    new['metrics']['detail_images'] = sum(i['kind'] in ('native_detail', 'detail') for i in new['images'])
    new['metrics']['image_pixels'] = image_pixels(task, new['images'])
    if len(json.dumps(new, ensure_ascii=False, indent=2, allow_nan=False).encode()) > MAX_JSON - 4096:
        raise ConversionError('sampling_budget', '证据更新达到观察 JSON 上限，保留已生成图像。')
    archive = task / f'observation-v{version}.json'
    if archive.exists() and digest(archive) != state['observation_sha256']:
        raise ConversionError('source_mismatch', '观察历史版本已改变。')
    if not archive.exists():
        archive.write_bytes((task / 'observation.json').read_bytes())
    write_json(task / f'evidence-request-{version+1}.json', request)
    write_json(task / 'observation.next.json', new)
    # Preserve the charged supplement budget, including earlier failed requests.
    sampling = load_json(task / 'sampling.json')
    write_json(task / 'sampling.next.json', sampling)
    updated = copy.deepcopy(state)
    updated.update(observation_sha256=digest(task / 'observation.next.json'), observation_version=version+1,
                   sampling_sha256=digest(task / 'sampling.next.json'), complete=False, phase='review', status='waiting',
                   issues=[], metrics=new['metrics'], next_action='Review requested evidence; retain unchanged accepted judgments and explicitly revise the latest decision binding.')
    write_json(task / 'task.next.json', updated)
    write_json(task / 'publication.json', dict(observation_sha256=updated['observation_sha256'],
        state_sha256=digest(task / 'task.next.json'), sampling_sha256=updated['sampling_sha256']))
    recover_publication(task)
    return updated | dict(materialized_images=ids, metrics=costs)
