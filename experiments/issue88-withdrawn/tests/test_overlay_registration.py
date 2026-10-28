"""Independent geometry evidence for screen overlays; RGB remains source data."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.fixed_overlays import detect
from drum_score.imaging import register
from drum_score.video_seek import ConversionError


class OverlayRegistration(unittest.TestCase):
    def test_gray_screen_watermark_bootstraps_from_distinct_dark_notation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 1600), 'white')
            draw = ImageDraw.Draw(sheet)
            rng = np.random.default_rng(89190)
            for y in range(40, 1500, 80):
                for line in range(5):
                    draw.line((10, y + line * 5, 630, y + line * 5), fill='black')
                for x in rng.integers(20, 610, 12):
                    draw.ellipse((int(x), y - 6, int(x) + 7, y + 3), fill='black')
                    draw.line((int(x) + 7, y - 20, int(x) + 7, y), fill='black', width=2)
            paths = []
            for index in range(10):
                image = sheet.crop((0, index * 37, 640, index * 37 + 520))
                ink = ImageDraw.Draw(image)
                # Opaque neutral gray, deliberately dominating the row profile.
                for y in (55, 165, 275, 385):
                    ink.rectangle((150, y, 490, y + 28), fill=(155, 155, 155))
                path = root / f'{index}.png'
                image.save(path)
                paths.append(path)
            invalid, comparisons = detect(paths, (0, 0, 640, 520))
            self.assertGreaterEqual(comparisons, 3)
            self.assertGreater(int(invalid.sum()), 20000)
            placements = register(paths, (0, 0, 640, 520), invalid=invalid)
            self.assertEqual([item['offset'] for item in placements], list(range(0, 370, 37)))

    def test_gray_bootstrap_does_not_choose_between_repeated_music_positions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 1600), 'white')
            draw = ImageDraw.Draw(sheet)
            for y in range(30, 1600, 80):
                for line in range(5):
                    draw.line((10, y + line * 5, 630, y + line * 5), fill='black')
                draw.ellipse((100, y - 6, 107, y + 3), fill='black')
                draw.line((107, y - 20, 107, y), fill='black', width=2)
            paths = []
            for index in range(10):
                frame = sheet.crop((0, index * 40, 640, index * 40 + 520))
                ImageDraw.Draw(frame).rectangle((150, 70, 490, 105), fill=(155, 155, 155))
                path = root / f'{index}.png'
                frame.save(path)
                paths.append(path)
            invalid, comparisons = detect(paths, (0, 0, 640, 520))
            self.assertEqual(comparisons, 0)
            self.assertFalse(invalid.any())

    def test_moving_colored_cursor_and_highlight_do_not_move_the_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 520), 'white')
            draw = ImageDraw.Draw(image)
            for y in (80, 220, 360):
                for line in range(5):
                    draw.line((20, y + line * 8, 620, y + line * 8), fill='black')
                draw.ellipse((91, y + 12, 106, y + 22), fill='black')
                draw.line((106, y - 28, 106, y + 18), fill='black', width=2)
            paths = []
            for index, x in enumerate((150, 360, 500)):
                frame = image.copy()
                draw = ImageDraw.Draw(frame)
                draw.rectangle((x, 15, x + 35, 500), fill=(70, 120, 255))
                draw.rectangle((200, 170 + index * 20, 300, 185 + index * 20), fill=(240, 220, 100))
                path = root / f'{index}.png'
                frame.save(path)
                paths.append(path)
            placements = register(paths, (0, 0, 640, 520))
            self.assertEqual([item['offset'] for item in placements], [0, 0, 0])
