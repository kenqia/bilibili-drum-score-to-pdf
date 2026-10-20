"""Conservative compact pagination on synthetic continuous score images."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'))
import longshot
import score_task


def compact_fixture(root, heights=None, spacing=8):
    heights = heights or [200] * 10
    image = Image.new('L', (640, sum(heights)), 249)
    draw, rows, top = ImageDraw.Draw(image), [], 0
    for height in heights:
        for line in range(5):
            y = round(top + 80 + line * spacing)
            draw.line((25, y, 615, y), fill=0)
        draw.ellipse((90, top + 90, 100, top + 98), fill=0)
        rows.append({'kind': 'system', 'bbox': [0, top, 640, top + height],
                     'width': 640, 'height': height, 'staff_top': 80,
                     'staff_spacing': spacing, 'staves': [{'top': 80, 'spacing': spacing}]})
        top += height
    path = root / 'longshot.png'
    image.save(path)
    image.close()
    return {'regions': rows, 'longshot': {'image': {'path': path.name,
        'sha256': score_task.digest(path), 'width': 640, 'height': top}}}


class CompactLayout(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_reduces_three_pages_to_two_at_largest_common_scale(self):
        record = compact_fixture(self.root)
        strips, placements = longshot._continuous_pages(self.root, record)
        self.assertEqual([s['crop_bbox'] for s in strips],
                         [[0, 0, 640, 1000], [0, 1000, 640, 2000]])
        base = (A4[0] - 48) / 640
        scale = (A4[1] - 48) / 1000
        self.assertAlmostEqual(placements[0]['scale'], scale)
        self.assertGreaterEqual(scale / base, .9)
        self.assertEqual(len({p['scale'] for p in placements}), 1)
        self.assertGreater(placements[0]['bbox'][0], 24)
        self.assertAlmostEqual(placements[0]['bbox'][0], A4[0] - placements[0]['bbox'][2])
        self.assertEqual([i for s in strips for i in s['source_regions']], list(range(10)))

    def test_preserves_original_size_without_page_savings_or_beyond_ten_percent(self):
        for heights in ([180] * 10, [210] * 10):
            with self.subTest(heights=heights):
                record = compact_fixture(self.root, heights)
                strips, placements = longshot._continuous_pages(self.root, record)
                self.assertEqual(len(strips), 2 if heights[0] == 180 else 3)
                self.assertEqual(placements[0]['scale'], (A4[0] - 48) / 640)
                self.assertEqual(placements[0]['bbox'][0], 24)

    def test_small_or_unknown_staff_geometry_keeps_original_size(self):
        for spacing in (4.8, 3):
            with self.subTest(spacing=spacing):
                record = compact_fixture(self.root, spacing=spacing)
                strips, placements = longshot._continuous_pages(self.root, record)
                self.assertEqual(len(strips), 3)
                self.assertEqual(placements[0]['scale'], (A4[0] - 48) / 640)
        for row in record['regions']:
            row.pop('staves')
            row.pop('staff_spacing')
        self.assertEqual(len(longshot._continuous_pages(self.root, record)[0]), 3)

    def test_ink_or_joined_systems_prevent_unsafe_page_savings(self):
        record = compact_fixture(self.root)
        path = self.root / record['longshot']['image']['path']
        with Image.open(path) as source:
            image = source.copy()
        ImageDraw.Draw(image).ellipse((380, 995, 390, 1005), outline=0)
        image.save(path)
        image.close()
        record['longshot']['image']['sha256'] = score_task.digest(path)
        strips, _ = longshot._continuous_pages(self.root, record)
        self.assertEqual(len(strips), 3)
        record = compact_fixture(self.root)
        joined = record['regions'][4]
        joined.update(height=400, bbox=[0, 800, 640, 1200],
                      staves=[{'top': 80, 'spacing': 8}, {'top': 280, 'spacing': 8}])
        record['regions'].pop(5)
        self.assertEqual(len(longshot._continuous_pages(self.root, record)[0]), 3)

    def test_manual_breaks_keep_original_scale_and_height_refusal(self):
        record = compact_fixture(self.root)
        strips, placements = longshot._continuous_pages(self.root, record, page_breaks=[600, 1400])
        self.assertEqual(len(strips), 3)
        self.assertEqual(placements[0]['scale'], (A4[0] - 48) / 640)
        for cuts in ([1000], []):
            with self.subTest(cuts=cuts), self.assertRaises(score_task.ReconstructionError):
                longshot._continuous_pages(self.root, record, page_breaks=cuts)

    def test_balancing_finds_feasible_global_partition(self):
        # The ideal midpoint is not a legal system boundary. The tallest
        # complete strip controls the shared scale, rather than total height.
        record = compact_fixture(self.root, [180, 240, 180, 200, 200, 220, 180, 200, 200])
        strips, placements = longshot._continuous_pages(self.root, record)
        self.assertEqual(len(strips), 2)
        self.assertEqual(strips[0]['crop_bbox'][3], 1000)
        self.assertAlmostEqual(placements[0]['scale'], (A4[1] - 48) / 1000)
        # The source stays unchanged, with a continuous gray interior.
        source = self.root / record['longshot']['image']['path']
        self.assertEqual(score_task.digest(source), record['longshot']['image']['sha256'])
        with Image.open(source) as image:
            self.assertTrue(np.all(np.asarray(image)[:, 5] == 249))


if __name__ == '__main__':
    unittest.main()
