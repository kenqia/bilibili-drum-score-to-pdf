"""Persisted batches through the approved unified CLI seam."""
import copy
import json
from pathlib import Path
import tempfile
import test_agent_continuity


class ResumeTests(test_agent_continuity.ContinuityTests):
    test_missing_identity_and_geometry_conflicts_remain_waiting = None
    test_scroll_and_pause_preserve_distinct_repeated_spatial_rows = None
    test_partial_observation_can_only_select_its_later_complete_source = None
    def test_prefix_resume_idempotency_revision_and_independent_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); task, full=self.prepare(base)
            prefix=copy.deepcopy(full)
            prefix['decision_id']='prefix'
            prefix['observations']=prefix['observations'][:6]
            prefix['transitions']=prefix['transitions'][:1]
            prefix['coverage']['last_frame']='frame-001'
            packet=json.loads((task/'observation.json').read_text())
            prefix['presented_images']=[i['id'] for i in packet['images']
                if i.get('frame_id')!='frame-002'
                and not any(p['frame_id']=='frame-002' for p in i.get('panels', []))
                or i['kind']=='comparison']
            batch=dict(schema_version=5,decision_id='batch-one',reviewed_frames=['frame-000','frame-001'],revision_of=None,decision=prefix)
            path=base/'batch.json';path.write_text(json.dumps(batch))
            result=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(result['phase'],'batch_accepted',result)
            resumed=self.cli('--operation','resume','--task',task)
            self.assertEqual(resumed['reviewed_frames'],batch['reviewed_frames'])
            self.assertFalse(resumed['complete'])
            original=(task/'task.json').read_bytes()
            retry=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual({k:v for k,v in retry.items() if k != 'performance'},
                             {k:v for k,v in resumed.items() if k != 'performance'})
            self.assertEqual(retry['performance']['script_operation_count'], resumed['performance']['script_operation_count']+1)
            self.assertEqual((task/'task.json').read_bytes(),original)
            result=self.cli('--operation','export','--task',task,'--output',base/'partial')
            self.assertEqual(result['status'],'waiting',result)
            self.assertFalse((base/'partial/score.pdf').exists())
            changed=copy.deepcopy(batch);changed['decision']['evidence']='Changed review.';path.write_text(json.dumps(changed))
            result=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(result['error']['code'],'existing_decision',result)
            changed['decision_id']='revision-one';changed['revision_of']='batch-one';path.write_text(json.dumps(changed))
            result=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(len(result['decision_history']),2,result)
            final=dict(schema_version=5,decision_id='batch-final',reviewed_frames=[f['id'] for f in packet['frames']],revision_of=None,decision=full)
            path.write_text(json.dumps(final))
            result=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(result['phase'],'accepted',result)
            result=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertEqual(result['status'],'success',result)
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual(len(replay['rows']),4)
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())
            history=result['decision_history']
            (task/history[0]['path']).write_text('{}')
            result=self.cli('--operation','resume','--task',task)
            self.assertEqual(result['error']['code'],'source_mismatch',result)

    def test_failed_supplement_preserves_charged_budget_and_requires_new_review(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare(base)
            path=base/'decision.json';path.write_text(json.dumps(decision))
            self.cli('--operation','submit','--task',task,'--decision',path)
            state=self.cli('--operation','resume','--task',task)
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],observation_version=1,
                         request_id='same-pts',issue=dict(reason='Check uncertain interval',start=0.8,end=1.2),timestamps=[0.9])
            path.write_text(json.dumps(request))
            result=self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertEqual(result['error']['code'],'invalid_request',result)
            resumed=self.cli('--operation','resume','--task',task)
            self.assertEqual(resumed['sampling_usage']['requests'],1,resumed)
            self.assertGreaterEqual(resumed['sampling_usage']['decode_seconds'],60)
            self.assertEqual(len(resumed['decision_history']),1)
            result=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertEqual(result['status'],'waiting',result)
            request['request_id']='next';request['timestamps']=[0.25];request['issue']=dict(reason='clean view',start=0,end=0.5)
            path.write_text(json.dumps(request))
            self.cli('--operation','supplement','--task',task,'--decision',path)
            path.write_text(json.dumps(decision))
            result=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(result['error']['code'],'invalid_decision',result)

    def test_resume_finishes_interrupted_publication_and_rejects_unknown_task(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,_=self.prepare(base)
            original=(task/'task.json').read_bytes()
            journal={}
            for stem,key in [('observation','observation_sha256'),('sampling','sampling_sha256'),('task','state_sha256')]:
                data=(task/f'{stem}.json').read_bytes()
                (task/f'{stem}.next.json').write_bytes(data)
                journal[key]=hashlib.sha256(data).hexdigest()
            (task/'publication.json').write_text(json.dumps(journal))
            (task/'observation.json').write_text('{}')
            result=self.cli('--operation','resume','--task',task)
            self.assertEqual(result['phase'],'review',result)
            self.assertFalse((task/'publication.json').exists())
            self.assertEqual((task/'task.json').read_bytes(),original)
            state=json.loads(original);state['schema_version']=99
            (task/'task.json').write_text(json.dumps(state))
            result=self.cli('--operation','resume','--task',task)
            self.assertEqual(result['error']['code'],'invalid_task',result)

    def test_sigterm_preserves_prepare_sampling_and_export_evidence(self):
        import subprocess
        import sys
        import time
        from score_fixtures import CLI
        def interrupt_when(args, ready):
            process=subprocess.Popen([sys.executable,str(CLI),*map(str,args)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+30
            while process.poll() is None and time.monotonic()<deadline:
                if ready():
                    process.terminate()
                    break
                time.sleep(0.002)
            stdout,stderr=process.communicate(timeout=30)
            self.assertTrue(stdout,stderr)
            result=json.loads(stdout)
            self.assertEqual(result['error']['code'],'interrupted',result)
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare(base)
            interrupted=base/'interrupted-prepare'
            interrupt_when([base/'input.mp4','--operation','prepare','--output',interrupted],lambda:(interrupted/'frame-000.png').exists())
            self.assertTrue((interrupted/'frame-000.png').exists())
            preserved=(interrupted/'frame-000.png').read_bytes()
            result=self.cli(base/'input.mp4','--operation','prepare','--output',interrupted)
            self.assertEqual(result['error']['code'],'existing_output',result)
            self.assertEqual((interrupted/'frame-000.png').read_bytes(),preserved)
            path=base/'decision.json';path.write_text(json.dumps(decision))
            self.cli('--operation','submit','--task',task,'--decision',path)
            state=self.cli('--operation','resume','--task',task)
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],observation_version=1,
                         request_id='interrupted',issue=dict(reason='need clean source',start=0,end=0.5),timestamps=[0.25])
            path.write_text(json.dumps(request))
            def reserved():
                try:return json.loads((task/'task.json').read_text())['phase']=='supplement_pending'
                except (ValueError,OSError):return False
            interrupt_when(['--operation','supplement','--task',task,'--decision',path],reserved)
            resumed=self.cli('--operation','resume','--task',task)
            self.assertEqual(resumed['sampling_usage']['requests'],1,resumed)
            self.assertEqual(len(resumed['decision_history']),1)
            revised=dict(schema_version=5,decision_id='after-interrupt',reviewed_frames=['frame-000','frame-001','frame-002'],revision_of='scroll',decision=decision)
            path.write_text(json.dumps(revised))
            result=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(result['phase'],'accepted',result)
            output=base/'interrupted-export'
            interrupt_when(['--operation','export','--task',task,'--output',output],lambda:(output/'frame-000.png').exists())
            result=self.cli('--operation','export','--task',task,'--output',output)
            self.assertEqual(result['error']['code'],'existing_output',result)
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(replay['status'],'success',replay)
