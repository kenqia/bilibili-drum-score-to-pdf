"""Bound review suggestions to native evidence and existing recovery operations."""
import copy
import hashlib
import json
from agent_performance import stage
from agent_proposals import suggest
from agent_regions import covered
from agent_sampling import check_request, LIMITS
from video_seek import ConversionError


def review_plan(task, output, request_path=None):
    from agent_workflow import checked_task, load_json, write_json, MAX_JSON
    with stage('source_verification'):
        state, packet = checked_task(task)
    image_access = 'unknown'
    if request_path:
        request = load_json(request_path)
        fields = {'schema_version','task_id','observation_sha256','observation_version','image_access'}
        if (not isinstance(request,dict) or set(request)!=fields or type(request['schema_version']) is not int
                or request['schema_version']!=1 or request['task_id']!=state['task_id']
                or request['observation_sha256']!=state['observation_sha256']
                or type(request['observation_version']) is not int or request['observation_version']!=state['observation_version']
                or type(request['image_access']) is not bool):
            raise ConversionError('invalid_request','审阅能力声明必须绑定当前观察包。')
        image_access = 'available' if request['image_access'] else 'unavailable'
    with stage('review_planning'):
        proposal = suggest(packet)
        frames = packet['frames']; by_frame = {f['id']:f for f in frames}
        candidates = {c['id']:c for c in packet['candidates']}
        sightings = proposal['structure']['observations']
        by_sighting = {s['id']:s for s in sightings}
        issues, required_regions = [], {}
        def context(ids):
            return [dict(id=f['id'],sha256=f['sha256'],pts=f['pts'],time_base=f['time_base'],timestamp=f['timestamp'],path=f['path'])
                    for f in frames if f['id'] in ids]
        def add(reason, ids, risk, regions=None, detail=None):
            ids=list(dict.fromkeys(ids))
            entry=dict(id=f'issue-{len(issues):03d}',reason=reason,risk=risk,context=context(ids),
                       status='uncertain',required_native_regions=[],detail=detail)
            for frame_id,bbox in regions or []:
                frame=by_frame[frame_id]
                region=dict(frame_id=frame_id,frame_sha256=frame['sha256'],pts=frame['pts'],time_base=frame['time_base'],bbox=bbox)
                entry['required_native_regions'].append(region)
                required_regions[(frame_id,tuple(bbox))]=region
            issues.append(entry)
            return entry
        def row_regions(ids):
            return [(c['frame_id'],c['bbox']) for c in packet['candidates'] if c['frame_id'] in ids]
        if image_access!='available':
            add('image_access', [f['id'] for f in frames[:2]], 'actual_visual_review_unavailable',detail=image_access)
        for index,frame in enumerate(frames):
            local=[c for c in packet['candidates'] if c['frame_id']==frame['id']]
            nearby=[f['id'] for f in frames[max(0,index-1):index+2]]
            if not local:
                add('missing_geometry',nearby,'identity_unproven',[(frame['id'],[0,0,frame['width'],frame['height']])])
            for candidate in local:
                if not candidate['clean']:
                    add('occlusion_or_cursor',nearby,'no_printable_source_confirmation',[(frame['id'],candidate['bbox'])],candidate['id'])
                if not candidate['complete']:
                    add('boundary',nearby,'partial_or_unverified_edge',[(frame['id'],candidate['bbox'])],candidate['id'])
            # Detector boundaries only nominate areas; they never certify title absence.
            top=min((c['bbox'][1] for c in local),default=frame['height'])
            bottom=max((c['bbox'][3] for c in local),default=0)
            regions=[]
            if top>0:
                regions.append((frame['id'],[0,0,frame['width'],top]))
            if bottom<frame['height'] and bottom>0:
                regions.append((frame['id'],[0,bottom,frame['width'],frame['height']]))
            add('outside_rows',[frame['id']],'title_tempo_time_signature_notation_pending',regions)
        for frame in (frames[0],frames[-1]):
            add('score_boundary',[frame['id']],'first_or_last_score_edge_unconfirmed',row_regions([frame['id']]))
        for row in proposal['structure']['rows']:
            same=[s for s in sightings if s['instance_id']==row['instance_id']]
            if not any(candidates[s['id']]['clean'] and candidates[s['id']]['complete'] for s in same if s['id'] in candidates):
                add('no_clean_observation',[s['frame_id'] for s in same],'printable_source_unavailable',
                    [(s['frame_id'],s['bbox']) for s in same],row['instance_id'])
            details=[i for i in packet['images'] if i.get('frame_id')==row['frame_id'] and i['kind'] in ('detail','native_detail')]
            if not packet.get('script_acceptance_policy') and not covered(row['bbox'],[i['bbox'] for i in details]):
                add('native_detail_required',[row['frame_id']],'ordinary_row_still_requires_native_review',[(row['frame_id'],row['bbox'])],row['instance_id'])
        audits={(a['from_frame'],a['to_frame']):a for a in proposal['geometry']}
        for before,after in zip(frames,frames[1:]):
            audit=audits.get((before['id'],after['id']),{'matches':[]})
            ids=[before['id'],after['id']]
            options=audit.get('plausible_translations',[])
            if len(options)>1:
                add('multiple_displacements',ids,'identity_ambiguous_including_lower_overlap',row_regions(ids),options)
            if len(audit['matches'])<2:
                add('insufficient_overlap',ids,'jump_or_page_turn_unconfirmed',row_regions(ids))
            groups_a=before.get('analysis',{}).get('groups',[])
            groups_b=after.get('analysis',{}).get('groups',[])
            layout_a=before.get('analysis',{}).get('bbox',[0,0,0,0])
            layout_b=after.get('analysis',{}).get('bbox',[0,0,0,0])
            if (groups_a and groups_b and abs(groups_a[0]['spacing']/groups_b[0]['spacing']-1)>.03
                    or layout_a[2]>layout_a[0] and layout_b[2]>layout_b[0] and
                    (abs((layout_a[2]-layout_a[0])/(layout_b[2]-layout_b[0])-1)>.03 or abs(layout_a[0]-layout_b[0])>2)):
                add('scale_or_layout_change',ids,'ordered_segment_boundary_required',row_regions(ids))
            if not options:
                add('unexplained_jump',ids,'page_turn_or_skip_or_backward_unconfirmed',row_regions(ids))
                add('page_or_segment_boundary',ids,'segment_order_and_continuity_unconfirmed',row_regions(ids))
            add('sampling_gap',ids,'hidden_content_not_proven_absent',detail=dict(start=before['timestamp'],end=after['timestamp']))
        for reason in packet['sampling'].get('unresolved',[]):
            add('navigation_limit',[frames[0]['id'],frames[-1]['id']],'sampling_coverage_unresolved',detail=reason)
        # Supplement suggestions use the charged durable ledger, never stale packet budget.
        sampling=load_json(task/'sampling.json')
        supplement_packet=copy.deepcopy(packet);supplement_packet['sampling']=sampling
        supplements=[]
        for issue in issues:
            if issue['reason'] not in ('occlusion_or_cursor','no_clean_observation','insufficient_overlap','multiple_displacements','unexplained_jump','sampling_gap','navigation_limit'):
                continue
            start=max(0,issue['context'][0]['timestamp'])
            end=min(packet['source']['duration'],start+30,issue['context'][-1]['timestamp'] if len(issue['context'])>1 else start+1)
            if not start<end:
                issue['supplement_available']=False
                continue
            times=[start+(end-start)*ratio for ratio in (.5,.25,.75)
                   if start+(end-start)*ratio not in {f['requested_timestamp'] for f in frames}]
            if not times:
                issue['supplement_available']=False
                continue
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                         observation_version=state['observation_version'],request_id=f'review-v{state["observation_version"]}-{issue["id"]}',
                         issue=dict(reason=issue['reason'],start=start,end=end),timestamps=[times[0]])
            try:
                check_request(request,state,supplement_packet)
            except ConversionError as error:
                issue['supplement_available']=False;issue['supplement_blocked_by']=error.code
            else:
                issue['supplement_available']=True
                supplements.append(dict(issue_id=issue['id'],request=request))
        if packet.get('script_acceptance_policy'):
            required_regions={}
            for frame in frames:
                bbox=[0,0,frame['width'],frame['height']]
                add('native_clean_roi',[frame['id']],'actual_agent_clean_scope_required',[(frame['id'],bbox)])
        requests=[]
        needed=[]
        for region in required_regions.values():
            details=[i for i in packet['images'] if i.get('frame_id')==region['frame_id'] and i['kind'] in ('detail','native_detail')]
            if not covered(region['bbox'],[i['bbox'] for i in details]):
                needed.append(region)
        for index,start in enumerate(range(0,len(needed),128)):
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                observation_version=state['observation_version'],source_sha256=packet['source']['sha256'],
                request_id=f'review-v{state["observation_version"]}-roi-{index:03d}',reason='Native review evidence for current unresolved regions.',regions=needed[start:start+128])
            filename=f'materialize-request-{index:03d}.json'
            write_json(output/filename,request)
            requests.append(dict(path=filename,request=request))
        for index,supplement in enumerate(supplements):
            filename=f'supplement-request-{index:03d}.json'
            write_json(output/filename,supplement['request']);supplement['path']=filename
        template=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
            observation_version=state['observation_version'],decision_id=f'review-v{state["observation_version"]}',
            model=dict(id='unknown',version='unknown'),prompt=dict(version='review-plan-1',text='Review all required native frames and details; resolve geometric, source, boundary and coverage issues.'),
            corrections=[],proposal=proposal['structure'],review=dict(identity_verified=False,coverage_verified=False,outside_rows_verified=False,
                presented_images=[],visual_review=False,complete=False,evidence='Unconfirmed review template.',
                unresolved=[i['id'] for i in issues],confirmations=[]))
        if packet.get('script_acceptance_policy'):
            template['review']['native_clean_regions']=[dict(frame_id=f['id'],frame_sha256=f['sha256'],pts=f['pts'],time_base=f['time_base'],
                bbox=[0,0,f['width'],f['height']],evidence_images=[],cursor='uncertain',occlusion='uncertain',evidence='Actually review the native source ROI before confirming clean.') for f in frames]
        if state.get('decision_history'):
            template['revision_of']=state['decision_history'][-1]['decision_id']
        if packet.get('evidence_mode')=='lazy':
            checks={key:dict(status='pending',regions=[],print_regions=[],evidence='Native confirmation required.') for key in ('title','tempo','time_signature','outside_rows')}
            edge=dict(complete=False,regions=[],evidence='Native edge confirmation required.')
            score_audit=dict(segments=[dict(id='score-000',checks=checks,first_edge=copy.deepcopy(edge),last_edge=copy.deepcopy(edge))],
                intervals=[dict(from_frame=a['id'],to_frame=b['id'],status='pending',regions=[],evidence='Native interval review required.') for a,b in zip(frames,frames[1:])],unresolved=[])
            write_json(output/'score-audit-template.json',score_audit)
        result=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                    observation_version=state['observation_version'],source_sha256=packet['source']['sha256'],
                    status='waiting',complete=False,phase='review_plan',image_access=image_access,
                    suggestion=proposal,issues=issues,materialize_requests=requests,supplement_requests=supplements,
                    sampling_usage=sampling['used'],sampling_limits=LIMITS,actual_presented_images=None,
                    required_review=dict(native_frames=[f['id'] for f in frames],all_selected_native_details=not bool(packet.get('script_acceptance_policy')),
                        native_detail_materialization_required=bool(needed),automatic_acceptance=False,
                        hidden_content_proven_absent=False),build_template='build-template.json',score_audit_template='score-audit-template.json' if packet.get('evidence_mode')=='lazy' else None,
                    next_action='Materialize required ROIs, actually review native evidence, then rebuild this plan after observation updates.')
        if packet.get('script_acceptance_policy'):
            result['script_acceptance']=dict(policy=packet['script_acceptance_policy'],enabled=True,
                requires_actual_native_clean_review=True,first_last_and_outside_agent_review=True,
                real_validated_support=[],script_reads_are_presentations=False)
        serialized=json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
        if len(serialized.encode('utf-8'))>MAX_JSON:
            raise ConversionError('sampling_budget','审阅计划超过 JSON 上限，保留任务与疑点。')
        write_json(output/'review-plan.json',result,compact=True)
        write_json(output/'build-template.json',template)
    return result


def reuse_accepted_review(task, state, packet, reviewed, baseline, structure, judgment_fields):
    """Opt-in reuse of immutable accepted review, never newly materialized images."""
    from agent_workflow import load_json, digest
    def require(condition,message):
        if not condition:
            raise ConversionError('invalid_decision',message)
    history=state['decision_history'];entry=history[-1]
    archive=task/f'observation-v{entry["observation_version"]}.json'
    if entry['observation_sha256']==state['observation_sha256']:
        archive=task/'observation.json'
    require(not archive.is_symlink() and archive.is_file(),'接受审阅的观察归档路径非法。')
    require(digest(archive)==entry['observation_sha256'],'接受审阅的观察归档已改变。')
    old=load_json(archive)
    require(old['source']['sha256']==packet['source']['sha256'],'接受审阅来源不一致。')
    keys=('id','sha256','pts','time_base','width','height')
    require([[f[k] for k in keys] for f in old['frames']]==[[f[k] for k in keys] for f in packet['frames']],
            '新增或改变原帧后不能沿用此局部审阅路径，请明确复查新接续。')
    accepted=load_json(task/entry['path'])
    prior_frames=accepted.get('reviewed_frames',[f['id'] for f in old['frames']])
    require(reviewed==prior_frames,'局部沿用必须保持已接受的审阅前缀。')
    old_images={i['id']:i for i in old['images']};current_images={i['id']:i for i in packet['images']}
    for image_id in baseline['presented_images']:
        require(image_id in old_images and image_id in current_images and old_images[image_id]==current_images[image_id],
                '既有实际呈交证据已改变，不能自动沿用判断。')
    def signature(value):
        if isinstance(value,dict):
            return {k:signature(v) for k,v in value.items() if k not in judgment_fields}
        if isinstance(value,list):
            return [signature(v) for v in value]
        return value
    restored=[]
    def restore(before,after,path):
        if isinstance(before,dict) and isinstance(after,dict):
            if signature(before)==signature(after):
                for key in sorted(judgment_fields & set(before) & set(after)):
                    after[key]=copy.deepcopy(before[key]);restored.append(path+[key])
            for key in sorted((set(before)&set(after))-judgment_fields):
                restore(before[key],after[key],path+[key])
        elif isinstance(before,list) and isinstance(after,list):
            for index,(a,b) in enumerate(zip(before,after)):
                restore(a,b,path+[index])
    old_structure={key:baseline[key] for key in structure}
    unchanged=signature(old_structure)==signature(structure)
    restore(old_structure,structure,[])
    return dict(presented_images=copy.deepcopy(baseline['presented_images']),unchanged=unchanged,
                defaults={key:copy.deepcopy(baseline[key]) for key in ('visual_review','complete','evidence','unresolved')} if unchanged else {},
                provenance=dict(decision_sha256=entry['sha256'],observation_sha256=entry['observation_sha256'],
                                restored_paths=restored,script_claimed_new_images_reviewed=False))
