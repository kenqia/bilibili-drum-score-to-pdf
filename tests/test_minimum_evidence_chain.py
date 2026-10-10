import json
from pathlib import Path
import tempfile
import test_agent_content as content_fixture


class MinimumEvidenceChainTests(content_fixture.ContentChecksTests):
    minimum_chain = True

    def test_new_lazy_flag_is_persisted_and_full_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,_=self.prepare_score(base)
            self.assertEqual(json.loads((task/'observation.json').read_text())['minimum_evidence_chain_policy'],'ordered_anchors_v1')
            state=self.cli(base/'input.mp4','--output',base/'full','--minimum-evidence-chain')
            self.assertEqual(state['status'],'failed',state)

    def test_two_clean_ordered_anchors_cover_redundant_cursor_pair_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            checks=draft['sources']['content_checks']
            self.assertTrue(any(c['status']=='uncertain' and c.get('blocking') is False for c in checks))
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            out=self.cli('--operation','export','--task',task,'--output',base/'out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(out['status'],'success',out)
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())

    def test_clean_bridge_keeps_every_intermediate_frame_and_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='bridge_cursor')
            request,packet=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            bridges=[c for c in draft['sources']['content_checks'] if c['scope']=='geometry_established_bridge' and c['status']=='not_contradicted']
            self.assertEqual({tuple(c['matches']) for c in bridges},{('0-B','2-B'),('0-C','2-C')})
            self.assertTrue(all(c['covered_frames']==[f['id'] for f in packet['frames']] for c in bridges))
            missing=json.loads(json.dumps(decision))
            missing['segments'][0]['observations']=[s for s in missing['segments'][0]['observations'] if s['id']!='1-C']
            request,_=self.reviewed_request(task,missing)
            rejected=self.build(base,task,request,'missing')
            self.assertFalse(rejected.get('ready_to_submit',False),rejected)

    def reviewed_request(self,task,decision):
        request,packet=super().reviewed_request(task,decision)
        if packet.get('minimum_evidence_chain_policy'):
            records=[]
            for s in decision['segments'][0]['observations']:
                f=next(f for f in packet['frames'] if f['id']==s['frame_id'])
                bbox=[0,s['bbox'][1],f['width'],s['bbox'][3]]
                from PIL import Image
                with Image.open(task/f['path']) as image:
                    # Fixture truth: the only colored pixels are the deliberately drawn cursor.
                    import numpy as np
                    pixels=np.asarray(image.crop(bbox)).astype(int)
                    cursor=bool(((pixels.max(axis=2)-pixels.min(axis=2))>70).any())
                records.append(dict(frame_id=f['id'],frame_sha256=f['sha256'],pts=f['pts'],time_base=f['time_base'],bbox=bbox,
                    evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id')==f['id'] and i['kind']=='native_detail'],
                    cursor='present' if cursor else 'clear',occlusion='clear',evidence='Controlled fixture native row reviewed; deliberate colored cursor only.'))
            request['review']['native_clean_regions']=records
        return request,packet

    def test_missing_native_authority_and_tampered_sidecar_stay_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            good=self.build(base,task,request,'good')
            self.assertTrue(good['ready_to_submit'],good)
            record=json.loads((base/'good/continuity.json').read_text())
            record['source_sha256']='0'*64
            (base/'good/continuity.json').write_text(json.dumps(record))
            rejected=self.cli('--operation','submit','--task',task,'--decision',base/'good/decision.json')
            self.assertNotEqual(rejected.get('phase'),'accepted',rejected)
            request['review']['native_clean_regions']=[]
            missing=self.build(base,task,request,'missing')
            self.assertFalse(missing['ready_to_submit'],missing)

    def test_bound_summary_has_no_redundant_supplements_and_raw_records_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            path=base/'review.json';path.write_text(json.dumps(request))
            result=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            self.assertFalse(result['summary']['critical_gaps'],result)
            self.assertEqual(result['supplement_requests'],[])
            self.assertTrue(result['summary']['existing_alternatives'])
            self.assertNotIn('issues',result)
            self.assertTrue(json.loads((base/'plan/review-plan.json').read_text())['issues'])

    def test_third_row_conflict_vetoes_two_other_trustworthy_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='third_conflict')
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            conflicts=[c for c in result['sources']['content_checks'] if c['status']=='conflict']
            self.assertTrue(any(c['matches']==['1-D','2-D'] for c in conflicts),conflicts)

    def test_only_missing_intervals_generate_one_deduplicated_local_request(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='cursor')
            request,_=self.reviewed_request(task,decision)
            path=base/'review.json';path.write_text(json.dumps(request))
            result=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            self.assertEqual(len(result['summary']['critical_gaps']),2,result)
            self.assertEqual(len(result['supplement_requests']),1,result)
            times=result['supplement_requests'][0]['request']['timestamps']
            self.assertEqual(len(times),2)
            self.assertEqual(len(set(times)),2)

    def test_unknown_occlusion_and_unreviewed_gap_do_not_borrow_anchor_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            for r in request['review']['native_clean_regions']:
                if r['cursor']=='present':
                    r['occlusion']='uncertain'
            rejected=self.build(base,task,request,'unknown')
            self.assertFalse(rejected['ready_to_submit'],rejected)
            request,_=self.reviewed_request(task,decision)
            request['review']['score_audit']['intervals'][1]['status']='pending'
            rejected=self.build(base,task,request,'unreviewed')
            self.assertFalse(rejected['ready_to_submit'],rejected)

    def test_bridge_checks_third_common_instance_before_selecting_two_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_bridge_conflict')
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            checks=result['sources']['content_checks']
            self.assertTrue(any(c['matches']==['0-C','2-C'] and c['scope']=='geometry_established_bridge' and c['status']=='conflict' for c in checks),checks)

    def test_two_single_anchors_on_different_edges_do_not_form_one_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='single_bridge_cursor')
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            intervals={(c['from_frame'],c['to_frame']):c['evidence_chain'] for c in result['sources']['content_checks'] if 'evidence_chain' in c}
            self.assertEqual(len(intervals),2)
            self.assertTrue(all(not interval['sufficient'] for interval in intervals.values()),intervals)

    def test_large_plan_stdout_is_short_and_retains_raw_diagnostics(self):
        import test_agent_review
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            ordinary=self.cli
            def prepare_chain(*args):
                return ordinary(*args,*(['--minimum-evidence-chain'] if '--script-acceptance' in args else []))
            self.cli=prepare_chain
            task=test_agent_review.ReviewTests.large_task(self,base,5)
            result=self.cli('--operation','review-plan','--task',task,'--output',base/'plan')
            self.assertNotIn('issues',result)
            self.assertLess(len(json.dumps(result).encode()),16000)
            raw=json.loads((base/'plan/review-plan.json').read_text())
            self.assertGreater(len(raw['issues']),250)
            self.assertEqual(raw['supplement_requests'],[])
            self.assertEqual(result['summary']['critical_gaps'],[])
            self.assertFalse(result['summary']['bound_geometry_checked'])

    def test_supplement_preserves_opt_in_and_rejects_old_decision_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,packet=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            supplemental=dict(schema_version=1,task_id=accepted['task_id'],observation_sha256=accepted['observation_sha256'],
                observation_version=accepted['observation_version'],request_id='new-native-gap',
                issue=dict(reason='required_content_witness',start=0,end=.8),timestamps=[.25])
            path=base/'supplement.json';path.write_text(json.dumps(supplemental))
            changed=self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertNotEqual(changed.get('observation_sha256'),accepted['observation_sha256'],changed)
            self.assertEqual(changed['minimum_evidence_chain_policy'],'ordered_anchors_v1')
            rejected=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertNotEqual(rejected.get('phase'),'accepted',rejected)
            exported=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertNotEqual(exported['status'],'success',exported)
