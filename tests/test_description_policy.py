"""Website policy at the public anonymous acquisition boundary, no real network."""
import io
from pathlib import Path
import tempfile
import unittest

from bbdown_fixture import fixture_config, configured_fake, URL
from drum_score.public_video import acquire, InputError


class DescriptionPolicy(unittest.TestCase):
    def test_website_hearts_are_rejected_before_any_media_request(self):
        from drum_score.description_policy import website_policy
        for heart in ('♥', '♡', '❤', '❣', '❥', '☙', '❦', '❧', '🎔',
                      '💓', '💔', '💕', '💖', '💗', '💘', '💙', '💚', '💛', '💜', '💝', '💞', '💟',
                      '🖤', '🤍', '🤎', '🧡', '🩷', '🩵', '🩶', '❤️‍🔥', '❤️‍🩹'):
            with self.subTest(heart=heart), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = fixture_config()
                config['view']['desc'] = 'synthetic ' + heart
                events = []
                def fetch(*args, **kwargs):
                    events.append('media')
                    return io.BytesIO(b'not a video')
                with configured_fake(root, config, response=fetch), website_policy():
                    with self.assertRaises(InputError) as caught:
                        acquire(URL, root / 'result')
                self.assertEqual(caught.exception.code, 'description_policy_rejected')
                self.assertEqual(str(caught.exception), '该视频暂不支持整理。')
                self.assertEqual(events, [])
                self.assertFalse((root / 'result').exists())

    def test_missing_description_and_excluded_emoji_pass_and_cli_has_no_policy(self):
        from drum_score.description_policy import website_policy
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = video_from_image(score_frame(), root)
            for index, description in enumerate((None, '', 123, '😍 🥰 😘 🫶 💌 🫀 🫰', '♥')):
                case = root / str(index)
                case.mkdir()
                config = fixture_config()
                config['view']['desc'] = description
                from contextlib import nullcontext
                with configured_fake(case, config, video), (website_policy() if description != '♥' else nullcontext()):
                    source, origin = acquire(URL, case / 'result')
                self.assertTrue(source.is_file())
                if description == '♥':
                    self.assertNotIn('description_policy', origin)
                else:
                    self.assertFalse(origin['description_policy']['matched'])

    def test_publication_io_failure_preserves_known_source_without_raw_exception(self):
        from unittest.mock import patch
        from drum_score.description_policy import website_policy
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = video_from_image(score_frame(), root)
            config = fixture_config()
            config['view']['desc'] = 'synthetic ordinary description'
            with configured_fake(root, config, video), website_policy(), patch('os.fsync', side_effect=OSError('SYNTHETIC_PRIVATE_IO')):
                with self.assertRaises(InputError) as caught:
                    acquire(URL, root / 'result')
            self.assertEqual(caught.exception.code, 'public_api_unavailable')
            self.assertEqual(caught.exception.origin['url'], URL)
            self.assertTrue(caught.exception.origin['description_policy']['valid_description'])
            self.assertFalse(caught.exception.origin['description_policy']['matched'])
            self.assertNotIn('SYNTHETIC_PRIVATE_IO', str(caught.exception))
