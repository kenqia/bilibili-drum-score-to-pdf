"""Synthetic short-link redirects, with no authentication or real networking."""
from pathlib import Path
import io
import socket
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.public_video import InputError, video_origin
from drum_score.short_links import _NoRedirect, resolve

SHORT = 'https://b23.tv/Synthetic7'
BV = 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2'
PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]


class NoRead(io.BytesIO):
    def read(self, *args):
        raise AssertionError('Short-link response bodies must not be read')


class ShortLinks(unittest.TestCase):
    def redirect(self, target, status=302):
        body = NoRead()
        self.addCleanup(body.close)
        return HTTPError(SHORT, status, 'SYNTHETIC_PRIVATE_ERROR', {'Location': target}, body)

    def resolve_with(self, responses):
        with patch('socket.getaddrinfo', return_value=PUBLIC), patch('urllib.request.OpenerDirector.open', side_effect=responses) as opened:
            result = resolve(SHORT)
        return result, opened

    def test_acceptance_is_local_and_tracking_fields_are_discarded(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError('No network in input parsing')):
            origin = video_origin(SHORT + '/?share_source=SYNTHETIC_TRACKING#fragment')
        self.assertEqual(origin['url'], SHORT)
        self.assertIsNone(origin['bvid'])
        self.assertIsNone(origin['page'])
        self.assertFalse(origin['authenticated'])

    def test_canonical_links_do_not_contact_shortener(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError('No shortener needed')):
            self.assertEqual(resolve(BV), video_origin(BV))

    def test_redirect_keeps_final_bv_and_page_without_reading_body(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                response = self.redirect(BV + '&share_source=SYNTHETIC_TRACKING', status)
                result, opened = self.resolve_with([response])
                self.assertEqual(result, video_origin(BV))
                self.assertEqual(opened.call_count, 1)
                self.assertTrue(response.fp.closed)

    def test_relative_shortener_redirect_and_five_hop_bound(self):
        result, opened = self.resolve_with([self.redirect('/Other7'), self.redirect(BV)])
        self.assertEqual(result, video_origin(BV))
        self.assertEqual(opened.call_args_list[1].args[0].full_url, 'https://b23.tv/Other7')
        with patch('socket.getaddrinfo', return_value=PUBLIC), patch('urllib.request.OpenerDirector.open', side_effect=[self.redirect(SHORT) for _ in range(5)]) as opened:
            with self.assertRaises(InputError) as caught:
                resolve(SHORT)
        self.assertEqual(caught.exception.code, 'short_link_unavailable')
        self.assertEqual(opened.call_count, 5)

    def test_unsafe_redirects_are_never_requested(self):
        for target in ('http://www.bilibili.com/video/BV1rH4y1R7Rk',
                       'https://127.0.0.1/private', 'file:///private/synthetic',
                       'https://b23.tv.attacker.example/test',
                       'https://user:synthetic@b23.tv/path',
                       'https://www.bilibili.com/read/cv123', BV + '&p=3',
                       'https://b23.tv/' + 'A' * 3000):
            with self.subTest(target=target):
                with patch('socket.getaddrinfo', return_value=PUBLIC), patch('urllib.request.OpenerDirector.open', side_effect=[self.redirect(target)]) as opened:
                    with self.assertRaises(InputError) as caught:
                        resolve(SHORT)
                self.assertEqual(opened.call_count, 1)
                self.assertNotIn(target, str(caught.exception))

    def test_private_dns_is_rejected_before_connecting(self):
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with patch('socket.getaddrinfo', return_value=private), patch('urllib.request.OpenerDirector.open') as opened:
            with self.assertRaises(InputError) as caught:
                resolve(SHORT)
        self.assertEqual(caught.exception.code, 'unsafe_media_target')
        opened.assert_not_called()
        with patch('socket.getaddrinfo', side_effect=[PUBLIC, private]), patch('urllib.request.OpenerDirector.open', side_effect=[self.redirect(BV)]) as opened:
            with self.assertRaises(InputError) as caught:
                resolve(SHORT)
        self.assertEqual(caught.exception.code, 'unsafe_media_target')
        self.assertEqual(opened.call_count, 1)

    def test_errors_are_closed_and_sanitized(self):
        for response in (self.redirect('', 302), self.redirect(BV, 403),
                         URLError('SYNTHETIC_PRIVATE_ERROR'), NoRead()):
            with self.subTest(response=type(response).__name__):
                with self.assertRaises(InputError) as caught:
                    self.resolve_with([response])
                self.assertEqual(caught.exception.code, 'short_link_unavailable')
                self.assertNotIn('SYNTHETIC_PRIVATE_ERROR', str(caught.exception))

    def test_no_automatic_redirects_or_inherited_proxy_configuration(self):
        from drum_score import short_links
        from urllib.request import ProxyHandler
        original = short_links.build_opener
        def build(*handlers):
            self.assertTrue(any(isinstance(h, ProxyHandler) and h.proxies == {} for h in handlers))
            self.assertTrue(any(isinstance(h, _NoRedirect) for h in handlers))
            return original(*handlers)
        with patch.object(short_links, 'build_opener', side_effect=build):
            self.resolve_with([self.redirect(BV)])
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, BV))

    def test_short_url_syntax_rejects_credentials_ports_and_lookalikes(self):
        for url in ('http://b23.tv/abc', 'https://b23.tv:444/abc',
                    'https://user:synthetic@b23.tv/abc', 'https://b23.tv.attacker.example/abc',
                    'https://b23.tv/a/b', 'https://b23.tv/', 'https://b23.tv/a\nb', None):
            with self.subTest(url=url), self.assertRaises(InputError):
                video_origin(url)
