"""Link behavior at the unified CLI, replacing only public HTTP transport."""
import contextlib
from email.message import Message
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from test_conversion import CLI, score_frame, video_from_image

sys.path.insert(0, str(CLI.parent))
spec = importlib.util.spec_from_file_location('link_cli', CLI)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class LinkInputTests(unittest.TestCase):
    def invoke(self, source, output, responses):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', [str(CLI), source, '--output', str(output)]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch('urllib.request.OpenerDirector.open', side_effect=responses, autospec=True) as transport:
            exit_code = cli.main()
        return exit_code, json.loads(stdout.getvalue()), transport, stdout.getvalue() + stderr.getvalue()

    def responses(self, video, media_url='https://upos-sz-mirrorcos.bilivideo.com/fixture.mp4?sign=DO_NOT_SAVE_TEST_SENTINEL', quality=80):
        view = {'code': 0, 'data': {'pages': [{'page': 1, 'cid': 123}, {'page': 2, 'cid': 456}], 'dimension': {'width': 1920, 'height': 1080}}}
        stream = {'code': 0, 'data': {'quality': quality, 'durl': [{'url': media_url}]}}
        return [io.BytesIO(json.dumps(view).encode()), io.BytesIO(json.dumps(stream).encode()), io.BytesIO(video.read_bytes())]

    def test_anonymous_link_generates_pdf_with_actual_dimensions_and_safe_origin(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            code, result, transport, output = self.invoke('https://www.bilibili.com/video/BV1b5411x7Ku?p=2&share_source=copy', base / 'result', self.responses(video))
            self.assertEqual(code, 0, result)
            self.assertEqual(result['status'], 'success')
            self.assertTrue((base / 'result/score.pdf').exists())
            self.assertEqual(result['origin']['page'], 2)
            self.assertEqual(result['origin']['cid'], 456)
            self.assertEqual((result['source']['width'], result['source']['height']), (1280, 960))
            self.assertEqual(result['origin']['api_quality'], 80)
            self.assertIn('cid=456', transport.call_args_list[1].args[1].full_url)
            manifest = (base / 'result/manifest.json').read_text()
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', output + manifest)
            self.assertNotIn('share_source', manifest)

    def test_api_failure_stops_with_safe_local_fallback(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / 'result'
            error = HTTPError('https://api.bilibili.com/?sign=DO_NOT_SAVE_TEST_SENTINEL', 412, 'DO_NOT_SAVE_TEST_SENTINEL', {}, None)
            code, result, transport, text = self.invoke('https://www.bilibili.com/video/BV1b5411x7Ku', output, [error])
            self.assertEqual(code, 2)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('本地视频', result['error']['message'])
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(result['error']['http_status'], 412)
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', text + (output / 'manifest.json').read_text())
            self.assertFalse((output / 'score.pdf').exists())

    def test_actual_low_quality_requests_local_input_and_can_continue(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            low = video_from_image(score_frame().resize((640, 360)), base, 'low')
            code, result, _, _ = self.invoke('https://www.bilibili.com/video/BV1b5411x7Ku', base / 'low-result', self.responses(low, quality=16))
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'low_resolution')
            self.assertEqual((result['source']['width'], result['source']['height']), (640, 360))
            self.assertEqual(result['origin']['api_quality'], 16)
            self.assertIn('本地视频', result['error']['message'])
            self.assertFalse((base / 'low-result/score.pdf').exists())
            high = video_from_image(score_frame(), base, 'high')
            code, result, transport, _ = self.invoke(str(high), base / 'local-result', [])
            self.assertEqual(code, 0, result)
            transport.assert_not_called()

    def test_invalid_urls_do_not_make_network_requests(self):
        for url in ('https://evil.example/video/BV1b5411x7Ku', 'https://www.bilibili.com.evil.example/video/BV1b5411x7Ku', 'https://secret@www.bilibili.com/video/BV1b5411x7Ku', 'https://www.bilibili.com/video/BV1b5411x7Ku?p=0', 'https://www.bilibili.com/video/BV1b5411x7Ku?p=1&p=2', 'file:///etc/passwd'):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as scratch:
                code, result, transport, _ = self.invoke(url, Path(scratch), [])
                self.assertEqual(code, 2)
                self.assertEqual(result['error']['code'], 'invalid_bilibili_url')
                transport.assert_not_called()

    def test_hostile_media_targets_stop_before_download_without_leaking_urls(self):
        for media in ('https://127.0.0.1/media?secret=DO_NOT_SAVE_TEST_SENTINEL', 'https://evilbilivideo.com/media?secret=DO_NOT_SAVE_TEST_SENTINEL', 'http://upos-sz-mirrorcos.bilivideo.com/media?secret=DO_NOT_SAVE_TEST_SENTINEL'):
            with self.subTest(media=media), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                fixture = base / 'fixture.mp4'
                fixture.write_bytes(b'not needed')
                code, result, transport, text = self.invoke('https://www.bilibili.com/video/BV1b5411x7Ku', base / 'result', self.responses(fixture, media_url=media))
                self.assertEqual(code, 2)
                self.assertEqual(result['error']['code'], 'unsafe_media_target')
                self.assertEqual(transport.call_count, 2)
                self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', text + (base / 'result/manifest.json').read_text())

    def test_transport_redirect_to_private_host_is_not_followed(self):
        def response(opener, request, timeout):
            headers = Message()
            headers['Location'] = 'https://127.0.0.1/?secret=DO_NOT_SAVE_TEST_SENTINEL'
            # Deliver a public HTTP redirect response to the real opener handlers.
            return opener.error('http', request, io.BytesIO(b''), 302, 'Moved', headers)
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            code, result, transport, text = self.invoke('https://www.bilibili.com/video/BV1b5411x7Ku', base, response)
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'network_redirect')
            self.assertEqual(transport.call_count, 1)
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', text + (base / 'manifest.json').read_text())

    def test_existing_partial_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            partial = base / 'anonymous-video.partial'
            partial.write_bytes(b'user-file')
            code, result, transport, _ = self.invoke('https://www.bilibili.com/video/BV1b5411x7Ku', base, [])
            self.assertEqual(code, 2)
            self.assertEqual(partial.read_bytes(), b'user-file')
            self.assertEqual(result['error']['code'], 'existing_output')
            transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
