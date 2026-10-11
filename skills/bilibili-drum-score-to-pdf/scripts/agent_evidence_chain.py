"""Select content witnesses only after complete spatial geometry has passed."""
POLICY = 'ordered_anchors_v1'
REPLACEABLE = {'cursor_or_obstruction'}


def select(task, decision, packet, checks, inspect_pair, native_review):
    frames = {f['id']: f for f in packet['frames']}
    recovery = packet.get('evidence_recovery_policy') == 'clean_sources_v1'
    from agent_regions import contains
    native_review = check_native_review(decision,packet,native_review)
    native_cache = {}
    def relevant(s):
        key=(s['frame_id'],s['id'])
        if key not in native_cache:
            f=frames[s['frame_id']]
            window=[0,round(s['staff_y'])-round(4*s['spacing']),f['width'],round(s['staff_y'])+round(8*s['spacing'])]
            def overlaps(a,b):
                return max(a[0],b[0]) < min(a[2],b[2]) and max(a[1],b[1]) < min(a[3],b[3])
            native_cache[key]=[r for r in native_review if r['frame_id']==s['frame_id']
                and (overlaps(r['bbox'],window) or overlaps(r['bbox'],s['bbox']))]
        return native_cache[key]
    def native_blockers(c,sightings):
        return [dict(sighting_id=s['id'],instance_id=s['instance_id'],frame_id=s['frame_id'],
                     bbox=r['bbox'],reason=f'native_{field}_{r[field]}')
                for i in c['matches'] for s in [sightings[i]] for r in relevant(s)
                for field in ('cursor','occlusion')
                if r[field]=='uncertain' or (field=='occlusion' and r[field]=='present')]
    def reviewed(s, cursor):
        f=frames[s['frame_id']]
        window=[0,round(s['staff_y'])-round(4*s['spacing']),f['width'],round(s['staff_y'])+round(8*s['spacing'])]
        records=relevant(s)
        if any(r['occlusion']!='clear' or r['cursor']=='uncertain' or (cursor=='clear' and r['cursor']=='present') for r in records):
            return False
        return any(r['cursor']==cursor and r['occlusion']=='clear' and contains(r['bbox'],window) and contains(r['bbox'],s['bbox']) for r in records)
    def trusted(c,sightings):
        return c['status']=='not_contradicted' and c.get('bridge_eligible',True) and all(reviewed(sightings[i],'clear') for i in c['matches'])
    def require_cursor_alternative(c,sightings,sufficient):
        for i in c['matches']:
            s=sightings[i]
            present=[r for r in relevant(s) if r['cursor']=='present']
            if present and (not sufficient or not reviewed(s,'present')):
                c['native_blockers'].extend(dict(sighting_id=s['id'],instance_id=s['instance_id'],
                    frame_id=s['frame_id'],bbox=r['bbox'],reason='native_cursor_requires_alternative') for r in present)
    def blocking(c,sightings,sufficient,clean_instances=None):
        if recovery:
            instances = {sightings[i]['instance_id'] for i in c['matches']}
            corroborated = bool(instances) and instances <= (clean_instances or set())
            # Unknown declarations, contradictory content and real alignment
            # failures never become diagnostics. A complete actually
            # reviewed clean exposure of this same spatial instance is required.
            unknown = any(b['reason'].endswith('_uncertain') for b in c['native_blockers'])
            replaceable = c['reason'] in REPLACEABLE | {'partial_or_missing_margin'} and all(
                r is None or r in REPLACEABLE | {'partial_or_missing_margin'} for r in c['endpoint_reasons'])
            blocked = unknown or c['status'] == 'conflict' or (
                c['status'] == 'uncertain' and not (replaceable and sufficient and corroborated))
            if c['native_blockers'] and not (sufficient and corroborated) or any(
                    r['cursor']=='present' for i in c['matches'] for r in relevant(sightings[i])) and not (sufficient and corroborated):
                blocked = True
            c['replacement_evidence'] = dict(interval_sufficient=sufficient, same_instance_clean_source=corroborated,
                original_result_retained=True, policy='clean_sources_v1')
            return bool(blocked)
        reasons=c['endpoint_reasons']
        replaceable=c['reason'] in REPLACEABLE and all(reason is None or reason in REPLACEABLE for reason in reasons)
        actual_review=all(reviewed(sightings[i],'present' if reason=='cursor_or_obstruction' else 'clear') for i,reason in zip(c['matches'],reasons))
        require_cursor_alternative(c,sightings,sufficient)
        return bool(c['native_blockers']) or c['status']=='conflict' or (c['status']=='uncertain' and (not sufficient or not replaceable or not actual_review))
    intervals = []
    bridge_attempts = 0
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
        for c in local:
            c['native_blockers']=native_blockers(c,sightings)
        # Check every geometry-established candidate, not just the selected anchors.
        # Bridges cannot cross a frame where the instance disappears or is incomplete.
        bridges = []
        gaps = []
        for t in part['transitions']:
            a, b = t['from_frame'], t['to_frame']
            good = [c for c in local if c['from_frame'] == a and c['to_frame'] == b and trusted(c, sightings)]
            if len(good) < 2:
                gaps.append((a, b))
        candidates = {}
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
                    eligible = not geometry_bad and all(s is not None and (s['complete'] or (recovery and
                        s['bbox'][1] <= s['staff_y'] and s['bbox'][3] > s['staff_y'] + 4*s['spacing'])) for s in span)
                    candidates.setdefault((right-left,left,right),[]).append((first,last,eligible))
        # Reserve the bounded comparisons for edges that can supply two native
        # clean anchors. Their content remains unproven until the entire edge is read.
        endpoint_pairs = sorted(key for key,batch in candidates.items()
            if len({first['instance_id'] for first,last,eligible in batch
                    if eligible and reviewed(first,'clear') and reviewed(last,'clear')}) >= (1 if recovery else 2))
        for distance,left,right in endpoint_pairs:
            if not any(left <= index[a] < index[b] <= right for a,b in gaps):
                continue
            batch=candidates[(distance,left,right)]
            if bridge_attempts+len(batch)>256:
                break
            # All common spatial pairs for this bridge are inspected before choosing anchors.
            for first,last,eligible in batch:
                result=inspect_pair(first,last,bridge=True)
                bridge_attempts+=1
                if 'id' in part:
                    result['segment_id']=part['id']
                result['covered_frames']=ids[left:right+1]
                result['bridge_eligible']=eligible
                result['native_blockers']=native_blockers(result,sightings)
                bridges.append(result)
            for a,b in list(gaps):
                edges={}
                for c in local+bridges:
                    if trusted(c,sightings) and index[c['from_frame']] <= index[a] < index[b] <= index[c['to_frame']]:
                        edges.setdefault((c['from_frame'],c['to_frame']),set()).add(sightings[c['matches'][0]]['instance_id'])
                if any(len(instances)>=2 for instances in edges.values()) or (recovery and len(set().union(*edges.values())) >= 2):
                    gaps.remove((a,b))
        all_checks = local + bridges
        clean_instances = {sightings[c['matches'][0]]['instance_id'] for c in all_checks if trusted(c,sightings)}
        if recovery:
            # One actually reviewed complete source may preserve a printed
            # instance; two independent comparisons still prove every gap.
            from PIL import Image
            from agent_content import local_ink
            from pathlib import Path
            for fid in ids:
                candidates = [s for s in observed[fid].values() if s['complete'] and reviewed(s,'clear')]
                if candidates:
                    with Image.open(Path(task)/frames[fid]['path']) as image:
                        clean_instances.update(s['instance_id'] for s in candidates if local_ink(image,s)[1] is None)
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
            if recovery and not chosen:
                # Independent clean edges may use different endpoint times, but
                # each must span this entire gap. Geometry already established
                # the same ordered global positions through every middle frame.
                unique = {}
                for c in witnesses:
                    unique.setdefault(sightings[c['matches'][0]]['instance_id'], c)
                chosen = sorted(unique.values(), key=lambda c:
                    sightings[c['matches'][0]]['staff_y'] + offsets[c['from_frame']])[:2]
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
                    c['blocking'] = blocking(c,sightings,sufficient,clean_instances)
                    c['evidence_chain'] = intervals[-1]
        checks.extend(bridges)
        for c in bridges:
            same_edge=[p for p in all_checks if (p['from_frame'],p['to_frame'])==(c['from_frame'],c['to_frame']) and trusted(p,sightings)]
            sufficient = len({sightings[p['matches'][0]]['instance_id'] for p in same_edge})>=2
            if recovery:
                sufficient = all(g['sufficient'] for g in intervals if g['from_frame'] in index and index[c['from_frame']] <= index[g['from_frame']] < index[c['to_frame']])
            c['blocking'] = blocking(c,sightings,sufficient,clean_instances)
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
    result = dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
        observation_version=state['observation_version'],source_sha256=packet['source']['sha256'],
        decision_sha256=decision_hash(value),policy=POLICY,native_clean_regions=copy.deepcopy(clean))
    if packet.get('evidence_recovery_policy'):
        result['evidence_recovery_policy'] = packet['evidence_recovery_policy']
    return result


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
