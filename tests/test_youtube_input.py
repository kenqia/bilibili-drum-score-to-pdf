"""YouTube public input and anonymous acquisition contracts."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.public_video import video_origin, InputError


class YoutubeInput(unittest.TestCase):
    def test_single_video_normalizes_shorts_short_links_and_ignored_ranges(self):
        expected = {'kind': 'youtube', 'video_id': 'dQw4w9WgXcQ',
                    'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'authenticated': False}
        for url in ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30&list=ignored',
                    'https://youtu.be/dQw4w9WgXcQ?t=30',
                    'https://youtube.com/shorts/dQw4w9WgXcQ?feature=share']:
            with self.subTest(url=url):
                self.assertEqual(video_origin(url), expected)
        for url in ['http://youtu.be/dQw4w9WgXcQ', 'https://youtube.com.evil/watch?v=dQw4w9WgXcQ',
                    'https://user@youtu.be/dQw4w9WgXcQ', 'https://youtu.be:444/dQw4w9WgXcQ',
                    'https://youtube.com/playlist?list=ignored',
                    'https://youtube.com/watch?v=dQw4w9WgXcQ&v=jNQXAC9IVRw',
                    'https://youtu.be/dQw4w9WgXc']:
            with self.subTest(url=url), self.assertRaises(InputError):
                video_origin(url)

    def test_http_queue_accepts_canonical_youtube_without_network(self):
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        with tempfile.TemporaryDirectory() as temp:
            with TestClient(create_app(Path(temp)), client=('192.0.2.1', 1234)) as client:
                response = client.post('/api/tasks', json={'url': 'https://youtu.be/dQw4w9WgXcQ?t=30'})
                self.assertEqual(response.status_code, 201, response.text)
                task = response.json()
                state = client.get('/api/tasks/' + task['id'],
                    headers={'Authorization': 'Bearer ' + task['capability']}).json()
                self.assertEqual(state['source']['video_id'], 'dQw4w9WgXcQ')
                self.assertEqual(state['source']['url'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    def test_real_acquisition_selects_native_track_and_keeps_signed_addresses_private(self):
        from drum_score.public_video import acquire
        from score_fixtures import score_frame, video_from_image
        from youtube_fixture import configured
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = video_from_image(score_frame(), root)
            before = video.read_bytes()
            with configured(video):
                source, origin = acquire('https://youtu.be/dQw4w9WgXcQ?t=30', root / 'result')
            self.assertEqual(source.name, 'youtube-dQw4w9WgXcQ.mp4')
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(origin['full_duration'], 2)
            self.assertEqual(origin['backend'], 'yt-dlp')
            self.assertEqual(origin['actual_video']['height'], 960)
            self.assertFalse(origin['authenticated'])
            self.assertNotIn('SYNTHETIC_DO_NOT_PUBLISH', json.dumps(origin))

    def test_acquisition_refuses_live_restricted_wrong_id_and_incomplete_media(self):
        from drum_score.public_video import acquire
        from score_fixtures import score_frame, video_from_image
        from youtube_fixture import configured, info
        cases = [({'live_status': 'is_live'}, 'unsupported_stream'),
                 ({'age_limit': 18}, 'unsupported_stream'),
                 ({'id': 'jNQXAC9IVRw'}, 'unsupported_stream'),
                 ({'duration': 20}, 'incomplete_video')]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = video_from_image(score_frame(), root)
            for index, (changes, code) in enumerate(cases):
                with self.subTest(changes=changes), configured(video, info(**changes)):
                    output = root / str(index)
                    with self.assertRaises(InputError) as caught:
                        acquire('https://youtu.be/dQw4w9WgXcQ', output)
                    self.assertEqual(caught.exception.code, code)
                    self.assertFalse(output.exists())

    def test_media_targets_and_private_dns_fail_before_transport(self):
        import socket
        from drum_score.public_video import acquire
        from youtube_fixture import configured, info, MEDIA
        cases = [('https://evil.example/video', None),
                 ('http://r1.googlevideo.com/video', None),
                 (MEDIA, [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, (address, dns) in enumerate(cases):
                metadata = info(formats=[{'url': address, 'vcodec': 'h264', 'acodec': 'none'}])
                with self.subTest(address=address), configured(root / 'missing', metadata, dns):
                    with self.assertRaises(InputError) as caught:
                        acquire('https://youtu.be/dQw4w9WgXcQ', root / str(index))
                    self.assertEqual(caught.exception.code, 'unsafe_media_target')

    def test_youtube_queued_source_round_trips_backup_without_changing_bilibili(self):
        from drum_score.jobs import Jobs
        from drum_score.maintenance import backup, restore
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            jobs = Jobs(root / 'source')
            task = jobs.enqueue('https://youtube.com/shorts/dQw4w9WgXcQ?t=2', '192.0.2.1')
            jobs.enqueue('https://www.bilibili.com/video/BV1b5411x7Ku?p=2', '192.0.2.2')
            backup(root / 'source', root / 'backup', services_stopped=True, min_free_bytes=1)
            restore(root / 'backup', root / 'restored', min_free_bytes=1)
            restored = Jobs(root / 'restored').view(task['id'], task['capability'])
            self.assertEqual(restored['source']['video_id'], 'dQw4w9WgXcQ')

    def test_metadata_is_bounded_after_gzip_and_rejects_foreign_hosts(self):
        import gzip
        import io
        from email.message import Message
        from unittest.mock import patch
        from yt_dlp.extractor.youtube import YoutubeIE
        from drum_score import youtube_backend
        from drum_score.public_video import acquire
        from youtube_fixture import configured
        class Response(io.BytesIO):
            status = 200
            headers = Message()
            headers['Content-Encoding'] = 'gzip'
            def geturl(self):
                return 'https://www.youtube.com/synthetic'
        def extract(extractor, url):
            return extractor._download_json('https://www.youtube.com/synthetic', 'dQw4w9WgXcQ')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with configured(root / 'unused'), patch.object(YoutubeIE, '_real_extract', extract), \
                 patch.object(youtube_backend, 'MAX_RESPONSE', 4096), \
                 patch('urllib.request.OpenerDirector.open', side_effect=lambda *a, **k: Response(gzip.compress(b'x' * 8192))):
                with self.assertRaises(InputError) as caught:
                    acquire('https://youtu.be/dQw4w9WgXcQ', root / 'bounded')
                self.assertEqual(caught.exception.code, 'download_too_large')
            def foreign(extractor, url):
                return extractor._download_json('https://evil.example/private', 'dQw4w9WgXcQ')
            with configured(root / 'unused'), patch.object(YoutubeIE, '_real_extract', foreign):
                with self.assertRaises(InputError) as caught:
                    acquire('https://youtu.be/dQw4w9WgXcQ', root / 'foreign')
                self.assertEqual(caught.exception.code, 'unsafe_media_target')

    def test_extractor_and_runtime_environment_do_not_receive_user_settings(self):
        import os
        from unittest.mock import patch
        from yt_dlp.extractor.youtube import YoutubeIE
        from score_fixtures import score_frame, video_from_image
        from youtube_fixture import configured, info
        from drum_score.public_video import acquire
        def extract(extractor, url):
            self.assertNotIn('SYNTHETIC_PRIVATE_ENV', os.environ)
            self.assertFalse(extractor.get_param('usenetrc'))
            self.assertIsNone(extractor.get_param('cookiefile'))
            self.assertIsNone(extractor.get_param('cookiesfrombrowser'))
            from yt_dlp.globals import plugin_dirs
            self.assertEqual(plugin_dirs.value, [])
            self.assertNotEqual(os.environ['HOME'], str(root))
            self.assertFalse(extractor.get_param('remote_components'))
            return info()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = video_from_image(score_frame(), root)
            with configured(video), patch.dict(os.environ, {'HOME': str(root), 'SYNTHETIC_PRIVATE_ENV': 'SYNTHETIC_VALUE'}), \
                 patch.object(YoutubeIE, '_real_extract', extract):
                acquire('https://youtu.be/dQw4w9WgXcQ', root / 'result')

    def test_whole_second_metadata_accepts_fractional_tail_but_refuses_truncation(self):
        from drum_score.public_video import acquire
        from score_fixtures import score_frame, video_from_image
        from youtube_fixture import configured, info
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = video_from_image(score_frame(), root, duration=2.7)
            with configured(video, info(duration=2)):
                source, origin = acquire('https://youtu.be/dQw4w9WgXcQ', root / 'fractional')
            self.assertEqual(source.read_bytes(), video.read_bytes())
            self.assertEqual(origin['duration_tolerance_seconds'], 1.0)
            with configured(video, info(duration=4)):
                with self.assertRaises(InputError) as caught:
                    acquire('https://youtu.be/dQw4w9WgXcQ', root / 'truncated')
                self.assertEqual(caught.exception.code, 'incomplete_video')
