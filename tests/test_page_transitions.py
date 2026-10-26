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


    def test_edge_fragment_is_replaced_only_by_a_unique_complete_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pages = []
            for page, tops in enumerate(((130, 340), (40, 300))):
                image = Image.new('RGB', (640, 520), 'white')
                draw = ImageDraw.Draw(image)
                for row, top in enumerate(tops):
                    for line in range(5):
                        draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                    for note in range(5):
                        x = 60 + page * 250 + note * 37
                        draw.ellipse((x, top + 12, x + 10, top + 20), fill='black')
                        draw.line((x + 10, top - 28 - row * 3, x + 10, top + 17), fill='black', width=2)
                if page:
                    draw.line((250, 8, 250, 32), fill='black', width=2)
                    draw.line((250, 8, 460, 8), fill='black', width=2)
                    draw.text((258, 13), '1.', fill='black')
                pages.append(image)
            pages[0].paste(pages[1].crop((0, 0, 640, 20)), (0, 500))
            for page, image in enumerate(pages):
                for frame in range(page * 8, (page + 1) * 8):
                    image.save(root / f'edge-{frame:03d}.png')
            source = root / 'edge.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '4', '-i',
                str(root / 'edge-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result', options={'region_percent': [0, 0, 100, 100]})
            self.assertEqual(result['staff_count'], 4)
            transition = result['registration']['transitions'][0]
            self.assertEqual(transition['edge_replacement']['target_sample'], transition['sample'])
            self.assertGreater(transition['edge_replacement']['independent_ink_pixels'], 64)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertIsNone(ImageChops.difference(actual.crop((0, 0, 640, 430)),
                    pages[0].crop((0, 0, 640, 430))).getbbox())
                self.assertIsNone(ImageChops.difference(actual.crop((0, actual.height - 520, 640, actual.height)),
                    pages[1]).getbbox())


    def test_native_page_order_does_not_excuse_returning_pages_or_hidden_short_pages(self):
        pages = []
        for page in range(3):
            image = Image.new('RGB', (640, 520), 'white')
            draw = ImageDraw.Draw(image)
            for row, top in enumerate((130, 340)):
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                for note in range(5):
                    x = 45 + page * 180 + note * 30
                    draw.ellipse((x, top + 12, x + 10, top + 20), fill='black')
                    draw.line((x + 10, top - 28 - row * 3, x + 10, top + 17), fill='black', width=2)
            pages.append(image)
        animation = Image.new('RGB', (640, 520), '#b0b0b0')
        cut = pages[0].copy()
        ImageDraw.Draw(cut).line((180, 500, 180, 519), fill='black', width=3)
        almost_same = pages[0].copy()
        ImageDraw.Draw(almost_same).rectangle((180, 220, 190, 230), fill='black')
        pale_almost_same = pages[0].copy()
        ImageDraw.Draw(pale_almost_same).rectangle((180, 220, 190, 230), fill=(195, 195, 195))
        scenarios = {
            'pale_small_unique_mark': [pages[0]] * 8 + [pale_almost_same] + [pages[1]] * 8,
            'small_unique_mark': [pages[0]] * 8 + [almost_same] + [pages[1]] * 8,
            'return_to_old_page': [pages[0]] * 8 + [pages[1]] * 8 + [pages[0]] * 8,
            'short_unique_page': [pages[0]] * 8 + [pages[2]] + [pages[1]] * 8,
            'transition_without_coverage': [pages[0]] * 8 + [animation] + [pages[1]] * 8,
            'unmatched_cut_stem': [cut] * 8 + [pages[1]] * 8,
        }
        for name, frames in scenarios.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for index, image in enumerate(frames):
                    image.save(root / f'unsafe-{index:03d}.png')
                source = root / 'unsafe.mkv'
                subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '4', '-i',
                    str(root / 'unsafe-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
                with self.assertRaises(drum_score.ConversionError) as caught:
                    drum_score.convert(source, root / 'result', options={
                        'region_percent': [0, 0, 100, 100], 'end_seconds': len(frames) / 4})
                self.assertIn(caught.exception.code, ('discontinuity', 'incomplete_score'))
                self.assertFalse((root / 'result').exists())


    def test_fragment_replacement_refuses_unique_pale_notation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pages = []
            for page, tops in enumerate(((130, 340), (40, 300))):
                image = Image.new('RGB', (640, 520), 'white')
                draw = ImageDraw.Draw(image)
                for row, top in enumerate(tops):
                    for line in range(5):
                        draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                    for note in range(5):
                        x = 60 + page * 250 + note * 37
                        draw.ellipse((x, top + 12, x + 10, top + 20), fill='black')
                        draw.line((x + 10, top - 28 - row * 3, x + 10, top + 17), fill='black', width=2)
                if page:
                    draw.line((250, 8, 250, 32), fill='black', width=2)
                    draw.line((250, 8, 460, 8), fill='black', width=2)
                    draw.text((258, 13), '1.', fill='black')
                pages.append(image)
            pages[0].paste(pages[1].crop((0, 0, 640, 20)), (0, 500))
            ImageDraw.Draw(pages[0]).text((100, 508), 'p', fill=(195, 195, 195))
            for page, image in enumerate(pages):
                for frame in range(page * 8, (page + 1) * 8):
                    image.save(root / f'pale-{frame:03d}.png')
            source = root / 'pale.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '4', '-i',
                str(root / 'pale-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result', options={'region_percent': [0, 0, 100, 100]})
            self.assertIn(caught.exception.code, ('discontinuity', 'incomplete_score'))
            self.assertFalse((root / 'result').exists())


    def test_native_page_window_cannot_exceed_shared_rgb_refinement_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
                image.save(root / f'page-{page}.png')
            source = root / 'high-rate.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-t', '1', '-i', str(root / 'page-0.png'),
                '-loop', '1', '-t', '1', '-i', str(root / 'page-1.png'), '-filter_complex',
                '[0:v][1:v]concat=n=2:v=1:a=0,fps=256', '-c:v', 'ffv1', str(source)], check=True)
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result', options={'region_percent': [0, 0, 100, 100]})
            self.assertEqual(caught.exception.code, 'discontinuity')
            self.assertIn('预算', str(caught.exception))
            self.assertFalse((root / 'result').exists())


if __name__ == '__main__':
    unittest.main()
