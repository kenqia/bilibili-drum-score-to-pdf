import tempfile
from pathlib import Path
import unittest
from score_fixtures import score_frame, video_from_image
import test_link_input
from bbdown_fixture import configured_fake, fixture_config, URL
from drum_score.public_video import acquire

class BBDownTracer(unittest.TestCase):
    def test_public_acquire_uses_anonymous_direct_bbdown_process(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            video = video_from_image(score_frame(), root)
            with configured_fake(root, fixture_config(), video):
                source, origin = acquire(URL, root / 'out')
            self.assertEqual(source.read_bytes(), video.read_bytes())
            self.assertEqual(origin['backend'], 'BBDownNext')
            self.assertEqual(origin['backend_version'], '2.3.0')
            self.assertEqual(origin['acquisition_route'], 'bbdown_direct')
