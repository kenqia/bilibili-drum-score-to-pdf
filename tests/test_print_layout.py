"""Public PDF relayout seam, with synthetic music and actual Poppler output."""
import sys
from pathlib import Path
import tempfile
import subprocess
import unittest
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class PrintLayout(unittest.TestCase):
    def test_rows_change_page_count_without_losing_colored_marks(self):
        from drum_score.print_layout import render
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 1800), 'white')
            draw = ImageDraw.Draw(image)
            for row in range(8):
                top = 60 + row * 210
                for line in range(5):
                    draw.line((20, top + line * 8, 620, top + line * 8), fill='black')
                draw.rectangle((70, top - 12, 75, top + 12), fill=(220, 20, 30))
            results = []
            for target in (2, 4):
                output = root / str(target)
                output.mkdir()
                result = render(image, output, paper='A4', rows=target)
                results.append(result)
                subprocess.run(['pdfimages', '-png', str(output / 'score.pdf'), str(output / 'ink')], check=True, capture_output=True)
                red = 0
                for path in output.glob('ink-*.png'):
                    with Image.open(path) as part:
                        red += sum(pixel == (220, 20, 30) for pixel in part.convert('RGB').get_flattened_data())
                self.assertEqual(red, 8 * 6 * 25)
            self.assertEqual([r['page_count'] for r in results], [4, 2])

    def test_extract_and_relayout_preserve_repeated_paint_order(self):
        from drum_score.print_layout import render, extract
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 800), 'white')
            draw = ImageDraw.Draw(image)
            for top in (70, 270, 470, 670):
                for line in range(5):
                    draw.line((20, top + line * 8, 620, top + line * 8), fill='black')
            first = root / 'first'
            first.mkdir()
            render(image, first, rows=2)
            with extract(first / 'score.pdf', first) as restored:
                second = root / 'second'
                second.mkdir()
                result = render(restored, second, rows=4, paper='A3')
            self.assertEqual(result['staff_count'], 4)
            self.assertEqual(result['page_count'], 1)

    def test_default_packs_sparse_rows_and_keeps_unsplittable_group(self):
        from drum_score.print_layout import render
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 2400), 'white')
            draw = ImageDraw.Draw(image)
            for top in range(100, 2350, 280):
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
            result = render(image, root)
            self.assertLessEqual(result['page_count'], 2)
            self.assertEqual(result['staff_count'], 9)
            # A mark joining all rows is never removed to force pagination.
            joined = root / 'joined'
            joined.mkdir()
            draw.line((10, 0, 10, 2399), fill=(255, 210, 0), width=2)
            preserved = render(image, joined, rows=1)
            self.assertEqual(preserved['page_count'], 1)
            self.assertEqual(preserved['actual_rows'], 9)
            self.assertTrue(preserved['adjusted'])
