"""Page-order behavior through the public converter and actual media tools."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import drum_score


class PageTransitions(unittest.TestCase):
    def test_clean_native_page_cut_preserves_both_complete_pages_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pages = []
            for page in range(2):
                image = Image.new('RGB', (640, 520), 'white')
                draw = ImageDraw.Draw(image)
                for row, top in enumerate((130, 340)):
                    for line in range(5):
                        draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                    for note in range(5):
                        x = 60 + page * 250 + note * 37
                        draw.ellipse((x, top + 12, x + 10, top + 20), fill='black')
                        draw.line((x + 10, top - 28 - row * 3, x + 10, top + 17), fill='black', width=2)
                pages.append(image)
                for frame in range(page * 8, (page + 1) * 8):
                    image.save(root / f'frame-{frame:03d}.png')
            source = root / 'pages.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '4', '-i',
                str(root / 'frame-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result', options={'region_percent': [0, 0, 100, 100]})
            self.assertFalse(result['reliable'])
            self.assertEqual(result['staff_count'], 4)
            self.assertEqual(result['registration']['continuity'], 'unverified')
            self.assertIn('page_order_unverified', [item['code'] for item in result['warnings']])
            expected = Image.new('RGB', (640, 1040), 'white')
            for index, page in enumerate(pages):
                expected.paste(page, (0, index * 520))
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, expected.size)
                self.assertIsNone(ImageChops.difference(actual.convert('RGB'), expected).getbbox())
            transition = result['registration']['transitions'][0]
            self.assertEqual(transition['kind'], 'native_page_cut')
            before, after = transition['adjacent_native_samples']
            samples = result['samples']
            self.assertEqual(samples[before]['decode_sequence'], samples[after]['decode_sequence'])
            self.assertEqual(samples[after]['native_ordinal'], samples[before]['native_ordinal'] + 1)
            self.assertEqual(samples[after]['previous_native_pts'], samples[before]['pts'])
            self.assertLessEqual(result['registration']['refinement_requests'], 64)


if __name__ == '__main__':
    unittest.main()
