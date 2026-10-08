"""Independent long-score fixture exercises visual seek and spatial candidates."""
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
from score_fixtures import CLI, score_frame

sys.path.insert(0, str(CLI.parent))
from viewport_sampler import ViewportSampler
from viewport_tracker import ViewportError


class DrawnReader:
    metadata = {'duration': 32.0}

    def __init__(self, moving=True):
        self.score = score_frame((1280, 1700), row_count=6)
        self.moving = moving

    def read(self, requested):
        timestamp = 31.9 if requested is None else requested
        offset = min(840, int(timestamp // 4) * 120) if self.moving else 0
        viewport = Image.new('RGB', (1280, 960), '#303030')
        viewport.paste(self.score.crop((70, 40 + offset, 1211, 911 + offset)), (70, 40))
        return timestamp, viewport


def metrics():
    return dict(analyzed_frames=0, candidate_observations=0, selected_keyframes=0)


class SamplerTests(unittest.TestCase):
    def test_complete_long_score_and_header_survive_scroll(self):
        with tempfile.TemporaryDirectory() as scratch:
            m = metrics()
            sampler = ViewportSampler(DrawnReader(), Path(scratch), m)
            rows = sampler.run()
            self.assertEqual(len(rows), 6)
            self.assertEqual([r.index for r in rows], list(range(6)))
            self.assertEqual([round(r.global_y) for r in rows], [220, 440, 660, 880, 1100, 1320])
            self.assertEqual(sampler.header['timestamp'], 0)
            self.assertGreater(len(sampler.transitions), 1)
            self.assertLess(m['analyzed_frames'], 60)
            for track in rows:
                self.assertTrue(track.selected_observation.complete)
                self.assertFalse(track.selected_observation.cursor_occluded)
                self.assertFalse(track.selected_observation.obstruction_detected)

    def test_never_complete_bottom_row_waits(self):
        with tempfile.TemporaryDirectory() as scratch:
            sampler = ViewportSampler(DrawnReader(moving=False), Path(scratch), metrics())
            with self.assertRaisesRegex(ViewportError, 'end_partial'):
                sampler.run()
