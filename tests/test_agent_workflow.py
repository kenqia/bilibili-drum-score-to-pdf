"""Agent decisions exercised through the unified CLI and native output artifacts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image
from score_fixtures import CLI, score_frame, video_from_image


class AgentWorkflowTests(unittest.TestCase):
    def cli(self, *args):
        p = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)
        self.assertTrue(p.stdout, p.stderr)
        return p.returncode, json.loads(p.stdout)

    def test_default_prepares_for_agent_and_resume_preserves_unreviewed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            _, prepared = self.cli(video, '--output', task)
            self.assertEqual(prepared['status'], 'waiting')
            self.assertEqual(prepared['phase'], 'review')
            packet = (task / 'observation.json').read_bytes()
            self.assertFalse(json.loads(packet).get('fixed_layout_only', False))
            _, resumed = self.cli('--operation', 'resume', '--task', task)
            self.assertEqual(resumed['status'], 'waiting')
            self.assertEqual(packet, (task / 'observation.json').read_bytes())
            self.assertFalse((task / 'score.pdf').exists())

    def test_fixed_local_score_decision_exports_and_replays_native_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            _, prepared = self.cli(video, '--operation', 'prepare', '--output', task)
            self.assertEqual(prepared['status'], 'waiting')
            observation = json.loads((task / 'observation.json').read_text())
            self.assertFalse(observation['fixed_layout_only'])
            self.assertEqual(len(observation['frames']), 3)
            self.assertIn('pts', observation['frames'][0])
            self.assertIn('time_base', observation['frames'][0])
            decision = {'schema_version': 1, 'task_id': prepared['task_id'],
                        'observation_sha256': prepared['observation_sha256'], 'decision_id': 'review-1',
                        'model': {'id': 'unknown', 'version': 'unknown'},
                        'prompt': {'version': 'test-1', 'text': 'Review native images and select complete rows.'},
                        'presented_images': [i['id'] for i in observation['images']],
                        'visual_review': True, 'complete': True, 'evidence': 'All three rows and header visible, unchanged at endpoints.',
                        'selected_candidates': [c['id'] for c in observation['candidates'] if c['frame_id'] == observation['frames'][0]['id']],
                        'unresolved': []}
            file = base / 'decision.json'
            for mutate, expected in [
                (lambda d: d.update(schema_version=2), 'invalid_decision'),
                (lambda d: d.update(schema_version=True), 'invalid_decision'),
                (lambda d: d.update(task_id='wrong'), 'invalid_decision'),
                (lambda d: d.update(selected_candidates=['../wrong']), 'invalid_decision'),
                (lambda d: d.update(presented_images=['comparison']), 'missing_evidence'),
                (lambda d: d.update(visual_review=False), 'review_required'),
                (lambda d: d.update(selected_candidates=d['selected_candidates'][:-1]), 'review_required'),
                (lambda d: d.update(unresolved=['tail uncertain']), 'review_required')]:
                bad = json.loads(json.dumps(decision))
                mutate(bad)
                file.write_text(json.dumps(bad))
                _, rejected = self.cli('--operation', 'submit', '--task', task, '--decision', file)
                self.assertEqual(rejected['error']['code'], expected, rejected)
                self.assertFalse((task / 'decision.json').exists())
            file.write_text(json.dumps(decision)[:-1] + ', "schema_version": 1}')
            _, rejected = self.cli('--operation', 'submit', '--task', task, '--decision', file)
            self.assertEqual(rejected['error']['code'], 'invalid_decision')
            file.write_text(json.dumps(decision))
            _, submitted = self.cli('--operation', 'submit', '--task', task, '--decision', file)
            self.assertEqual(submitted['phase'], 'accepted')
            code, result = self.cli('--operation', 'export', '--task', task, '--output', base / 'out')
            self.assertEqual(code, 0, result)
            self.assertEqual(len(result['rows']), 3)
            for row in result['rows']:
                with Image.open(base / 'out' / row['source_frame']) as frame, Image.open(base / 'out' / row['original_image']) as original:
                    self.assertEqual(frame.crop(row['bbox']).tobytes(), original.tobytes())
            code, replay = self.cli('--operation', 'replay', '--task', task, '--output', base / 'replay')
            self.assertEqual(code, 0, replay)
            self.assertEqual((base / 'out/score.pdf').read_bytes(), (base / 'replay/score.pdf').read_bytes())
            original_packet = (task / 'observation.json').read_bytes()
            (task / 'observation.json').write_bytes(original_packet + b' ')
            _, result = self.cli('--operation', 'replay', '--task', task, '--output', base / 'tampered')
            self.assertEqual(result['error']['code'], 'source_mismatch')
            self.assertFalse((base / 'tampered/score.pdf').exists())
            (task / 'observation.json').write_bytes(original_packet)
            with video.open('ab') as stream:
                stream.write(b'changed-source')
            _, result = self.cli('--operation', 'replay', '--task', task, '--output', base / 'changed')
            self.assertEqual(result['error']['code'], 'source_mismatch')
            self.assertFalse((base / 'changed/score.pdf').exists())

    def test_invalid_json_and_existing_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            video = video_from_image(score_frame(), base)
            self.cli(video, '--operation', 'prepare', '--output', task)
            preserved = (task / 'observation.json').read_bytes()
            _, result = self.cli(video, '--operation', 'prepare', '--output', task)
            self.assertEqual(result['error']['code'], 'existing_output')
            self.assertEqual(preserved, (task / 'observation.json').read_bytes())
            for text in ('{"schema_version": NaN}', '{"schema_version": 1, "schema_version": 2}', '{"schema_version": Infinity}'):
                (base / 'bad.json').write_text(text)
                _, result = self.cli('--operation', 'submit', '--task', task, '--decision', base / 'bad.json')
                self.assertEqual(result['error']['code'], 'invalid_decision')
            self.assertFalse((task / 'decision.json').exists())

    def test_prepare_empty_and_low_resolution_do_not_export(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, frame, expected in [('empty', Image.new('RGB', (1280, 960), 'white'), 'waiting'),
                                           ('small', score_frame().resize((640, 480)), 'failed')]:
                video = video_from_image(frame, base, name)
                _, result = self.cli(video, '--operation', 'prepare', '--output', base / name)
                self.assertEqual(result['status'], expected)
                self.assertFalse((base / name / 'score.pdf').exists())

    def test_agent_native_regions_preserve_symbols_and_accept_clean_color(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            image = score_frame()
            draw = ImageDraw.Draw(image)
            draw.arc((290, 175, 460, 215), 180, 360, fill='black', width=2)
            draw.text((200, 180), '(x)', fill='black')
            draw.text((700, 315), 'pp', fill='black')
            draw.line((870, 190, 870, 280), fill='red', width=7)
            video = video_from_image(image, base)
            task = base / 'task'
            _, state = self.cli(video, '--operation', 'prepare', '--output', task)
            packet = json.loads((task / 'observation.json').read_text())
            frame = packet['frames'][0]
            details = [i for i in packet['images'] if i['kind'] == 'native_detail' and i['frame_id'] == frame['id']]
            self.assertTrue(details)
            for detail in details:
                with Image.open(task / frame['path']) as original, Image.open(task / detail['path']) as tile:
                    self.assertEqual(tile.tobytes(), original.crop(detail['bbox']).tobytes())
                self.assertEqual(detail['mapping']['scale'], [1, 1])
            rows = []
            for box in ([80, 160, 1200, 350], [80, 390, 1200, 560], [80, 610, 1200, 780]):
                rows.append(dict(frame_id=frame['id'], coordinate_space='native_pixels', roi=[70, 40, 1210, 910], bbox=box,
                                 evidence_images=[i['id'] for i in details], complete=True, cursor='clear', occlusion='clear',
                                 boundary_verified=True, evidence='Whole staff, ornaments and margins visible; red source mark is notation.'))
            decision = dict(schema_version=2, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                            decision_id='native-rows', model=dict(id='test', version='unknown'),
                            prompt=dict(version='regions-1', text='Compare thumbnail context then native detail; retain source notation.'),
                            presented_images=[i['id'] for i in packet['images']], visual_review=True, complete=True,
                            evidence='Fixed three rows; no missing or duplicate rows.', rows=rows, unresolved=[])
            path = base / 'decision.json'
            for change, code in [
                (lambda d: d['rows'][0].update(coordinate_space='comparison_pixels'), 'invalid_decision'),
                (lambda d: d['rows'][0].update(bbox=[100, 160, 1400, 350]), 'invalid_decision'),
                (lambda d: d['rows'][0].update(cursor='present'), 'review_required'),
                (lambda d: d['rows'][0].update(occlusion='uncertain'), 'review_required'),
                (lambda d: d['rows'][0].update(boundary_verified=False), 'review_required'),
                (lambda d: d['rows'][0].update(evidence_images=[details[0]['id']]), 'missing_evidence'),
                (lambda d: d['rows'][0].update(refinement=dict(bbox=[80, 180, 1200, 350], reason='cut', boundary_verified=True)), 'invalid_decision'),
                (lambda d: d['rows'][0].update(refinement=dict(bbox=[80, 164, 1200, 350], reason='unsafe', boundary_verified=False)), 'review_required')]:
                bad = json.loads(json.dumps(decision))
                change(bad)
                path.write_text(json.dumps(bad))
                _, result = self.cli('--operation', 'submit', '--task', task, '--decision', path)
                self.assertEqual(result['error']['code'], code, result)
                self.assertFalse((task / 'decision.json').exists())
            decision['rows'][0]['refinement'] = dict(bbox=[80, 156, 1200, 350], reason='retain above-staff symbols with a larger blank margin', boundary_verified=True)
            path.write_text(json.dumps(decision))
            _, accepted = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(accepted['phase'], 'accepted', accepted)
            _, result = self.cli('--operation', 'export', '--task', task, '--output', base / 'out')
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(result['rows'][0]['bbox'], [80, 156, 1200, 350])
            self.assertEqual(result['rows'][0]['selected_candidate']['proposed_bbox'], [80, 160, 1200, 350])
            for row in result['rows']:
                with Image.open(base / 'out' / row['source_frame']) as source, Image.open(base / 'out' / row['original_image']) as crop, Image.open(base / 'out' / row['image']) as gray:
                    self.assertEqual(crop.tobytes(), source.crop(row['bbox']).tobytes())
                    self.assertEqual(gray.tobytes(), crop.convert('L').tobytes())
            _, replay = self.cli('--operation', 'replay', '--task', task, '--output', base / 'replay')
            self.assertEqual(replay['status'], 'success', replay)
            self.assertEqual((base / 'out/score.pdf').read_bytes(), (base / 'replay/score.pdf').read_bytes())

    def test_clean_frame_choices_work_when_detector_cannot_propose_short_single_row(self):
        from PIL import ImageDraw
        for name, dirty_first, width, all_dirty in [('narrow-first', True, 5, False), ('wide-last', False, 180, False), ('wide-always', True, 180, True)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                clean = score_frame(row_count=1)
                ImageDraw.Draw(clean).rectangle((800, 210, 1180, 280), fill='white')
                ImageDraw.Draw(clean).text((200, 180), '(x)', fill='black')
                dirty = clean.copy()
                ImageDraw.Draw(dirty).rectangle((420, 165, 420 + width, 340), fill='blue')
                for index in range(8):
                    selected = dirty if all_dirty or (index < 4) == dirty_first else clean
                    selected.save(base / f'{index:03d}.png')
                video = base / 'input.mp4'
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '4', '-i', str(base / '%03d.png'), '-pix_fmt', 'yuv420p', str(video)], check=True)
                task = base / 'task'
                _, state = self.cli(video, '--operation', 'prepare', '--output', task)
                self.assertEqual(state['phase'], 'review', state)
                packet = json.loads((task / 'observation.json').read_text())
                self.assertEqual(packet['candidates'], [])
                frame = packet['frames'][1 if dirty_first else 0]
                refs = [i['id'] for i in packet['images'] if i['kind'] == 'native_detail' and i['frame_id'] == frame['id']]
                row = dict(frame_id=frame['id'], coordinate_space='native_pixels', roi=[70,40,1210,910], bbox=[80,150,1200,350], evidence_images=refs,
                           complete=True, cursor='present' if all_dirty else 'clear', occlusion='present' if all_dirty else 'clear',
                           boundary_verified=True, evidence='Short staff followed by blank space; choose entire clean native row, not a mosaic.')
                decision = dict(schema_version=2, task_id=state['task_id'], observation_sha256=state['observation_sha256'], decision_id=name,
                                model=dict(id='test', version='unknown'), prompt=dict(version='native-1', text='Compare clean and obscured views then inspect native symbols.'),
                                presented_images=[i['id'] for i in packet['images']], visual_review=True, complete=True, evidence='One fixed short row.', rows=[row], unresolved=[])
                path=base/'decision.json'; path.write_text(json.dumps(decision))
                _, result = self.cli('--operation', 'submit', '--task', task, '--decision', path)
                if all_dirty:
                    self.assertEqual(result['status'], 'waiting', result)
                    self.assertFalse((task / 'decision.json').exists())
                else:
                    self.assertEqual(result['phase'], 'accepted', result)
                    _, result = self.cli('--operation', 'export', '--task', task, '--output', base / 'out')
                    self.assertEqual(result['status'], 'success', result)
                    self.assertEqual(result['rows'][0]['source_frame'], frame['path'])
