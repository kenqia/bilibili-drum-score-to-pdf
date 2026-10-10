"""Select content witnesses only after complete spatial geometry has passed."""
POLICY = 'ordered_anchors_v1'
REPLACEABLE = {'cursor_or_obstruction', 'unreliable_alignment'}


def select(task, decision, packet, checks, inspect_pair, native_review):
    frames = {f['id']: f for f in packet['frames']}
    from agent_regions import contains
    native_review = check_native_review(decision,packet,native_review)
    def reviewed(s, cursor):
        f=frames[s['frame_id']]
        window=[0,round(s['staff_y'])-round(4*s['spacing']),f['width'],round(s['staff_y'])+round(8*s['spacing'])]
        return any(r['frame_id']==s['frame_id'] and r['cursor']==cursor and r['occlusion']=='clear' and contains(r['bbox'],window) and contains(r['bbox'],s['bbox']) for r in native_review)
    def trusted(c,sightings):
        return c['status']=='not_contradicted' and c.get('bridge_eligible',True) and all(reviewed(sightings[i],'clear') for i in c['matches'])
    intervals = []
    parts = decision['segments'] if decision['schema_version'] == 4 else [decision]
    for part in parts:
        ids = part.get('frames', list(frames))
        index = {fid: i for i, fid in enumerate(ids)}
        sightings = {s['id']: s for s in part['observations']}
        observed = {fid: {s['instance_id']: s for s in sightings.values() if s['frame_id'] == fid} for fid in ids}
        offsets = {ids[0]: 0.0}
        for t in part['transitions']:
            delta = sum(sightings[a]['staff_y'] - sightings[b]['staff_y'] for a, b in t['matches']) / len(t['matches'])
            offsets[t['to_frame']] = offsets[t['from_frame']] + max(0, delta)
        local = [c for c in checks if c.get('segment_id') == part.get('id')]
        # Check every geometry-established candidate, not just the selected anchors.
        # Bridges cannot cross a frame where the instance disappears or is incomplete.
        bridges = []
        gaps = []
        for t in part['transitions']:
            a, b = t['from_frame'], t['to_frame']
            good = [c for c in local if c['from_frame'] == a and c['to_frame'] == b and trusted(c, sightings)]
            if len(good) < 2:
                gaps.append((a, b))
        candidates = []
        for left in range(len(ids)):
            for right in range(left + 2, len(ids)):
                if not any(left <= index[a] < index[b] <= right for a, b in gaps):
                    continue
                for instance, first in observed[ids[left]].items():
                    span = [observed[fid].get(instance) for fid in ids[left:right + 1]]
                    last=span[-1]
                    if last is None:
                        continue
                    present=[s for s in span if s is not None]
                    geometry_bad = (any(abs((s['staff_y'] + offsets[s['frame_id']]) - (first['staff_y'] + offsets[first['frame_id']])) > min(s['spacing'], first['spacing']) / 2 for s in present)
                            or abs(first['spacing'] / last['spacing'] - 1) > .03
                            or abs((first['bbox'][2] - first['bbox'][0]) / (last['bbox'][2] - last['bbox'][0]) - 1) > .03
                            or abs(first['bbox'][0] - last['bbox'][0]) > max(2, first['spacing'] / 2))
                    candidates.append((right-left, left, right, first['staff_y'], first, last,not geometry_bad))
        endpoint_pairs=sorted({(distance,left,right) for distance,left,right,_,first,last,eligible in candidates})
        for _,left,right in endpoint_pairs:
            if not any(left <= index[a] < index[b] <= right for a,b in gaps):
                continue
            batch=[(first,last,eligible) for _,l,r,_,first,last,eligible in candidates if (l,r)==(left,right)]
            if len(bridges)+len(batch)>256:
                break
            # All common spatial pairs for this bridge are inspected before choosing anchors.
            for first,last,eligible in batch:
                result=inspect_pair(first,last,bridge=True)
                if 'id' in part:
                    result['segment_id']=part['id']
                result['covered_frames']=ids[left:right+1]
                result['bridge_eligible']=eligible and all(observed[fid].get(first['instance_id']) is not None and observed[fid][first['instance_id']]['complete'] for fid in ids[left:right+1])
                bridges.append(result)
            for a,b in list(gaps):
                edges={}
                for c in local+bridges:
                    if trusted(c,sightings) and index[c['from_frame']] <= index[a] < index[b] <= index[c['to_frame']]:
                        edges.setdefault((c['from_frame'],c['to_frame']),set()).add(sightings[c['matches'][0]]['instance_id'])
                if any(len(instances)>=2 for instances in edges.values()):
                    gaps.remove((a,b))
        all_checks = local + bridges
        for t in part['transitions']:
            a,b = t['from_frame'], t['to_frame']
            witnesses = [c for c in all_checks if trusted(c, sightings)
                         and index[c['from_frame']] <= index[a] < index[b] <= index[c['to_frame']]]
            edges={}
            for c in witnesses:
                edges.setdefault((c['from_frame'],c['to_frame']),{}).setdefault(sightings[c['matches'][0]]['instance_id'],c)
            sufficient_edges=[(edge,list(values.values())) for edge,values in edges.items() if len(values)>=2]
            sufficient_edges.sort(key=lambda item:(index[item[0][1]]-index[item[0][0]],index[item[0][0]]))
            chosen=sorted(sufficient_edges[0][1],key=lambda c:sightings[c['matches'][0]]['staff_y'])[:2] if sufficient_edges else []
            sufficient = len(chosen) == 2
            intervals.append(dict(from_frame=a,to_frame=b,sufficient=sufficient,
                affected_instances=[sightings[pair[0]]['instance_id'] for pair in t['matches']],
                witnesses=[dict(matches=c['matches'],from_frame=c['from_frame'],to_frame=c['to_frame']) for c in chosen],
                next_action=None if sufficient else 'Supplement this interval and review its native endpoints; two ordered trustworthy witnesses are missing.'))
            if not sufficient:
                checks.append(dict(status='uncertain',reason='missing_native_content_witnesses',blocking=True,
                    from_frame=a,to_frame=b,matches=[],analyzed_pixels=0,evidence_chain=intervals[-1],scope='required_interval',identity_established_by_content=False))
            for c in local:
                if (c['from_frame'],c['to_frame']) == (a,b):
                    actual_review = all(reviewed(sightings[i], 'present' if c['reason']=='cursor_or_obstruction' and not reviewed(sightings[i],'clear') else 'clear') for i in c['matches'])
                    c['blocking'] = c['status'] == 'conflict' or (c['status'] == 'uncertain' and (not sufficient or c['reason'] not in REPLACEABLE or not actual_review))
                    c['evidence_chain'] = intervals[-1]
        checks.extend(bridges)
        for c in bridges:
            c['blocking'] = c['status'] == 'conflict'
    return intervals


def enabled(state, packet):
    from agent_regions import invalid
    if packet.get('minimum_evidence_chain_policy') is None and state.get('minimum_evidence_chain_policy') is None:
        return False
    if packet.get('minimum_evidence_chain_policy') != POLICY or state.get('minimum_evidence_chain_policy') != POLICY or packet.get('evidence_mode') != 'lazy':
        invalid('最小证据链必须在新 lazy 任务固定。')
    return True


def bind(value,state,packet,clean):
    import copy
    from agent_audit import decision_hash
    return dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
        observation_version=state['observation_version'],source_sha256=packet['source']['sha256'],
        decision_sha256=decision_hash(value),policy=POLICY,native_clean_regions=copy.deepcopy(clean))


def check(record,value,state,packet):
    from agent_regions import invalid
    if not isinstance(record,dict) or set(record)!=set(bind(value,state,packet,[])) or type(record['schema_version']) is not int or type(record['observation_version']) is not int:
        invalid('连续证据旁记录字段非法。')
    if record != bind(value,state,packet,record['native_clean_regions']):
        invalid('连续证据旁记录不属于当前决定或观察。')
    return check_native_review(value.get('decision',value),packet,record['native_clean_regions'])


def load_for_submit(path,value,state,packet,load):
    from pathlib import Path
    from agent_workflow import digest
    from agent_regions import invalid
    from video_seek import ConversionError
    target=Path(path).parent/'continuity.json'
    if not target.is_file() or target.is_symlink():
        raise ConversionError('review_required','最小证据链缺少 continuity.json。')
    record=load(target)
    if record.get('decision_sha256')!=digest(path):
        invalid('连续证据必须绑定精确决定文件。')
    return record,check(record,value,state,packet)


def check_native_review(decision,packet,records):
    from agent_acceptance import clean_review
    from agent_regions import invalid
    if not isinstance(records,list) or len(records)>2000:
        invalid('连续证据原生核查清单超过观察范围。')
    for start in range(0,len(records),128):
        clean_review(decision,packet,records[start:start+128])
    return records
