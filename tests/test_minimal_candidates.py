from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'))
from viewport_tracker import RowObservation, RowTrack, ViewportError
from candidate_selector import select


def observation(time, **kwargs):
    return RowObservation(time, [0, 0, 1200, 200], 70, 12,
                          original_crop=f'original-{time}.png', **kwargs)


class CandidateTests(unittest.TestCase):
    def test_clean_then_cursor_keeps_early_original(self):
        clean = observation(1, sharpness=10)
        track = RowTrack(0, 70, [clean, observation(2, cursor_occluded=True, sharpness=100)])
        self.assertIs(select(track), clean)

    def test_cursor_then_clean_keeps_late_original(self):
        clean = observation(2, sharpness=10)
        track = RowTrack(0, 70, [observation(1, cursor_occluded=True), clean])
        self.assertIs(select(track), clean)

    def test_filters_obstruction_and_partial_then_sharpness_and_time(self):
        winner = observation(2, sharpness=30)
        track = RowTrack(0, 70, [observation(0, obstruction_detected=True, sharpness=500),
                               observation(1, complete=False, sharpness=600),
                               observation(3, sharpness=30), winner, observation(4, sharpness=20)])
        self.assertIs(select(track), winner)

    def test_no_clean_observation_waits(self):
        for kwargs in ({'complete': False}, {'cursor_occluded': True}, {'obstruction_detected': True}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ViewportError, 'no_clean_observation'):
                select(RowTrack(0, 70, [observation(1, **kwargs)]))
