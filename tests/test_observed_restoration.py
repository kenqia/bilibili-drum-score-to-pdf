"""Public conversion uses real observed pixels, never a whitening estimate."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score import convert


def fixture(root, *, scrolling=True):
    sheet = Image.new('RGB', (640, 1600), 'white')
    draw = ImageDraw.Draw(sheet)
    rng = np.random.default_rng(89190)
    for y in range(40, 1500, 80):
        for line in range(5):
            draw.line((10, y + line * 5, 630, y + line * 5), fill='black')
        for x in rng.integers(20, 610, 12):
            draw.ellipse((int(x), y - 6, int(x) + 7, y + 3), fill='black')
            draw.line((int(x) + 7, y - 20, int(x) + 7, y), fill='black', width=2)
    if not scrolling:
        ImageDraw.Draw(sheet).rectangle((150, 55, 490, 83), fill=(155, 155, 155))
    for index in range(10):
        frame = sheet.crop((0, index * 37, 640, index * 37 + 520))
        if scrolling:
            for y in (55, 165, 275, 385):
                ImageDraw.Draw(frame).rectangle((150, y, 490, y + 28), fill=(155, 155, 155))
        frame.save(root / f'frame-{index:02d}.png')
    video = root / 'source.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(root / 'frame-%02d.png'),
                    '-c:v', 'ffv1', str(video)], check=True)
    return video, sheet


class ObservedRestoration(unittest.TestCase):
    def test_screen_watermark_restores_real_notes_and_records_exact_pixel_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, original = fixture(root)
            result = convert(video, root / 'result', options={'region_percent': [0, 0, 100, 100]})
            recovery = result['restoration']
            self.assertGreater(recovery['restored_pixels'], 1000)
            self.assertFalse(result['reliable'])
            with Image.open(root / 'result' / result['longshot']['path']) as restored:
                # Independent unoccluded original: this strip contains real dark notes.
                np.testing.assert_array_equal(np.array(restored)[170:380, 150:491],
                                              np.array(original)[170:380, 150:491])
                for block in recovery['blocks']:
                    sample = result['samples'][block['source_sample']]
                    self.assertEqual(block['source_pts'], sample['pts'])
                    self.assertEqual(block['source_time_base'], sample['time_base'])
                    with Image.open(root / 'result' / sample['path']) as source:
                        np.testing.assert_array_equal(np.array(restored.crop(block['target_box'])),
                                                      np.array(source.crop(block['source_box'])))
            self.assertTrue(result['pages'])
            self.assertTrue((root / 'result' / result['pdf']['path']).is_file())

    def test_moving_screen_cursor_restores_notes_and_keeps_real_colored_notation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sheet = fixture(root)
            original = sheet.crop((0, 0, 640, 520))
            # A colored source annotation is never a license to erase its pixels.
            ImageDraw.Draw(original).rectangle((80, 10, 95, 510), fill=(70, 120, 255))
            for index, x in enumerate((150, 300, 450)):
                frame = original.copy()
                ImageDraw.Draw(frame).rectangle((x, 10, x + 15, 510), fill=(70, 120, 255))
                frame.save(root / f'cursor-{index:02d}.png')
            video = root / 'cursor.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(root / 'cursor-%02d.png'),
                            '-c:v', 'ffv1', str(video)], check=True)
            result = convert(video, root / 'result', options={'region_percent': [0, 0, 100, 100]})
            self.assertGreater(result['restoration']['restored_pixels'], 5000)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                np.testing.assert_array_equal(np.array(actual), np.array(original))
