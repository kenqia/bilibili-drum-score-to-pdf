"""Build existing decisions from bound suggestions and explicit Agent judgments."""
import copy
import math
import json
from agent_proposals import suggest
from agent_regions import box, invalid
from agent_performance import stage
from video_seek import ConversionError

STRUCTURES = {
    2: {'rows'}, 3: {'rows','observations','transitions','coverage'},
    4: {'segments','boundaries','coverage'},
}
ROW_FIELDS = {'frame_id','coordinate_space','roi','bbox','evidence_images','complete','cursor','occlusion','boundary_verified','evidence'}
SIGHTING_FIELDS = {'id','frame_id','instance_id','staff_y','spacing','bbox','complete','evidence'}
TRANSITION_FIELDS = {'from_frame','to_frame','matches','evidence'}
BOUNDARY_FIELDS = {'from_segment','to_segment','from_frame','to_frame','change','relation','before_complete','after_complete','continuity_verified','evidence_images','unresolved','evidence'}
JUDGMENTS = {'complete','boundary_verified','cursor','occlusion','evidence','before_complete','after_complete','continuity_verified','outside_rows_verified'}


def require(condition, message='决定构建请求字段或引用非法。'):
    if not condition:
        invalid(message)


def shape(value, fields):
    require(isinstance(value, dict) and set(value) == fields)


def records(structure):
    if structure['schema_version'] == 4:
        for segment in structure['segments']:
            yield segment
    else:
        yield structure


def check_structure(structure, packet):
    """Check every field/reference before missing confirmations can mask bad input."""
    version = structure.get('schema_version')
    require(type(version) is int and version in STRUCTURES)
    shape(structure, STRUCTURES[version] | {'schema_version'})
    frames = {f['id']: f for f in packet['frames']}
    images = {i['id']: i for i in packet['images']}
    def refs(values, known):
        require(isinstance(values,list) and all(isinstance(v,str) and v in known for v in values))
    def text(value):
        require(isinstance(value,str) and bool(value.strip()) and len(value)<=2000)
    def number(value):
        try:
            require(type(value) in (int,float) and math.isfinite(value))
        except OverflowError:
            invalid("几何数值必须为有限数。")
    def row(value, spatial):
        required = ROW_FIELDS | ({'instance_id','observation_id'} if spatial else set())
        require(isinstance(value,dict) and set(value) in (required, required | {'refinement'}))
        require(isinstance(value['frame_id'],str) and value['frame_id'] in frames)
        frame = frames[value['frame_id']]
        for key in ('roi','bbox'):
            box(value[key],frame)
        refs(value['evidence_images'], images)
        require(value['coordinate_space'] == 'native_pixels')
        text(value['evidence'])
        if spatial:
            text(value['instance_id']);text(value['observation_id'])
        for key in ('complete','boundary_verified'):
            require(type(value[key]) is bool)
        require(value['cursor'] in ('clear','present','uncertain') and value['occlusion'] in ('clear','present','uncertain'))
        if 'refinement' in value:
            shape(value['refinement'], {'bbox','reason','boundary_verified'})
            box(value['refinement']['bbox'], frame)
            require(type(value['refinement']['boundary_verified']) is bool)
            text(value['refinement']['reason'])
    if version == 4:
        require(isinstance(structure['segments'],list) and structure['segments'])
        segment_ids = set()
        for segment in structure['segments']:
            shape(segment, {'id','frames','rows','observations','transitions','extras','outside_rows_verified','evidence'})
            require(isinstance(segment['id'],str) and segment['id'] and segment['id'] not in segment_ids)
            segment_ids.add(segment['id']); refs(segment['frames'],frames)
            text(segment['evidence'])
            require(type(segment['outside_rows_verified']) is bool and isinstance(segment['extras'],list))
            for extra in segment['extras']:
                shape(extra, {'kind','placement','region'})
                require(extra['kind'] in ('title','notation') and extra['placement'] in ('before_rows','after_rows'))
                row(extra['region'],False)
        require(isinstance(structure['boundaries'],list))
        for boundary in structure['boundaries']:
            shape(boundary, BOUNDARY_FIELDS)
            for k in ('from_segment','to_segment'):
                require(isinstance(boundary[k],str) and boundary[k] in segment_ids)
            for k in ('from_frame','to_frame'):
                require(isinstance(boundary[k],str) and boundary[k] in frames)
            refs(boundary['evidence_images'],images)
            text(boundary['evidence'])
            require(boundary['change'] in ('page_turn','scale','layout_jump') and boundary['relation'] in ('next','skip','backward','uncertain'))
            require(isinstance(boundary['unresolved'],list))
            for k in ('before_complete','after_complete','continuity_verified'):
                require(type(boundary[k]) is bool)
    for part in records(structure):
        require(isinstance(part['rows'],list))
        for r in part['rows']:
            row(r,version in (3,4))
        if version in (3,4):
            require(isinstance(part['observations'],list) and isinstance(part['transitions'],list))
            ids = set()
            for sighting in part['observations']:
                shape(sighting,SIGHTING_FIELDS)
                require(isinstance(sighting['id'],str) and sighting['id'] and sighting['id'] not in ids)
                ids.add(sighting['id'])
                require(isinstance(sighting['frame_id'],str) and sighting['frame_id'] in frames)
                box(sighting['bbox'],frames[sighting['frame_id']])
                require(type(sighting['complete']) is bool)
                text(sighting['instance_id']);text(sighting['evidence'])
                number(sighting['staff_y']);number(sighting['spacing'])
                require(sighting['spacing']>0 and sighting['bbox'][1]<=sighting['staff_y']<sighting['bbox'][3])
            for r in part['rows']:
                require(isinstance(r['observation_id'],str) and r['observation_id'] in ids)
            for t in part['transitions']:
                shape(t,TRANSITION_FIELDS)
                text(t['evidence'])
                for k in ('from_frame','to_frame'):
                    require(isinstance(t[k],str) and t[k] in frames)
                require(isinstance(t['matches'],list))
                for pair in t['matches']:
                    require(isinstance(pair,list) and len(pair)==2)
                    refs(pair, ids)
    if version in (3,4):
        shape(structure['coverage'],{'first_frame','last_frame','unresolved'})
        for k in ('first_frame','last_frame'):
            require(isinstance(structure['coverage'][k],str) and structure['coverage'][k] in frames)
        require(isinstance(structure['coverage']['unresolved'],list))


def clear_review(value):
    if isinstance(value,list):
        for item in value:
            clear_review(item)
    elif isinstance(value,dict):
        for key,item in value.items():
            if key in JUDGMENTS:
                value[key] = 'uncertain' if key in ('cursor','occlusion') else 'Script suggestion; explicit Agent evidence required.' if key == 'evidence' else False
            elif key == 'evidence_images':
                # These are available evidence suggestions, not presentation claims.
                continue
            else:
                clear_review(item)


def patch(structure, changes, review=False):
    require(isinstance(changes,list) and len(changes)<=2000)
    for change in changes:
        shape(change,{'path','value'})
        path = change['path']
        require(isinstance(path,list) and path and all(type(k) in (str,int) for k in path))
        require(path[0] != 'schema_version')
        target=structure
        for key in path[:-1]:
            require((isinstance(target,dict) and isinstance(key,str) and key in target) or
                    (isinstance(target,list) and type(key) is int and 0<=key<len(target)))
            target=target[key]
        key=path[-1]
        require((isinstance(target,dict) and isinstance(key,str) and key in target) or
                (isinstance(target,list) and type(key) is int and 0<=key<len(target)))
        require((key in JUDGMENTS or key == 'evidence_images') if review else key not in JUDGMENTS,
                '视觉判断须放在 review.confirmations，结构修正不能静默确认。')
        target[key]=copy.deepcopy(change['value'])


def difference(before, after, path=None):
    path=path or []
    if type(before) is type(after) and isinstance(before,dict) and set(before)==set(after):
        return [change for key in sorted(before) for change in difference(before[key],after[key],path+[key])]
    if type(before) is type(after) and isinstance(before,list) and len(before)==len(after):
        return [change for index,(a,b) in enumerate(zip(before,after)) for change in difference(a,b,path+[index])]
    return [] if before==after else [dict(path=path,before=before,after=after)]


def build(task, request_path, output):
    from agent_workflow import checked_task, load_json, write_json, validate, MAX_JSON
    with stage('source_verification'):
        state,packet=checked_task(task)
    request=load_json(request_path)
    required={'schema_version','task_id','observation_sha256','observation_version','decision_id','model','prompt','corrections'}
    optional={'proposal','review','reviewed_frames','revision_of','reuse_accepted_review'}
    require(isinstance(request,dict) and required <= set(request) <= required|optional)
    require(type(request['schema_version']) is int and request['schema_version']==1)
    require(request['task_id']==state['task_id'] and request['observation_sha256']==state['observation_sha256'] and
            type(request['observation_version']) is int and request['observation_version']==state['observation_version'], '构建请求不属于当前观察包。')
    require('reuse_accepted_review' not in request or type(request['reuse_accepted_review']) is bool)
    history=state.get('decision_history',[])
    if history:
        require(request.get('revision_of')==history[-1]['decision_id'], '已有接受历史，构建必须显式 revision_of 最新决定。')
    else:
        require(request.get('revision_of') is None)
    reviewed=request.get('reviewed_frames',[f['id'] for f in packet['frames']])
    require(isinstance(reviewed,list) and reviewed and reviewed==[f['id'] for f in packet['frames']][:len(reviewed)], 'reviewed_frames 必须为有序前缀。')
    partial=copy.deepcopy(packet)
    partial['frames']=[f for f in packet['frames'] if f['id'] in reviewed]
    partial['candidates']=[c for c in packet['candidates'] if c['frame_id'] in reviewed]
    allowed={i['id'] for i in packet['images'] if i.get('frame_id') in reviewed or i['kind']=='comparison' or
             (i['kind']=='batch_comparison' and all(p['frame_id'] in reviewed for p in i['panels']))}
    partial['images']=[i for i in packet['images'] if i['id'] in allowed]
    with stage('decision_building'):
        geometry=suggest(partial)
        baseline=None
        if 'proposal' in request:
            structure=copy.deepcopy(request['proposal']); origin='caller_bound_suggestion'
        elif history:
            baseline=load_json(task/history[-1]['path']); baseline=baseline.get('decision',baseline)
            version=baseline['schema_version'];require(version in STRUCTURES)
            structure={k:copy.deepcopy(baseline[k]) for k in sorted(STRUCTURES[version]|{'schema_version'})}
            origin='accepted_decision'
        else:
            structure=copy.deepcopy(geometry['structure']);origin='script_geometry'
        check_structure(structure,partial)
        require(len(reviewed)==len(packet['frames']) or structure['schema_version'] in (3,4), '固定协议不能用于部分进度。')
        if history:
            accepted=load_json(task/history[0]['path']);accepted=accepted.get('decision',accepted)
            require(request['model']==accepted['model'] and structure['schema_version']==accepted['schema_version'], '任务不能混用模型标识或决定协议。')
            require(request['decision_id'] not in {entry['decision_id'] for entry in history}, '修订须使用新的决定 ID。')
        before=copy.deepcopy(structure)
        clear_review(structure)
        patch(structure,request['corrections'])
        check_structure(structure,partial)
        # Replacement objects may themselves contain stale positive judgments.
        clear_review(structure)
        reused=None
        if request.get('reuse_accepted_review'):
            require(baseline is not None, '沿用审阅必须使用最新已接受结构，不能用新建议替代。')
            from agent_review import reuse_accepted_review
            reused=reuse_accepted_review(task,state,packet,reviewed,baseline,structure,JUDGMENTS)
        review=request.get('review',{})
        fields={'identity_verified','coverage_verified','outside_rows_verified','presented_images','visual_review','complete','evidence','unresolved','confirmations','rows','observations','transitions','score_audit','native_clean_regions'}
        require(isinstance(review,dict) and set(review)<=fields)
        for key in ('identity_verified','coverage_verified','outside_rows_verified','visual_review','complete'):
            require(key not in review or type(review[key]) is bool)
        for part in records(structure):
            for key,allowed_fields in [('rows',{'complete','cursor','occlusion','boundary_verified','evidence'}),
                                       ('observations',{'complete','evidence'}),('transitions',{'evidence'})]:
                if key in review:
                    require(isinstance(review[key],dict) and set(review[key])<=allowed_fields)
                    require(key in part)
                    for record in part[key]:
                        record.update(copy.deepcopy(review[key]))
        patch(structure,review.get('confirmations',[]),review=True)
        check_structure(structure,partial)
        if packet.get('evidence_mode') == 'lazy':
            from agent_audit import wrap_continuous
            structure = wrap_continuous(structure, partial['frames'], review)
            check_structure(structure,partial)

        prior=reused['defaults'] if reused else {}
        presented=review.get('presented_images',[])
        require(isinstance(presented,list) and all(isinstance(i,str) and i in allowed for i in presented) and len(set(presented))==len(presented))
        if reused:
            presented=list(dict.fromkeys(reused['presented_images']+presented))
        decision={**structure,'task_id':state['task_id'],'observation_sha256':state['observation_sha256'],
                  'decision_id':request['decision_id'],'model':request['model'],'prompt':request['prompt'],
                  'presented_images':presented,'visual_review':review.get('visual_review',prior.get('visual_review',False)),
                  'complete':review.get('complete',prior.get('complete',False)),'evidence':review.get('evidence',prior.get('evidence','Draft; Agent confirmation required.')),
                  'unresolved':review.get('unresolved',prior.get('unresolved',[]))}
        acceptance_context, acceptance_items = None, []
        reused_acceptance=None
        if reused and history[-1].get('acceptance_path'):
            reused_acceptance=load_json(task/history[-1]['acceptance_path'])
        native_clean = review.get('native_clean_regions',copy.deepcopy(reused_acceptance['native_clean_regions']) if reused_acceptance else [])
        if packet.get('script_acceptance_policy'):
            from agent_acceptance import compute, fill
            script_paths=copy.deepcopy([i['path'] for i in reused_acceptance['items']]) if reused_acceptance else []
            for si,part in enumerate(decision['segments']):
                for collection in ('rows','observations','transitions'):
                    for ri,node in enumerate(part[collection]):
                        unconfirmed = not node.get('complete',False) if collection != 'transitions' else node['evidence'].startswith('Script suggestion;')
                        if unconfirmed and ['segments',si,collection,ri] not in script_paths:
                            script_paths.append(['segments',si,collection,ri])
            if script_paths:
                acceptance_context, acceptance_items = compute(task,state,partial,decision,script_paths,native_clean)
                fill(decision,acceptance_context)
                decision['visual_review']=False
                decision['complete']=review.get('complete',prior.get('complete',False))
        issues=[dict(reason='confirmation_required',field=k) for k in ('identity_verified','coverage_verified','outside_rows_verified') if review.get(k) is not True and (acceptance_context is None or k == 'outside_rows_verified')]
        for key in ('decision_id','evidence'):
            require(isinstance(decision[key],str) and bool(decision[key].strip()) and len(decision[key])<=2000)
        shape(decision['model'],{'id','version'})
        require(all(isinstance(v,str) and v for v in decision['model'].values()))
        shape(decision['prompt'],{'version','text'})
        require(all(isinstance(v,str) and v and len(v)<=16000 for v in decision['prompt'].values()))
        require(isinstance(decision['presented_images'],list) and all(isinstance(i,str) and i in allowed for i in decision['presented_images'])
                and len(set(decision['presented_images']))==len(decision['presented_images']))
        require(isinstance(decision['unresolved'],list))
        no_geometry=origin=='script_geometry' and not any(p['observations'] for p in records(structure))
        if no_geometry:
            issues.extend(geometry['issues'])
        # Validation probes use only local copies to catch malformed fields even while waiting.
        probe=copy.deepcopy(decision)
        if acceptance_context is None:
            probe.update(visual_review=True,complete=True,unresolved=[],presented_images=list(allowed))
        content_checks = []
        probe_content_checks = []
        with stage('decision_validation'):
            try:
                if not no_geometry:
                    validate(probe,state,partial,task,probe_content_checks,acceptance_context)
            except ConversionError as error:
                if error.code not in ('review_required','missing_evidence'):
                    raise
                issues.append(dict(reason=error.code,message=str(error)))
            try:
                if not no_geometry:
                    validate(decision,state,partial,task,content_checks,acceptance_context)
            except ConversionError as error:
                if error.code not in ('review_required','missing_evidence'):
                    raise
                issues.append(dict(reason=error.code,message=str(error)))
        score_audit = None
        if packet.get('evidence_mode') == 'lazy':
            from agent_audit import inspect
            with stage('coverage_audit'):
                score_review=copy.deepcopy(review.get('score_audit'))
                if acceptance_context and isinstance(score_review,dict):
                    for index,interval in enumerate(score_review['intervals']):
                        if ('segments',0,'transitions',index) in acceptance_context and interval['status']=='pending':
                            interval.update(status='script',regions=[],evidence='Recomputed common geometry, complete required pairs and native clean review authority.')
                score_audit, audit_issues = inspect(decision,partial,score_review,acceptance_context)
                issues.extend(audit_issues)
        if acceptance_items:
            issues.extend(dict(reason='script_acceptance_unresolved',path=i['path'],checks=i['unresolved']) for i in acceptance_items if i['unresolved'])
        if issues:
            decision['complete']=False
        value=decision
        if history or 'reviewed_frames' in request or 'revision_of' in request:
            value=dict(schema_version=5,decision_id=request['decision_id'],reviewed_frames=reviewed,
                       revision_of=request.get('revision_of'),decision=decision)
        require(len((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())<=MAX_JSON, '构建决定超过提交读取限额。')
        diff=difference(before,structure)
        sources=dict(task_id=state['task_id'],observation_sha256=state['observation_sha256'],source_sha256=packet['source']['sha256'],
                     observation_version=state['observation_version'],basis=origin,
                     accepted_sha256=history[-1]['sha256'] if history else None,
                     content_checks=content_checks or probe_content_checks,
                     geometry=geometry['geometry'],suggestion_issues=geometry['issues'],script_visual_review=False,
                     agent_confirmations=copy.deepcopy(review),reused_review=reused['provenance'] if reused else None,
                     reused_acceptance_sha256=history[-1].get('acceptance_sha256') if reused_acceptance else None,
                     selected_frames=[dict(id=f['id'],sha256=f['sha256'],pts=f['pts'],time_base=f['time_base']) for f in partial['frames']])
        if acceptance_items:
            from agent_acceptance import bind as bind_acceptance
            write_json(output/'acceptance.json',bind_acceptance(value,state,partial,acceptance_items,native_clean))
            sources['script_acceptance_items']=acceptance_items
        for name,data in [('decision.json',value),('diff.json',diff),('sources.json',sources),('unresolved.json',issues)]:
            write_json(output/name,data)
        if score_audit is not None:
            from agent_audit import bind
            write_json(output/'audit.json',bind(value,state,score_audit))
    return dict(status='waiting' if issues else 'success',complete=False,phase='decision_built',
                acceptance_counts=dict(script_items=len(acceptance_context or {}),pending_script_items=sum(bool(i['unresolved']) for i in acceptance_items),agent_clean_regions=len(native_clean)),
                ready_to_submit=not issues,decision=str((output/'decision.json').resolve()),
                diff=diff,sources=sources,unresolved=issues,
                next_action='Resolve draft confirmations.' if issues else 'Submit the built decision; no decision has been accepted by building.')
