"""Opt-in mixed authority, recomputed from native sources at every execution boundary.

Pixel checks preserve visible row ink; they do not prove arbitrary occlusions absent.
Clean authority therefore remains an actual Agent native-ROI judgment.
"""
import copy
from pathlib import Path
import numpy as np
from PIL import Image
from agent_regions import box, covered, contains, invalid
from agent_performance import ACTIVE, stage
from video_seek import ConversionError

POLICY = 'continuous_clean_v1'


def enabled(state, packet):
    value = packet.get('script_acceptance_policy')
    if value is None and state.get('script_acceptance_policy') is None:
        return False
    if value != POLICY or state.get('script_acceptance_policy') != POLICY or packet.get('evidence_mode') != 'lazy':
        invalid('脚本接受策略必须在新 lazy 任务建立时固定。')
    return True


def region(frame, bbox):
    return dict(frame_id=frame['id'], bbox=list(bbox), frame_sha256=frame['sha256'],
                pts=frame['pts'], time_base=frame['time_base'])


def clean_review(decision, packet, records):
    if not isinstance(records, list) or len(records) > 128:
        invalid('原生干净区域核查清单非法。')
    frames = {f['id']: f for f in packet['frames']}
    images = {i['id']: i for i in packet['images']}
    for record in records:
        if not isinstance(record, dict) or set(record) != {'frame_id','frame_sha256','pts','time_base','bbox','evidence_images','cursor','occlusion','evidence'}:
            invalid('原生干净核查字段非法。')
        frame = frames.get(record['frame_id'])
        if frame is None:
            invalid('原生干净核查帧非法。')
        if type(record['pts']) is not int or not isinstance(record['time_base'],list) or len(record['time_base'])!=2 or any(type(v) is not int for v in record['time_base']):
            invalid('Agent 原生来源时间必须使用整数 PTS/time_base。')
        if any(record[k] != frame[v] for k,v in [('frame_sha256','sha256'),('pts','pts'),('time_base','time_base')]):
            invalid('Agent 原生干净核查不属于当前 PTS 或原帧。')
        box(record['bbox'], frame)
        refs = record['evidence_images']
        if not isinstance(refs,list) or not refs or len(set(refs)) != len(refs) or any(not isinstance(i,str) or i not in images or i not in decision['presented_images'] for i in refs):
            invalid('Agent 干净核查必须实际呈交原生细节。')
        details = [images[i] for i in refs]
        if any(i.get('frame_id') != frame['id'] or i['kind'] not in ('detail','native_detail') or i['mapping']['coordinate_space']!='native_pixels' or i['mapping']['scale']!=[1,1] or i['mapping']['source_offset']!=i['bbox'][:2] for i in details) or not covered(record['bbox'], [i['bbox'] for i in details]):
            invalid('Agent 干净核查必须覆盖同帧完整原生区域。')
        if record['cursor'] not in ('clear','present','uncertain') or record['occlusion'] not in ('clear','present','uncertain') or not isinstance(record['evidence'],str) or not record['evidence'].strip() or len(record['evidence']) > 2000:
            invalid('Agent 干净核查判断非法。')
    return records


def native_check(frame, image, actual, sighting, clean):
    """Inspect a detector-derived full-width ownership band, never just the crop."""
    from cursor_detect import cursor_occluded, obstruction_detected
    checks = dict(source_integrity='pass', native_bounds='pass', staff_geometry='uncertain',
                  full_row_edges='uncertain', clean_candidate='uncertain')
    if actual is None:
        return checks, []
    roi = actual['bbox']; groups = actual['groups']
    matches = [(i,g) for i,g in enumerate(groups) if abs(roi[1]+g['top']-sighting['staff_y']) <= .75
               and abs(g['spacing']-sighting['spacing']) <= .1]
    if len(matches) != 1:
        return checks, []
    index, group = matches[0]
    checks['staff_geometry'] = 'pass'
    if index == 0 or index == len(groups)-1:
        return checks, [region(frame,roi)]
    upper = round(roi[1]+(groups[index-1]['bottom']+group['top'])/2)
    lower = round(roi[1]+(group['bottom']+groups[index+1]['top'])/2)
    band = [roi[0], upper, roi[2], lower]
    source_regions = [region(frame,band)]
    raster = np.asarray(image.crop(band))
    gray = np.asarray(image.crop(band).convert('L'))
    # Exact white raster cuts preserve even a single disconnected nonwhite pixel.
    occupied = np.any(raster < 255, axis=2)
    if occupied[:4].any() or occupied[-4:].any():
        return checks, source_regions
    ys,xs = np.nonzero(occupied)
    if not len(xs):
        return checks, source_regions
    ink = [band[0]+int(xs.min()),band[1]+int(ys.min()),band[0]+int(xs.max())+1,band[1]+int(ys.max())+1]
    if not contains(sighting['bbox'], ink):
        return checks, source_regions
    checks['full_row_edges'] = 'pass'
    color = raster.max(axis=2).astype(int)-raster.min(axis=2).astype(int)
    supported = not (color > 24).any() and float((gray > 235).mean()) >= .85
    native = image.crop(sighting['bbox'])
    blocked = cursor_occluded(native,group['spacing']) or obstruction_detected(native,sighting['staff_y']-sighting['bbox'][1],group['spacing'])
    agent_clean = any(r['frame_id'] == frame['id'] and r['cursor'] == 'clear' and r['occlusion'] == 'clear'
                      and contains(r['bbox'],band) and contains(r['bbox'],sighting['bbox']) for r in clean)
    if supported and not blocked and agent_clean:
        checks['clean_candidate'] = 'pass'
    return checks, source_regions


def compute(task, state, packet, decision, paths, clean):
    """Return authority only for explicitly requested, independently passing items."""
    if not enabled(state, packet):
        invalid('任务未启用脚本接受，不能迁移既有任务。')
    if decision['schema_version'] != 4 or len(decision['segments']) != 1 or decision['boundaries']:
        raise ConversionError('review_required','脚本接受首版只支持一个连续谱面段。')
    if not isinstance(paths,list) or len(paths)>4000 or any(not isinstance(p,list) or not p or any(type(k) not in (int,str) for k in p) for p in paths) or len({tuple(p) for p in paths}) != len(paths):
        invalid('脚本接受项路径非法或重复。')
    clean = clean_review(decision,packet,clean)
    segment = decision['segments'][0]
    from agent_proposals import suggest
    from score_detect import analyze_frame, staff_groups
    native = {}; rawpacket = {**packet,'frames':[],'candidates':[]}
    all_groups_accounted = True
    raw = {}
    with stage('script_acceptance'):
        for frame in packet['frames']:
            with Image.open(Path(task)/frame['path']) as original:
                image=original.convert('RGB')
            recorder=ACTIVE.get()
            if recorder is not None:
                count=recorder.operation.setdefault('metrics',{}).setdefault('script_acceptance',dict(native_reads=0,read_pixels=0,items_checked=0))
                count['native_reads']+=1;count['read_pixels']+=image.width*image.height
                recorder.save()
            try:
                with stage('native_analysis'):
                    actual=analyze_frame(image)
                with stage('native_staff_recheck'):
                    groups=staff_groups(image.crop(actual['bbox']))
                if groups != actual['groups']:
                    all_groups_accounted=False
            except ConversionError:
                actual=None;groups=[];all_groups_accounted=False
            native[frame['id']] = (image,actual)
            proposed={**frame,'analysis':actual or dict(groups=[],bbox=[0,0,image.width,image.height])}
            rawpacket['frames'].append(proposed)
            sightings=[x for x in segment['observations'] if x['frame_id']==frame['id']]
            if len(sightings)!=len(groups) or any(abs(x['staff_y']-(actual['bbox'][1]+g['top']))>.75 or abs(x['spacing']-g['spacing'])>.1 for x,g in zip(sightings,groups)):
                all_groups_accounted=False
            for number,g in enumerate(groups):
                top=round(actual['bbox'][1]+g['top'])
                rawpacket['candidates'].append(dict(id=f'native-{frame["id"]}-{number}',frame_id=frame['id'],index=number,
                    bbox=[actual['bbox'][0],max(0,top-round(g['spacing']*4)),actual['bbox'][2],min(frame['height'],top+round(g['spacing']*9))]))
        geometry=suggest(rawpacket)
        unique=len(packet['frames'])>=2 and all_groups_accounted and len(geometry['geometry'])==len(packet['frames'])-1 and all(len(t['plausible_translations'])==1 for t in geometry['geometry'])
        for sighting in segment['observations']:
            frame=next(f for f in packet['frames'] if f['id']==sighting['frame_id'])
            image,actual=native[frame['id']]
            raw[sighting['id']]=native_check(frame,image,actual,sighting,clean)
            if recorder is not None:
                count['items_checked']+=1
                recorder.save()
    context, items = {}, []
    for path in paths:
        node=decision
        for key in path:
            if not ((isinstance(node,dict) and isinstance(key,str) and key in node) or
                    (isinstance(node,list) and type(key) is int and 0<=key<len(node))):
                invalid('脚本接受路径未指向当前决定。')
            node=node[key]
        if len(path) != 4 or path[:2] != ['segments',0] or path[2] not in ('rows','observations','transitions'):
            invalid('脚本接受路径类型不受支持。')
        kind=path[2]
        checks = dict(single_displacement='pass' if unique else 'uncertain')
        sources=[]
        if kind in ('rows','observations'):
            sid=node.get('observation_id') if kind == 'rows' else node['id']
            if sid not in raw:
                invalid('脚本接受观察引用非法。')
            local, sources=raw[sid]
            checks.update(local)
            if kind == 'rows':
                sighting=next(s for s in segment['observations'] if s['id']==sid)
                executed=node.get('refinement',{}).get('bbox',node['bbox'])
                band=sources[0]['bbox'] if sources else []
                if node['bbox'] != sighting['bbox'] or not contains(executed,sighting['bbox']) or not band or not contains(band,executed):
                    checks['full_row_edges']='uncertain'
                if not any(r['frame_id']==node['frame_id'] and contains(r['bbox'],executed) and r['cursor']=='clear' and r['occlusion']=='clear' for r in clean):
                    checks['clean_candidate']='uncertain'
        else:
            expected=next((g for g in geometry['geometry'] if (g['from_frame'],g['to_frame']) == (node['from_frame'],node['to_frame'])),None)
            # Geometry IDs derive from detector candidates; compare anchor pairs rather than caller IDs.
            sightings={s['id']:s for s in segment['observations']}
            pairs=[]
            for pair in node['matches']:
                if len(pair)!=2 or any(s not in sightings for s in pair):
                    invalid('脚本接续引用非法。')
                a,b=(sightings[s] for s in pair)
                pairs.append((a,b))
                for s in (a,b):
                    local,regions=raw[s['id']];sources.extend(regions)
                    # Boundary/clean on outer rows remains Agent. Native five-line recomputation is mandatory.
                    if local['staff_geometry'] != 'pass':
                        checks['staff_geometry']='uncertain'
            actual_pairs=[[s['staff_y'] for s in pair] for pair in pairs]
            proposed={s['id']:s for s in geometry['structure']['observations']}
            expected_pairs=[[proposed[i]['staff_y'] for i in pair] for pair in expected['matches']] if expected else []
            checks['ordered_overlap']='pass' if len(pairs)>=2 and len(actual_pairs)==len(expected_pairs) and all(abs(a-b)<=.75 for pair_a,pair_b in zip(actual_pairs,expected_pairs) for a,b in zip(pair_a,pair_b)) else 'uncertain'
            checks.setdefault('staff_geometry','pass')
            checks['clean_candidate']='pass' if pairs else 'uncertain'
            for pair in pairs:
                for s in pair:
                    frame=next(f for f in packet['frames'] if f['id']==s['frame_id'])
                    _,regions=raw[s['id']]
                    required=[r['bbox'] for r in regions]+[s['bbox'],
                        [0,round(s['staff_y'])-round(4*s['spacing']),frame['width'],round(s['staff_y'])+round(8*s['spacing'])]]
                    required += [r.get('refinement',{}).get('bbox',r['bbox']) for r in segment['rows']
                                 if r['observation_id']==s['id']]
                    if not regions or not any(r['frame_id']==s['frame_id'] and r['cursor']=='clear'
                            and r['occlusion']=='clear' and all(contains(r['bbox'],bbox) for bbox in required)
                            for r in clean):
                        checks['clean_candidate']='uncertain'
        passed=all(v=='pass' for v in checks.values())
        item=dict(path=path,authority='script',kind=kind,source_regions=sources,checks=checks,
                  evidence='Recomputed native ink ownership and geometry; clean scope requires actual Agent native-ROI review.',
                  unresolved=[] if passed else [k for k,v in checks.items() if v!='pass'])
        items.append(item)
        if passed:
            context[tuple(path)] = item
    from agent_content import check_pairs
    provisional=copy.deepcopy(decision)
    fill(provisional,context)
    try:
        check_pairs(task,provisional,packet)
        content_status='pass'
    except ConversionError:
        content_status='uncertain'
    for item in items:
        item['checks']['content_not_contradicted']=content_status
        if content_status!='pass':
            item['unresolved'].append('content_not_contradicted')
            context.pop(tuple(item['path']),None)
    return context, items


def fill(decision, context):
    for path,item in context.items():
        node=decision
        for k in path:
            node=node[k]
        if item['kind']=='rows':
            node.update(complete=True,boundary_verified=True,cursor='clear',occlusion='clear',evidence_images=[],evidence=item['evidence'])
        elif item['kind']=='observations':
            node.update(complete=True,evidence=item['evidence'])
        else:
            node['evidence']=item['evidence']


def bind(value, state, packet, items, clean):
    from agent_audit import decision_hash
    return dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                observation_version=state['observation_version'],source_sha256=packet['source']['sha256'],
                decision_sha256=decision_hash(value),policy=POLICY,items=items,native_clean_regions=copy.deepcopy(clean))


def check(record, value, state, packet, task):
    if not isinstance(record,dict) or set(record)!={'schema_version','task_id','observation_sha256','observation_version','source_sha256','decision_sha256','policy','items','native_clean_regions'} or type(record['schema_version']) is not int or record['schema_version']!=1 or record['policy']!=POLICY or type(record['observation_version']) is not int:
        invalid('脚本接受旁记录字段或版本非法。')
    decision=value.get('decision',value)
    if not isinstance(record['items'],list) or any(not isinstance(i,dict) or 'path' not in i for i in record['items']):
        invalid('脚本接受项清单非法。')
    context,items=compute(task,state,packet,decision,[i['path'] for i in record['items']],record['native_clean_regions'])
    if record != bind(value,state,packet,items,record['native_clean_regions']):
        invalid('脚本接受绑定、来源或重算结果已改变。')
    if len(context)!=len(items) or not items:
        raise ConversionError('review_required','脚本接受依据仍有未决事项。')
    if decision['visual_review'] is not False:
        invalid('混合脚本接受不能声称全局已视觉审阅。')
    return context


def load_for_submit(path,value,state,packet,task,load):
    from agent_workflow import digest
    target=Path(path).parent/'acceptance.json'
    if not target.exists():
        raise ConversionError('review_required','混合决定缺少 acceptance.json。')
    record=load(target)
    if record.get('decision_sha256')!=digest(path):
        invalid('脚本接受须绑定决定文件的精确 hash。')
    return record,check(record,value,state,packet,task)
