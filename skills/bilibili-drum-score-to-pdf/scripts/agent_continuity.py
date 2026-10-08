"""Check visual row correspondences against spatial geometry, never image hashes."""
import math
from agent_regions import box, native_rows, invalid
from video_seek import ConversionError


def waiting(message):
    raise ConversionError('review_required', message)


def text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2000


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def continuous_rows(decision, packet, presented):
    frames = {f['id']: f for f in packet['frames']}
    ordered = list(frames)
    sightings = decision['observations']
    if not isinstance(sightings, list) or not sightings or len(sightings) > 2000:
        invalid('缺少有界谱行观察。')
    by_id, by_frame = {}, {f: [] for f in frames}
    fields = {'id','frame_id','instance_id','staff_y','spacing','bbox','complete','evidence'}
    for s in sightings:
        if not isinstance(s, dict) or set(s) != fields or any(not text(s[k]) for k in ('id','instance_id','evidence')):
            invalid('身份观察字段非法。')
        if s['id'] in by_id or s['frame_id'] not in frames or type(s['complete']) is not bool:
            invalid('身份观察重复或帧引用非法。')
        box(s['bbox'], frames[s['frame_id']])
        if not number(s['staff_y']) or not number(s['spacing']) or s['spacing'] <= 0 or not s['bbox'][1] <= s['staff_y'] < s['bbox'][3]:
            invalid('五线锚点或间距非法。')
        by_id[s['id']] = s
        by_frame[s['frame_id']].append(s)
    for observations in by_frame.values():
        if not observations or len({s['instance_id'] for s in observations}) != len(observations):
            waiting('每帧必须有不重复的空间观察。')
        if any(a['staff_y'] >= b['staff_y'] or a['bbox'][3] > b['bbox'][1]
               for a, b in zip(observations, observations[1:])):
            waiting('帧内行顺序矛盾。')
    coverage = decision['coverage']
    if not isinstance(coverage, dict) or set(coverage) != {'first_frame','last_frame','unresolved'}:
        invalid('覆盖声明字段非法。')
    if coverage['first_frame'] != ordered[0] or coverage['last_frame'] != ordered[-1] or not isinstance(coverage['unresolved'], list) or coverage['unresolved']:
        waiting('缺少首尾或覆盖区间仍有疑点。')
    transitions = decision['transitions']
    if not isinstance(transitions, list) or len(transitions) != len(ordered)-1:
        waiting('相邻观察接续缺失。')
    offsets, relations = {ordered[0]: 0.0}, []
    for before, after, t in zip(ordered, ordered[1:], transitions):
        if not isinstance(t, dict) or set(t) != {'from_frame','to_frame','matches','evidence'} or not text(t['evidence']):
            invalid('接续字段或可观察依据非法。')
        if (t['from_frame'],t['to_frame']) != (before,after):
            waiting('接续顺序成环或非相邻。')
        matches = t['matches']
        if not isinstance(matches,list) or len(matches)<2:
            waiting('只有单条重叠或没有可靠接续，请补采。')
        pairs=[]
        for pair in matches:
            if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(i,str) or i not in by_id for i in pair):
                invalid('对应谱行引用非法。')
            a,b = (by_id[i] for i in pair)
            if a['frame_id']!=before or b['frame_id']!=after or a['instance_id']!=b['instance_id']:
                waiting('视觉对应与空间实例冲突。')
            if abs(a['spacing']/b['spacing']-1)>0.03 or abs((a['bbox'][2]-a['bbox'][0])/(b['bbox'][2]-b['bbox'][0])-1)>0.03 or abs(a['bbox'][0]-b['bbox'][0])>max(2,a['spacing']/2):
                waiting('比例或横向布局变化，不能套用连续长谱坐标。')
            pairs.append((a,b))
        if len({a['id'] for a,b in pairs})!=len(pairs) or len({b['id'] for a,b in pairs})!=len(pairs):
            waiting('一条观察被对应多次。')
        if [a['staff_y'] for a,b in pairs]!=sorted(a['staff_y'] for a,b in pairs) or [b['staff_y'] for a,b in pairs]!=sorted(b['staff_y'] for a,b in pairs):
            waiting('对应顺序相交。')
        deltas=[a['staff_y']-b['staff_y'] for a,b in pairs]
        tolerance=min(s['spacing'] for pair in pairs for s in pair)/2
        delta=sum(deltas)/len(deltas)
        if delta < -tolerance or any(abs(d-delta)>tolerance for d in deltas):
            waiting('共同位移冲突，置信度不能代替几何。')
        offsets[after]=offsets[before]+max(0,delta)
        common={s['instance_id'] for s in by_frame[before]} & {s['instance_id'] for s in by_frame[after]}
        if common!={a['instance_id'] for a,b in pairs}:
            waiting('共同空间实例缺少对应证据。')
        relations.append(dict(**t,scroll_delta=max(0,delta),scroll_offset=offsets[after],
                              start=frames[before]['timestamp'],end=frames[after]['timestamp'],
                              sample_gap=frames[after]['timestamp']-frames[before]['timestamp']))
    instances={}
    for frame_id in ordered:
        previous_max=max(instances.values(),default=-math.inf)
        for s in by_frame[frame_id]:
            y=s['staff_y']+offsets[frame_id]
            if s['instance_id'] in instances:
                if abs(y-instances[s['instance_id']])>s['spacing']/2:
                    waiting('同一空间实例的 global_y 矛盾。')
            else:
                if y<=previous_max:
                    waiting('新空间实例插入已接受行之前，可能漏行或重复。')
                instances[s['instance_id']]=y
                previous_max=y
    rows=decision['rows']
    if not isinstance(rows,list) or any(not isinstance(r,dict) or 'instance_id' not in r or 'observation_id' not in r for r in rows):
        invalid('所选谱行缺少空间实例与观察引用。')
    if [r['instance_id'] for r in rows]!=list(instances):
        waiting('空间实例漏行、重复或打印顺序非法。')
    native=[]
    for r in rows:
        s=by_id.get(r['observation_id'])
        if not s or s['instance_id']!=r['instance_id'] or s['frame_id']!=r.get('frame_id') or s['bbox']!=r.get('bbox'):
            waiting('所选原裁剪与身份观察不一致。')
        if not s['complete']:
            waiting('半行必须等到完整出现才能打印。')
        native.append({k:v for k,v in r.items() if k not in ('instance_id','observation_id')})
    chosen=native_rows({**decision,'rows':native},packet,presented)
    for c,r in zip(chosen,rows):
        c.update(instance_id=r['instance_id'],observation_id=r['observation_id'],global_y=instances[r['instance_id']],scroll_offset=offsets[r['frame_id']])
    audit=dict(first_frame=ordered[0],last_frame=ordered[-1],first_timestamp=frames[ordered[0]]['timestamp'],last_timestamp=frames[ordered[-1]]['timestamp'],
               transitions=relations,accepted_instances=list(instances),unresolved=[],hidden_content_proven_absent=False,
               scope='observed_continuous_score')
    return chosen,audit
