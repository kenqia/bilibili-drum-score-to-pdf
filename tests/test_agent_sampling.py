"""Bounded supplemental evidence through the public CLI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from score_fixtures import CLI, score_frame, video_from_image


class SamplingTests(unittest.TestCase):
    def cli(self, *args):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)
        self.assertTrue(result.stdout, result.stderr)
        return json.loads(result.stdout)

    def test_supplement_retains_old_evidence_and_rejects_stale_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = video_from_image(score_frame(), base)
            task = base / 'task'
            state = self.cli(source, '--operation', 'prepare', '--output', task)
            old = (task / 'observation.json').read_bytes()
            old_contexts = {i['path']: (task / i['path']).read_bytes() for i in json.loads(old)['images'] if i['kind'] == 'batch_comparison'}
            request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                           observation_version=1, request_id='occlusion-1', issue=dict(reason='brief clean view needs checking', start=0, end=1), timestamps=[0.25])
            path = base / 'request.json'; path.write_text(json.dumps(request))
            result = self.cli('--operation', 'supplement', '--task', task, '--decision', path)
            self.assertEqual(result['status'], 'waiting', result)
            self.assertEqual(result['observation_version'], 2)
            self.assertEqual((task / 'observation-v1.json').read_bytes(), old)
            packet = json.loads((task / 'observation.json').read_text())
            self.assertGreater(len(packet['frames']), 3)
            self.assertTrue(all((task / name).read_bytes() == content for name, content in old_contexts.items()))
            self.assertFalse(set(old_contexts) & {i['path'] for i in packet['images'] if i['kind'] == 'batch_comparison'})
            self.assertEqual(packet['sampling']['used']['requests'], 1)
            rejected = self.cli('--operation', 'supplement', '--task', task, '--decision', path)
            self.assertEqual(rejected['error']['code'], 'invalid_request')

    def test_bounded_requests_reject_bad_times_and_empty_progress_without_changing_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = video_from_image(score_frame(), base); task = base / 'task'
            subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(base/'input.png'),'-t','2','-r','16','-pix_fmt','yuv420p',str(source)],check=True)
            state = self.cli(source, '--operation', 'prepare', '--output', task)
            original = (task / 'observation.json').read_bytes()
            request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                           observation_version=1, request_id='gap', issue=dict(reason='occluded', start=0, end=1), timestamps=[0.25])
            path = base / 'request.json'
            for times in ([0], [-1], [float('inf')], [True], [0.25, 0.25], [], [1.5]):
                bad = dict(request, timestamps=times); path.write_text(json.dumps(bad))
                result = self.cli('--operation', 'supplement', '--task', task, '--decision', path)
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual((task / 'observation.json').read_bytes(), original)
            for index in range(8):
                state = json.loads((task / 'task.json').read_text())
                request.update(observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                               request_id=f'gap-{index}', timestamps=[0.1 + index * 0.1])
                path.write_text(json.dumps(request))
                result = self.cli('--operation', 'supplement', '--task', task, '--decision', path)
                self.assertEqual(result['status'], 'waiting', result)
            state = json.loads((task / 'task.json').read_text())
            request.update(observation_sha256=state['observation_sha256'], observation_version=state['observation_version'], request_id='over-budget', timestamps=[0.95])
            path.write_text(json.dumps(request))
            result = self.cli('--operation', 'supplement', '--task', task, '--decision', path)
            self.assertEqual(result['error']['code'], 'sampling_budget', result)
            self.assertFalse((task / 'score.pdf').exists())

    def test_oversized_request_numbers_fail_without_exposing_values_or_changing_evidence(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = video_from_image(score_frame(), base); task = base / 'task'
            state = self.cli(source, '--operation', 'prepare', '--output', task)
            original = (task / 'observation.json').read_bytes()
            frame = (task / 'frame-000.png').read_bytes()
            request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                           observation_version=1, request_id='huge', issue=dict(reason='inspect gap', start=0, end=1), timestamps=[0.25])
            path = base / 'request.json'
            for field in ('start', 'end', 'timestamps'):
                with self.subTest(field=field):
                    bad = copy.deepcopy(request)
                    if field == 'timestamps':
                        bad[field] = [10**1000]
                    else:
                        bad['issue'][field] = 10**1000
                    path.write_text(json.dumps(bad))
                    process = subprocess.run([sys.executable, str(CLI), '--operation', 'supplement', '--task', str(task), '--decision', str(path)], capture_output=True, text=True)
                    self.assertTrue(process.stdout, 'CLI must return a failure JSON')
                    self.assertNotEqual(process.returncode, 0)
                    self.assertNotIn('Traceback', process.stderr)
                    self.assertNotIn(str(10**1000), process.stdout + process.stderr)
                    result = json.loads(process.stdout)
                    self.assertEqual(result['status'], 'failed', result)
                    self.assertEqual(result['error']['code'], 'invalid_request', result)
                    self.assertNotIn(str(10**1000), json.dumps(result))
                    self.assertEqual((task / 'observation.json').read_bytes(), original)
                    self.assertEqual((task / 'frame-000.png').read_bytes(), frame)

    def test_long_pause_and_change_navigation_produce_overlapping_native_context(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for index in range(24):
                image = score_frame()
                if index >= 12:
                    image = image.crop((0,20,1280,960)).resize((1280,960))
                if index in (9, 10):
                    ImageDraw.Draw(image).rectangle((400,100,550,850), fill='blue')
                image.save(base / f'{index:03d}.png')
            source = base / 'input.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-framerate','2','-i',str(base/'%03d.png'),'-pix_fmt','yuv420p',str(source)],check=True)
            task = base / 'task'; result = self.cli(source,'--operation','prepare','--output',task)
            self.assertEqual(result['status'],'waiting',result)
            packet = json.loads((task/'observation.json').read_text())
            self.assertGreater(len(packet['frames']),3)
            self.assertGreater(packet['metrics']['thumbnail_checks'],0)
            self.assertEqual(packet['frames'][0]['timestamp'],0)
            self.assertGreater(packet['frames'][-1]['timestamp'],11)
            self.assertEqual(packet['batches'][0]['frames'][-1],packet['batches'][1]['frames'][0])
            for batch in packet['batches']:
                picture = next(i for i in packet['images'] if i['id'] == batch['image_id'])
                self.assertEqual([p['frame_id'] for p in picture['panels']], batch['frames'])
                from PIL import Image
                with Image.open(task / picture['path']) as context:
                    self.assertLessEqual(context.height, 510)


    def test_local_supplement_can_choose_brief_clean_source_and_keeps_obscured_trial_waiting(self):
        from PIL import ImageDraw
        for all_dirty in (False, True):
            with self.subTest(all_dirty=all_dirty), tempfile.TemporaryDirectory() as directory:
                base=Path(directory)
                for index in range(8):
                    image=score_frame(row_count=1)
                    if all_dirty or index != 1:
                        ImageDraw.Draw(image).rectangle((400,170,580,350),fill='blue')
                    image.save(base/f'{index:03d}.png')
                source=base/'input.mp4'
                subprocess.run(['ffmpeg','-v','error','-y','-framerate','4','-i',str(base/'%03d.png'),'-pix_fmt','yuv420p',str(source)],check=True)
                task=base/'task';state=self.cli(source,'--operation','prepare','--output',task)
                request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],observation_version=1,
                             request_id='brief',issue=dict(reason='initial views obscured; inspect local interval',start=0,end=0.5),timestamps=[0.25])
                path=base/'request.json';path.write_text(json.dumps(request));state=self.cli('--operation','supplement','--task',task,'--decision',path)
                packet=json.loads((task/'observation.json').read_text());frame=next(f for f in packet['frames'] if f['id']=='v2-frame-000')
                row=dict(frame_id=frame['id'],coordinate_space='native_pixels',roi=[0,0,1280,960],bbox=[80,150,1200,360],
                         evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id')==frame['id'] and i['kind']=='native_detail'],
                         complete=True,cursor='clear',occlusion='present' if all_dirty else 'clear',boundary_verified=True,evidence='Native evidence reports clean or always obscured source.')
                decision=dict(schema_version=2,task_id=state['task_id'],observation_sha256=state['observation_sha256'],decision_id='brief-reviewed',
                              model=dict(id='fixture',version='unknown'),prompt=dict(version='brief-1',text='Compare original symbols around obstruction.'),
                              presented_images=[i['id'] for i in packet['images']],visual_review=True,complete=True,evidence='One fixed row.',rows=[row],unresolved=[])
                path=base/'decision.json';path.write_text(json.dumps(decision));result=self.cli('--operation','submit','--task',task,'--decision',path)
                if all_dirty:
                    self.assertEqual(result['status'],'waiting',result)
                    self.assertFalse((task/'decision.json').exists())
                else:
                    self.assertEqual(result['phase'],'accepted',result)
                    result=self.cli('--operation','export','--task',task,'--output',base/'out')
                    self.assertEqual(result['status'],'success',result)
                    self.assertEqual(result['rows'][0]['source_frame'],'v2-frame-000.png')
                    decision['observation_sha256']=request['observation_sha256'];path.write_text(json.dumps(decision))
                    result=self.cli('--operation','submit','--task',task,'--decision',path)
                    self.assertEqual(result['error']['code'],'invalid_decision',result)

    def test_different_request_time_that_decodes_existing_pts_cannot_claim_new_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);source=video_from_image(score_frame(),base);task=base/'task'
            state=self.cli(source,'--operation','prepare','--output',task)
            original=(task/'observation.json').read_bytes()
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],observation_version=1,
                         request_id='no-new-pts',issue=dict(reason='nearby interval',start=0.8,end=1.2),timestamps=[0.9])
            path=base/'request.json';path.write_text(json.dumps(request))
            result=self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertEqual(result['error']['code'],'invalid_request',result)
            self.assertEqual((task/'observation.json').read_bytes(),original)

    def test_modified_ledger_cannot_reset_resource_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);source=video_from_image(score_frame(),base);task=base/'task'
            state=self.cli(source,'--operation','prepare','--output',task)
            packet=json.loads((task/'observation.json').read_text());ledger=packet['sampling']
            ledger['used']['requests']=-100
            (task/'sampling.json').write_text(json.dumps(ledger))
            request=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],observation_version=1,
                         request_id='bad-ledger',issue=dict(reason='inspect gap',start=0,end=0.5),timestamps=[0.25])
            path=base/'request.json';path.write_text(json.dumps(request))
            result=self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertEqual(result['error']['code'],'invalid_request',result)
