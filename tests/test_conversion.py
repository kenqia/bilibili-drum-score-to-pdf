"""CLI acceptance tests using drawn score features and real video/PDF tools."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'skills/bilibili-drum-score-to-pdf/scripts/convert.py'


def score_frame(size=(1280, 960), row_count=3):
    frame = Image.new('RGB', size, '#303030')
    draw = ImageDraw.Draw(frame)
    draw.rectangle((70, 40, 1210, size[1] - 50), fill='white')
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28)
    draw.text((130, 75), 'Fixture song    tempo 96    4/4', fill='black', font=font)
    for row, top in enumerate(220 + row * 220 for row in range(row_count)):
        for line in range(5):
            draw.line((110, top + line * 12, 1170, top + line * 12), fill='black', width=2)
        for note in range(4 + row % 3):
            x = 220 + note * 125
            draw.ellipse((x - 8, top + 27, x + 8, top + 39), fill='black')
            draw.line((x + 8, top + 33, x + 8, top - 32), fill='black', width=3)
        draw.text((120, top + 80), f'ROW {row + 1}', fill='black', font=font)
    return frame


def video_from_image(image, directory, name='input'):
    png = directory / f'{name}.png'
    video = directory / f'{name}.mp4'
    image.save(png)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', str(png), '-t', '2', '-r', '4', '-pix_fmt', 'yuv420p', str(video)], check=True)
    return video


class ConversionTests(unittest.TestCase):
    def run_cli(self, source, output):
        run = subprocess.run([sys.executable, str(CLI), str(source), '--output', str(output)], capture_output=True, text=True)
        self.assertTrue(run.stdout.strip(), run.stderr)
        return run, json.loads(run.stdout)

    def test_fixed_score_keeps_header_complete_rows_and_video_provenance(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = video_from_image(score_frame(), base)
            output = base / 'result'
            run, result = self.run_cli(source, output)
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(run.returncode, 0)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(len(manifest['rows']), 3)
            self.assertEqual(manifest['page_count'], 1)
            self.assertTrue(manifest['header']['image'])
            self.assertLessEqual(manifest['header']['bbox'][1], 75)
            self.assertGreaterEqual(manifest['header']['bbox'][3], 103)
            for index, row in enumerate(manifest['rows']):
                staff_top = 220 + index * 220
                self.assertLessEqual(row['bbox'][1], staff_top - 32)
                self.assertGreaterEqual(row['bbox'][3], staff_top + 105)
                self.assertGreaterEqual(row['timestamp'], 0)
                self.assertLess(row['timestamp'], 2)
                crop = Image.open(output / row['image']).convert('L')
                # A complete row includes the upward stem and its label below the staff.
                self.assertGreater(crop.height, 145)
                self.assertLess(int(np.asarray(crop).min()), 40)
            pdf = output / 'score.pdf'
            info = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True, check=True).stdout
            self.assertIn('595.276 x 841.89 pts (A4)', info)
            subprocess.run(['pdftoppm', '-scale-to', '1200', '-singlefile', '-png', str(pdf), str(base / 'page')], check=True, capture_output=True)
            rendered = Image.open(base / 'page.png').convert('L')
            dark = np.asarray(rendered) < 100
            line_y = np.where(dark.sum(axis=1) > 500)[0]
            line_count = sum(index == 0 or y > line_y[index - 1] + 1 for index, y in enumerate(line_y))
            self.assertEqual(line_count, 15, 'PDF must retain all 15 staff lines')

    def test_unreadable_input_reports_failure_without_pdf(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            run, result = self.run_cli(base / 'missing.mp4', base / 'result')
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error']['code'], 'unreadable_input')
            self.assertFalse((base / 'result/score.pdf').exists())
            self.assertEqual(run.returncode, 2)

    def test_changing_score_never_claims_complete_fixed_restoration(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            first = score_frame()
            second = score_frame()
            ImageDraw.Draw(second).rectangle((700, 625, 735, 660), fill='black')
            first.save(base / 'part-0.png')
            second.save(base / 'part-1.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '1', '-i', str(base / 'part-%d.png'), '-r', '4', '-pix_fmt', 'yuv420p', str(base / 'changing.mp4')], check=True)
            run, result = self.run_cli(base / 'changing.mp4', base / 'result')
            self.assertEqual(result['status'], 'waiting')
            self.assertFalse(result['complete'])
            self.assertFalse((base / 'result/score.pdf').exists())
            self.assertTrue(result['issues'][0]['id'])
            self.assertTrue((base / 'result' / result['issues'][0]['image']).exists())
            self.assertIn('timestamp', result['issues'][0])

    def test_large_fixed_score_breaks_pages_only_between_rows(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = video_from_image(score_frame((1280, 2150), row_count=8), base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(len(result['rows']), 8)
            self.assertEqual(result['page_count'], 2)
            for row in result['rows']:
                left, bottom, right, top = row['pdf_bbox']
                self.assertGreaterEqual(bottom, 36)
                self.assertLessEqual(top, 806)
                self.assertGreater(top - bottom, 65)

    def test_native_low_resolution_requests_clearer_local_input(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = video_from_image(score_frame().resize((640, 480)), base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error']['code'], 'low_resolution')
            self.assertIn('本地视频', result['error']['message'])
            self.assertFalse((base / 'result/score.pdf').exists())

    def test_obviously_blurred_source_cannot_claim_printable_success(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = video_from_image(score_frame().filter(ImageFilter.GaussianBlur(3)), base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['complete'])
            self.assertTrue(result['error']['message'])
            self.assertFalse((base / 'result/score.pdf').exists())


if __name__ == '__main__':
    unittest.main()
