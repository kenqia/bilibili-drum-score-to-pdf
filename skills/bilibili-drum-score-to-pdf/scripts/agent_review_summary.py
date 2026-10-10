"""Small actionable summaries retain the detailed original diagnostics separately."""
import copy
from agent_sampling import check_request
from video_seek import ConversionError


def summarize(issues, checks, packet, bound):
    groups = {}
    for issue in issues:
        groups.setdefault(issue['reason'], []).append(issue['id'])
    intervals = {}
    for c in checks:
        if 'evidence_chain' in c:
            item = copy.deepcopy(c['evidence_chain'])
            key=(item['from_frame'],item['to_frame'])
            intervals[key]=item
    missing = []
    alternatives = []
    for key,item in intervals.items():
        local=[c for c in checks if (c['from_frame'],c['to_frame'])==key]
        spanning_conflicts=[c for c in checks if c.get('blocking') and c.get('scope')=='geometry_established_bridge' and all(fid in c.get('covered_frames',[]) for fid in key)]
        blocking=[c for c in local if c.get('blocking',c['status']!='not_contradicted')]+spanning_conflicts
        if blocking:
            native=[b for c in blocking for b in c.get('native_blockers',[])]
            item['reasons']=sorted({b['reason'] for b in native}|{c['reason'] for c in blocking if c['status']=='conflict' or not c.get('native_blockers')})
            item['next_action']='Review the native interval and request a new original frame only if existing evidence cannot resolve these reasons.'
            if native:
                item['native_blockers']=[dict(v) for v in {tuple((k,tuple(v) if isinstance(v,list) else v) for k,v in b.items()):b for b in native}.values()]
                if any(b['reason']!='native_cursor_requires_alternative' for b in native):
                    item['next_action']='Verify each listed native instance and endpoint range. Explicitly revise an incorrect declaration using that original range; otherwise retain waiting. Unrelated new frames cannot clear these declarations.'
                else:
                    item['next_action']='Review the listed native cursor ranges and supplement this interval only to obtain two ordered clean witnesses under the existing alternative-chain contract.'
            missing.append(item)
        elif any(c['status']=='uncertain' for c in local):
            item['diagnostic_count']=sum(c['status']=='uncertain' for c in local)
            alternatives.append(item)
    return dict(bound_geometry_checked=bound,critical_gaps=missing,
        existing_alternatives=alternatives,
        duplicate_candidates=[dict(reason=k,count=len(v),record_ids=v) for k,v in groups.items() if k=='multiple_displacements'],
        low_value_diagnostics=[dict(reason=k,count=len(v)) for k,v in groups.items() if k in ('sampling_gap',)],
        required_native_review=dict(detector_diagnostic_groups=[dict(reason=k,count=len(v)) for k,v in groups.items() if k not in ('multiple_displacements','sampling_gap')],first_last_edges=True,outside_rows=True,every_frame=True,every_interval=True,selected_print_sources=True),
        next_action='Resolve only the listed critical intervals, retaining every native coverage audit.' if bound else 'Review native geometry and supply a bound build request; detector candidates alone do not establish missing rows.',
        raw_diagnostic_count=len(issues),raw_content_pair_count=len(checks),hidden_content_proven_absent=False)


def targeted(summary,state,packet):
    frames={f['id']:f for f in packet['frames']}
    intervals=[]
    for gap in summary['critical_gaps']:
        # Actual conflicts need correspondence correction, not automatic extra frames.
        if 'contradictory_local_notation' in gap['reasons'] or any(b['reason']!='native_cursor_requires_alternative' for b in gap.get('native_blockers',[])):
            continue
        start=frames[gap['from_frame']]['timestamp'];end=frames[gap['to_frame']]['timestamp']
        if 0 <= start < end <= packet['source']['duration'] and end-start <=30:
            intervals.append((start,end,(start+end)/2))
    grouped=[]
    existing={f['requested_timestamp'] for f in packet['frames']}
    for start,end,timestamp in sorted(set(intervals)):
        if timestamp in existing:
            timestamp=start+(end-start)/4
        if timestamp in existing:
            continue
        if grouped and end-grouped[-1][0]<=30 and len(grouped[-1][2])<8:
            grouped[-1][1]=max(end,grouped[-1][1]);grouped[-1][2].append(timestamp)
        else:
            grouped.append([start,end,[timestamp]])
    planned=copy.deepcopy(packet);result=[]
    for n,(start,end,times) in enumerate(grouped):
        request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
            observation_version=state['observation_version'],request_id=f'chain-v{state["observation_version"]}-{n:03d}',
            issue=dict(reason='required_content_witness',start=start,end=end),timestamps=list(dict.fromkeys(times)))
        try:
            check_request(request,state,planned)
        except ConversionError as error:
            summary.setdefault('blocked_requests',[]).append(dict(start=start,end=end,reason=error.code))
            continue
        result.append(dict(issue_id=f'chain-gap-{n:03d}',request=request))
        used=planned['sampling']['used'];used['requests']+=1;used['native_frames']+=len(request['timestamps']);used['requested_frames']+=len(request['timestamps'])
        planned['sampling']['request_ids'].append(request['request_id'])
    return result
