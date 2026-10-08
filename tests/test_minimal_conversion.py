"""CLI, native provenance, actual PTS, boundaries and whole-row PDF contracts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image, ImageDraw
from score_fixtures import CLI, score_frame, video_from_image

sys.path.insert(0, str(CLI.parent))
from video_seek import probe_video, VideoReader
from pdf_export import write_pdf
from manifest import save_crop


class ConversionTests(unittest.TestCase):
    def run_cli(self, video, output):
        process = subprocess.run([sys.executable, str(CLI), str(video), '--output', str(output)],
                                 capture_output=True, text=True, check=False)
        return process.returncode, json.loads(process.stdout)

    def test_fixed_score_header_original_provenance_and_pdf(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = video_from_image(score_frame(), base)
            output = base / 'result'
            code, result = self.run_cli(source, output)
            self.assertEqual(code, 0, result)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['rows']), 3)
            self.assertEqual(result['page_count'], 1)
            self.assertEqual(result['header']['timestamp'], 0)
            for block in [result['header']] + result['rows']:
                with Image.open(output / block['source_frame']) as frame, Image.open(output / block['original_image']) as original:
                    np.testing.assert_array_equal(np.asarray(frame.convert('RGB').crop(block['bbox'])), np.asarray(original))
                    with Image.open(output / block['image']) as printable:
                        np.testing.assert_array_equal(np.asarray(original.convert('L')), np.asarray(printable))
            info = subprocess.run(['pdfinfo', str(output / 'score.pdf')], capture_output=True, text=True, check=True).stdout
            self.assertIn('595.276 x 841.89 pts (A4)', info)
            subprocess.run(['pdftoppm', '-scale-to', '1200', '-singlefile', '-png', str(output / 'score.pdf'), str(base / 'page')], capture_output=True, check=True)
            with Image.open(base / 'page.png') as page:
                y = np.where((np.asarray(page.convert('L')) < 100).sum(axis=1) > 500)[0]
            self.assertEqual(sum(i == 0 or value > y[i - 1] + 1 for i, value in enumerate(y)), 15)

    def test_bad_input_and_low_resolution_fail_without_pdf(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            for video, code in ((base / 'missing.mp4', 'invalid_input'),
                                (video_from_image(score_frame().resize((640, 480)), base), 'low_resolution')):
                output = base / code
                exit_code, result = self.run_cli(video, output)
                self.assertEqual(exit_code, 2)
                self.assertEqual(result['error']['code'], code)
                self.assertFalse((output / 'score.pdf').exists())

    def test_partial_bottom_forever_waits_with_source_screenshot(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            frame = score_frame(row_count=4)
            _, result = self.run_cli(video_from_image(frame, base), base / 'result')
            self.assertEqual(result['status'], 'waiting')
            self.assertEqual(result['error']['code'], 'end_partial')
            self.assertTrue((base / 'result' / result['issues'][0]['screenshot']).exists())
            self.assertFalse((base / 'result/score.pdf').exists())

    def test_persistent_cursor_waits_without_reconstruction(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            frame = score_frame()
            ImageDraw.Draw(frame).rectangle((550, 170, 575, 340), fill=(205, 223, 237))
            _, result = self.run_cli(video_from_image(frame, base), base / 'result')
            self.assertEqual(result['status'], 'waiting')
            self.assertEqual(result['error']['code'], 'no_clean_observation')
            self.assertFalse((base / 'result/score.pdf').exists())

    def test_actual_pts_tail_and_temporary_cleanup(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = video_from_image(score_frame(), base)
            metrics = dict(seek_count=0, decode_elapsed=0, decoded_reported_frames=0, peak_temp_disk=0)
            reader = VideoReader(source, probe_video(source), metrics)
            directory = Path(reader.scratch.name)
            try:
                pts, image = reader.read(.31)
                self.assertAlmostEqual(pts, .5)
                self.assertEqual(image.size, (1280, 960))
                pts, _ = reader.read()
                self.assertAlmostEqual(pts, 1.75)
                self.assertEqual(len(list(directory.iterdir())), 1)
                self.assertGreater(metrics['peak_temp_disk'], 0)
            finally:
                reader.close()
            self.assertFalse(directory.exists())

    def test_a4_rows_do_not_split_and_pdf_is_deterministic(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            Image.new('RGB', (1200, 220), 'white').save(base / 'source.png')
            rows = [save_crop(base, 'source.png', [0, 0, 1200, 220], f'row-{i}') for i in range(9)]
            self.assertEqual(write_pdf(base, None, rows), 2)
            first = (base / 'score.pdf').read_bytes()
            write_pdf(base, None, rows)
            self.assertEqual(first, (base / 'score.pdf').read_bytes())
            second = base / 'different-directory'
            second.mkdir()
            for row in rows:
                (second / row['image']).write_bytes((base / row['image']).read_bytes())
            write_pdf(second, None, rows)
            self.assertEqual(first, (second / 'score.pdf').read_bytes())
            for row in rows:
                self.assertGreaterEqual(row['pdf_bbox'][1], 36)
                self.assertLessEqual(row['pdf_bbox'][3], 806)
