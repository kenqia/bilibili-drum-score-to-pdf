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

    def test_fixed_local_score_decision_exports_and_replays_native_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            _, prepared = self.cli(video, '--operation', 'prepare', '--output', task)
            self.assertEqual(prepared['status'], 'waiting')
            observation = json.loads((task / 'observation.json').read_text())
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
