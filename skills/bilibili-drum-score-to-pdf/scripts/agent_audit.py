"""Explicit native whole-score checks bound to the exact saved decision."""
import copy
import hashlib
import json
import re
from pathlib import Path
from agent_regions import box, contains, covered, invalid, native_rows
from video_seek import ConversionError

CHECKS = ('title', 'tempo', 'time_signature', 'outside_rows')
NAVIGATION_LIMIT = 'Navigation limit reached; review gaps and request local evidence.'


def require(condition, message='整曲审计字段或原生证据引用非法。'):
    if not condition:
        invalid(message)


def serialized(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def decision_hash(value):
    return hashlib.sha256(serialized(value)).hexdigest()


def wrap_continuous(structure, frames, review):
    if structure['schema_version'] != 3:
        return structure
    segment = dict(id='score-000', frames=[f['id'] for f in frames],
                   extras=[], outside_rows_verified=review.get('outside_rows_verified', False),
                   evidence=review.get('evidence', 'Explicit score audit required.'))
    segment.update({k: structure[k] for k in ('rows', 'observations', 'transitions')})
    return dict(schema_version=4, segments=[segment], boundaries=[], coverage=structure['coverage'])


def inspect(decision, packet, review):
    require(decision['schema_version'] == 4, '实验整曲审计只支持显式 v4 原生图块。')
    issues = []
    def pending(reason, **where):
        issues.append(dict(reason=reason, **where))
    frames = {f['id']: f for f in packet['frames']}
    images = {i['id']: i for i in packet['images']}
    presented = set(decision['presented_images'])
    sources = []
    def text(value):
        require(isinstance(value, str) and bool(value.strip()) and len(value) <= 2000)
    def regions(values, positive):
        require(isinstance(values, list) and len(values) <= 128)
        if positive and not values:
            pending('native_audit_evidence_required')
        for value in values:
            require(isinstance(value, dict) and set(value) == {'frame_id', 'bbox', 'evidence_images'})
            fid = value['frame_id']
            require(isinstance(fid, str) and fid in frames)
            frame = frames[fid]
            bbox = box(value['bbox'], frame)
            refs = value['evidence_images']
            require(isinstance(refs, list) and bool(refs) and all(isinstance(i, str) and i in images and i in presented for i in refs)
                    and len(set(refs)) == len(refs))
            details = [images[i] for i in refs]
            require(all(i.get('frame_id') == fid and i['kind'] in ('detail', 'native_detail')
                        and i['mapping']['coordinate_space'] == 'native_pixels' and i['mapping']['scale'] == [1,1]
                        and i['mapping']['source_offset'] == i['bbox'][:2] for i in details))
            if not covered(bbox, [i['bbox'] for i in details]):
                pending('native_audit_coverage_required', frame_id=fid)
            sources.append(dict(frame_id=fid, frame_sha256=frame['sha256'], source_sha256=packet['source']['sha256'],
                                pts=frame['pts'], time_base=frame['time_base'], timestamp=frame['timestamp'], bbox=bbox,
                                images=[dict(id=i['id'],sha256=i['sha256'],bbox=i['bbox'],mapping=i['mapping']) for i in details]))
        return values
    if review is None:
        pending('score_audit_required')
        review = dict(segments=[], intervals=[], unresolved=[])
    require(isinstance(review, dict) and {'segments','intervals','unresolved'} <= set(review)
            <= {'segments','intervals','unresolved','navigation_resolution'})
    require(isinstance(review['segments'], list) and isinstance(review['intervals'], list)
            and isinstance(review['unresolved'], list))
    segments = decision['segments']
    if not review['segments']:
        pending('segment_audit_required')
    else:
        require([s.get('id') for s in review['segments'] if isinstance(s,dict)] == [s['id'] for s in segments])
    for segment, audit in zip(segments, review['segments']):
        require(isinstance(audit, dict) and set(audit) == {'id', 'checks', 'first_edge', 'last_edge'})
        require(isinstance(audit['checks'], dict) and set(audit['checks']) == set(CHECKS))
        for name, check in audit['checks'].items():
            require(isinstance(check, dict) and set(check) == {'status', 'regions', 'print_regions', 'evidence'})
            require(check['status'] in ('checked', 'absent', 'pending'))
            text(check['evidence'])
            native = regions(check['regions'], check['status'] != 'pending')
            require(all(r['frame_id'] in segment['frames'] for r in native))
            targets = check['print_regions']
            require(isinstance(targets, list) and len(targets) <= 200)
            selected = []
            for target in targets:
                require(isinstance(target, dict) and set(target) == {'kind','index'}
                        and target['kind'] in ('row','extra') and type(target['index']) is int and target['index'] >= 0)
                collection = segment['rows'] if target['kind'] == 'row' else segment['extras']
                require(target['index'] < len(collection))
                chosen = collection[target['index']]
                if name == 'title' and check['status'] == 'checked':
                    require(target['kind'] == 'extra' and chosen['kind'] == 'title', '已核查标题必须来自实际打印的 title extra。')
                raw = chosen if target['kind'] == 'row' else chosen['region']
                candidate = ({k:v for k,v in raw.items() if k not in ('instance_id','observation_id')}
                             if target['kind'] == 'row' else raw)
                try:
                    selected.extend(native_rows({'rows':[candidate]}, packet, presented))
                except ConversionError as error:
                    if error.code not in ('review_required','missing_evidence'):
                        raise
                    pending(error.code, segment_id=segment['id'], field=name, message=str(error))
            if check['status'] == 'pending':
                pending('score_region_pending', segment_id=segment['id'], field=name)
            elif check['status'] == 'absent':
                require(not targets, '不存在的项目不能同时指定打印图块。')
            elif not selected or any(not any(p['frame_id'] == r['frame_id'] and contains(p['bbox'], r['bbox']) for p in selected) for r in native):
                pending('score_region_not_printed', segment_id=segment['id'], field=name)
        for key, fid in [('first_edge',segment['frames'][0]),('last_edge',segment['frames'][-1])]:
            edge = audit[key]
            require(isinstance(edge, dict) and set(edge) == {'complete','regions','evidence'} and type(edge['complete']) is bool)
            text(edge['evidence'])
            native = regions(edge['regions'], edge['complete'])
            require(all(r['frame_id'] == fid for r in native))
            if not edge['complete']:
                pending('incomplete_score_edge', segment_id=segment['id'], edge=key)
    pairs = list(zip(packet['frames'],packet['frames'][1:]))
    if not review['intervals'] and pairs:
        pending('interval_audit_required')
    else:
        require([(i.get('from_frame'),i.get('to_frame')) for i in review['intervals'] if isinstance(i,dict)] == [(a['id'],b['id']) for a,b in pairs])
    for interval, (a,b) in zip(review['intervals'],pairs):
        require(isinstance(interval, dict) and set(interval) == {'from_frame','to_frame','status','regions','evidence'}
                and interval['status'] in ('checked','pending'))
        text(interval['evidence'])
        native = regions(interval['regions'], interval['status'] == 'checked')
        require(all(r['frame_id'] in (a['id'],b['id']) for r in native))
        if interval['status'] != 'checked' or {r['frame_id'] for r in native} != {a['id'],b['id']}:
            pending('unresolved_sampling_interval', start=a['timestamp'],end=b['timestamp'])
    if review['unresolved']:
        pending('unresolved_score_risks', risks=copy.deepcopy(review['unresolved']))
    navigation = packet['sampling'].get('unresolved', [])
    resolution = review.get('navigation_resolution')
    resolved_navigation = False
    if resolution is not None:
        require(isinstance(resolution,dict) and set(resolution) == {'status','new_frames','intervals','evidence'}
                and resolution['status'] in ('pending','reviewed_after_supplement'))
        text(resolution['evidence'])
        requested = resolution['new_frames']
        require(isinstance(requested,list) and all(isinstance(f,str) and f in frames for f in requested) and len(set(requested)) == len(requested))
        require(isinstance(resolution['intervals'],list))
        if resolution['status'] == 'reviewed_after_supplement':
            # New PTS are established by the existing supplement publication, not by a boolean assertion.
            initial_pts = {(f['pts'],tuple(f['time_base'])) for f in packet['frames'] if f['id'].startswith('frame-')}
            supplemented = {f['id'] for f in packet['frames'] if re.fullmatch(r'v[0-9]+-frame-[0-9]+',f['id'])
                            and (f['pts'],tuple(f['time_base'])) not in initial_pts}
            expected_pairs = [[a['id'],b['id']] for a,b in pairs]
            proof_frames = {s['frame_id'] for s in sources}
            checked_pairs = all(i['status'] == 'checked' for i in review['intervals']) and len(review['intervals']) == len(pairs)
            resolved_navigation = (bool(navigation) and all(n == NAVIGATION_LIMIT for n in navigation)
                                   and bool(requested) and set(requested) <= supplemented and set(requested) <= proof_frames
                                   and resolution['intervals'] == expected_pairs and checked_pairs)
            if not resolved_navigation:
                pending('navigation_resolution_requires_supplement_and_bound_gap_review')
    if navigation and not resolved_navigation:
        pending('unresolved_navigation', risks=copy.deepcopy(navigation))
    def endpoint(frame):
        return {k: frame[k] for k in ('id','sha256','pts','time_base','timestamp')}
    coverage = dict(scope='explicit_review_of_observed_score', first=endpoint(packet['frames'][0]),
                    last=endpoint(packet['frames'][-1]), video_duration=packet['source']['duration'],
                    intervals=[dict(from_frame=a['id'],to_frame=b['id'],start=a['timestamp'],end=b['timestamp'],
                                    sample_gap=b['timestamp']-a['timestamp']) for a,b in pairs],
                    accepted_instances=[r['instance_id'] for s in segments for r in s['rows']],
                    segments=[dict(id=s['id'],frames=s['frames']) for s in segments], boundaries=decision['boundaries'],
                    unresolved=copy.deepcopy(issues), navigation_unresolved=copy.deepcopy(navigation),
                    navigation_resolution=copy.deepcopy(resolution), navigation_review_resolved=resolved_navigation,
                    hidden_content_proven_absent=False)
    return dict(review=copy.deepcopy(review), coverage=coverage, source_regions=sources), issues


def bind(value, state, audit):
    return dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                decision_sha256=decision_hash(value), **audit)


def check(record, value, state, packet):
    require(isinstance(record, dict) and set(record) == {'schema_version','task_id','observation_sha256','decision_sha256','review','coverage','source_regions'}
            and type(record['schema_version']) is int and record['schema_version'] == 1, '审计记录字段或版本非法。')
    require(record['task_id'] == state['task_id'] and record['observation_sha256'] == state['observation_sha256']
            and record['decision_sha256'] == decision_hash(value), '审计不属于当前任务、观察包或精确决定。')
    decision = value.get('decision',value)
    rebuilt, issues = inspect(decision, packet, record['review'])
    require(record == bind(value,state,rebuilt), '审计计算结果或来源记录已改变。')
    if issues:
        error = ConversionError('review_required', '整曲边界、标题或行外区域审计仍有未决事项。')
        error.issues = issues
        raise error
    return record


def load_for_submit(path, value, state, packet, load):
    from agent_workflow import digest
    target = Path(path).parent / 'audit.json'
    if not target.exists():
        raise ConversionError('review_required', '实验 lazy 缺少绑定当前决定的 audit.json，请通过 build-decision 完成原生核查。')
    record = load(target)
    require(record.get('decision_sha256') == digest(path), '审计须绑定构建决定文件的精确 hash，不能替换或重新序列化。')
    return check(record,value,state,packet)
