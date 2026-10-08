"""Spatial contracts independent of note content and encoded pixel noise."""
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'
sys.path.insert(0, str(SCRIPTS))
from viewport_tracker import RowObservation, ViewportTracker, ViewportError, translation


def observations(anchors, timestamp=0, **kwargs):
    return [RowObservation(timestamp, [0, y - 40, 1200, y + 90], y, 12, **kwargs) for y in anchors]


class GeometryTests(unittest.TestCase):
    def test_fixed_window_has_one_track_per_spatial_row(self):
        tracker = ViewportTracker()
        for time in range(4):
            tracker.accept(observations([300, 500, 700], time))
        self.assertEqual(len(tracker.rows), 3)
        self.assertTrue(all(len(r.observations) == 4 for r in tracker.rows))

    def test_upward_scroll_adds_only_new_global_row(self):
        tracker = ViewportTracker()
        tracker.accept(observations([300, 500, 700]))
        self.assertEqual(tracker.accept(observations([171, 371, 571, 771], 1)), 129)
        self.assertEqual([r.global_y for r in tracker.rows], [300, 500, 700, 900])

    def test_successive_translations_keep_order_and_repeated_content(self):
        tracker = ViewportTracker()
        tracker.accept(observations([300, 500, 700], original_crop='same.png'))
        for time, anchors in enumerate(([171, 371, 571, 771], [242, 442, 642, 842],
                                       [113, 313, 513, 713, 913]), 1):
            tracker.accept(observations(anchors, time, original_crop='same.png'))
        self.assertEqual([r.global_y for r in tracker.rows], [300, 500, 700, 900, 1100, 1300])
        self.assertEqual([r.index for r in tracker.rows], list(range(6)))

    def test_partial_observation_waits_until_complete(self):
        tracker = ViewportTracker()
        tracker.accept(observations([300, 500]) + observations([700], complete=False))
        self.assertEqual(len(tracker.rows), 2)
        tracker.accept(observations([300, 500, 700], 1))
        self.assertEqual(len(tracker.rows), 3)

    def test_multiple_equally_good_geometric_shifts_wait(self):
        with self.assertRaisesRegex(ViewportError, 'ambiguous_scroll'):
            translation(observations([300, 500, 700, 900]), observations([100, 300, 500]))

    def test_scale_change_is_unsupported(self):
        new = observations([300, 500, 700])
        for r in new:
            r.staff_spacing = 15
        with self.assertRaisesRegex(ViewportError, 'unsupported_layout'):
            translation(observations([300, 500, 700]), new)

    def test_no_overlap_and_backward_motion_wait(self):
        for anchors in ([310, 510, 710], [50, 170, 290]):
            with self.subTest(anchors=anchors), self.assertRaises(ViewportError):
                translation(observations([300, 500, 700]), observations(anchors))


if __name__ == '__main__':
    unittest.main()
