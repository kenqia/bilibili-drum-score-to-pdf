"""Explicit chat decisions and replay at the unified conversion CLI."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_conversion import CLI
from test_ordered_conversion import sequence_video, window


class ResumeTests(unittest.TestCase):
    def test_interrupted_pdf_or_manifest_commit_cannot_be_resumed_as_old_progress(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF')], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            self.assertEqual(waiting['status'], 'waiting')
            self.assertFalse((output / 'score.pdf').exists())
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'confirm_join'}}))
            manifest_path, state_path = output / 'manifest.json', output / 'state.json'
            saved_manifest, saved_state = manifest_path.read_bytes(), state_path.read_bytes()
            # Inject a process exit at the filesystem replacement boundary.
            # Then ask the real CLI to inspect the surviving directory.
            launcher = """
import os, pathlib, runpy, sys
cli, destination, *arguments = sys.argv[1:]
replace = os.replace
def interrupted(src, dst, *args, **kwargs):
    result = replace(src, dst, *args, **kwargs)
    if pathlib.Path(dst).resolve() == pathlib.Path(destination).resolve():
        os._exit(73)
    return result
os.replace = interrupted
sys.path.insert(0, str(pathlib.Path(cli).parent))
sys.argv = [cli, *arguments]
runpy.run_path(cli, run_name='__main__')
"""
            for name in ('score.pdf', 'manifest.json'):
                with self.subTest(interrupted_after=name):
                    manifest_path.write_bytes(saved_manifest)
                    state_path.write_bytes(saved_state)
                    (output / 'score.pdf').unlink(missing_ok=True)
                    crashed = subprocess.run([sys.executable, '-c', launcher, str(CLI), str(output / name), '--resume', str(output), '--answers', str(answers)], capture_output=True, text=True)
                    self.assertEqual(crashed.returncode, 73, crashed.stderr)
                    artifacts_before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}
                    _, result = self.invoke('--resume', output)
                    self.assertEqual(result['status'], 'failed')
                    self.assertEqual(result['error']['code'], 'invalid_progress')
                    artifacts_after = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}
                    self.assertEqual(artifacts_before, artifacts_after)

    def test_incomplete_legacy_or_escaping_artifact_state_cannot_resume(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC')], base)
            output = base / 'result'
            _, original = self.invoke(source, '--output', output)
            self.assertEqual(original['status'], 'success')
            manifest_path, state_path = output / 'manifest.json', output / 'state.json'
            original_manifest = manifest_path.read_bytes()
            original_state = state_path.read_bytes()
            for damage in ('missing_pdf_hash', 'missing_evidence_hash', 'legacy_schema', 'absolute_pdf', 'escaping_image'):
                with self.subTest(damage=damage):
                    manifest = json.loads(original_manifest)
                    state = json.loads(original_state)
                    if damage == 'missing_pdf_hash':
                        state['artifacts'].pop(manifest['pdf'], None)
                    elif damage == 'missing_evidence_hash':
                        state['artifacts'].pop(manifest['boundaries']['start']['image'])
                    elif damage == 'legacy_schema':
                        state['schema_version'] = 1
                    elif damage == 'absolute_pdf':
                        manifest['pdf'] = str(output / 'score.pdf')
                    elif damage == 'escaping_image':
                        reference = manifest['boundaries']['start']
                        old_name = reference['image']
                        external = base / 'external.png'
                        external.write_bytes((output / old_name).read_bytes())
                        reference['image'] = '../external.png'
                        state['artifacts']['../external.png'] = state['artifacts'][old_name]
                    manifest_path.write_text(json.dumps(manifest))
                    state['manifest_sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    state_path.write_text(json.dumps(state))
                    damaged_manifest, damaged_state = manifest_path.read_bytes(), state_path.read_bytes()
                    _, result = self.invoke('--resume', output)
                    self.assertEqual(result['status'], 'failed')
                    self.assertEqual(result['error']['code'], 'invalid_progress')
                    self.assertEqual(manifest_path.read_bytes(), damaged_manifest)
                    self.assertEqual(state_path.read_bytes(), damaged_state)
            manifest_path.write_bytes(original_manifest)
            state_path.write_bytes(original_state)
            _, restored = self.invoke('--resume', output)
            self.assertEqual(restored['status'], 'success')

    def test_pdf_changes_or_loss_refuse_resume_and_preserve_progress(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC')], base)
            output = base / 'result'
            _, original = self.invoke(source, '--output', output)
            self.assertEqual(original['status'], 'success')
            pdf = output / original['pdf']
            saved_pdf = pdf.read_bytes()
            saved_manifest = (output / 'manifest.json').read_bytes()
            saved_state = (output / 'state.json').read_bytes()
            for damaged in (b'replaced-pdf-generation', None):
                with self.subTest(damaged=damaged):
                    if damaged is None:
                        pdf.unlink()
                    else:
                        pdf.write_bytes(damaged)
                    _, result = self.invoke('--resume', output)
                    self.assertEqual(result['status'], 'failed')
                    self.assertEqual(result['error']['code'], 'invalid_progress')
                    self.assertEqual((output / 'manifest.json').read_bytes(), saved_manifest)
                    self.assertEqual((output / 'state.json').read_bytes(), saved_state)
                    pdf.write_bytes(saved_pdf)

    def invoke(self, *arguments):
        run = subprocess.run([sys.executable, str(CLI), *map(str, arguments)], capture_output=True, text=True)
        self.assertTrue(run.stdout.strip(), run.stderr)
        return run, json.loads(run.stdout)

    def test_waiting_can_resume_without_answer_and_preserves_progress(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF')], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            before = (output / 'manifest.json').read_bytes()
            _, resumed = self.invoke('--resume', output)
            self.assertEqual(resumed['status'], 'waiting')
            self.assertEqual(resumed['issues'][0]['id'], waiting['issues'][0]['id'])
            self.assertEqual(before, (output / 'manifest.json').read_bytes())
            self.assertTrue((output / 'state.json').exists())

    def test_confirmed_join_replays_past_question_and_does_not_duplicate_on_retry(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF'), window('EFA')], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'confirm_join'}}))
            _, result = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['rows']), 7)
            self.assertEqual(result['boundaries']['end']['timestamp'], 5.75)
            hashes = [hashlib.sha256((output / row['image']).read_bytes()).hexdigest() for row in result['rows']]
            _, repeated = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(len(repeated['rows']), 7)
            self.assertEqual(hashes, [hashlib.sha256((output / row['image']).read_bytes()).hexdigest() for row in repeated['rows']])

    def test_accepted_missing_is_marked_between_correct_rows_and_not_complete(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF'), window('EFA')], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'accept_missing'}}))
            _, result = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(result['status'], 'success', result)
            self.assertFalse(result['complete'])
            self.assertEqual(result['gaps'][0]['position'], 3)
            gap = result['gaps'][0]
            before = (result['rows'][2]['page'], -result['rows'][2]['pdf_bbox'][3])
            marker = (gap['page'], -gap['pdf_bbox'][3])
            after = (result['rows'][3]['page'], -result['rows'][3]['pdf_bbox'][3])
            self.assertLess(before, marker)
            self.assertLess(marker, after)
            self.assertTrue(result['limitations'])
            text = subprocess.run(['pdftotext', '-layout', str(output / 'score.pdf'), '-'], capture_output=True, text=True, check=True).stdout
            self.assertIn('MISSING CONTENT', text)
            self.assertLess(result['rows'][2]['pdf_bbox'][1], result['rows'][1]['pdf_bbox'][1])
            self.assertEqual(len(result['rows']), 7)


    def test_observable_single_row_supplement_restores_gap(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF'), window('EFA')], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            supplement = base / 'full-row.png'
            window('ABC').crop((70, 145, 1211, 365)).save(supplement)
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'supplement', 'image': str(supplement)}}))
            _, result = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['rows']), 8)
            self.assertTrue(result['rows'][3]['supplement']['user_provided'])
            self.assertEqual(result['boundaries']['end']['timestamp'], 5.75)

    def test_unknown_and_malformed_answers_preserve_decisions_and_source_corruption_stops(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF'), window('ABC')], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'confirm_join'}}))
            _, continued = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(continued['status'], 'waiting')
            self.assertEqual(continued['confirmation_count'], 1)
            manifest_before = (output / 'manifest.json').read_bytes()
            answers.write_text('{invalid json')
            _, insufficient = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(insufficient['status'], 'waiting')
            self.assertEqual(insufficient['confirmation_count'], 1)
            self.assertEqual(manifest_before, (output / 'manifest.json').read_bytes())
            answers.write_text(json.dumps({'unknown-id': {'action': 'accept_missing'}}))
            _, insufficient = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(insufficient['status'], 'waiting')
            self.assertEqual(manifest_before, (output / 'manifest.json').read_bytes())
            with source.open('ab') as stream:
                stream.write(b'changed')
            _, changed = self.invoke('--resume', output)
            self.assertEqual(changed['error']['code'], 'invalid_progress')
            self.assertEqual(manifest_before, (output / 'manifest.json').read_bytes())

    def test_fresh_conversion_refuses_existing_output_without_erasing_pdf_or_progress(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch)
            (output / 'score.pdf').write_bytes(b'user-pdf')
            (output / 'manifest.json').write_bytes(b'user-progress')
            _, result = self.invoke('https://www.bilibili.com/video/BV1b5411x7Ku', '--output', output)
            self.assertEqual(result['error']['code'], 'existing_output')
            self.assertEqual((output / 'score.pdf').read_bytes(), b'user-pdf')
            self.assertEqual((output / 'manifest.json').read_bytes(), b'user-progress')

    def test_explicit_repeat_choice_preserves_played_repeated_rows(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            shifted = Image.new('RGB', (1280, 960), '#303030')
            from PIL import ImageDraw
            ImageDraw.Draw(shifted).rectangle((70, 40, 1210, 910), fill='white')
            shifted.paste(window('AAA').crop((70, 76, 1211, 911)), (70, 40))
            source = sequence_video([window('AAA'), shifted], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            self.assertEqual(waiting['issues'][0]['kind'], 'ambiguous_repeat')
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'confirm_repeat'}}))
            _, repeated = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(repeated['status'], 'success', repeated)
            self.assertEqual(len(repeated['rows']), 6)

    def test_corrupted_state_and_unusable_supplement_do_not_claim_completion(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF')], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            from PIL import Image
            image = base / 'bad.png'
            Image.new('RGB', (640, 360), 'white').save(image)
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'supplement', 'image': str(image)}}))
            _, insufficient = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(insufficient['status'], 'waiting')
            self.assertEqual(insufficient['confirmation_count'], 0)
            self.assertFalse((output / 'score.pdf').exists())
            before = (output / 'manifest.json').read_bytes()
            (output / 'state.json').write_text('{corrupt')
            _, failed = self.invoke('--resume', output)
            self.assertEqual(failed['error']['code'], 'invalid_progress')
            self.assertEqual(before, (output / 'manifest.json').read_bytes())

    def test_cursor_acceptance_replaces_obscured_row_with_positioned_gap(self):
        from test_cursor_quality import cursor_window
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([cursor_window(211), cursor_window(211)], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            self.assertEqual(waiting['issues'][0]['kind'], 'cursor_occlusion')
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'accept_missing'}}))
            _, result = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(result['status'], 'success', result)
            self.assertFalse(result['complete'])
            gap = result['gaps'][0]
            self.assertEqual(gap['position'], 0)
            self.assertTrue(gap['replace_row'])
            self.assertLess((gap['page'], -gap['pdf_bbox'][3]), (result['rows'][1]['page'], -result['rows'][1]['pdf_bbox'][3]))
            self.assertNotIn('pdf_bbox', result['rows'][0])
            text = subprocess.run(['pdftotext', str(output / 'score.pdf'), '-'], capture_output=True, text=True, check=True).stdout
            self.assertIn('MISSING CONTENT', text)
            _, again = self.invoke('--resume', output)
            self.assertEqual(again['confirmation_count'], 1)

    def test_cursor_supplement_replaces_only_obscured_row_and_keeps_provenance(self):
        from test_cursor_quality import cursor_window
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([cursor_window(211), cursor_window(211)], base)
            output = base / 'result'
            _, waiting = self.invoke(source, '--output', output)
            supplied = base / 'visible-row.png'
            cursor_window().crop((70, 145, 1211, 365)).save(supplied)
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'supplement', 'image': str(supplied)}}))
            _, result = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['rows']), 3)
            self.assertTrue(result['rows'][0]['supplement']['user_provided'])
            self.assertEqual(result['quality']['unrecovered_rows'], [])
            self.assertTrue((output / result['rows'][0]['original_image']).exists())
            hashes = [row['content_sha256'] for row in result['rows']]
            _, again = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(hashes, [row['content_sha256'] for row in again['rows']])


if __name__ == '__main__':
    unittest.main()
