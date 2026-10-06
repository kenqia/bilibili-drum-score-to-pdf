"""Unified CLI acquisition tests at the yt-dlp and HTTP boundaries."""
import contextlib
import builtins
import importlib
import importlib.util
import io
import json
from pathlib import Path
import socket
from email.message import Message
from urllib.error import HTTPError
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_conversion import CLI, score_frame, video_from_image
from yt_dlp import YoutubeDL

sys.path.insert(0, str(CLI.parent))
spec = importlib.util.spec_from_file_location('link_cli', CLI)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

URL = 'https://www.bilibili.com/video/BV1b5411x7Ku?p=2'
MEDIA = 'https://cdn.bilivideo.com/video?sign=DO_NOT_SAVE_TEST_SENTINEL'


class LinkInputTests(unittest.TestCase):
    def invoke(self, output, video, formats=None, url=URL, response=None, backend_error=None, dns=None, real_transport=False, info_id=None, actual_backend=False):
        info = {'id': info_id or 'BV1b5411x7Ku_p2', 'formats': formats or [
            {'url': MEDIA, 'width': 1280, 'height': 960, 'vcodec': 'avc1', 'acodec': 'none', 'format_id': '80'}]}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', [str(CLI), url, '--output', str(output)]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), (contextlib.nullcontext() if actual_backend else patch.object(YoutubeDL, 'extract_info', return_value=info, side_effect=backend_error)), (contextlib.nullcontext() if real_transport else patch('urllib.request.OpenerDirector.open', side_effect=response or (lambda *a, **k: io.BytesIO(video.read_bytes())))), patch('socket.getaddrinfo', return_value=dns or [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]):
            code = cli.main()
        return code, json.loads(stdout.getvalue()), stdout.getvalue() + stderr.getvalue()

    def test_dash_only_link_uses_native_video_track_and_records_anonymous_backend(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            code, result, logs = self.invoke(base / 'result', video)
            self.assertEqual(code, 0, result)
            self.assertTrue((base / 'result/score.pdf').exists())
            self.assertEqual(result['origin']['page'], 2)
            self.assertEqual(result['origin']['backend'], 'yt-dlp')
            self.assertFalse(result['origin']['authenticated'])
            self.assertFalse(result['origin']['single_file_fallback'])
            self.assertEqual(result['origin']['actual_video']['width'], 1280)
            combined = logs + (base / 'result/manifest.json').read_text()
            if 'DO_NOT_SAVE_TEST_SENTINEL' in combined:
                offset = combined.index('DO_NOT_SAVE_TEST_SENTINEL')
                self.fail(repr(combined[max(0, offset-180):offset+120]))

    def test_highest_native_resolution_video_only_wins_over_muxed_or_audio(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            formats = [
                {'url': MEDIA, 'height': 720, 'width': 1280, 'acodec': 'none', 'vcodec': 'avc1', 'quality': 64},
                {'url': MEDIA, 'height': 2160, 'width': 3840, 'acodec': 'aac', 'vcodec': 'avc1', 'quality': 120},
                {'url': MEDIA, 'height': 960, 'width': 1280, 'acodec': 'none', 'vcodec': 'avc1', 'quality': 80},
                {'url': MEDIA, 'acodec': 'aac', 'vcodec': 'none', 'quality': 999}]
            code, result, logs = self.invoke(base / 'result', video, formats)
            self.assertEqual(code, 0, result)
            self.assertEqual(result['origin']['selected_format']['quality'], 80)
            self.assertFalse(result['origin']['single_file_fallback'])

    def test_no_separate_video_records_single_file_fallback(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            code, result, _ = self.invoke(base / 'result', video, [{'url': MEDIA, 'vcodec': 'h264', 'acodec': 'aac'}])
            self.assertEqual(code, 0, result)
            self.assertTrue(result['origin']['single_file_fallback'])

    def test_metadata_cannot_claim_higher_resolution_than_download(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame().resize((640, 360)), base)
            code, result, logs = self.invoke(base / 'result', video)
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'media_resolution_mismatch')
            self.assertEqual(result['origin']['actual_video']['width'], 640)
            self.assertEqual(result['origin']['actual_video']['height'], 360)
            self.assertFalse(list((base / 'result').glob('*.mp4')))
            self.assertFalse(list((base / 'result').glob('*.partial')))
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', logs)

    def test_official_backup_can_recover_http_failure_without_leaking_signature(self):
        def response(opener, request, **kwargs):
            if '/video?' in request.full_url:
                raise HTTPError(request.full_url, 412, 'DO_NOT_SAVE_TEST_SENTINEL', {}, None)
            return io.BytesIO(video.read_bytes())
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            code, result, logs = self.invoke(base / 'result', video, [{'url': MEDIA, 'backup_urls': ['https://backup.bilivideo.cn/recovery?sign=DO_NOT_SAVE_TEST_SENTINEL'], 'acodec': 'none', 'vcodec': 'avc1'}], response=lambda request, **kw: response(None, request, **kw))
            self.assertEqual(code, 0, result)
            combined = logs + (base / 'result/manifest.json').read_text()
            if 'DO_NOT_SAVE_TEST_SENTINEL' in combined:
                offset = combined.index('DO_NOT_SAVE_TEST_SENTINEL')
                self.fail(repr(combined[max(0, offset-180):offset+120]))

    def test_media_412_is_sanitized_and_leaves_no_download_in_output(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = base / 'unused'
            failure = HTTPError(MEDIA, 412, 'DO_NOT_SAVE_TEST_SENTINEL', {}, None)
            code, result, logs = self.invoke(base / 'result', video, response=lambda *a, **k: (_ for _ in ()).throw(failure))
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['http_status'], 412)
            failure.close()
            combined = logs + (base / 'result/manifest.json').read_text()
            if 'DO_NOT_SAVE_TEST_SENTINEL' in combined:
                offset = combined.index('DO_NOT_SAVE_TEST_SENTINEL')
                self.fail(repr(combined[max(0, offset-180):offset+120]))
            self.assertFalse(list((base / 'result').glob('*.mp4')))

    def test_private_dns_and_unsafe_media_targets_are_rejected_before_transport(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('must not connect')
        cases = [('https://127.0.0.1/secret', None), ('http://cdn.bilivideo.com/secret', None),
                 ('https://secret@cdn.bilivideo.com/secret', None),
                 (MEDIA, [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.2', 443))])]
        for media, dns in cases:
            with self.subTest(media=media), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                code, result, logs = self.invoke(base / 'result', base / 'unused', [{'url': media, 'vcodec': 'h264', 'acodec': 'none'}], response=forbidden, dns=dns)
                self.assertEqual(code, 2)
                self.assertEqual(result['error']['code'], 'unsafe_media_target')

    def test_https_redirect_to_private_dns_is_rejected(self):
        def response(request, **kwargs):
            headers = Message()
            headers['Location'] = 'https://127.0.0.1/?sign=DO_NOT_SAVE_TEST_SENTINEL'
            from anonymous_network import PublicRedirect
            from unittest.mock import patch
            with patch('socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]):
                return PublicRedirect().redirect_request(request, io.BytesIO(), 302, 'Moved', headers, headers['Location'])
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            code, result, logs = self.invoke(base / 'result', base / 'unused', response=response)
            self.assertEqual(result['error']['code'], 'unsafe_media_target')
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', logs)

    def test_invalid_initial_url_never_invokes_backend(self):
        urls = ('https://evil.example/video/BV1b5411x7Ku', 'https://www.bilibili.com.evil.example/video/BV1b5411x7Ku',
                'https://secret@www.bilibili.com/video/BV1b5411x7Ku', 'https://www.bilibili.com/video/BV1b5411x7Ku?p=0',
                'https://www.bilibili.com/video/BV1b5411x7Ku?p=1&p=2', 'file:///etc/passwd')
        for url in urls:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                code, result, logs = self.invoke(base / 'result', base / 'unused', url=url, backend_error=AssertionError('backend must not run'))
                self.assertEqual(code, 2)
                self.assertEqual(result['error']['code'], 'invalid_bilibili_url')

    def test_existing_user_partial_and_results_are_preserved(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            partial = base / 'anonymous-video.partial'
            partial.write_bytes(b'user-file')
            code, result, logs = self.invoke(base, base / 'unused', backend_error=AssertionError('backend must not run'))
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'existing_output')
            self.assertEqual(partial.read_bytes(), b'user-file')

    def test_acquisition_failure_can_retry_same_directory_without_overwriting_user_files(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            output = base / 'result'
            code, result, _ = self.invoke(output, video, backend_error=RuntimeError('fixture failure'))
            self.assertEqual(code, 2)
            self.assertEqual(result['phase'], 'acquisition')
            self.assertEqual(set(path.name for path in output.iterdir()), {'manifest.json'})
            code, result, _ = self.invoke(output, video)
            self.assertEqual(code, 0, result)
            pdf = (output / 'score.pdf').read_bytes()
            code, result, _ = self.invoke(output, video)
            self.assertEqual(result['error']['code'], 'existing_output')
            self.assertEqual((output / 'score.pdf').read_bytes(), pdf)

    def test_failure_diagnosis_with_unknown_files_cannot_retry(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            output = base / 'result'
            self.invoke(output, base / 'unused', backend_error=RuntimeError('fixture'))
            diagnosis = (output / 'manifest.json').read_bytes()
            user = output / 'notes.txt'
            user.write_bytes(b'user notes')
            _, result, _ = self.invoke(output, base / 'unused')
            self.assertEqual(result['error']['code'], 'existing_output')
            self.assertEqual((output / 'manifest.json').read_bytes(), diagnosis)
            self.assertEqual(user.read_bytes(), b'user notes')

    def test_probe_failure_can_retry_the_same_directory(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            invalid = base / 'invalid.mp4'
            invalid.write_bytes(b'not a video')
            output = base / 'result'
            _, result, _ = self.invoke(output, invalid)
            self.assertEqual(result['error']['code'], 'undecodable_video')
            self.assertFalse(list(output.glob('*.mp4')))
            video = video_from_image(score_frame(), base)
            code, result, _ = self.invoke(output, video)
            self.assertEqual(code, 0, result)

    @unittest.skipUnless(Path('/dev/shm').is_dir(), 'requires separate destination filesystem')
    def test_cross_filesystem_publication_uses_exclusive_complete_video(self):
        with tempfile.TemporaryDirectory() as scratch, tempfile.TemporaryDirectory(dir='/dev/shm') as destination:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            output = Path(destination) / 'result'
            if base.stat().st_dev == Path(destination).stat().st_dev:
                self.skipTest('fixture and destination are on same filesystem')
            code, result, _ = self.invoke(output, video)
            self.assertEqual(code, 0, result)
            self.assertEqual((output / 'BV1b5411x7Ku-p2.mp4').read_bytes(), video.read_bytes())
            self.assertEqual({p.name for p in Path(destination).iterdir()}, {'result'})

    def test_config_cookie_netrc_and_plugin_sentinels_are_not_read(self):
        from yt_dlp.extractor.bilibili import BiliBiliIE
        def extractor(backend, url):
            # This runs the actual YoutubeDL API/constructor and cookiejar setup.
            params = backend._downloader.params
            if params.get('cookiefile') or params.get('cookiesfrombrowser') or params.get('usenetrc') or params.get('cachedir'):
                raise AssertionError('anonymous isolation violated')
            if list(backend._downloader.cookiejar):
                raise AssertionError('loaded cookies')
            return {'id': 'BV1b5411x7Ku_p2', 'title': 'fixture', 'formats': [{'url': MEDIA, 'vcodec': 'avc1', 'acodec': 'none'}]}
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            config = base / 'yt-dlp/config'
            config.parent.mkdir()
            config.write_text('--cookies sentinel-cookie\n--netrc\n--username DO_NOT_SAVE_TEST_SENTINEL\n')
            netrc = base / '.netrc'
            netrc.write_text('machine bilibili.com login DO_NOT_SAVE_TEST_SENTINEL password TEST_ONLY')
            cookie = base / 'sentinel-cookie'
            cookie.write_text('DO_NOT_SAVE_TEST_SENTINEL')
            plugin = base / 'yt_dlp_plugins/extractor/sentinel.py'
            plugin.parent.mkdir(parents=True)
            plugin.write_text('raise RuntimeError("plugin sentinel was executed")')
            real_open = builtins.open
            def guarded_open(file, *args, **kwargs):
                if isinstance(file, (str, Path)) and Path(file) in {config, netrc, cookie}:
                    raise AssertionError('credential/config sentinel was read')
                return real_open(file, *args, **kwargs)
            ydl_module = importlib.import_module('yt_dlp.YoutubeDL')
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(BiliBiliIE, '_real_extract', extractor), patch.object(builtins, 'open', guarded_open), patch.object(ydl_module, 'load_all_plugins', side_effect=AssertionError('plugins were loaded')), patch.object(sys, 'path', [str(base), *sys.path]), patch.dict('os.environ', {'XDG_CONFIG_HOME': str(base), 'HOME': str(base)}), patch.object(sys, 'argv', [str(CLI), URL, '--output', str(base / 'result')]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch('urllib.request.OpenerDirector.open', side_effect=lambda *a, **k: io.BytesIO(video.read_bytes())), patch('socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]):
                code = cli.main()
            result = json.loads(stdout.getvalue())
            self.assertEqual(code, 0, result)
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', stdout.getvalue() + stderr.getvalue())

    def test_actual_connection_pins_public_dns_and_keeps_tls_hostname(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            payload = video.read_bytes()
            class WireSocket:
                def sendall(self, data): pass
                def close(self): pass
                def makefile(self, *args):
                    return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(payload)).encode() + b'\r\n\r\n' + payload)
            def connect(address, *args, **kwargs):
                if address != ('8.8.8.8', 443):
                    raise AssertionError('connection did not use the pinned address')
                return WireSocket()
            def tls(context, sock, **kwargs):
                if kwargs.get('server_hostname') != 'cdn.bilivideo.com':
                    raise AssertionError('TLS lost the original hostname')
                return sock
            proxy_env = {key: '' for key in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')}
            with patch.dict('os.environ', proxy_env), patch('socket.create_connection', side_effect=connect), patch('ssl.SSLContext.wrap_socket', tls):
                code, result, logs = self.invoke(base / 'result', video, real_transport=True)
            self.assertEqual(code, 0, result)

    def test_environment_proxy_tunnels_to_pinned_origin_without_forwarding_credentials(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            payload = video.read_bytes()
            class WireSocket:
                tunnel = False
                def sendall(self, data):
                    if data.startswith(b'CONNECT '):
                        if not data.startswith(b'CONNECT 8.8.8.8:443 '):
                            raise AssertionError('proxy must not resolve origin again')
                    elif b'Proxy-Authorization' in data:
                        raise AssertionError('proxy credentials reached origin')
                def close(self): pass
                def makefile(self, *args):
                    if not self.tunnel:
                        self.tunnel = True
                        return io.BytesIO(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(payload)).encode() + b'\r\n\r\n' + payload)
            def connect(address, *args, **kwargs):
                if address != ('127.0.0.1', 8888):
                    raise AssertionError('environment proxy was not used')
                return WireSocket()
            proxy_env = {key: '' for key in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'no_proxy', 'NO_PROXY')}
            proxy_env['https_proxy'] = 'http://test:DO_NOT_SAVE_TEST_SENTINEL@127.0.0.1:8888'
            with patch.dict('os.environ', proxy_env), patch('socket.create_connection', side_effect=connect), patch('ssl.SSLContext.wrap_socket', lambda context, sock, **kwargs: sock):
                code, result, logs = self.invoke(base / 'result', video, real_transport=True)
            self.assertEqual(code, 0, result)
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', logs)

    def test_wrong_page_and_undecodable_video_stop_without_publication(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            invalid = base / 'invalid'
            invalid.write_bytes(b'not a video')
            code, result, logs = self.invoke(base / 'wrong-page', invalid, info_id='BV1b5411x7Ku_p1')
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'unavailable_page')
            code, result, logs = self.invoke(base / 'invalid-video', invalid)
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'undecodable_video')
            self.assertFalse(list((base / 'invalid-video').glob('*.mp4')))

    def test_redirects_reject_http_and_stop_after_five_hops(self):
        for mode in ('http', 'loop'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                video = video_from_image(score_frame(), base)
                count = [0]
                class WireSocket:
                    def sendall(self, data): pass
                    def close(self): pass
                    def makefile(self, *args):
                        count[0] += 1
                        if count[0] > 6:
                            raise AssertionError('redirect limit did not stop connections')
                        scheme = 'http' if mode == 'http' else 'https'
                        address = f'{scheme}://cdn.bilivideo.com/hop{count[0]}?sign=DO_NOT_SAVE_TEST_SENTINEL'
                        return io.BytesIO(b'HTTP/1.1 302 Found\r\nLocation: ' + address.encode() + b'\r\nContent-Length: 0\r\n\r\n')
                proxy_env = {key: '' for key in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')}
                with patch.dict('os.environ', proxy_env), patch('socket.create_connection', return_value=WireSocket()), patch('ssl.SSLContext.wrap_socket', lambda context, sock, **kwargs: sock):
                    code, result, logs = self.invoke(base / 'result', video, real_transport=True)
                self.assertEqual(code, 2)
                self.assertEqual(result['error']['code'], 'unsafe_media_target' if mode == 'http' else 'http_unavailable')
                self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', logs)

    def test_extractor_can_read_metadata_through_real_bounded_transport(self):
        from yt_dlp.extractor.bilibili import BiliBiliIE
        def extractor(backend, url):
            html = backend._download_webpage('https://www.bilibili.com/metadata', 'fixture')
            if html != 'fixture html':
                raise AssertionError('metadata response did not cross transport correctly')
            return {'id': 'BV1b5411x7Ku_p2', 'title': 'fixture', 'formats': [{'url': MEDIA, 'vcodec': 'avc1', 'acodec': 'none'}]}
        for oversized in (False, True):
            with self.subTest(oversized=oversized), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                video = video_from_image(score_frame(), base)
                class WireSocket:
                    metadata = False
                    def sendall(self, data):
                        self.metadata = b'GET /metadata ' in data
                    def close(self): pass
                    def makefile(self, *args):
                        payload = ((b'x' * (2 * 1024**2 + 1)) if oversized else b'fixture html') if self.metadata else video.read_bytes()
                        return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(payload)).encode() + b'\r\n\r\n' + payload)
                proxy_env = {key: '' for key in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')}
                with patch.object(BiliBiliIE, '_real_extract', extractor), patch.dict('os.environ', proxy_env), patch('socket.create_connection', side_effect=lambda *a, **k: WireSocket()), patch('ssl.SSLContext.wrap_socket', lambda context, sock, **kwargs: sock):
                    code, result, logs = self.invoke(base / 'result', video, real_transport=True, actual_backend=True)
                self.assertEqual(code, 2 if oversized else 0, result)
                if oversized:
                    self.assertEqual(result['error']['code'], 'download_too_large')

if __name__ == '__main__':
    unittest.main()
