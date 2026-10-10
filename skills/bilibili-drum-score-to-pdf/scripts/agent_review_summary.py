"""Small actionable summaries retain the detailed original diagnostics separately."""
import copy
from agent_sampling import check_request
from video_seek import ConversionError
from agent_evidence_chain import REPLACEABLE

SUPPLEMENT_REASONS=REPLACEABLE|{'missing_native_content_witnesses','native_cursor_requires_alternative'}


def diagnostics(issues, packet, decision, checks, review, category):
    """Group diagnostics by actual source scope; proposals never supply identities."""
    frames={f['id']:f for f in packet['frames']}
    order={fid:n for n,fid in enumerate(frames)}
    parts=decision.get('segments',[]) if decision else []
    observations=[s for part in parts for s in part['observations']]
    audit=(review or {}).get('score_audit') or {}
    groups={}
    for issue in issues:
        ids=[fid for fid in (issue.get('from_frame'),issue.get('to_frame'),issue.get('frame_id')) if fid in frames]
        regions=issue.get('required_native_regions',[])
        ids.extend(r['frame_id'] for r in regions if r['frame_id'] in frames)
        if not ids and decision and issue.get('path'):
            target=decision
            try:
                for key in issue['path']:
                    target=target[key]
                target=target.get('region',target)
                ids=[fid for fid in (target.get('frame_id'),target.get('from_frame'),target.get('to_frame')) if fid in frames]
            except (KeyError,IndexError,TypeError,AttributeError):
                pass
        if not ids and 'start' in issue and 'end' in issue:
            ids=[fid for fid,f in frames.items() if issue['start']<=f['timestamp']<=issue['end']]
        if not ids:
            ids=[c['id'] for c in issue.get('context',[]) if c['id'] in frames]
        part=next((p for p in parts if p['id']==issue.get('segment_id')),None)
        if not ids and part:
            if issue.get('edge') in ('first_edge','last_edge'):
                ids=[part['frames'][0 if issue['edge']=='first_edge' else -1]]
            else:
                segment=next((s for s in audit.get('segments',[]) if s['id']==part['id']),{})
                native=segment.get('checks',{}).get(issue.get('field'),{}).get('regions',[])
                ids=[r['frame_id'] for r in native] or part['frames']
        ids=sorted(set(ids),key=order.get)
        key=(issue.get('reason','native_review_required'),ids[0] if ids else None,ids[-1] if ids else None)
        if category!='required':
            key=(key[0],None,None)
        group=groups.setdefault(key,dict(issues=[],ids=set()))
        group['issues'].append(issue);group['ids'].update(ids)
    result=[]
    for (reason,first,last),group in groups.items():
        ids=sorted(group['ids'],key=order.get)
        if category!='required' and ids:
            first,last=ids[0],ids[-1]
        reasons=sorted({i.get('reason','native_review_required') for i in group['issues']})
        regions=[r for i in group['issues'] for r in i.get('required_native_regions',[])]
        def relevant(s):
            return s['frame_id'] in ids and (not regions or any(r['frame_id']==s['frame_id'] and
                max(r['bbox'][0],s['bbox'][0])<min(r['bbox'][2],s['bbox'][2]) and
                max(r['bbox'][1],s['bbox'][1])<min(r['bbox'][3],s['bbox'][3]) for r in regions))
        instances=sorted({s['instance_id'] for s in observations if relevant(s)})
        details=[i for i in packet['images'] if i.get('frame_id') in ids and i['kind']=='native_detail']
        chains={(c['evidence_chain']['from_frame'],c['evidence_chain']['to_frame']):c['evidence_chain'] for c in checks if 'evidence_chain' in c}
        witnesses={tuple(w['matches']) for (a,b),chain in chains.items() if first is not None and
            order[first]<=order[a]<order[b]<=order[last] for w in chain['witnesses']}
        native_audits=[i for i in audit.get('intervals',[]) if first is not None and
            order[first]<=order[i['from_frame']]<order[i['to_frame']]<=order[last]]
        statuses={i['status'] for i in native_audits}
        audit_status=next(iter(statuses)) if len(statuses)==1 else 'mixed' if statuses else 'unknown'
        if category=='duplicate':
            action='Retain the bound correspondence and leave redundant detector candidates in the raw report.' if decision else 'Review the native endpoints and establish one ordered geometric correspondence before using detector candidates.'
        elif category=='low_value':
            action='Retain the checked interval audit; no diagnostic-only supplement is needed.' if statuses and statuses<=set(('checked','script')) else 'Review the pending coverage actions; the raw sampling diagnostics alone do not require additional frames.'
        elif category=='required':
            action='Review this native interval and complete its pending coverage audit.' if any(r in ('unresolved_sampling_interval','unresolved_script_interval') for r in reasons) else 'Review the listed pending native fields in bound-build/unresolved.json and explicitly complete their audit.'
            if not ids:
                action='Locate the missing native scope in bound-build/unresolved.json before making a confirmation; its interval and identity remain unknown.'
        else:
            action='Check these detector nominations against the bound native geometry and audit; change only an actual unresolved item.' if decision else 'Review the native source range and establish geometry and coverage before assigning a spatial identity.'
        result.append(dict(reason=reason,reasons=reasons,count=len(group['issues']),
            interval=dict(from_frame=first,to_frame=last,start=frames[first]['timestamp'] if first else None,end=frames[last]['timestamp'] if last else None),
            interval_scope='required_interval' if category=='required' else 'raw_diagnostic_range',
            affected_instances=instances or None,identity_scope='bound_geometry' if instances else 'unknown',
            existing_evidence=dict(available_original_frames=len(ids),available_native_details=len(details),
                declared_presented_native_details=sum(i['id'] in decision['presented_images'] for i in details) if decision else None,
                trusted_content_witness_count=len(witnesses),coverage_audit_status=audit_status),
            pending_fields=sorted({i['field'] for i in group['issues'] if 'field' in i}),next_action=action))
    return result


def summarize(issues, checks, packet, bound, decision=None, review=None, required=None):
    decision=decision if bound else None
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
            pixel={c['reason'] for c in blocking if c['status']=='conflict' or not c.get('native_blockers') or c['reason'] not in REPLACEABLE and c['status']=='uncertain'}
            pixel.update(r for c in blocking for r in c.get('endpoint_reasons',[]) if r is not None and r not in REPLACEABLE)
            item['reasons']=sorted({b['reason'] for b in native}|pixel)
            item['next_action']='Review the native interval and request a new original frame only if existing evidence cannot resolve these reasons.'
            hard=[c for c in blocking if c['status'] in ('conflict','uncertain') and (c['reason'] not in SUPPLEMENT_REASONS or any(r is not None and r not in REPLACEABLE for r in c.get('endpoint_reasons',[])))]
            if hard:
                item['content_blockers']=[dict(segment_id=c.get('segment_id'),from_frame=c['from_frame'],to_frame=c['to_frame'],matches=c['matches'],reason=c['reason']) for c in hard]
                item['next_action']='Review the listed native correspondences and correct identity, source completeness or actual alignment. Retain waiting if these sources remain unprovable; unrelated new frames cannot remove a hard reason.'
            if native:
                item['native_blockers']=[dict(v) for v in {tuple((k,tuple(v) if isinstance(v,list) else v) for k,v in b.items()):b for b in native}.values()]
                if any(b['reason']!='native_cursor_requires_alternative' for b in native):
                    item['next_action']='Verify each listed native instance and endpoint range. Explicitly revise an incorrect declaration using that original range; otherwise retain waiting. Unrelated new frames cannot clear these declarations.'
                elif not hard:
                    item['next_action']='Review the listed native cursor ranges and supplement this interval only to obtain two ordered clean witnesses under the existing alternative-chain contract.'
            missing.append(item)
        elif any(c['status']=='uncertain' for c in local):
            item['diagnostic_count']=sum(c['status']=='uncertain' for c in local)
            alternatives.append(item)
    for items in (missing,alternatives):
        for item in items:
            extra=diagnostics([item],packet,decision,checks,review,'required')[0]
            for key in ('interval','existing_evidence'):
                item[key]=extra[key]
            if not bound:
                item['affected_instances']=None
            elif item.get('native_blockers') or item.get('content_blockers'):
                affected={b['instance_id'] for b in item.get('native_blockers',[])}
                sightings={(p['id'],s['id']):s for p in (decision or {}).get('segments',[]) for s in p['observations']}
                for c in item.get('content_blockers',[]):
                    affected.update(sightings[(c['segment_id'],i)]['instance_id'] for i in c['matches'] if (c['segment_id'],i) in sightings)
                item['affected_instances']=sorted(affected) or item['affected_instances']
            if items is alternatives:
                item['next_action']='Retain the existing clean witnesses and native cursor review; no redundant supplement is needed.'
    return dict(bound_geometry_checked=bound,critical_gaps=missing,
        existing_alternatives=alternatives,
        duplicate_candidates=diagnostics([i for i in issues if i['reason']=='multiple_displacements'],packet,decision,checks,review,'duplicate'),
        low_value_diagnostics=diagnostics([i for i in issues if i['reason']=='sampling_gap'],packet,decision,checks,review,'low_value'),
        other_required_actions=diagnostics(required or [],packet,decision,checks,review,'required'),
        required_native_review=dict(detector_diagnostic_groups=diagnostics([i for i in issues if i['reason'] not in ('multiple_displacements','sampling_gap')],packet,decision,checks,review,'detector'),first_last_edges=True,outside_rows=True,every_frame=True,every_interval=True,selected_print_sources=True),
        next_action='Resolve only the listed critical intervals, retaining every native coverage audit.' if bound else 'Review native geometry and supply a bound build request; detector candidates alone do not establish missing rows.',
        raw_diagnostic_count=len(issues),raw_content_pair_count=len(checks),hidden_content_proven_absent=False)


def targeted(summary,state,packet):
    frames={f['id']:f for f in packet['frames']}
    intervals=[]
    for gap in summary['critical_gaps']:
        # Actual conflicts need correspondence correction, not automatic extra frames.
        if any(reason not in SUPPLEMENT_REASONS for reason in gap['reasons']):
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
