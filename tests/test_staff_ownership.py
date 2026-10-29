"""Vertical-only evidence, whole annotations and actual PDF row attribution."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
import test_staff_boundaries as boundary_fixture


def base():
    image = Image.new('RGB', (640, 400), 'white')
    draw = ImageDraw.Draw(image)
    for top in (80, 230):
        for offset in range(5):
            draw.line((20, top + offset * 8, 620, top + offset * 8), fill='black')
    draw.rectangle((0, 0, 1, 399), fill=(227, 227, 227))
    return image


class VerticalOwnership(unittest.TestCase):
    render_parts = boundary_fixture.StaffBoundaries.render_parts

    def assert_mark(self, image, color, row):
        with tempfile.TemporaryDirectory() as temporary:
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(len(parts), 2, result['boundary_analysis'])
            y, x = np.where((np.asarray(image) == color).all(axis=2))
            dy, dx = np.where((np.asarray(parts[row]) == color).all(axis=2))
            self.assertEqual(dx.tolist(), x.tolist())
            self.assertEqual(len(set((y - dy).tolist())), 1)
            self.assertFalse((np.asarray(parts[1 - row]) == color).all(axis=2).any())
            return result

    def test_lower_open_circle_uses_same_column_not_euclidean_neighbor(self):
        for color in ((10, 90, 10), (235, 235, 235), (250, 220, 250)):
            with self.subTest(color=color):
                image = base()
                draw = ImageDraw.Draw(image)
                draw.ellipse((500, 175, 510, 185), outline=color)
                draw.line((496, 110, 496, 180), fill='black')
                draw.rectangle((500, 193, 510, 246), fill='black')
                result = self.assert_mark(image, color, 1)
                self.assertEqual(result['boundary_analysis']['boundaries'][0]['annotations'][0]['owner'], 2)

    def test_upper_mf_is_a_whole_annotation(self):
        image = base()
        ImageDraw.Draw(image).text((100, 135), 'mf', font=ImageFont.load_default(size=16), fill=(180, 0, 0))
        self.assert_mark(image, (180, 0, 0), 0)

    def test_frame_and_contained_text_follow_same_lower_staff(self):
        image = base()
        draw = ImageDraw.Draw(image)
        color = (10, 110, 10)
        draw.rectangle((60, 181, 98, 211), outline=color, width=2)
        draw.text((66, 186), 'A1', font=ImageFont.load_default(size=16), fill=color)
        self.assert_mark(image, color, 1)

    def test_rrl_column_conflicts_preserve_group(self):
        image = boundary_fixture.interleaved_score()
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=14)
        for x, letter in ((100, 'R'), (125, 'R'), (150, 'L')):
            draw.text((x, 165), letter, font=font, fill=(180, 0, 0))
        draw.rectangle((100, 110, 111, 160), fill='black')
        draw.rectangle((125, 185, 135, 246), fill='black')
        draw.rectangle((150, 185, 160, 246), fill='black')
        with tempfile.TemporaryDirectory() as temporary:
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(len(parts), 1)
            self.assertEqual(result['boundary_analysis']['boundaries'][0]['reason'], 'detached_mark_ambiguous')

    def test_sparse_rrl_cannot_be_assigned_letter_by_letter(self):
        image = base()
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=16)
        for x, letter in ((100, 'R'), (160, 'R'), (220, 'L')):
            draw.text((x, 150), letter, font=font, fill=(180, 0, 0))
        draw.rectangle((100, 110, 115, 140), fill='black')
        for x in (160, 220):
            draw.rectangle((x, 180, x + 15, 246), fill='black')
        with tempfile.TemporaryDirectory() as temporary:
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(len(parts), 1)
            records = result['boundary_analysis']['boundaries'][0]['annotations']
            self.assertEqual(len(records), 1)
            self.assertGreaterEqual(len(records[0]['components']), 3)
            self.assertIsNone(records[0]['owner'])

    def test_wide_frame_and_centered_text_are_one_annotation(self):
        image = base()
        draw = ImageDraw.Draw(image)
        color = (10, 110, 10)
        draw.rectangle((60, 160, 240, 220), outline=color, width=2)
        draw.text((130, 185), 'A1', font=ImageFont.load_default(size=16), fill=color)
        result = self.assert_mark(image, color, 1)
        records = result['boundary_analysis']['boundaries'][0]['annotations']
        self.assertEqual(len(records), 1)
        self.assertGreaterEqual(len(records[0]['components']), 3)

    def test_no_same_column_black_target_cannot_use_lateral_neighbor(self):
        image = base()
        draw = ImageDraw.Draw(image)
        draw.rectangle((625, 150, 635, 158), outline=(180, 0, 0))
        with tempfile.TemporaryDirectory() as temporary:
            result, parts = self.render_parts(image, Path(temporary))
            # Staff ink stops at x=620; lateral targets cannot support this mark.
            self.assertEqual(len(parts), 1)
            record = result['boundary_analysis']['boundaries'][0]['annotations'][0]
            self.assertEqual(record['paired_columns'], 0)


    def test_ray_direction_does_not_override_anchored_owner(self):
        from drum_score.staff_ownership import assign
        import cv2
        image = Image.new('RGB', (100, 180), 'white')
        draw = ImageDraw.Draw(image)
        for y in (20, 160):
            draw.line((10, y, 90, y), fill='black')
        draw.rectangle((40, 50, 50, 56), fill=(180, 0, 0))
        rgb = np.asarray(image)
        _, labels, stats, _ = cv2.connectedComponentsWithStats((rgb.min(axis=2) < 245).astype('uint8'))
        owners = np.zeros(len(stats), 'uint8')
        # Deliberately reversed direction: reference ownership is supplied by
        # established connections, not by which side of the symbol it hits.
        owners[int(labels[20, 30])] = 2
        owners[int(labels[160, 30])] = 1
        result, records, _ = assign(rgb, labels, stats, owners, top=0, begin=30, end=150, spacing=8)
        self.assertIsNotNone(result, records)
        self.assertEqual(records[0]['owner'], 2)

    def test_ray_budget_refuses_without_changing_delivery(self):
        from unittest.mock import patch
        image = base()
        ImageDraw.Draw(image).text((100, 135), 'mf', font=ImageFont.load_default(size=16), fill=(180, 0, 0))
        with tempfile.TemporaryDirectory() as temporary, patch('drum_score.staff_ownership.MAX_RAY_PIXELS', 1):
            result, parts = self.render_parts(image, Path(temporary))
            self.assertEqual(len(parts), 1)
            self.assertEqual(result['boundary_analysis']['boundaries'][0]['reason'], 'annotation_ray_limit')

    def test_unknown_annotations_do_not_become_reference_targets(self):
        from drum_score.staff_ownership import assign
        import cv2
        image = Image.new('RGB', (100, 180), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((10, 20, 90, 20), fill='black')
        draw.line((10, 160, 90, 160), fill='black')
        draw.rectangle((40, 110, 50, 116), fill='black')
        draw.rectangle((40, 140, 50, 146), fill='black')
        rgb = np.asarray(image)
        _, labels, stats, _ = cv2.connectedComponentsWithStats((rgb.min(axis=2) < 245).astype('uint8'))
        owners = np.zeros(len(stats), 'uint8')
        owners[int(labels[20, 30])] = 1
        owners[int(labels[160, 30])] = 2
        result, records, reason = assign(rgb, labels, stats, owners, top=0, begin=30, end=150, spacing=8)
        self.assertIsNotNone(result, records)
        self.assertEqual([r['owner'] for r in records], [2, 2])
        self.assertEqual(records[0]['median_lower_staff_distance'], 44)
        self.assertEqual(records[1]['median_upper_staff_distance'], 120)


if __name__ == '__main__':
    unittest.main()
