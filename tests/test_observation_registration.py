"""Paired observation errors and real notation differences at the conversion CLI."""
from pathlib import Path
import tempfile
import subprocess
import unittest
import cv2
import numpy as np
from PIL import Image, ImageDraw
import test_conversion as base_tests
from test_ordered_conversion import sequence_video
from test_cursor_quality import cursor_window


def observed(image, kind):
    pixels = np.asarray(image)
    if kind == 'vertical':
        matrix = np.float32([[1, 0, 0], [0, 1, 2]])
    elif kind == 'subpixel':
        matrix = np.float32([[1.002, 0, -.8], [0, 1.002, -.4]])
    elif kind == 'antialias':
        matrix = np.float32([[1, 0, .35], [0, 1, .35]])
    else:
        return image.copy()
    return Image.fromarray(cv2.warpAffine(pixels, matrix, image.size, borderValue=(48, 48, 48)))


class ObservationRegistrationTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli

    def check_pair(self, kind, changed=False):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            middle, clean = cursor_window(441), cursor_window()
            if changed:
                for image in [middle, clean]:
                    draw = ImageDraw.Draw(image)
                    if kind == 'subpixel':
                        draw.line((343, 181, 343, 187), fill='black', width=3)
                    elif kind == 'antialias':
                        draw.ellipse((695, 228, 699, 232), fill='black')
                        draw.line((699, 230, 699, 217), fill='black', width=2)
                    else:
                        draw.ellipse((700, 236, 704, 240), fill='black')
            source = sequence_video([cursor_window(211), observed(middle, kind), observed(clean, kind)], base)
            if kind == 'compression':
                encoded = base / 'h264.mp4'
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-c:v', 'libx264', '-crf', '26', '-pix_fmt', 'yuv420p', str(encoded)], check=True)
                source = encoded
            run, result = self.run_cli(source, base / 'result')
            if changed:
                self.assertEqual(result['status'], 'waiting', result)
                self.assertFalse(result['complete'])
                self.assertFalse((base / 'result/score.pdf').exists())
            else:
                self.assertEqual(result['status'], 'success', result)
                self.assertEqual(len(result['rows']), 3)
                self.assertTrue(result['rows'][0]['cursor_recoveries'])
                self.assertTrue((base / 'result/score.pdf').exists())
                row = result['rows'][0]
                original = np.asarray(Image.open(base / 'result' / row['original_image']))
                # Output really uses the selected decoded crop, never registered pixels.
                import io
                decoded = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(row['timestamp']), '-i', str(source), '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-threads', '1', '-'], capture_output=True, check=True).stdout
                expected = np.asarray(Image.open(io.BytesIO(decoded)).convert('RGB').crop(row['bbox']))
                np.testing.assert_array_equal(original, expected)

    def test_vertical_offset_recovers_actual_pixels(self):
        self.check_pair('vertical')

    def test_vertical_offset_cannot_hide_ghost_note(self):
        self.check_pair('vertical', True)

    def test_subpixel_scale_recovers_actual_pixels(self):
        self.check_pair('subpixel')

    def test_subpixel_scale_cannot_hide_extended_stem(self):
        self.check_pair('subpixel', True)

    def test_compression_recovers_actual_pixels(self):
        self.check_pair('compression')

    def test_compression_cannot_hide_ghost_note(self):
        self.check_pair('compression', True)

    def test_antialias_cursor_recovers_actual_pixels(self):
        self.check_pair('antialias')

    def test_antialias_cursor_cannot_hide_grace_note(self):
        self.check_pair('antialias', True)

    def test_large_displacement_cannot_borrow_later_cursor_coverage(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            matrix = np.float32([[1, 0, 0], [0, 1, 12]])
            shifted = [Image.fromarray(cv2.warpAffine(np.asarray(image), matrix, image.size, borderValue=(48, 48, 48)))
                       for image in [cursor_window(441), cursor_window()]]
            source = sequence_video([cursor_window(211)] + shifted, base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'waiting', result)
            self.assertFalse(result['complete'])
            self.assertFalse((base / 'result/score.pdf').exists())
