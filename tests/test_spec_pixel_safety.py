"""CLI regressions for faint edge staffs and bright colored notation."""
from pathlib import Path
import tempfile
import subprocess
import unittest
import numpy as np
from PIL import Image, ImageDraw
import test_conversion as base_tests
from test_conversion import score_frame, video_from_image
from test_edge_cards import card
from test_ordered_conversion import sequence_video, window


class SpecPixelSafetyTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli

    def test_crisp_titles_with_faint_staff_signals_remain_uncertain(self):
        faint = card()
        ImageDraw.Draw(faint).line((100, 220, 1180, 220), fill='#383838', width=2)
        for images in ([faint, window('ABC')], [window('ABC'), faint]):
            with self.subTest(edge='start' if images[0] is faint else 'end'), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                _, result = self.run_cli(sequence_video(images, base), base / 'result')
                self.assertEqual(result['status'], 'waiting', result)
                self.assertFalse(result['complete'])
                self.assertFalse((base / 'result/score.pdf').exists())

    def test_bright_colored_notation_below_last_staff_survives_crop(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            frame = score_frame()
            ImageDraw.Draw(frame).ellipse((650, 805, 664, 819), fill=(255, 255, 0))
            _, result = self.run_cli(video_from_image(frame, base), base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(result['complete'])
            row = result['rows'][-1]
            self.assertGreaterEqual(row['bbox'][3], 820)
            pixels = np.asarray(Image.open(base / 'result' / row['image']).convert('L'))
            x0, y0 = row['bbox'][:2]
            self.assertLess(float(pixels[808-y0:817-y0, 654-x0:661-x0].mean()), 245)
            self.assertTrue((base / 'result/score.pdf').exists())
            subprocess.run(['pdftoppm', '-f', str(row['page']), '-l', str(row['page']), '-r', '144', '-singlefile', '-png', str(base / 'result/score.pdf'), str(base / 'page')], check=True, capture_output=True)
            page = np.asarray(Image.open(base / 'page.png').convert('L'))
            left, bottom, right, top = row['pdf_bbox']
            scale = (right - left) / (row['bbox'][2] - x0)
            cx = int(2 * (left + (657 - x0) * scale))
            cy = int(page.shape[0] - 2 * top + 2 * (812 - y0) * scale)
            self.assertLess(float(page[cy-1:cy+2, cx-1:cx+2].mean()), 245)
