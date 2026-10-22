"""Offline regressions for safe same-stream media backup selection."""
import io
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from score_fixtures import score_frame, video_from_image
import test_link_input
from bbdown_fixture import configured_fake, fixture_config, URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score import anonymous_backend
from drum_score.public_video import InputError, video_origin


ORIGIN = video_origin('https://www.bilibili.com/video/BV1b5411x7Ku?p=2')
BACKUP = 'https://backup.bilivideo.cn/video?sign=SYNTHETIC_SIGNATURE'
UNSAFE = 'https://cdn.bilivideo.com:8082/video?sign=SYNTHETIC_SIGNATURE'
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]


class MediaBackupTests(unittest.TestCase):
    def route(self, staging, fmt, response, *, public_api=False, dns=None, duration=2):
        from drum_score.public_video import acquire
        config = fixture_config()
        config['view']['pages'][1]['duration'] = duration
        config['play']['timelength'] = duration * 1000
        config['play']['dash']['video'] = [{'baseUrl': fmt.get('url'),
            'backupUrl': fmt.get('backup_urls') or [], 'width': fmt.get('width'),
            'height': fmt.get('height'), 'codecs': fmt.get('vcodec'), 'id': 80}]
        with configured_fake(staging, config, response=response, dns=dns):
            source, result = acquire(URL, staging / 'acquired')
        (staging / 'video.mp4').write_bytes(source.read_bytes())
        return result

    def test_unsafe_primary_and_first_backup_use_second_backup_on_both_routes(self):
        for public_api in (False, True):
            with self.subTest(public_api=public_api), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                video = video_from_image(score_frame(), base)
                calls = base / 'calls'

                def response(request, **kwargs):
                    calls.write_text(calls.read_text() + request.full_url + '\n' if calls.exists() else request.full_url + '\n')
                    self.assertEqual(request.full_url, BACKUP)
                    return io.BytesIO(video.read_bytes())

                fmt = {'url': UNSAFE, 'backup_urls': ['http://cdn.bilivideo.com/video', BACKUP],
                       'width': 1280, 'height': 960, 'vcodec': 'avc1', 'acodec': 'none'}
                result = self.route(base, fmt, response, public_api=public_api)
                self.assertEqual(calls.read_text().splitlines(), [BACKUP])
                self.assertTrue(result['backup_used'])
                self.assertEqual(result['format_attempts'], 1)
                self.assertEqual(result['actual_video']['width'], 1280)
                self.assertEqual((base / 'video.mp4').read_bytes(), video.read_bytes())
                self.assertNotIn('SYNTHETIC_SIGNATURE', str(result))

    def test_all_unsafe_candidates_fail_without_transport_or_partial_file(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            fmt = {'url': UNSAFE, 'backup_urls': ['https://evil.example/video', 'http://cdn.bilivideo.com/video'],
                   'vcodec': 'avc1', 'acodec': 'none'}
            with self.assertRaises(InputError) as raised:
                self.route(base, fmt, lambda *a, **k: self.fail('must not connect'))
            self.assertEqual(raised.exception.code, 'unsafe_media_target')
            self.assertFalse((base / 'video.mp4').exists())
            self.assertNotIn('SYNTHETIC_SIGNATURE', str(raised.exception))

    def test_private_dns_primary_is_rejected_before_trying_public_backup(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            calls = base / 'calls'

            def dns(host, *args, **kwargs):
                return ([(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.2', 443))]
                        if host == 'private.bilivideo.com' else PUBLIC_DNS)

            def response(request, **kwargs):
                calls.write_text(calls.read_text() + request.full_url + '\n' if calls.exists() else request.full_url + '\n')
                return io.BytesIO(video.read_bytes())

            fmt = {'url': 'https://private.bilivideo.com/video', 'backup_urls': [BACKUP],
                   'vcodec': 'avc1', 'acodec': 'none'}
            result = self.route(base, fmt, response, dns=dns)
            self.assertTrue(result['backup_used'])
            self.assertEqual(calls.read_text().splitlines(), [BACKUP])

    def test_backup_still_obeys_size_resolution_and_duration_checks(self):
        cases = [('download_too_large', False, 1280, 960, 1),
                 ('media_resolution_mismatch', False, 2560, 1920, None),
                 ('incomplete_video', True, 1280, 960, None)]
        for expected, public_api, width, height, limit in cases:
            with self.subTest(error=expected), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                video = video_from_image(score_frame(), base)
                calls = base / 'calls'

                def response(request, **kwargs):
                    calls.write_text(calls.read_text() + request.full_url + '\n' if calls.exists() else request.full_url + '\n')
                    return io.BytesIO(video.read_bytes())

                fmt = {'url': UNSAFE, 'backup_urls': [BACKUP, BACKUP + '&unused=1'],
                       'width': width, 'height': height, 'vcodec': 'avc1', 'acodec': 'none'}
                with patch.object(anonymous_backend, 'MAX_BYTES', limit or 2 * 1024**3):
                    with self.assertRaises(InputError) as raised:
                        self.route(base, fmt, response, public_api=public_api, duration=10 if expected == 'incomplete_video' else 2)
                self.assertEqual(raised.exception.code, expected)
                self.assertEqual(calls.read_text().splitlines(), [BACKUP])

    def test_undecodable_backup_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as scratch:
            fmt = {'url': UNSAFE, 'backup_urls': [BACKUP], 'vcodec': 'avc1', 'acodec': 'none'}
            with self.assertRaises(InputError) as raised:
                self.route(Path(scratch), fmt, lambda *a, **k: io.BytesIO(b'not a video'))
            self.assertEqual(raised.exception.code, 'undecodable_video')
