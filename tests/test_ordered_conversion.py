"""Ordered recovery acceptance at the agreed conversion CLI boundary."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from PIL import Image, ImageDraw, ImageFont
import test_conversion as base_tests


FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def window(labels, partial_top=False, partial_bottom=False):
    frame = Image.new('RGB', (1280, 960), '#303030')
    draw = ImageDraw.Draw(frame)
    draw.rectangle((70, 40, 1210, 910), fill='white')
    font = ImageFont.truetype(FONT, 28)
    if not partial_top:
        draw.text((130, 75), 'Ordered song   tempo 96   4/4', fill='black', font=font)
    if partial_top:
        for y in [40, 52, 64]:
            draw.line((110, y, 1170, y), fill='black', width=2)
    if partial_bottom:
        for y in [884, 896, 908]:
            draw.line((110, y, 1170, y), fill='black', width=2)
    for top, label in zip([220, 440, 660], labels):
        for line in range(5):
            draw.line((110, top + line * 12, 1170, top + line * 12), fill='black', width=2)
        for note in range({'A': 4, 'B': 5, 'C': 6, 'D': 7, 'E': 8, 'F': 3}[label]):
            x = 220 + note * 115
            draw.ellipse((x - 8, top + 27, x + 8, top + 39), fill='black')
            draw.line((x + 8, top + 33, x + 8, top - 32), fill='black', width=3)
        draw.text((120, top + 80), label, fill='black', font=font)
    return frame


def sequence_video(windows, base):
    for index, image in enumerate(windows):
        image.save(base / f'window-{index:02d}.png')
    path = base / 'sequence.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '1/2', '-i', str(base / 'window-%02d.png'), '-r', '4', '-pix_fmt', 'yuv420p', str(path)], check=True)
    return path


class OrderedConversionTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli
    def test_neighbor_overlap_keeps_later_repeated_segment_and_stable_order(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('BCD', partial_top=True, partial_bottom=True), window('CDA')], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(len(result['rows']), 5, 'expected ordered A B C D A, including later A')
            self.assertEqual(len(result['seams']), 2)
            self.assertTrue(result['boundaries']['start']['image'])
            self.assertTrue(result['boundaries']['end']['image'])
            self.assertEqual(result['boundaries']['end']['timestamp'], 5.75, 'must retain actual last decoded frame at 4 fps')
            for seam in result['seams']:
                self.assertEqual(seam['overlap_rows'], 2)
                self.assertTrue((base / 'result' / seam['before']['image']).exists())
                self.assertTrue((base / 'result' / seam['after']['image']).exists())
                self.assertLess(seam['before']['timestamp'], seam['after']['timestamp'])
            # Count note stems independently in each delivered row: A B C D A.
            counts = []
            for row in result['rows']:
                image = Image.open(base / 'result' / row['image']).convert('L')
                import numpy as np
                dark = np.asarray(image) < 100
                # Stems lie above the first horizontal staff and span at least 25 px.
                long_lines = np.where(dark.sum(axis=1) > 900)[0]
                above = dark[:long_lines[0]]
                xs = np.where(above.sum(axis=0) >= 25)[0]
                counts.append(sum(i == 0 or x > xs[i - 1] + 1 for i, x in enumerate(xs)))
            self.assertEqual(counts, [4, 5, 6, 7, 4])
            _, again = self.run_cli(source, base / 'again')
            first_hashes = [hashlib.sha256((base / 'result' / row['image']).read_bytes()).hexdigest() for row in result['rows']]
            second_hashes = [hashlib.sha256((base / 'again' / row['image']).read_bytes()).hexdigest() for row in again['rows']]
            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual([row['timestamp'] for row in result['rows']], [row['timestamp'] for row in again['rows']])

    def test_slow_scroll_uses_accumulated_motion_and_keeps_only_complete_rows(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            # Draw a long source page independently, then expose translated windows.
            page = Image.new('RGB', (1280, 1500), 'white')
            draw = ImageDraw.Draw(page)
            font = ImageFont.truetype(FONT, 28)
            draw.text((130, 75), 'Scroll song  tempo 96  4/4', fill='black', font=font)
            for top, label in zip([220, 440, 660, 880, 1100], 'ABCDA'):
                for line in range(5):
                    draw.line((110, top + line * 12, 1170, top + line * 12), fill='black', width=2)
                for note in range({'A': 4, 'B': 5, 'C': 6, 'D': 7}[label]):
                    x = 220 + note * 115
                    draw.ellipse((x - 8, top + 27, x + 8, top + 39), fill='black')
                    draw.line((x + 8, top + 33, x + 8, top - 32), fill='black', width=3)
                draw.text((120, top + 80), label, fill='black', font=font)
            windows = []
            for offset in [0, 60, 70, 80, 140, 150, 160, 280, 290, 300, 360, 440]:
                image = Image.new('RGB', (1280, 960), '#303030')
                image.paste(page.crop((70, 40 + offset, 1211, 911 + offset)), (70, 40))
                windows.append(image)
            source = sequence_video(windows, base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(len(result['rows']), 5)
            self.assertEqual(len(result['seams']), 2)

    def test_nonoverlapping_window_waits_with_unconfirmed_candidates(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('DEF')], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'waiting')
            self.assertFalse(result['complete'])
            self.assertEqual(len(result['rows']), 3)
            self.assertEqual(len(result['candidate_rows']), 3)
            issue = result['issues'][0]
            self.assertEqual(issue['kind'], 'no_overlap')
            self.assertEqual(issue['position'], 3)
            self.assertTrue(issue['choices'])
            self.assertTrue((base / 'result' / issue['image']).exists())
            self.assertFalse((base / 'result/score.pdf').exists())

    def test_unrecovered_final_edge_row_waits_instead_of_claiming_complete(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([window('ABC'), window('BCD', partial_bottom=True)], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'waiting')
            self.assertEqual(result['issues'][0]['kind'], 'end_gap')
            self.assertEqual(result['issues'][0]['position'], 4)
            self.assertTrue((base / 'result' / result['issues'][0]['image']).exists())
            self.assertFalse((base / 'result/score.pdf').exists())


if __name__ == '__main__':
    unittest.main()
