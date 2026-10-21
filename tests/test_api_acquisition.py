"""Exercise API recovery through the public entry matrix and real HTTP parser."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from score_fixtures import score_frame, video_from_image
import test_link_input  # installs the source package path
from test_public_contracts import ACQUISITION_ENTRIES, SCRIPT_CONVERSION_ENTRIES
from yt_dlp.extractor.bilibili import BiliBiliIE
from drum_score import public_video

BV = 'BV1b5411x7Ku'
URL = f'https://www.bilibili.com/video/{BV}?p=2'
MEDIA = 'https://cdn.bilivideo.com/video?sign=SYNTHETIC_SIGNED_SECRET'


class APIAcquisitionTests(unittest.TestCase):
    def run_case(self, base, video, *, entry='acquire', refusal='proxy403', view=None,
                 play=None, private_media=False):
        events = base / 'events.jsonl'
        metadata = view if view is not None else {'bvid': BV, 'title': 'Fixture', 'pages': [
            {'page': 1, 'cid': 11, 'duration': 2}, {'page': 2, 'cid': 22, 'duration': 2}]}
        playdata = play if play is not None else {'timelength': 2000, 'dash': {'video': [{
            'id': 80, 'baseUrl': MEDIA, 'width': 1280, 'height': 960,
            'codecs': 'avc1', 'mimeType': 'video/mp4', 'frameRate': '4/1'}]}}
        def event(kind):
            with events.open('a') as f:
                f.write(json.dumps(kind) + '\n')
        class WireSocket:
            def __init__(self, proxy):
                self.proxy = proxy
                self.request = b''
            def sendall(self, packet):
                self.request = packet
            def close(self):
                pass
            def makefile(self, *args):
                if self.proxy:
                    event('proxy')
                    code = 407 if refusal == 'proxy407' else 403
                    return io.BytesIO(f'HTTP/1.1 {code} SYNTHETIC_PROXY_SECRET\r\n\r\n'.encode())
                if b'GET /video/BV' in self.request:
                    event('webpage')
                    code = 403 if refusal == 'http403' else 412
                    return io.BytesIO(f'HTTP/1.1 {code} Refused\r\n\r\n'.encode())
                if b'GET /x/web-interface/view?' in self.request:
                    event('view')
                    body = json.dumps({'code': 0, 'data': metadata}).encode()
                elif b'GET /x/web-interface/nav ' in self.request:
                    event('nav')
                    body = json.dumps({'data': {'wbi_img': {
                        'img_url': 'https://i.example/' + 'a' * 32 + '.png',
                        'sub_url': 'https://i.example/' + 'b' * 32 + '.png'}}}).encode()
                elif b'GET /x/player/wbi/playurl?' in self.request:
                    if b'cid=22' not in self.request or b'qn=80' not in self.request:
                        raise AssertionError('API must bind requested page and quality')
                    event('play')
                    body = json.dumps({'code': 0, 'data': playdata}).encode()
                else:
                    event('media')
                    body = video.read_bytes()
                return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
        def connect(address, *args, **kwargs):
            if address == ('proxy.example', 8888):
                return WireSocket(True)
            if address != ('8.8.8.8', 443):
                raise AssertionError('direct connection must pin the public address')
            return WireSocket(False)
        def dns(host, *args, **kwargs):
            ip = '10.0.0.1' if private_media and host == 'cdn.bilivideo.com' else '8.8.8.8'
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]
        env = {k: '' for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
                               'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY')}
        if refusal.startswith('proxy'):
            env['https_proxy'] = 'http://fixture:SYNTHETIC_PROXY_SECRET@proxy.example:8888'
        output = base / 'result'
        stdout = io.StringIO()
        # The socket fixture belongs to this process. Exercise the unchanged
        # downloader/image boundary here; supervision has real process tests.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score.supervision
        from drum_score.core import _convert
        with patch.dict(os.environ, env), patch('socket.getaddrinfo', side_effect=dns), patch(
            'socket.create_connection', side_effect=connect), patch('ssl.SSLContext.wrap_socket',
                side_effect=lambda self, sock, **kw: sock, autospec=True), patch.object(
                    BiliBiliIE, '_wbi_key_cache', {}), patch(
                    'drum_score.supervision.run', side_effect=_convert), contextlib.redirect_stdout(stdout):
            try:
                if entry in SCRIPT_CONVERSION_ENTRIES:
                    import drum_score
                    if entry == 'script_core':
                        result = drum_score.convert(URL, output)
                        status = 0
                    else:
                        from drum_score.cli import main
                        status = main([URL, '--output', str(output)])
                        result = json.loads(stdout.getvalue())
                else:
                    source, origin = public_video.acquire(URL, output)
                    result = {'origin': origin, 'source': {'path': str(source)}}
                    status = 0
            except (public_video.InputError, __import__('drum_score.video_seek', fromlist=['ConversionError']).ConversionError) as error:
                status = 2
                result = {'error': {'code': error.code, **getattr(error, 'diagnostics', {})}}
        logs = stdout.getvalue()
        for marker in ('SYNTHETIC_SIGNED_SECRET', 'SYNTHETIC_PROXY_SECRET'):
            self.assertNotIn(marker, logs)
            self.assertNotIn(marker, json.dumps(result))
        history = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
        return status, result, history

    def test_proxy_refusal_recovers_public_api_at_every_entry(self):
        for entry in ACQUISITION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                video = video_from_image(score_frame(), base)
                status, result, events = self.run_case(base, video, entry=entry)
                self.assertEqual(status, 0, result)
                self.assertEqual(result['origin']['acquisition_route'], 'public_api_direct')
                self.assertEqual(result['origin']['fallback_trigger']['proxy_connect_status'], 403)
                self.assertIn('proxy', events)
                self.assertIn('media', events)
                self.assertNotIn('webpage', events)
                self.assertEqual(Path(result['source']['path']).read_bytes(), video.read_bytes())

    def test_api_unsafe_primary_uses_official_backup_at_every_entry(self):
        play = {'timelength': 2000, 'dash': {'video': [{
            'id': 80, 'baseUrl': MEDIA.replace('.com/', '.com:8082/'),
            'backupUrl': [MEDIA], 'width': 1280, 'height': 960,
            'codecs': 'avc1', 'mimeType': 'video/mp4', 'frameRate': '4/1'}]}}
        for entry in ACQUISITION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                video = video_from_image(score_frame(), base)
                status, result, events = self.run_case(base, video, entry=entry, play=play)
                self.assertEqual(status, 0, result)
                self.assertTrue(result['origin']['backup_used'])
                self.assertEqual(result['origin']['format_attempts'], 1)
                self.assertEqual(events.count('media'), 1)
                self.assertEqual(Path(result['source']['path']).read_bytes(), video.read_bytes())

    def test_webpage_412_recovers_without_requiring_proxy_refusal(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            status, result, events = self.run_case(base, video, refusal='http412')
            self.assertEqual(status, 0, result)
            self.assertEqual(result['origin']['fallback_trigger']['http_status'], 412)
            self.assertEqual(events.count('webpage'), 1)
            self.assertIn('media', events)

    def test_api_recovery_rejects_private_media_dns(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            status, result, events = self.run_case(base, video, private_media=True)
            self.assertEqual(status, 2, result)
            self.assertEqual(result['error']['code'], 'unsafe_media_target')
            self.assertNotIn('media', events)

    def test_other_refusals_do_not_trigger_direct_api(self):
        for refusal in ('proxy407', 'http403'):
            with self.subTest(refusal=refusal), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                video = video_from_image(score_frame(), base)
                status, result, events = self.run_case(base, video, refusal=refusal)
                self.assertEqual(status, 2, result)
                self.assertNotIn('view', events)
                self.assertNotIn('media', events)

    def test_wrong_or_ambiguous_page_never_downloads_media(self):
        for metadata in (
            {'bvid': 'BV1np421S78S', 'pages': [{'page': 2, 'cid': 22, 'duration': 2}]},
            {'bvid': BV, 'pages': [{'page': 1, 'cid': 11, 'duration': 2}]},
            {'bvid': BV, 'pages': [{'page': 2, 'cid': 22, 'duration': 2}] * 2},
        ):
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                status, result, events = self.run_case(base, base / 'unused', view=metadata)
                self.assertEqual(status, 2, result)
                self.assertEqual(result['error']['code'], 'unavailable_page')
                self.assertNotIn('media', events)

    def test_restricted_or_preview_api_response_never_downloads_media(self):
        cases = [
            ({'bvid': BV, 'is_upower_exclusive': True}, None, 'unsupported_stream'),
            ({'bvid': BV, 'rights': {'is_stein_gate': True}}, None, 'unsupported_stream'),
            (None, {'timelength': 2000, 'is_preview': True}, 'incomplete_video'),
            (None, {'timelength': 500}, 'incomplete_video'),
        ]
        for metadata, play, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                status, result, events = self.run_case(base, base / 'unused', view=metadata, play=play)
                self.assertEqual(status, 2, result)
                self.assertEqual(result['error']['code'], expected)
                self.assertNotIn('media', events)

    def test_actual_media_duration_must_match_the_api_not_just_its_dimensions(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            view = {'bvid': BV, 'title': 'Fixture', 'pages': [{'page': 2, 'cid': 22, 'duration': 20}]}
            play = {'timelength': 20000, 'dash': {'video': [{'id': 80, 'baseUrl': MEDIA,
                    'width': 1280, 'height': 960, 'codecs': 'avc1', 'mimeType': 'video/mp4'}]}}
            status, result, events = self.run_case(base, video, view=view, play=play)
            self.assertEqual(status, 2, result)
            self.assertEqual(result['error']['code'], 'incomplete_video')
            self.assertIn('media', events)
            self.assertFalse((base / 'result').exists())
            self.assertEqual(result['error']['fallback_trigger']['proxy_connect_status'], 403)

    def test_script_conversion_entries_share_real_downloader_boundary(self):
        for entry in SCRIPT_CONVERSION_ENTRIES:
            for private in (False, True):
                with self.subTest(entry=entry, private=private), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    video = video_from_image(score_frame(), root)
                    status, result, events = self.run_case(root, video, entry=entry, private_media=private)
                    if private:
                        self.assertEqual(status, 2)
                        self.assertFalse((root / 'result').exists())
                    else:
                        self.assertEqual(status, 0, result)
                        self.assertEqual(result['source']['page'], 2)
                        self.assertEqual(result['source']['bvid'], BV)
                        self.assertFalse(result['source']['retained'])
                        self.assertGreater(len(result['pages']), 0)
                        self.assertTrue((root / 'result' / result['pdf']['path']).is_file())
                        self.assertIn('media', events)
