"""Actual PDF evidence for complete rows with interleaved vertical extents."""
from collections import Counter
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def interleaved_score():
    image = Image.new('RGB', (640, 400), 'white')
    draw = ImageDraw.Draw(image)
    for top in (80, 230):
        for offset in range(5):
            draw.line((20, top + offset * 8, 620, top + offset * 8), fill='black')
        draw.line((600, top, 600, top + 32), fill='black')
    # Both stems touch their own staff, but their vertical extents overlap.
    draw.line((200, 100, 200, 190), fill=(20, 30, 150), width=3)
    draw.line((400, 155, 400, 246), fill=(150, 30, 20), width=3)
    draw.rectangle((30, 195, 50, 210), outline=(0, 100, 0), width=2)
    draw.ellipse((500, 194, 510, 204), outline=(235, 235, 235))
    draw.line((45, 210, 45, 246), fill=(0, 100, 0))
    draw.line((505, 204, 505, 246), fill=(235, 235, 235))
    draw.point((300, 170), fill=(241, 241, 241))
    return image


class StaffBoundaries(unittest.TestCase):
    def render_parts(self, image, root):
        from drum_score.print_layout import render
        result = render(image, root, rows=1)
        subprocess.run(['pdfimages', '-png', str(root / 'score.pdf'), str(root / 'part')],
                       check=True, capture_output=True)
        parts = []
        for path in sorted(root.glob('part-*.png')):
            with Image.open(path) as part:
                parts.append(part.convert('RGB'))
        expected = Counter(pixel for pixel in image.get_flattened_data() if min(pixel) < 255)
        actual = Counter(pixel for part in parts for pixel in part.get_flattened_data() if min(pixel) < 255)
        self.assertEqual(actual, expected, 'Source RGB pixels were lost, duplicated or recolored')
        return result, parts

    def test_gray_edge_and_faint_pixel_do_not_join_all_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Image.new('RGB', (640, 600), (250, 250, 250))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 1, 599), fill=(227, 227, 227))
            for top in (80, 240, 400):
                for offset in range(5):
                    draw.line((20, top + offset * 8, 620, top + offset * 8), fill='black')
            # A different faint pixel on every line vetoes all straight cuts.
            for y in range(600):
                draw.point((250 + (y % 2) * 100, y), fill=(241, 241, 241))
            before = image.tobytes()
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(result['page_count'], 3)
            self.assertEqual(result['actual_rows'], 1)
            self.assertEqual(len(parts), 3)
            self.assertEqual(image.tobytes(), before)

    def test_pale_compression_island_is_preserved_whole(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Image.new('RGB', (640, 400), 'white')
            draw = ImageDraw.Draw(image)
            for top in (80, 230):
                for offset in range(5):
                    draw.line((20, top + offset * 8, 620, top + offset * 8), fill='black')
            draw.rectangle((0, 0, 1, 399), fill=(227, 227, 227))
            for point in ((310, 168), (310, 169), (311, 169), (310, 170), (310, 171)):
                draw.point(point, fill=(241, 241, 241))
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(result['page_count'], 2)
            self.assertEqual(result['boundary_analysis']['boundaries'][0]['reason'],
                             'component_safe_path')
            islands = [np.argwhere((np.asarray(part) == (241, 241, 241)).all(axis=2))
                       for part in parts]
            self.assertEqual(sorted(map(len, islands)), [0, 5])
            coordinates = next(points for points in islands if len(points))
            self.assertEqual(np.ptp(coordinates, axis=0).tolist(), [3, 1])

    def test_detached_open_circle_does_not_acquire_an_inferred_staff(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Image.new('RGB', (640, 400), 'white')
            draw = ImageDraw.Draw(image)
            for top in (80, 230):
                for offset in range(5):
                    draw.line((20, top + offset * 8, 620, top + offset * 8), fill='black')
            draw.rectangle((0, 0, 1, 399), fill=(227, 227, 227))
            draw.line((100, 110, 100, 155), fill='black')
            draw.ellipse((490, 169, 498, 177), outline=(10, 90, 10))
            draw.line((495, 184, 495, 246), fill='black')
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(result['page_count'], 1)
            self.assertEqual(result['boundary_analysis']['boundaries'][0]['reason'],
                             'detached_mark_ambiguous')

    def test_interleaved_stems_and_anchored_marks_stay_whole(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = interleaved_score()
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(result['page_count'], 2)
            self.assertEqual(result['actual_rows'], 1)
            self.assertEqual(len(parts), 2)
            for color, row in (((20, 30, 150), 0), ((150, 30, 20), 1),
                               ((0, 100, 0), 1), ((235, 235, 235), 1)):
                original = np.asarray(image)
                source_y, source_x = np.where((original == color).all(axis=2))
                target_y, target_x = np.where((np.asarray(parts[row]) == color).all(axis=2))
                self.assertEqual(target_x.tolist(), source_x.tolist())
                self.assertEqual(len(set((source_y - target_y).tolist())), 1,
                                 'A complete mark changed shape or internal position')
                self.assertFalse((np.asarray(parts[1 - row]) == color).all(axis=2).any())

    def test_ambiguous_detached_boxes_text_and_dark_dots_keep_rows_together(self):
        for mark in ('box', 'dark_dot', 'near_text'):
            with self.subTest(mark=mark), tempfile.TemporaryDirectory() as temporary:
                image = interleaved_score()
                draw = ImageDraw.Draw(image)
                if mark == 'box':
                    draw.rectangle((65, 150, 102, 180), outline='black', width=2)
                    draw.text((70, 155), 'A1', fill='black')
                elif mark == 'near_text':
                    from PIL import ImageFont
                    font = ImageFont.load_default(size=10)
                    for x, letter in ((100, 'R'), (124, 'R'), (148, 'L')):
                        draw.text((x, 170), letter, font=font, fill='black')
                    draw.line((103, 110, 103, 170), fill='black')
                    draw.line((127, 181, 127, 246), fill='black')
                    draw.line((150, 181, 150, 246), fill='black')
                else:
                    draw.point((320, 170), fill='black')
                result, parts = self.render_parts(image, Path(temporary))
                self.assertEqual(len(parts), 1)
                self.assertEqual(result['boundary_analysis']['boundaries'][0]['reason'],
                                 'detached_mark_ambiguous')

    def test_shaped_padding_budget_retains_original_group(self):
        from drum_score.imaging import system_groups
        from drum_score.staff_boundaries import split
        image = interleaved_score()
        groups, staffs = system_groups(image, detailed=True)
        _, analysis = split(image, groups, staffs, max_output_pixels=image.width * image.height)
        self.assertEqual(analysis['max_staffs_per_group'], 2)
        self.assertEqual(analysis['boundaries'][0]['reason'], 'output_pixel_limit')

    def test_real_cross_row_and_faint_cross_row_marks_remain_grouped(self):
        for color in ((255, 210, 0), (235, 235, 235), (250, 220, 250)):
            with self.subTest(color=color), tempfile.TemporaryDirectory() as temporary:
                image = interleaved_score()
                ImageDraw.Draw(image).line((15, 50, 15, 350), fill=color, width=2)
                result, parts = self.render_parts(image, Path(temporary))
                self.assertEqual(result['page_count'], 1)
                self.assertEqual(result['actual_rows'], 2)
                self.assertEqual(len(parts), 1)
                self.assertEqual(result['boundary_analysis']['max_staffs_per_group'], 2)

    def test_nonuniform_edge_mark_and_analysis_limits_keep_the_group(self):
        from unittest.mock import patch
        from drum_score.imaging import system_groups
        from drum_score.staff_boundaries import split
        image = interleaved_score()
        draw = ImageDraw.Draw(image)
        draw.line((0, 0, 0, 399), fill=(227, 227, 227))
        draw.rectangle((0, 150, 5, 160), fill='black')
        groups, staffs = system_groups(image, detailed=True)
        _, analysis = split(image, groups, staffs)
        self.assertEqual(analysis['gray_edge_columns'], [])
        self.assertEqual(analysis['max_staffs_per_group'], 2)
        for option in ('MAX_BAND_PIXELS', 'MAX_WIDTH', 'MAX_PROBES', 'MAX_TOTAL_RUNS'):
            with self.subTest(option=option), patch('drum_score.staff_boundaries.' + option, 0):
                _, analysis = split(interleaved_score(), groups, staffs)
                self.assertEqual(analysis['max_staffs_per_group'], 2)


if __name__ == '__main__':
    unittest.main()
