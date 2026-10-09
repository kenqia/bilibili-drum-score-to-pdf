"""Explainable review plans through the approved unified CLI."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import ImageDraw
from score_fixtures import CLI, score_frame


class ReviewTests(unittest.TestCase):
    def cli(self,*args):
        p=subprocess.run([sys.executable,str(CLI),*map(str,args)],capture_output=True,text=True)
        self.assertTrue(p.stdout,p.stderr)
        return json.loads(p.stdout)

    def prepare(self,base,mode='lazy',occluded=True):
        for index in range(8):
            image=score_frame()
            if index<4 and occluded:
                ImageDraw.Draw(image).rectangle((500,180,515,330),fill='blue')
            image.save(base/f'{index:03d}.png')
        source=base/'input.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-framerate','4','-i',str(base/'%03d.png'),'-pix_fmt','yuv420p',str(source)],check=True)
        task=base/'task'
        state=self.cli(source,'--output',task,'--evidence-mode',mode)
        self.assertEqual(state['status'],'waiting',state)
        return task

    def plan(self,base,task,name='plan',decision=None):
        args=['--operation','review-plan','--task',task,'--output',base/name]
        if decision is not None:
            path=base/'review-input.json';path.write_text(json.dumps(decision));args+=['--decision',path]
        return self.cli(*args)

    def test_mixed_clean_and_occluded_frames_produce_bound_native_review_context(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task=self.prepare(base)
            before=(task/'observation.json').read_bytes()
            result=self.plan(base,task)
            self.assertEqual(result['status'],'waiting',result)
            plan=json.loads((base/'plan/review-plan.json').read_text())
            reasons={i['reason'] for i in plan['issues']}
            self.assertIn('occlusion_or_cursor',reasons)
            self.assertIn('outside_rows',reasons)
            self.assertIn('sampling_gap',reasons)
            self.assertEqual(plan['actual_presented_images'],None)
            self.assertFalse(plan['suggestion']['visual_review'])
            self.assertEqual((task/'observation.json').read_bytes(),before)
            self.assertFalse((task/'decision.json').exists())
            for issue in plan['issues']:
                self.assertTrue(issue['context'])
                self.assertTrue(all('pts' in f and 'time_base' in f for f in issue['context']))
            template=json.loads((base/'plan/build-template.json').read_text())
            self.assertEqual(template['observation_sha256'],hashlib.sha256(before).hexdigest())
            self.assertFalse(template['review']['visual_review'])
            self.assertEqual(template['review']['presented_images'],[])

    def test_clean_roi_review_rebinds_template_and_enters_build_submit_export_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task=self.prepare(base,occluded=False)
            planned=self.plan(base,task)
            self.assertTrue(planned['materialize_requests'])
            roi=base/'plan'/planned['materialize_requests'][0]['path']
            expanded=self.cli('--operation','materialize','--task',task,'--decision',roi)
            self.assertEqual(expanded['observation_version'],2,expanded)
            old=base/'plan/build-template.json'
            stale=self.cli('--operation','build-decision','--task',task,'--decision',old,'--output',base/'stale')
            self.assertEqual(stale['status'],'failed',stale)
            current=self.plan(base,task,'current')
            self.assertEqual(current['observation_sha256'],expanded['observation_sha256'])
            template=json.loads((base/'current/build-template.json').read_text())
            packet=json.loads((task/'observation.json').read_text())
            last=packet['frames'][-1]['id']
            corrections=[]
            for index,row in enumerate(template['proposal']['rows']):
                selected=next(s for s in template['proposal']['observations'] if s['instance_id']==row['instance_id'] and s['frame_id']==last)
                for key,value in [('observation_id',selected['id']),('frame_id',last),('bbox',selected['bbox']),
                                  ('evidence_images',[i['id'] for i in packet['images'] if i.get('frame_id')==last and i['kind']=='native_detail'])]:
                    corrections.append(dict(path=['rows',index,key],value=value))
            template['corrections']=corrections
            template['model']=dict(id='controlled-fixture',version='unknown')
            template['review']=dict(identity_verified=True,coverage_verified=True,outside_rows_verified=True,
                presented_images=[i['id'] for i in packet['images']],visual_review=True,complete=True,
                evidence='Controlled fixture verifies stable five-line identities and clean later crops.',unresolved=[],
                rows=dict(complete=True,cursor='clear',occlusion='clear',boundary_verified=True,evidence='Controlled native source confirmation.'),
                observations=dict(complete=True,evidence='Controlled five-line correspondence confirmation.'),
                transitions=dict(evidence='Controlled stationary correspondence, unchanged source geometry.'))
            path=base/'confirmed.json';path.write_text(json.dumps(template))
            built=self.cli('--operation','build-decision','--task',task,'--decision',path,'--output',base/'built')
            self.assertTrue(built.get('ready_to_submit'),built)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            exported=self.cli('--operation','export','--task',task,'--output',base/'out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(exported['status'],'success',exported)
            self.assertEqual(replay['status'],'success',replay)
            self.assertTrue(all(r['selected_candidate']['frame_id']==last for r in exported['rows']))
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())

    def test_no_image_access_keeps_waiting_and_counts_only_actual_plan_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task=self.prepare(base,'full')
            state=self.cli('--operation','resume','--task',task)
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                         observation_version=state['observation_version'],image_access=False)
            first=self.plan(base,task,'one',request)
            second=self.plan(base,task,'two',request)
            self.assertEqual(first['status'],'waiting',first)
            self.assertEqual(first['image_access'],'unavailable')
            self.assertIn('image_access',[i['reason'] for i in first['issues']])
            self.assertEqual((base/'one/review-plan.json').read_bytes(),(base/'two/review-plan.json').read_bytes())
            report=self.cli('--operation','report','--task',task)
            events=[e for e in report['performance']['operations'] if e['operation']=='review-plan']
            self.assertEqual(len(events),2)
            self.assertEqual(len([e for e in report['performance']['stages'] if e['name']=='review_planning']),2)
            self.assertIsNone(report['performance']['actual_presented_images'])
            self.assertFalse((task/'decision.json').exists())
            stale=dict(request,observation_sha256='0'*64)
            failed=self.plan(base,task,'stale',stale)
            self.assertEqual(failed['status'],'failed',failed)

    def test_periodic_staff_reports_alternatives_even_when_maximum_overlap_is_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task=self.prepare(base,'full')
            result=self.plan(base,task)
            risks=[i for i in result['issues'] if i['reason']=='multiple_displacements']
            self.assertTrue(risks,result)
            alternatives=risks[0]['detail']
            self.assertEqual(sorted({len(p['matches']) for p in alternatives}),[2,3])
            self.assertTrue(result['required_review']['all_selected_native_details'])
            self.assertFalse(result['required_review']['automatic_acceptance'])

    def test_supplement_suggestions_respect_durable_budget_and_rebind_after_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task=self.prepare(base)
            first=self.plan(base,task)
            request=first['supplement_requests'][0]['request']
            self.assertLessEqual(request['issue']['end']-request['issue']['start'],30)
            self.assertLessEqual(len(request['timestamps']),8)
            path=base/'supplement.json';path.write_text(json.dumps(request))
            self.cli('--operation','supplement','--task',task,'--decision',path)
            state=self.cli('--operation','resume','--task',task)
            packet=json.loads((task/'observation.json').read_text())
            for index in range(7):
                state=json.loads((task/'task.json').read_text())
                request.update(observation_sha256=state['observation_sha256'],observation_version=state['observation_version'],
                               request_id=f'budget-{index}',issue=dict(reason='Controlled review budget',start=0,end=1),timestamps=[.08+index*.11])
                path.write_text(json.dumps(request))
                self.cli('--operation','supplement','--task',task,'--decision',path)
            plan=self.plan(base,task,'exhausted')
            self.assertEqual(plan['sampling_usage']['requests'],8,plan)
            self.assertEqual(plan['supplement_requests'],[])
            blocked=[i for i in plan['issues'] if i.get('supplement_blocked_by')=='sampling_budget']
            self.assertTrue(blocked,plan)
            self.assertFalse((task/'decision.json').exists())
            self.assertFalse((base/'exhausted/score.pdf').exists())

    def test_explicit_reuse_keeps_only_unchanged_accepted_judgments_after_roi_update(self):
        import test_agent_continuity
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            task,full=test_agent_continuity.ContinuityTests.prepare(self,base)
            # Existing controlled fixture carries full accepted native evidence.
            path=base/'accepted.json';path.write_text(json.dumps(full))
            accepted=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(accepted['phase'],'accepted',accepted)
            packet=json.loads((task/'observation.json').read_text())
            frame=packet['frames'][0]
            request=dict(schema_version=1,task_id=accepted['task_id'],observation_sha256=accepted['observation_sha256'],
                observation_version=accepted['observation_version'],source_sha256=packet['source']['sha256'],
                request_id='extra-detail',reason='Inspect one extra native area.',regions=[dict(frame_id=frame['id'],frame_sha256=frame['sha256'],
                    pts=frame['pts'],time_base=frame['time_base'],bbox=[75,180,1205,320])])
            path.write_text(json.dumps(request))
            updated=self.cli('--operation','materialize','--task',task,'--decision',path)
            revision=dict(schema_version=1,task_id=updated['task_id'],observation_sha256=updated['observation_sha256'],
                observation_version=updated['observation_version'],decision_id='reuse-1',revision_of='scroll',
                model=full['model'],prompt=full['prompt'],corrections=[],reuse_accepted_review=True,
                review=dict(identity_verified=True,coverage_verified=True,outside_rows_verified=True))
            path.write_text(json.dumps(revision))
            built=self.cli('--operation','build-decision','--task',task,'--decision',path,'--output',base/'reuse')
            self.assertTrue(built.get('ready_to_submit'),built)
            repeated=self.cli('--operation','build-decision','--task',task,'--decision',path,'--output',base/'reuse-again')
            self.assertTrue(repeated.get('ready_to_submit'),repeated)
            for name in ('decision.json','diff.json','sources.json','unresolved.json'):
                self.assertEqual((base/'reuse'/name).read_bytes(),(base/'reuse-again'/name).read_bytes())
            saved=json.loads((base/'reuse/decision.json').read_text())['decision']
            self.assertEqual(saved['rows'],full['rows'])
            self.assertEqual(saved['presented_images'],full['presented_images'])
            self.assertTrue(set(updated['materialized_images']).isdisjoint(saved['presented_images']))
            sources=json.loads((base/'reuse/sources.json').read_text())
            self.assertEqual(sources['reused_review']['decision_sha256'],accepted['decision_history'][-1]['sha256'])
            changed=copy.deepcopy(revision);changed['decision_id']='changed'
            changed['corrections']=[dict(path=['rows',0,'bbox'],value=[75,180,1205,320]),
                                   dict(path=['observations',0,'bbox'],value=[75,180,1205,320])]
            path.write_text(json.dumps(changed))
            waiting=self.cli('--operation','build-decision','--task',task,'--decision',path,'--output',base/'changed')
            self.assertEqual(waiting['status'],'waiting',waiting)
            draft=json.loads((base/'changed/decision.json').read_text())['decision']
            self.assertFalse(draft['rows'][0]['boundary_verified'])
            self.assertTrue(draft['rows'][1]['boundary_verified'])
            self.assertFalse(draft['complete'])
            self.assertEqual(len(self.cli('--operation','resume','--task',task)['decision_history']),1)
            accepted_reuse=self.cli('--operation','submit','--task',task,'--decision',base/'reuse/decision.json')
            self.assertEqual(accepted_reuse['phase'],'accepted',accepted_reuse)
            exported=self.cli('--operation','export','--task',task,'--output',base/'reuse-out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'reuse-replay')
            self.assertEqual(exported['status'],'success',exported)
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual((base/'reuse-out/score.pdf').read_bytes(),(base/'reuse-replay/score.pdf').read_bytes())
            self.assertEqual(len(accepted_reuse['decision_history']),2)
            state=self.cli('--operation','resume','--task',task)
            supplement=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                observation_version=state['observation_version'],request_id='new-frame',issue=dict(reason='Controlled new native observation.',start=0,end=.5),timestamps=[.25])
            path.write_text(json.dumps(supplement))
            updated=self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertEqual(updated['observation_version'],3,updated)
            revision.update(decision_id='reuse-after-new-frame',revision_of='reuse-1',
                            observation_sha256=updated['observation_sha256'],observation_version=updated['observation_version'])
            path.write_text(json.dumps(revision))
            refused=self.cli('--operation','build-decision','--task',task,'--decision',path,'--output',base/'new-frame-reuse')
            self.assertEqual(refused['status'],'failed',refused)
            self.assertFalse((base/'new-frame-reuse/decision.json').exists())

    def test_scale_change_and_missing_staff_route_to_native_evidence_without_identity_invention(self):
        from PIL import Image
        for layout in ('scale','blank'):
            with self.subTest(layout=layout),tempfile.TemporaryDirectory() as directory:
                base=Path(directory)
                for index in range(8):
                    image=score_frame()
                    if index>=4:
                        changed=Image.new('RGB',(1280,960),'white')
                        if layout=='scale':
                            changed.paste(image.resize((1152,864)),(0,0))
                        image=changed
                    image.save(base/f'{index:03d}.png')
                source=base/'input.mp4'
                subprocess.run(['ffmpeg','-v','error','-y','-framerate','4','-i',str(base/'%03d.png'),'-pix_fmt','yuv420p',str(source)],check=True)
                task=base/'task';self.cli(source,'--output',task,'--evidence-mode','lazy')
                plan=self.plan(base,task)
                self.assertEqual(plan['status'],'waiting',plan)
                reasons={i['reason'] for i in plan['issues']}
                self.assertIn('scale_or_layout_change' if layout=='scale' else 'missing_geometry',reasons)
                self.assertIn('insufficient_overlap',reasons)
                self.assertFalse(plan['suggestion']['visual_review'])
                if layout=='blank':
                    self.assertTrue(all(s['frame_id']=='frame-000' for s in plan['suggestion']['structure']['observations']))
                audit=json.loads((base/'plan/score-audit-template.json').read_text())
                self.assertTrue(all(c['status']=='pending' for c in audit['segments'][0]['checks'].values()))
                self.assertFalse(audit['segments'][0]['first_edge']['complete'])
                self.assertFalse((task/'decision.json').exists())
