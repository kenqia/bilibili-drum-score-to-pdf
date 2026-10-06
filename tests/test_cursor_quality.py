"""Verify readable pixels delivered by the conversion CLI, without private hooks."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import test_conversion as base_tests
from test_ordered_conversion import sequence_video, window


def cursor_window(x=None, faint=False):
    image = window('ABC')
    draw = ImageDraw.Draw(image)
    # Native colored multimeasure rest line and number-like marker in row 2.
    draw.line((810, 409, 990, 409), fill=(40, 110, 220), width=4)
    draw.text((870, 380), '3', font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28), fill=(40, 110, 220))
    # Beam between four independently specified stems in the first row.
    draw.line((228, 188, 573, 188), fill='black', width=4)
    if x is not None:
        draw.rectangle((x, 182, x + (48 if faint else 32), 312), fill=(217, 242, 245) if faint else (120, 215, 255))
    return image


class CursorQualityTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli

    def test_clean_actual_frame_preserves_heads_stems_beam_and_native_blue_notation(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([cursor_window(211), cursor_window(441), cursor_window()], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(len(result['rows']), 3)
            row = result['rows'][0]
            self.assertGreaterEqual(row['timestamp'], 4)
            self.assertTrue((base / 'result' / row['original_image']).exists())
            output = Image.open(base / 'result' / row['image'])
            self.assertEqual(output.mode, 'L')
            pixels = np.asarray(output)
            x0, y0, _, _ = row['bbox']
            for x in [220, 335, 450, 565]:
                self.assertLess(int(pixels[253 - y0, x - x0]), 40, 'all known notehead centers must survive')
                self.assertLess(int(pixels[202 - y0, x + 8 - x0]), 40, 'all four stems must survive')
            self.assertLess(int(pixels[188 - y0, 400 - x0]), 40, 'known beam must survive')
            blue_row = result['rows'][1]
            blue_pixels = np.asarray(Image.open(base / 'result' / blue_row['image']))
            bx, by, _, _ = blue_row['bbox']
            self.assertLess(int(blue_pixels[409 - by, 900 - bx]), 150, 'native blue rest line must print as ink')
            self.assertGreater(np.count_nonzero(blue_pixels[386 - by:407 - by, 870 - bx:890 - bx] < 150), 20, 'native blue rest number 3 must survive')
            self.assertGreaterEqual(len(row['observations']), 3)
            recovery = row['cursor_recoveries'][0]
            self.assertGreaterEqual(recovery['after']['timestamp'], 4)
            self.assertGreaterEqual(len(recovery['evidence']), 2)
            for observation in recovery['evidence'] + [recovery['after']]:
                self.assertTrue((base / 'result' / observation['image']).exists())
            self.assertEqual(result['quality']['unrecovered_rows'], [])

    def test_persistent_cursor_returns_stable_evidence_and_never_claims_complete(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([cursor_window(211), cursor_window(211)], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'waiting')
            self.assertFalse(result['complete'])
            issue = result['issues'][0]
            self.assertEqual(issue['kind'], 'cursor_occlusion')
            self.assertEqual(issue['position'], 0)
            self.assertEqual(issue['id'], 'cursor_occlusion-0000')
            self.assertTrue((base / 'result' / issue['image']).exists())
            self.assertEqual(result['quality']['unrecovered_rows'], ['row-0001'])
            self.assertFalse((base / 'result/score.pdf').exists())

    def test_cursor_mask_cannot_prove_changed_notation_is_the_same_row(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            blocked = cursor_window(685)
            changed = cursor_window()
            ImageDraw.Draw(changed).ellipse((700, 236, 704, 240), fill="black")
            source = sequence_video([blocked, changed], base)
            run, result = self.run_cli(source, base / "result")
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result["status"], "waiting", result)
            self.assertFalse(result["complete"])
            self.assertTrue(result["issues"])
            self.assertEqual(result["quality"]["unrecovered_rows"], ["row-0001"])
            self.assertFalse((base / "result/score.pdf").exists())

    def test_moving_cursor_cannot_hide_a_change_from_accumulated_visible_evidence(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            changed = cursor_window(441)
            ImageDraw.Draw(changed).ellipse((700, 236, 704, 240), fill='black')
            clean_changed = cursor_window()
            ImageDraw.Draw(clean_changed).ellipse((700, 236, 704, 240), fill='black')
            source = sequence_video([cursor_window(211), cursor_window(685), changed, clean_changed], base)
            run, result = self.run_cli(source, base / 'result')
            self.assertEqual(run.returncode, 2)
            self.assertEqual(result['status'], 'waiting', result)
            self.assertFalse(result['complete'])
            issue = result['issues'][0]
            self.assertEqual(issue['kind'], 'cursor_occlusion')
            self.assertGreaterEqual(issue['timestamp'], 4)
            self.assertTrue((base / 'result' / issue['image']).exists())
            self.assertFalse((base / 'result/score.pdf').exists())

    def test_hidden_changed_notation_between_identical_clean_frames_remains_unproven(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            hidden = cursor_window()
            draw = ImageDraw.Draw(hidden)
            draw.ellipse((700, 236, 704, 240), fill='black')
            draw.rectangle((685, 182, 717, 312), fill=(120, 215, 255))
            source = sequence_video([cursor_window(), hidden, cursor_window()], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'waiting', result)
            self.assertFalse(result['complete'])
            issue = result['issues'][0]
            self.assertEqual(issue['kind'], 'cursor_occlusion')
            self.assertGreaterEqual(issue['timestamp'], 2)
            self.assertTrue((base / 'result' / issue['image']).exists())
            self.assertGreaterEqual(issue['reference']['timestamp'], 4)
            self.assertTrue((base / 'result' / issue['reference']['image']).exists())
            self.assertFalse((base / 'result/score.pdf').exists())
            resumed = subprocess.run([sys.executable, str(base_tests.CLI), '--resume', str(base / 'result')], capture_output=True, text=True)
            self.assertEqual(resumed.returncode, 2, resumed.stderr)
            replay = json.loads(resumed.stdout)
            self.assertEqual(replay['status'], 'waiting')
            self.assertEqual(replay['issues'][0]['id'], issue['id'])
            self.assertFalse(replay['complete'])

    def test_faint_sample_contrast_cursor_is_not_treated_as_clear_source(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            blocked = base / 'blocked'
            blocked.mkdir()
            source = sequence_video([cursor_window(211, faint=True), cursor_window(211, faint=True)], blocked)
            _, waiting = self.run_cli(source, blocked / 'result')
            self.assertEqual(waiting['status'], 'waiting')
            self.assertEqual(waiting['issues'][0]['kind'], 'cursor_occlusion')
            clean = base / 'clean'
            clean.mkdir()
            source = sequence_video([cursor_window(211, faint=True), cursor_window(441, faint=True), cursor_window()], clean)
            _, result = self.run_cli(source, clean / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertGreaterEqual(result['rows'][0]['timestamp'], 4)


if __name__ == '__main__':
    unittest.main()
