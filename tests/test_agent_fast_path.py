"""Explicit mixed authority through the unified CLI and saved artifacts."""
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
import copy
import test_agent_audit
from PIL import Image, ImageDraw
import test_agent_evidence
from score_fixtures import score_frame, video_from_image


class FastPathTests(unittest.TestCase):
    cli = test_agent_evidence.LazyEvidenceTests.cli

    def test_opt_in_is_only_for_new_lazy_tasks_and_survives_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            invalid = self.cli(video, '--output', base/'full', '--script-acceptance')
            self.assertEqual(invalid['status'], 'failed')
            self.assertEqual(invalid['error']['code'], 'invalid_input')
            legacy=self.cli(video,'--operation','convert','--output',base/'legacy','--script-acceptance')
            self.assertEqual(legacy['error']['code'],'invalid_input',legacy)
            self.assertFalse((base/'legacy').exists())
            state = self.cli(video, '--output', base/'lazy', '--evidence-mode','lazy','--script-acceptance')
            self.assertEqual(state['status'], 'waiting', state)
            packet = json.loads((base/'lazy/observation.json').read_text())
            self.assertEqual(packet['script_acceptance_policy'],'continuous_clean_v1')
            self.assertEqual(self.cli('--operation','resume','--task',base/'lazy')['script_acceptance_policy'],'continuous_clean_v1')
            rejected = self.cli('--operation','resume','--task',base/'lazy','--script-acceptance')
            self.assertEqual(rejected['status'],'failed',rejected)
            self.assertEqual(rejected['error']['code'],'invalid_input')

    native_sources = test_agent_audit.AuditTests.native_sources
    build = test_agent_audit.AuditTests.build

    def mixed(self, base, clean=True, mutate=None, equal_spacing=False):
        old=score_frame(); image=old.copy()
        ImageDraw.Draw(image).rectangle((70,160,1210,910),fill='white')
        shifts=[0,0,0] if equal_spacing else [0,5,40]
        for upper,lower,shift in [(160,380,shifts[0]),(380,600,shifts[1]),(600,850,shifts[2])]:
            image.paste(old.crop((70,upper,1211,lower)),(70,upper+shift))
        if mutate:
            mutate(image)
        image.save(base/'source.png')
        video=base/'input.mkv'
        subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(base/'source.png'),'-t','2','-r','4','-c:v','ffv1',str(video)],check=True)
        task=base/'task'
        state=self.cli(video,'--output',task,'--evidence-mode','lazy','--script-acceptance')
        packet=json.loads((task/'observation.json').read_text())
        state,packet=self.native_sources(base,task,state,packet)
        request=test_agent_audit.AuditTests.reviewed_request(self,state,packet)
        segment=request['proposal']['segments'][0]
        for s in segment['observations']:
            number=int(s['id'].rsplit('-',1)[1]); shift=shifts[number]
            s['staff_y']+=shift;s['bbox'][1]+=shift;s['bbox'][3]+=shift
        # Leave only middle rows/observations and ordinary gaps to script authority.
        request['review']['confirmations']=[c for c in request['review']['confirmations'] if not
            (len(c['path'])>=4 and c['path'][:2]==['segments',0] and
             ((c['path'][2]=='rows' and c['path'][3]==1) or
              (c['path'][2]=='observations' and c['path'][3]%3==1) or c['path'][2]=='transitions'))]
        request['review'].update(visual_review=False,identity_verified=False,coverage_verified=False)
        request['review']['score_audit']['segments'][0]['checks']['outside_rows']['regions'][0]['bbox']=segment['rows'][0]['bbox']
        for interval in request['review']['score_audit']['intervals']:
            interval.update(status='pending',regions=[])
        if clean:
            refs={f['id']:next(i['id'] for i in packet['images'] if i['kind']=='native_detail' and i['frame_id']==f['id']) for f in packet['frames']}
            request['review']['native_clean_regions']=[dict(frame_id=f['id'],frame_sha256=f['sha256'],pts=f['pts'],time_base=f['time_base'],bbox=[0,0,f['width'],f['height']],evidence_images=[refs[f['id']]],cursor='clear',occlusion='clear',evidence='Actually reviewed the complete controlled native ROI for obstructions.') for f in packet['frames']]
        return task,state,packet,request

    def test_mixed_authority_keeps_visual_review_false_and_replays_native_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,request=self.mixed(base)
            built=self.build(base,task,request)
            self.assertTrue(built.get('ready_to_submit'),built)
            saved_sources=json.loads((base/'built/sources.json').read_text())
            self.assertEqual(saved_sources,built['sources'])
            decision=json.loads((base/'built/decision.json').read_text())
            self.assertFalse(decision['visual_review'])
            self.assertEqual(decision['segments'][0]['rows'][1]['evidence_images'],[])
            acceptance=json.loads((base/'built/acceptance.json').read_text())
            self.assertTrue(acceptance['items'])
            self.assertEqual(acceptance['native_clean_regions'],request['review']['native_clean_regions'])
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            self.assertIn('acceptance_sha256',accepted['decision_history'][-1])
            results=[]
            for operation in ('export','replay'):
                result=self.cli('--operation',operation,'--task',task,'--output',base/operation)
                self.assertEqual(result['status'],'success',result)
                self.assertEqual(len(result['rows']),3)
                middle=result['rows'][1]['selected_candidate']
                self.assertIn('script_acceptance',middle)
                self.assertNotIn('visual_judgment',middle)
                with Image.open(base/operation/result['rows'][1]['original_image']) as crop, Image.open(task/packet['frames'][0]['path']) as source:
                    self.assertEqual(crop.tobytes(),source.crop(middle['bbox']).tobytes())
                results.append(result)
            self.assertEqual((base/'export/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())
            self.assertIsNone(results[0]['metrics']['model_tokens'])

    def test_exact_decision_bytes_and_acceptance_history_are_checked_on_repeat_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,request=self.mixed(base)
            built=self.build(base,task,request)
            self.assertTrue(built.get('ready_to_submit'),built)
            decision=base/'built/decision.json'
            accepted=self.cli('--operation','submit','--task',task,'--decision',decision)
            self.assertEqual(accepted['phase'],'accepted',accepted)
            decision.write_bytes(decision.read_bytes()+b' ')
            duplicate=self.cli('--operation','submit','--task',task,'--decision',decision)
            self.assertEqual(duplicate['status'],'failed',duplicate)
            self.assertEqual(duplicate['error']['code'],'invalid_decision')

    def test_full_frame_and_roi_recheck_costs_are_separate_and_failed_attempts_survive(self):
        from unittest.mock import patch
        from test_agent_performance import PerformanceTests
        import test_link_input
        from video_seek import ConversionError
        import score_detect
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,request=self.mixed(base)
            built=self.build(base,task,request)
            self.assertTrue(built.get('ready_to_submit'),built)
            report=built['performance']
            self.assertEqual(report['full_frame_analysis_attempts'],6)
            self.assertEqual(report['native_staff_recheck_attempts'],3)
            actual_staff_groups=score_detect.staff_groups
            calls=0
            def fail_recheck(image):
                nonlocal calls
                calls+=1
                if calls%2==0:
                    raise ConversionError('review_required','Controlled ROI recheck failure.')
                return actual_staff_groups(image)
            request_path=base/'build-request.json'
            with patch('score_detect.staff_groups',side_effect=fail_recheck):
                failed=PerformanceTests().controlled_cli('--operation','build-decision','--task',task,
                    '--decision',request_path,'--output',base/'failed-recheck')
            self.assertFalse(failed.get('ready_to_submit'),failed)
            report=self.cli('--operation','report','--task',task)['performance']
            self.assertEqual(report['full_frame_analysis_attempts'],9)
            self.assertEqual(report['native_staff_recheck_attempts'],6)
            stages=[e for e in report['stages'] if e['name']=='native_staff_recheck']
            self.assertEqual(sum(e['status']=='failed' for e in stages),3)
            self.assertTrue(all(e['elapsed_seconds'] is not None for e in stages))
            resumed=self.cli('--operation','resume','--task',task)['performance']
            self.assertEqual(resumed['native_staff_recheck_attempts'],6)

    def test_gap_clean_windows_cannot_replace_endpoint_ownership_review(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,request=self.mixed(base)
            original=test_agent_audit.AuditTests.reviewed_request(self,state,packet)
            request['review']['confirmations'] += [c for c in original['review']['confirmations']
                if len(c['path'])>=4 and c['path'][2] in ('rows','observations')
                and c not in request['review']['confirmations']]
            refs={r['frame_id']:r['evidence_images'] for r in request['review']['native_clean_regions']}
            request['review']['native_clean_regions']=[dict(frame_id=f['id'],frame_sha256=f['sha256'],
                pts=f['pts'],time_base=f['time_base'],bbox=[0,round(s['staff_y'])-round(4*s['spacing']),
                    f['width'],round(s['staff_y'])+round(8*s['spacing'])],evidence_images=refs[f['id']],
                cursor='clear',occlusion='clear',evidence='Reviewed only the required pair window.')
                for f in packet['frames'] for s in request['proposal']['segments'][0]['observations']
                if s['frame_id']==f['id']]
            built=self.build(base,task,request)
            self.assertFalse(built.get('ready_to_submit'),built)
            transitions=[i for i in built['sources']['script_acceptance_items'] if i['kind']=='transitions']
            self.assertEqual(len(transitions),2)
            self.assertTrue(all('clean_candidate' in i['unresolved'] for i in transitions))
            submitted=self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertNotEqual(submitted.get('phase'),'accepted',submitted)
            for operation in ('export','replay'):
                result=self.cli('--operation',operation,'--task',task,'--output',base/operation)
                self.assertNotEqual(result['status'],'success',result)
                self.assertFalse((base/operation/'score.pdf').exists())

    def test_unresolved_clean_gap_boundary_geometry_and_outside_never_publish_success(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,good=self.mixed(base)
            mutations=[
                lambda r:r['review'].pop('native_clean_regions'),
                lambda r:r['review']['native_clean_regions'][0].update(bbox=[80,405,1200,575]),
                lambda r:r['review']['native_clean_regions'][1].update(occlusion='uncertain'),
                lambda r:r['review']['native_clean_regions'][0].update(pts=99),
                lambda r:r['review'].update(presented_images=['comparison']),
                lambda r:r['proposal']['segments'][0]['observations'][1].update(staff_y=450),
                lambda r:r['proposal']['segments'][0]['observations'].pop(),
                lambda r:r['proposal']['segments'][0]['transitions'][0].update(matches=r['proposal']['segments'][0]['transitions'][0]['matches'][:2]),
                lambda r:r['review']['score_audit']['segments'][0]['last_edge'].update(complete=False),
                lambda r:r['review']['score_audit']['segments'][0]['checks']['title'].update(status='pending',regions=[],print_regions=[]),
            ]
            for index,mutate in enumerate(mutations):
                with self.subTest(index=index):
                    request=copy.deepcopy(good);mutate(request)
                    built=self.build(base,task,request,f'bad-{index}')
                    self.assertFalse(built.get('ready_to_submit',False),built)
                    self.assertNotEqual(built['status'],'success',built)
                    if (base/f'bad-{index}/decision.json').exists():
                        submitted=self.cli('--operation','submit','--task',task,'--decision',base/f'bad-{index}/decision.json')
                        self.assertNotEqual(submitted.get('phase'),'accepted',submitted)
            self.assertFalse((task/'decision.json').exists())
            for operation in ('export','replay'):
                result=self.cli('--operation',operation,'--task',task,'--output',base/operation)
                self.assertNotEqual(result['status'],'success',result)
                self.assertFalse((base/operation/'score.pdf').exists())

    def test_acceptance_claim_tampering_and_history_corruption_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,request=self.mixed(base)
            self.assertTrue(self.build(base,task,request).get('ready_to_submit'))
            path=base/'built/acceptance.json';original=path.read_bytes()
            record=json.loads(original)
            record['items'][0]['checks']['full_row_edges']='fail'
            path.write_text(json.dumps(record))
            rejected=self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(rejected['status'],'failed',rejected)
            path.write_bytes(original)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            saved=task/accepted['decision_history'][-1]['acceptance_path']
            saved.write_bytes(saved.read_bytes()+b' ')
            for operation in ('resume','export','replay','report'):
                result=self.cli('--operation',operation,'--task',task,'--output',base/operation)
                self.assertEqual(result['status'],'failed',result)
                self.assertEqual(result['error']['code'],'source_mismatch')
                self.assertFalse((base/operation/'score.pdf').exists())

    def test_explicit_history_reuse_recomputes_script_authority_after_materialization(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,review=self.mixed(base)
            self.assertTrue(self.build(base,task,review).get('ready_to_submit'))
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            old_entry=accepted['decision_history'][-1]
            materialize=test_agent_evidence.LazyEvidenceTests.request(self,accepted,packet,[[80,405,1200,575]])
            path=base/'extra-native.json';path.write_text(json.dumps(materialize))
            state=self.cli('--operation','materialize','--task',task,'--decision',path)
            packet=json.loads((task/'observation.json').read_text())
            stale=self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json')
            self.assertEqual(stale['status'],'failed',stale)
            revision={k:copy.deepcopy(review[k]) for k in ('schema_version','model','prompt','corrections')}
            revision.update(task_id=state['task_id'],observation_sha256=state['observation_sha256'],observation_version=state['observation_version'],
                decision_id='recomputed',revision_of=old_entry['decision_id'],reuse_accepted_review=True,
                review=dict(identity_verified=False,coverage_verified=False,outside_rows_verified=True,score_audit=review['review']['score_audit']))
            built=self.build(base,task,revision,'revision')
            self.assertTrue(built.get('ready_to_submit'),built)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'revision/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            self.assertEqual(len(accepted['decision_history']),2)
            new_entry=accepted['decision_history'][-1]
            self.assertNotEqual(new_entry['acceptance_sha256'],old_entry['acceptance_sha256'])
            for operation in ('export','replay'):
                result=self.cli('--operation',operation,'--task',task,'--output',base/operation)
                self.assertEqual(result['status'],'success',result)
            self.assertEqual((base/'export/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())


    def test_lower_overlap_displacements_disconnected_ink_and_unknown_occlusion_wait(self):
        variants=[
            dict(equal_spacing=True),
            dict(mutate=lambda im:ImageDraw.Draw(im).rectangle((400,580,402,582),fill='black')),
            dict(mutate=lambda im:ImageDraw.Draw(im).rectangle((74,548,76,550),fill='black')),
            dict(clean=False,mutate=lambda im:ImageDraw.Draw(im).rectangle((700,448,702,450),fill='#888888')),
            dict(clean=False,mutate=lambda im:ImageDraw.Draw(im).rectangle((400,445,415,448),fill='white')),
        ]
        for index,kwargs in enumerate(variants):
            with self.subTest(index=index),tempfile.TemporaryDirectory() as directory:
                base=Path(directory);task,state,packet,request=self.mixed(base,**kwargs)
                result=self.build(base,task,request)
                self.assertFalse(result.get('ready_to_submit'),result)
                if index==0:
                    self.assertTrue(any(len(t['plausible_translations'])>1 for t in result['sources']['geometry']))
                self.assertNotEqual(self.cli('--operation','submit','--task',task,'--decision',base/'built/decision.json').get('phase'),'accepted')
                self.assertFalse((task/'decision.json').exists())

    def test_script_refinement_shrink_and_single_frame_prefix_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,state,packet,good=self.mixed(base)
            request=copy.deepcopy(good)
            row=request['proposal']['segments'][0]['rows'][1]
            row['refinement']=dict(bbox=[80,413,1200,575],reason='Shrink upper margin.',boundary_verified=True)
            request['review']['confirmations'].append(dict(path=['segments',0,'rows',1,'refinement','boundary_verified'],value=True))
            self.assertFalse(self.build(base,task,request,'shrink').get('ready_to_submit'))
            prefix=copy.deepcopy(good);frame=packet['frames'][0]['id'];part=prefix['proposal']['segments'][0]
            prefix['reviewed_frames']=[frame]
            part['frames']=[frame];part['observations']=part['observations'][:3];part['transitions']=[]
            prefix['proposal']['coverage']['last_frame']=frame
            prefix['review']['native_clean_regions']=prefix['review']['native_clean_regions'][:1]
            prefix['review']['presented_images']=[i['id'] for i in packet['images'] if i.get('frame_id')==frame or i['kind']=='comparison']
            prefix['review']['score_audit']['intervals']=[]
            prefix['review']['score_audit']['segments'][0]['last_edge']=copy.deepcopy(prefix['review']['score_audit']['segments'][0]['first_edge'])
            prefix['review']['confirmations']=[c for c in prefix['review']['confirmations'] if not (len(c['path'])>=4 and c['path'][2]=='observations' and c['path'][3]>=3)]
            self.assertFalse(self.build(base,task,prefix,'prefix').get('ready_to_submit'))
