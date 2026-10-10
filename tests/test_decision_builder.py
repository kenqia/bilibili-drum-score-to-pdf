"""Decision drafts and explicit review exercised through the unified CLI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import test_agent_continuity


class DecisionBuilderTests(unittest.TestCase):
    cli = test_agent_continuity.ContinuityTests.cli
    prepare = test_agent_continuity.ContinuityTests.prepare

    def request(self, task, decision):
        packet = json.loads((task / 'observation.json').read_text())
        request = dict(schema_version=1, task_id=decision['task_id'],
                       observation_sha256=decision['observation_sha256'],
                       observation_version=packet['observation_version'], decision_id='built-1',
                       model=decision['model'], prompt=decision['prompt'], corrections=[])
        return request, packet

    def build(self, base, task, request, name='draft'):
        path = base / 'corrections.json'
        path.write_text(json.dumps(request))
        return self.cli('--operation', 'build-decision', '--task', task,
                        '--decision', path, '--output', base / name)

    def test_unconfirmed_geometry_produces_draft_without_claiming_visual_review(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); task, full = self.prepare(base)
            request, _ = self.request(task, full)
            result = self.build(base, task, request)
            self.assertEqual(result['status'], 'waiting', result)
            draft = json.loads((base / 'draft/decision.json').read_text())
            self.assertFalse(draft['visual_review'])
            self.assertFalse(draft['complete'])
            self.assertEqual(draft['presented_images'], [])
            self.assertTrue(result['unresolved'])
            self.assertFalse((task / 'decision.json').exists())
            self.assertFalse((base / 'draft/score.pdf').exists())

    def reviewed_request(self, task, decision):
        request, packet = self.request(task, decision)
        keys = {2: ('rows',), 3: ('rows','observations','transitions','coverage'),
                4: ('segments','boundaries','coverage')}[decision['schema_version']]
        request['proposal'] = {k: copy.deepcopy(decision[k]) for k in ('schema_version', *keys)}
        confirmations = []
        judgments = {'complete','boundary_verified','cursor','occlusion','evidence','before_complete',
                     'after_complete','continuity_verified','outside_rows_verified'}
        def visit(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in judgments:
                        confirmations.append(dict(path=path+[key],value=item))
                    else:
                        visit(item,path+[key])
            elif isinstance(value,list):
                for index,item in enumerate(value):
                    visit(item,path+[index])
        visit(request['proposal'], [])
        request['review'] = dict(identity_verified=True,coverage_verified=True,outside_rows_verified=True,
                                 presented_images=decision['presented_images'],visual_review=True,complete=True,
                                 evidence=decision['evidence'],unresolved=[],confirmations=confirmations)
        return request, packet

    def test_bound_suggestion_and_one_crop_correction_submit_export_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,full=self.prepare(base)
            request,packet=self.reviewed_request(task,full)
            # A four-pixel crop refinement comes from the reviewer, never rebuilt pixels.
            request['corrections']=[dict(path=['rows',0,'bbox'],value=[74,180,1206,320]),
                                    dict(path=['observations',0,'bbox'],value=[74,180,1206,320])]
            result=self.build(base,task,request)
            self.assertEqual(result['status'],'success',result)
            self.assertTrue(result['ready_to_submit'])
            self.assertFalse((task/'decision.json').exists())
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            exported=self.cli('--operation','export','--task',task,'--output',base/'out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(exported['status'],'success',exported)
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual([r['instance_id'] for r in exported['rows']],list('ABCD'))
            self.assertEqual(exported['rows'][0]['selected_candidate']['bbox'],[74,180,1206,320])
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())
            sources=json.loads((base/'draft/sources.json').read_text())
            self.assertEqual(sources['basis'],'caller_bound_suggestion')
            self.assertFalse(sources['script_visual_review'])
            self.assertEqual([f['pts'] for f in sources['selected_frames']],[f['pts'] for f in packet['frames']])
            report=self.cli('--operation','report','--task',task)
            self.assertIn('build-decision',[e['operation'] for e in report['performance']['operations']])
            self.assertIn('decision_building',[e['name'] for e in report['performance']['stages']])

    def test_script_geometry_can_be_confirmed_without_rewriting_complete_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,full=self.prepare(base)
            request,packet=self.request(task,full)
            request['review']=dict(identity_verified=True,coverage_verified=True,outside_rows_verified=True,
                presented_images=[i['id'] for i in packet['images']], visual_review=True,complete=True,
                evidence='Controlled fixture confirms stable native staffs at the sampled frames.',unresolved=[],
                rows=dict(complete=True,cursor='clear',occlusion='clear',boundary_verified=True,
                          evidence='Controlled fixture confirms all selected native row crops.'),
                observations=dict(complete=True,evidence='Controlled fixture confirms all five-line observations.'),
                transitions=dict(evidence='Controlled fixture confirms stationary ordered correspondence.'))
            result=self.build(base,task,request)
            self.assertTrue(result.get('ready_to_submit'),result)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            exported=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertEqual(exported['status'],'success',exported)
            self.assertEqual(len(exported['rows']),3)
            draft=json.loads((base/'draft/decision.json').read_text())
            self.assertEqual(draft['rows'][0]['observation_id'],'frame-000-row-000')

    def test_unconfirmed_draft_rejects_unknown_references_and_illegal_later_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,full=self.prepare(base)
            request,_=self.reviewed_request(task,full)
            request.pop('review')
            cases=[lambda r:r['proposal']['rows'][-1].update(frame_id='unknown'),
                   lambda r:r['proposal']['rows'][-1].update(evidence={'illegal':'field'}),
                   lambda r:r['proposal']['observations'][-1].update(complete='true'),
                   lambda r:r['proposal']['rows'][-1].update(secret='unknown')]
            for index,change in enumerate(cases):
                bad=copy.deepcopy(request);change(bad)
                result=self.build(base,task,bad,f'rejected-{index}')
                self.assertEqual(result['status'],'failed',result)
                self.assertFalse((base/f'rejected-{index}/decision.json').exists())

    def test_current_accepted_prefix_requires_explicit_revision_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,full=self.prepare(base)
            prefix=copy.deepcopy(full);prefix['decision_id']='prefix'
            prefix['observations']=prefix['observations'][:6]
            prefix['transitions']=prefix['transitions'][:1]
            prefix['coverage']['last_frame']='frame-001'
            packet=json.loads((task/'observation.json').read_text())
            prefix['presented_images']=[i['id'] for i in packet['images'] if i.get('frame_id')!='frame-002'
                and not any(p['frame_id']=='frame-002' for p in i.get('panels',[])) or i['kind']=='comparison']
            request,_=self.reviewed_request(task,prefix)
            request['reviewed_frames']=['frame-000','frame-001']
            result=self.build(base,task,request,'prefix')
            self.assertTrue(result['ready_to_submit'],result)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'prefix/decision.json')
            self.assertEqual(accepted['phase'],'batch_accepted',accepted)
            resumed=self.cli('--operation','resume','--task',task)
            self.assertEqual(resumed['reviewed_frames'],['frame-000','frame-001'])
            history=copy.deepcopy(resumed['decision_history'])
            revision,_=self.reviewed_request(task,prefix)
            revision['decision_id']='revised-prefix'
            revision['reviewed_frames']=['frame-000','frame-001']
            rejected=self.build(base,task,revision,'no-revision')
            self.assertEqual(rejected['status'],'failed',rejected)
            revision['revision_of']='built-1'
            # Structure comes from saved acceptance; no full proposal is rewritten.
            revision.pop('proposal')
            revised=self.build(base,task,revision,'revision')
            self.assertTrue(revised['ready_to_submit'],revised)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'revision/decision.json')
            self.assertEqual(len(accepted['decision_history']),2,accepted)
            self.assertEqual(accepted['decision_history'][0],history[0])
            self.assertEqual(accepted['decision_history'][1]['revision_of'],'built-1')
            self.assertEqual(json.loads((base/'revision/sources.json').read_text())['accepted_sha256'],history[0]['sha256'])
            final,_=self.reviewed_request(task,full)
            final.update(decision_id='final',revision_of='revised-prefix')
            ready=self.build(base,task,final,'final')
            self.assertTrue(ready['ready_to_submit'],ready)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'final/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            self.assertEqual(len(accepted['decision_history']),3)
            out=self.cli('--operation','export','--task',task,'--output',base/'out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(out['status'],'success',out)
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())

    def test_illegal_replacement_judgment_is_not_silently_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,full=self.prepare(base)
            request,_=self.reviewed_request(task,full)
            request.pop('review')
            illegal=copy.deepcopy(full['rows']);illegal[-1]['complete']='true'
            request['corrections']=[dict(path=['rows'],value=illegal)]
            result=self.build(base,task,request)
            self.assertEqual(result['status'],'failed',result)
            self.assertFalse((base/'draft/decision.json').exists())

    def test_existing_v2_and_v4_structures_keep_native_sources_and_replay(self):
        import test_agent_segments
        for version in (2,4):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as directory:
                base=Path(directory)
                if version==4:
                    task,decision=test_agent_segments.SegmentTests.decision(self,base)
                else:
                    task,full=self.prepare(base)
                    decision={k:copy.deepcopy(v) for k,v in full.items() if k not in ('observations','transitions','coverage')}
                    decision['schema_version']=2
                    decision['rows']=[{k:v for k,v in r.items() if k not in ('instance_id','observation_id')} for r in decision['rows'][:3]]
                request,packet=self.reviewed_request(task,decision)
                result=self.build(base,task,request)
                self.assertTrue(result['ready_to_submit'],result)
                accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
                self.assertEqual(accepted['phase'],'accepted',accepted)
                exported=self.cli('--operation','export','--task',task,'--output',base/'out')
                replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
                self.assertEqual(exported['status'],'success',exported)
                self.assertEqual(replay['status'],'success',replay)
                self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())
                if version==4:
                    self.assertEqual([r['segment_id'] for r in exported['rows']],['page-0']*3+['page-1']*3)
                    self.assertEqual(len(exported['extras']),2)

    def test_absent_detector_geometry_stays_uncertain_without_fabricated_identity(self):
        from PIL import Image
        from score_fixtures import video_from_image
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            video=video_from_image(Image.new('RGB',(1280,960),'white'),base)
            task=base/'task';state=self.cli(video,'--operation','prepare','--output',task)
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                observation_version=state['observation_version'],decision_id='no-geometry',
                model=dict(id='fixture',version='unknown'),prompt=dict(version='fixture',text='Review uncertain score.'),corrections=[])
            result=self.build(base,task,request)
            self.assertEqual(result['status'],'waiting',result)
            draft=json.loads((base/'draft/decision.json').read_text())
            self.assertEqual(draft['rows'],[])
            self.assertEqual(draft['observations'],[])
            self.assertEqual(draft['presented_images'],[])
            self.assertFalse(draft['visual_review'])

    def test_build_is_deterministic_and_rejects_stale_binding_and_unknown_review_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,full=self.prepare(base)
            request,_=self.reviewed_request(task,full)
            first=self.build(base,task,request,'one')
            second=self.build(base,task,request,'two')
            self.assertTrue(first['ready_to_submit'],first)
            self.assertTrue(second['ready_to_submit'],second)
            for name in ('decision.json','diff.json','sources.json','unresolved.json'):
                self.assertEqual((base/'one'/name).read_bytes(),(base/'two'/name).read_bytes())
            cases=[lambda r:r.update(observation_sha256='0'*64),
                   lambda r:r.update(observation_version=0),
                   lambda r:r['review'].update(unknown=True),
                   lambda r:r['review'].update(presented_images=['unknown']),
                   lambda r:r.update(corrections=[dict(path=['rows',0,'complete'],value=True)])]
            for index,change in enumerate(cases):
                bad=copy.deepcopy(request);change(bad)
                result=self.build(base,task,bad,f'bad-{index}')
                self.assertEqual(result['status'],'failed',result)
                self.assertFalse((base/f'bad-{index}/decision.json').exists())
