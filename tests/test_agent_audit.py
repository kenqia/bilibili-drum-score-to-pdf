"""Bounded whole-score audit through the approved CLI boundary."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
import test_agent_evidence


class AuditTests(unittest.TestCase):
    cli = test_agent_evidence.LazyEvidenceTests.cli
    prepare = test_agent_evidence.LazyEvidenceTests.prepare

    def native_sources(self, base, task, state, packet):
        request = test_agent_evidence.LazyEvidenceTests.request(self, state, packet)
        request['request_id'] = 'audit-sources'
        request['regions'] = [dict(frame_id=f['id'], frame_sha256=f['sha256'], pts=f['pts'], time_base=f['time_base'],
                                   bbox=[0,0,f['width'],f['height']]) for f in packet['frames']]
        path = base / 'native-request.json'
        path.write_text(json.dumps(request))
        state = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
        return state, json.loads((task / 'observation.json').read_text())

    def reviewed_request(self, state, packet, frames=None):
        frames = frames or packet['frames']
        details = {f['id']: next(i['id'] for i in packet['images'] if i['kind'] == 'native_detail'
                   and i['frame_id'] == f['id'] and i['bbox'] == [0,0,f['width'],f['height']]) for f in frames}
        def region(fid, bbox):
            return dict(frame_id=fid, bbox=bbox, evidence_images=[details[fid]])
        def row(fid, bbox):
            return dict(frame_id=fid, coordinate_space='native_pixels', roi=[0,0,1280,960], bbox=bbox,
                        evidence_images=[details[fid]], complete=True, cursor='clear', occlusion='clear',
                        boundary_verified=True, evidence='Controlled fixture whole native region and margins.')
        rows, sightings, transitions = [], [], []
        for index, frame in enumerate(frames):
            for number, top in enumerate([220,440,660]):
                sighting = dict(id=f'{frame["id"]}-{number}', frame_id=frame['id'], instance_id=f'row-{number}',
                                staff_y=top, spacing=12, bbox=[80,top-40,1200,top+130], complete=True,
                                evidence='Controlled fixture complete five-line staff.')
                sightings.append(sighting)
                if index == 0:
                    rows.append(dict(instance_id=sighting['instance_id'], observation_id=sighting['id'], **row(frame['id'], sighting['bbox'])))
            if index:
                transitions.append(dict(from_frame=frames[index-1]['id'], to_frame=frame['id'],
                                        matches=[[f'{frames[index-1]["id"]}-{n}',f'{frame["id"]}-{n}'] for n in range(3)],
                                        evidence='Controlled fixture stationary spatial correspondence.'))
        first, last = frames[0]['id'], frames[-1]['id']
        segment = dict(id='score-000', frames=[f['id'] for f in frames], rows=rows, observations=sightings,
                       transitions=transitions, outside_rows_verified=True, evidence='Controlled fixture whole score.',
                       extras=[dict(kind='title', placement='before_rows', region=row(first,[80,50,1200,155]))])
        proposal = dict(schema_version=4, segments=[segment], boundaries=[],
                        coverage=dict(first_frame=first,last_frame=last,unresolved=[]))
        confirmations = []
        judgments = {'complete','boundary_verified','cursor','occlusion','evidence','outside_rows_verified'}
        def visit(value, path):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in judgments:
                        confirmations.append(dict(path=path+[key], value=item))
                    else:
                        visit(item,path+[key])
            elif isinstance(value,list):
                for index,item in enumerate(value):
                    visit(item,path+[index])
        visit(proposal,[])
        checks = {kind: dict(status='checked', regions=[region(first,[110,70,1120,120])],
                            print_regions=[dict(kind='extra',index=0)], evidence='Controlled fixture visible title, tempo 96 and 4/4.')
                  for kind in ('title','tempo','time_signature')}
        checks['outside_rows'] = dict(status='checked', regions=[region(first,rows[0]['bbox'])],
                                     print_regions=[dict(kind='row',index=0)], evidence='Stem and row label are inside the complete printed row.')
        audit = dict(segments=[dict(id=segment['id'],checks=checks,
                     first_edge=dict(complete=True,regions=[region(first,[0,0,1280,960])],evidence='Complete opening staff and margins.'),
                     last_edge=dict(complete=True,regions=[region(last,[0,0,1280,960])],evidence='Complete ending staff and margins.'))],
                     intervals=[dict(from_frame=a['id'],to_frame=b['id'],status='checked',
                                     regions=[region(f['id'],[0,0,1280,960]) for f in (a,b)],
                                     evidence='Observed stable endpoints; unobserved time is not proved unchanged.')
                                for a,b in zip(frames,frames[1:])],unresolved=[])
        return dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                    observation_version=state['observation_version'],decision_id='audited',
                    model=dict(id='controlled-fixture',version='unknown'),prompt=dict(version='audit-test',text='Review native sources and complete coverage.'),
                    corrections=[],proposal=proposal,review=dict(identity_verified=True,coverage_verified=True,outside_rows_verified=True,
                    presented_images=[i['id'] for i in packet['images'] if i.get('frame_id') in [f['id'] for f in frames] or i['kind']=='comparison'],
                    visual_review=True,complete=True,evidence='Controlled fixture three rows and explicit title.',unresolved=[],
                    confirmations=confirmations,score_audit=audit))

    def build(self, base, task, request, name='built'):
        path = base / 'build-request.json'
        path.write_text(json.dumps(request))
        return self.cli('--operation','build-decision','--task',task,'--decision',path,'--output',base/name)

    def test_explicit_native_title_and_whole_score_audit_exports_and_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, state, packet = self.prepare(base)
            state, packet = self.native_sources(base,task,state,packet)
            request = self.reviewed_request(state,packet)
            built = self.build(base,task,request)
            self.assertTrue(built.get('ready_to_submit'),built)
            audit = json.loads((base/'built/audit.json').read_text())
            self.assertEqual(audit['decision_sha256'],hashlib.sha256((base/'built/decision.json').read_bytes()).hexdigest())
            self.assertFalse(audit['coverage']['hidden_content_proven_absent'])
            self.assertEqual(audit['coverage']['first']['pts'],packet['frames'][0]['pts'])
            self.assertEqual(len(audit['coverage']['intervals']),2)
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            self.assertIn('audit_sha256',accepted['decision_history'][-1])
            for name,operation in [('out','export'),('replay','replay')]:
                result = self.cli('--operation',operation,'--task',task,'--output',base/name)
                self.assertEqual(result['status'],'success',result)
                self.assertEqual(len(result['extras']),1)
                self.assertEqual(result['extras'][0]['selected_region']['bbox'],[80,50,1200,155])
                self.assertEqual(result['score_audit']['coverage']['accepted_instances'],['row-0','row-1','row-2'])
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())

    def test_lazy_legacy_decision_cannot_skip_explicit_title_and_coverage_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, state, packet = self.prepare(base)
            frame = packet['frames'][0]
            request = test_agent_evidence.LazyEvidenceTests.request(self, state, packet)
            path = base / 'request.json'
            path.write_text(json.dumps(request))
            state = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            packet = json.loads((task / 'observation.json').read_text())
            details = [i for i in packet['images'] if i['kind'] == 'native_detail']
            decision = dict(schema_version=2, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                            decision_id='legacy', model=dict(id='fixture', version='unknown'),
                            prompt=dict(version='test', text='Review score.'), presented_images=[i['id'] for i in packet['images']],
                            visual_review=True, complete=True, evidence='Three complete rows.', unresolved=[],
                            rows=[dict(frame_id=frame['id'], coordinate_space='native_pixels', roi=[0,0,1280,960],
                                       bbox=i['bbox'], evidence_images=[i['id']], complete=True, cursor='clear',
                                       occlusion='clear', boundary_verified=True, evidence='Full native row.') for i in details])
            path.write_text(json.dumps(decision))
            rejected = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(rejected['status'], 'waiting', rejected)
            self.assertIn('v4', rejected['error']['message'])
            exported = self.cli('--operation', 'export', '--task', task, '--output', base / 'out')
            self.assertNotEqual(exported['status'], 'success', exported)
            self.assertFalse((base / 'out/score.pdf').exists())

    def test_refinement_cannot_remove_audited_row_or_extra_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task,state,packet = self.prepare(base)
            state,packet = self.native_sources(base,task,state,packet)
            for kind in ('row','extra'):
                with self.subTest(kind=kind):
                    request = self.reviewed_request(state,packet)
                    segment = request['proposal']['segments'][0]
                    if kind == 'row':
                        target = segment['rows'][0]
                        refined = [80,188,1200,350]
                        path = ['segments',0,'rows',0,'refinement','boundary_verified']
                    else:
                        target = segment['extras'][0]['region']
                        target['bbox'] = [80,50,1200,120]
                        refined = [80,50,1200,112]
                        path = ['segments',0,'extras',0,'region','refinement','boundary_verified']
                    target['refinement'] = dict(bbox=refined,reason='Eight-pixel inward boundary correction.',boundary_verified=True)
                    request['review']['confirmations'].append(dict(path=path,value=True))
                    built = self.build(base,task,request,kind)
                    self.assertFalse(built.get('ready_to_submit'),built)
                    self.assertIn('score_region_not_printed',[i['reason'] for i in built['unresolved']])
                    rejected = self.cli('--operation','submit','--task',task,'--decision',base/kind/'decision.json')
                    self.assertEqual(rejected['status'],'waiting',rejected)
                    self.assertNotEqual(rejected.get('phase'),'accepted',rejected)
                    for operation in ('export','replay'):
                        output = base/f'{kind}-{operation}'
                        result = self.cli('--operation',operation,'--task',task,'--output',output)
                        self.assertNotEqual(result['status'],'success',result)
                        self.assertFalse((output/'score.pdf').exists())

    def test_refined_rows_and_extras_containing_audit_regions_export_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task,state,packet = self.prepare(base)
            state,packet = self.native_sources(base,task,state,packet)
            request = self.reviewed_request(state,packet)
            segment = request['proposal']['segments'][0]
            segment['rows'][0]['refinement'] = dict(bbox=[80,188,1200,350],reason='Remove blank upper margin.',boundary_verified=True)
            segment['extras'][0]['region']['refinement'] = dict(bbox=[80,50,1200,147],reason='Remove blank lower margin.',boundary_verified=True)
            request['review']['score_audit']['segments'][0]['checks']['outside_rows']['regions'][0]['bbox'] = [100,190,1180,340]
            for path in (['segments',0,'rows',0,'refinement','boundary_verified'],
                         ['segments',0,'extras',0,'region','refinement','boundary_verified']):
                request['review']['confirmations'].append(dict(path=path,value=True))
            built = self.build(base,task,request)
            self.assertTrue(built['ready_to_submit'],built)
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            for operation in ('export','replay'):
                result = self.cli('--operation',operation,'--task',task,'--output',base/operation)
                self.assertEqual(result['status'],'success',result)
                self.assertEqual(result['rows'][0]['bbox'],[80,188,1200,350])
                self.assertEqual(result['extras'][0]['selected_region']['bbox'],[80,50,1200,147])
                self.assertEqual(result['score_audit']['source_regions'][3]['bbox'],[100,190,1180,340])
            self.assertEqual((base/'export/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())

    def test_unverified_refinement_keeps_waiting_audit_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task,state,packet = self.prepare(base)
            state,packet = self.native_sources(base,task,state,packet)
            for kind in ('row','extra'):
                with self.subTest(kind=kind):
                    request = self.reviewed_request(state,packet)
                    segment = request['proposal']['segments'][0]
                    if kind == 'row':
                        target = segment['rows'][0]
                        path = ['segments',0,'rows',0,'refinement','boundary_verified']
                    else:
                        target = segment['extras'][0]['region']
                        path = ['segments',0,'extras',0,'region','refinement','boundary_verified']
                    target['refinement'] = dict(bbox=target['bbox'][:],reason='Boundary needs native review.',boundary_verified=False)
                    request['review']['confirmations'].append(dict(path=path,value=False))
                    built = self.build(base,task,request,kind)
                    self.assertEqual(built['status'],'waiting',built)
                    self.assertFalse(built['ready_to_submit'])
                    self.assertIn('review_required',[i['reason'] for i in built['unresolved']])
                    for name in ('decision.json','diff.json','sources.json','unresolved.json','audit.json'):
                        self.assertTrue((base/kind/name).exists(),name)
                    rejected = self.cli('--operation','submit','--task',task,'--decision',base/kind/'decision.json')
                    self.assertEqual(rejected['status'],'waiting',rejected)
                    self.assertNotEqual(rejected.get('phase'),'accepted',rejected)

    def test_pending_missing_cropped_and_stale_audits_cannot_publish_success(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task,state,packet = self.prepare(base)
            state,packet = self.native_sources(base,task,state,packet)
            good = self.reviewed_request(state,packet)
            mutations = [
                lambda r:r['review'].pop('score_audit'),
                lambda r:r['review']['score_audit']['segments'][0]['checks']['title'].update(status='pending',regions=[],print_regions=[]),
                lambda r:r['review']['score_audit']['segments'][0]['checks']['tempo'].update(status='absent',regions=[],print_regions=[]),
                lambda r:r['review']['score_audit']['segments'][0]['first_edge'].update(complete=False),
                lambda r:r['review']['score_audit']['intervals'][0].update(status='pending'),
                lambda r:r['review']['score_audit'].update(unresolved=['Possible jump needs a new clean source.']),
                lambda r:r['proposal']['segments'][0]['extras'][0]['region'].update(bbox=[80,50,1200,85])]
            for index,change in enumerate(mutations):
                request = copy.deepcopy(good)
                change(request)
                # The replacement is still explicitly confirmed; the audit ROI must catch the cut.
                built = self.build(base,task,request,f'bad-{index}')
                self.assertFalse(built.get('ready_to_submit',False),built)
                self.assertEqual(built['status'],'waiting',built)
                rejected = self.cli('--operation','submit','--task',task,'--decision',base/f'bad-{index}/decision.json')
                self.assertNotEqual(rejected.get('phase'),'accepted',rejected)
            built = self.build(base,task,good,'good')
            self.assertTrue(built['ready_to_submit'],built)
            audit_path = base/'good/audit.json'
            original_audit = audit_path.read_bytes()
            audit_path.unlink()
            rejected = self.cli('--operation','submit','--task',task,'--decision',base/'good/decision.json')
            self.assertEqual(rejected['status'],'waiting',rejected)
            audit = json.loads(original_audit)
            audit['decision_sha256'] = '0'*64
            audit_path.write_text(json.dumps(audit))
            rejected = self.cli('--operation','submit','--task',task,'--decision',base/'good/decision.json')
            self.assertEqual(rejected['error']['code'],'invalid_decision',rejected)
            audit_path.write_bytes(original_audit)
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'good/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            saved = task/accepted['decision_history'][-1]['audit_path']
            saved.write_bytes(saved.read_bytes()+b' ')
            replayed = self.cli('--operation','replay','--task',task,'--output',base/'tampered')
            self.assertEqual(replayed['error']['code'],'source_mismatch',replayed)
            self.assertFalse((base/'tampered/score.pdf').exists())

    def test_prefix_and_materialization_require_new_audit_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task,state,packet = self.prepare(base)
            state,packet = self.native_sources(base,task,state,packet)
            request = self.reviewed_request(state,packet,packet['frames'][:2])
            request['reviewed_frames'] = [f['id'] for f in packet['frames'][:2]]
            built = self.build(base,task,request,'prefix')
            self.assertTrue(built['ready_to_submit'],built)
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'prefix/decision.json')
            self.assertEqual(accepted['phase'],'batch_accepted',accepted)
            self.assertFalse(accepted['complete'])
            old_history = copy.deepcopy(accepted['decision_history'])
            region = test_agent_evidence.LazyEvidenceTests.request(self,accepted,packet,[[80,50,1200,155]])
            region['request_id'] = 'title-detail'
            path = base/'roi.json'
            path.write_text(json.dumps(region))
            changed = self.cli('--operation','materialize','--task',task,'--decision',path)
            self.assertEqual(changed['decision_history'],old_history)
            stale = self.cli('--operation','submit','--task',task,'--decision',base/'prefix/decision.json')
            self.assertEqual(stale['error']['code'],'invalid_decision',stale)
            current = json.loads((task/'observation.json').read_text())
            final = self.reviewed_request(changed,current)
            final.update(decision_id='whole-score',revision_of='audited')
            built = self.build(base,task,final,'final')
            self.assertTrue(built['ready_to_submit'],built)
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'final/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            self.assertEqual(accepted['decision_history'][0],old_history[0])
            exported = self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertEqual(exported['status'],'success',exported)

    def test_navigation_limit_needs_real_supplement_and_all_current_gap_reviews(self):
        from PIL import ImageDraw
        from score_fixtures import score_frame
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for index in range(64):
                image = score_frame()
                ImageDraw.Draw(image).rectangle((0,920,1279,959),fill='white' if index%2 else 'black')
                image.save(base/f'{index:03d}.png')
            video = base/'input.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-framerate','4','-i',str(base/'%03d.png'),'-pix_fmt','yuv420p',str(video)],check=True)
            task = base/'task'
            state = self.cli(video,'--output',task,'--evidence-mode','lazy')
            self.assertEqual(state['status'],'waiting',state)
            packet = json.loads((task/'observation.json').read_text())
            self.assertTrue(packet['sampling']['unresolved'])
            self.assertLess(len({f['pts'] for f in packet['frames']}),len(packet['frames']))
            history_flag = copy.deepcopy(packet['sampling']['unresolved'])
            state,packet = self.native_sources(base,task,state,packet)
            self.assertEqual(len({i['id'] for i in packet['images']}),len(packet['images']))
            request = self.reviewed_request(state,packet)
            before = self.build(base,task,request,'limited')
            self.assertTrue('ready_to_submit' in before,{k:v for k,v in before.items() if k!='performance'})
            self.assertFalse(before['ready_to_submit'],before)
            resolution = dict(status='reviewed_after_supplement',new_frames=[packet['frames'][0]['id']],
                              intervals=[[a['id'],b['id']] for a,b in zip(packet['frames'],packet['frames'][1:])],
                              evidence='Claiming a new view cannot substitute for a real new PTS.')
            request['review']['score_audit']['navigation_resolution'] = resolution
            forged = self.build(base,task,request,'forged-resolution')
            self.assertFalse(forged['ready_to_submit'],forged)
            timestamps = {f['timestamp'] for f in packet['frames']}
            new_time = next(i/4 for i in range(1,63) if i/4 not in timestamps)
            supplement = dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                              observation_version=state['observation_version'],request_id='resolve-navigation-gap',
                              issue=dict(reason='Review an unsampled local navigation gap',start=max(0,new_time-.25),end=new_time+.25),
                              timestamps=[new_time])
            path = base/'supplement.json'
            path.write_text(json.dumps(supplement))
            state = self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertEqual(state['status'],'waiting',state)
            current = json.loads((task/'observation.json').read_text())
            added = [f for f in current['frames'] if f['id'] not in {f['id'] for f in packet['frames']}]
            self.assertEqual(len(added),1)
            self.assertNotIn(added[0]['timestamp'],timestamps)
            self.assertEqual(current['sampling']['unresolved'],history_flag)
            # Request only the new source; the earlier native audit evidence remains valid.
            materialize = test_agent_evidence.LazyEvidenceTests.request(self,state,current)
            materialize['request_id'] = 'supplemented-native-audit'
            f = added[0]
            materialize['regions'] = [dict(frame_id=f['id'],frame_sha256=f['sha256'],pts=f['pts'],time_base=f['time_base'],bbox=[0,0,1280,960])]
            path.write_text(json.dumps(materialize))
            state = self.cli('--operation','materialize','--task',task,'--decision',path)
            current = json.loads((task/'observation.json').read_text())
            request = self.reviewed_request(state,current)
            request['review']['score_audit']['navigation_resolution'] = dict(status='reviewed_after_supplement',new_frames=[f['id']],
                intervals=[[a['id'],b['id']] for a,b in zip(current['frames'],current['frames'][1:])],
                evidence='Actual new PTS and each current native gap endpoint have been checked; sparse uncertainty remains.')
            built = self.build(base,task,request,'resolved')
            self.assertTrue(built['ready_to_submit'],built)
            audit = json.loads((base/'resolved/audit.json').read_text())
            self.assertTrue(audit['coverage']['navigation_review_resolved'])
            self.assertEqual(audit['coverage']['navigation_unresolved'],history_flag)
            self.assertFalse(audit['coverage']['hidden_content_proven_absent'])
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'resolved/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            self.assertEqual(accepted['sampling_usage']['requests'],1)

    def test_explicit_absence_and_single_segment_upgrade_keep_native_evidence(self):
        from PIL import ImageDraw
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            image = score_frame()
            ImageDraw.Draw(image).rectangle((80,50,1200,155),fill='white')
            video = video_from_image(image,base)
            task = base/'task'
            state = self.cli(video,'--output',task,'--evidence-mode','lazy')
            packet = json.loads((task/'observation.json').read_text())
            state,packet = self.native_sources(base,task,state,packet)
            request = self.reviewed_request(state,packet)
            segment = request['proposal']['segments'][0]
            request['proposal'] = dict(schema_version=3,rows=segment['rows'],observations=segment['observations'],
                                      transitions=segment['transitions'],coverage=request['proposal']['coverage'])
            review = request['review']
            review['confirmations'] = []
            review['rows'] = dict(complete=True,cursor='clear',occlusion='clear',boundary_verified=True,evidence='Complete native fixture rows.')
            review['observations'] = dict(complete=True,evidence='Complete native fixture five-line observations.')
            review['transitions'] = dict(evidence='Stationary ordered fixture correspondence.')
            for name in ('title','tempo','time_signature'):
                check = review['score_audit']['segments'][0]['checks'][name]
                check.update(status='absent',print_regions=[],evidence='Controlled source header area is blank; absence checked on native pixels.')
            built = self.build(base,task,request)
            self.assertTrue(built['ready_to_submit'],built)
            value = json.loads((base/'built/decision.json').read_text())
            self.assertEqual(value['schema_version'],4)
            self.assertEqual(value['segments'][0]['extras'],[])
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            result = self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertEqual(result['status'],'success',result)
            self.assertIsNone(result['header'])
            self.assertEqual(result['extras'],[])

    def test_local_supplement_budget_exhaustion_preserves_lazy_waiting(self):
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video_from_image(score_frame(),base)
            subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(base/'input.png'),'-t','2','-r','16','-pix_fmt','yuv420p',str(base/'input.mp4')],check=True)
            task = base/'task'
            state = self.cli(base/'input.mp4','--output',task,'--evidence-mode','lazy')
            path = base/'supplement.json'
            for index in range(8):
                request = dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                               observation_version=state['observation_version'],request_id=f'gap-{index}',
                               issue=dict(reason='Inspect local risk',start=0,end=1),timestamps=[.1+index*.1])
                path.write_text(json.dumps(request))
                state = self.cli('--operation','supplement','--task',task,'--decision',path)
                self.assertEqual(state['status'],'waiting',state)
            request.update(observation_sha256=state['observation_sha256'],observation_version=state['observation_version'],request_id='exhausted',timestamps=[.95])
            path.write_text(json.dumps(request))
            failed = self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertEqual(failed['error']['code'],'sampling_budget',failed)
            resumed = self.cli('--operation','resume','--task',task)
            self.assertEqual(resumed['sampling_usage']['requests'],8)
            packet = json.loads((task/'observation.json').read_text())
            self.assertEqual(packet['evidence_mode'],'lazy')
            self.assertEqual(packet['metrics']['detail_images'],0)
            exported = self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertNotEqual(exported['status'],'success',exported)
            self.assertFalse((base/'out/score.pdf').exists())


if __name__ == '__main__':
    unittest.main()
