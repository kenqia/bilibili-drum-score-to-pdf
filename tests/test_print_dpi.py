"""Validate native row resolution through real video and the public CLI."""
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw
import test_conversion as base_tests

PRINTABLE_WIDTH_INCHES = (595.2755905511812 - 72) / 72


def dpi_frame(row_width):
    frame_width = row_width + 140
    frame_width += frame_width % 2
    frame = Image.new('RGB', (frame_width, 960), '#303030')
    draw = ImageDraw.Draw(frame)
    draw.rectangle((70, 40, 70 + row_width - 1, 910), fill='white')
    for top in (220, 440, 660):
        for line in range(5):
            draw.line((110, top + line * 12, row_width + 30, top + line * 12), fill='black', width=2)
        for x in (220, 345, 470, 595):
            draw.ellipse((x - 8, top + 27, x + 8, top + 39), fill='black')
            draw.line((x + 8, top + 33, x + 8, top - 32), fill='black', width=3)
    return frame


class PrintDpiTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli

    def convert_width(self, width, base):
        source = base_tests.video_from_image(dpi_frame(width), base, str(width))
        output = base / f'result-{width}'
        run, result = self.run_cli(source, output)
        return run, result, output

    def test_118_dpi_requires_clearer_input_without_pdf(self):
        with tempfile.TemporaryDirectory() as scratch:
            run, result, output = self.convert_width(858, Path(scratch))
            self.assertEqual(result['status'], 'failed', result)
            self.assertEqual(result['error']['code'], 'low_print_resolution')
            self.assertEqual(run.returncode, 2)
            self.assertFalse(result['complete'])
            self.assertIn('本地视频', result['error']['message'])
            self.assertFalse((output / 'score.pdf').exists())

    def test_150_dpi_uses_native_pixels_before_rounding(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, below, output = self.convert_width(1090, base)
            self.assertLess(1090 / PRINTABLE_WIDTH_INCHES, 150)
            self.assertEqual(below['status'], 'failed', below)
            self.assertEqual(below['error']['code'], 'low_print_resolution')
            self.assertFalse((output / 'score.pdf').exists())
            _, above, output = self.convert_width(1091, base)
            self.assertEqual(above['status'], 'success', above)
            self.assertTrue(above['complete'])
            self.assertEqual(above['quality']['effective_dpi']['status'], 'printable_candidate')
            self.assertTrue((output / 'score.pdf').exists())
            self.assertEqual([row['quality']['native_width'] for row in above['rows']], [1091] * 3)

    def test_200_dpi_classification_preserves_native_rows(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            for width, band in ((1453, 'printable_candidate'), (1454, 'high_quality_candidate')):
                with self.subTest(width=width):
                    _, result, output = self.convert_width(width, base)
                    self.assertEqual(result['status'], 'success', result)
                    self.assertTrue(result['complete'])
                    self.assertEqual(result['quality']['effective_dpi']['status'], band)
                    self.assertTrue((output / 'score.pdf').exists())
                    for row in result['rows']:
                        self.assertEqual(row['quality']['print_quality'], band)
                        with Image.open(output / row['image']) as image:
                            self.assertEqual(image.width, width)


if __name__ == '__main__':
    unittest.main()
