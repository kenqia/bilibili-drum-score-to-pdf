"""General candidate vetoes and complete crops, without codec-specific contracts."""
from pathlib import Path
import sys
import unittest
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'))
from cursor_detect import cursor_occluded, obstruction_detected, stationary_overlays
from score_detect import analyze_frame
from score_fixtures import score_frame


class DetectionTests(unittest.TestCase):
    def test_vertical_cursor_crossing_black_staff_is_unusable(self):
        row = Image.new('RGB', (1200, 200), 'white')
        draw = ImageDraw.Draw(row)
        draw.rectangle((300, 25, 335, 175), fill=(205, 223, 237))
        for y in range(70, 119, 12):
            draw.line((20, y, 1180, y), fill='black', width=2)
        self.assertTrue(cursor_occluded(row, 12))

    def test_horizontal_colored_notation_is_kept(self):
        row = Image.new('RGB', (1200, 200), 'white')
        ImageDraw.Draw(row).rectangle((100, 90, 550, 100), fill='blue')
        self.assertFalse(cursor_occluded(row, 12))

    def test_broad_staff_cover_vetoes_candidate(self):
        row = Image.new('RGB', (1200, 200), 'white')
        draw = ImageDraw.Draw(row)
        for y in range(70, 119, 12):
            draw.line((20, y, 1180, y), fill='black', width=2)
        self.assertFalse(obstruction_detected(row, 70, 12))
        draw.rectangle((100, 65, 650, 125), fill='white')
        self.assertTrue(obstruction_detected(row, 70, 12))

    def test_fixed_screen_overlay_is_detected_when_score_translates(self):
        old = score_frame()
        new = Image.fromarray(np.roll(np.asarray(old), -100, axis=0))
        for frame in (old, new):
            draw = ImageDraw.Draw(frame)
            draw.rectangle((930, 120, 1150, 190), fill='white')
            draw.text((950, 140), 'PLAYER OVERLAY', fill=(160, 160, 160), stroke_width=1)
        boxes = stationary_overlays(old, new, 12)
        self.assertTrue(any(x0 < 1100 and x1 > 950 and y0 < 165 and y1 > 140 for x0, y0, x1, y1 in boxes))

    def test_header_is_separate_and_rows_include_marks_above_and_below_staff(self):
        result = analyze_frame(score_frame())
        self.assertEqual(len(result['groups']), 3)
        self.assertLessEqual(result['header_bbox'][1], 75)
        self.assertGreaterEqual(result['header_bbox'][3], 103)
        for index, (group, (top, bottom)) in enumerate(zip(result['groups'], result['row_bounds'])):
            self.assertLessEqual(top + result['bbox'][1], 220 + index * 220 - 32)
            self.assertGreaterEqual(bottom + result['bbox'][1], 220 + index * 220 + 105)
