"""Title-named delivery, exact source pixels and registered confirmation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from score_fixtures import score_frame, video_from_image
import test_agent_performance as performance_fixture


class DeliveryLayoutTests(unittest.TestCase):
    cli = performance_fixture.PerformanceTests.cli

    def test_title_export_replay_sources_confirmation_and_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, output = base/'task', base/'output'
            self.cli(video_from_image(score_frame(), base), '--output', task)
            self.cli('--operation', 'submit', '--task', task, '--decision', performance_fixture.PerformanceTests().decision(task, base))
            title = '空白与宣泄 / Girls Band Cry'
            result = self.cli('--operation', 'export', '--task', task, '--output', output, '--title', title)
            self.assertEqual(result['status'], 'success', result.get('error'))
            self.assertEqual(result['pdf'], '空白与宣泄 _ Girls Band Cry.pdf')
            self.assertEqual({p.name for p in output.iterdir()}, {result['pdf'], '材料'})
            manifest_path = output/result['manifest']
            manifest = json.loads(manifest_path.read_text())
            for row in manifest['rows']:
                with Image.open(output/row['source_frame']) as source, Image.open(output/row['original_image']) as original, Image.open(output/row['image']) as printable:
                    self.assertEqual(source.convert('RGB').crop(row['bbox']).tobytes(), original.tobytes())
                    self.assertEqual(original.convert('L').tobytes(), printable.tobytes())
            replay = self.cli('--operation', 'replay', '--task', task, '--output', base/'replay', '--title', title)
            self.assertEqual(replay['status'], 'success', replay.get('error'))
            self.assertEqual((output/result['pdf']).read_bytes(), (base/'replay'/replay['pdf']).read_bytes())
            state = json.loads((task/'task.json').read_text())
            receipt = dict(schema_version=1, review_id='fixture-title', task_id=state['task_id'],
                lifecycle_id=result['performance']['lifecycle_id'], observation_sha256=state['observation_sha256'],
                decision_sha256=state['decision_history'][-1]['sha256'],
                pdf_sha256=hashlib.sha256((output/result['pdf']).read_bytes()).hexdigest(),
                manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                reviewer=dict(kind='controlled_fixture', id='test'), source_manifest_verified=True,
                complete_score_verified=True, pages=[dict(page=i, evidence='Controlled fixture page.') for i in range(1,result['page_count']+1)])
            path = base/'receipt.json';path.write_text(json.dumps(receipt))
            confirmed = self.cli('--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', path)
            self.assertEqual(confirmed['status'], 'success', confirmed.get('error'))
            self.assertTrue(confirmed['performance']['delivery_confirmed'])
            (output/result['pdf']).write_bytes(b'tampered')
            rejected = self.cli('--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', path)
            self.assertEqual(rejected.get('error', {}).get('code'), 'invalid_delivery')
            before = manifest_path.read_bytes()
            invalid = self.cli('--operation', 'export', '--task', task, '--output', output, '--title', '   ')
            self.assertEqual(invalid.get('error', {}).get('code'), 'invalid_input')
            self.assertEqual(manifest_path.read_bytes(), before)
            self.assertFalse((output/'manifest.json').exists())

    def test_filename_is_portable_and_cannot_escape_output(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/bilibili-drum-score-to-pdf/scripts'))
        from delivery_layout import pdf_name
        from video_seek import ConversionError
        for title in ('../曲名', 'CON', '曲'*200, 'A:B?C\\D'):
            name = pdf_name(title)
            self.assertEqual(Path(name).name, name)
            self.assertNotIn('\\', name)
            self.assertLessEqual(len(name.encode('utf-8')), 244)
        for title in ('', '   ', 'x'*201):
            with self.assertRaises(ConversionError):
                pdf_name(title)
