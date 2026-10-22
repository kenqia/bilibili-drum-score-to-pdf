"""Opaque relay tests with synthetic local peers, never public services."""
import socket
import socketserver
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from drum_score.bbdown_network import DirectGateway
from drum_score.public_video import InputError


def connect(gateway):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(3)
    client.connect(('127.0.0.1', urlsplit(gateway.url).port))
    return client


class DirectGatewayTests(unittest.TestCase):
    def test_arbitrary_hosts_ports_cleartext_and_oversized_headers_never_resolve(self):
        cases = [b'GET https://api.bilibili.com/ HTTP/1.1\r\n\r\n',
                 b'CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n',
                 b'CONNECT api.bilibili.com:80 HTTP/1.1\r\n\r\n',
                 b'CONNECT api.bilibili.com.evil.example:443 HTTP/1.1\r\n\r\n',
                 b'CONNECT account@api.bilibili.com:443 HTTP/1.1\r\n\r\n',
                 b'CONNECT api.bilibili.com:443 HTTP/1.1\r\nX: ' + b'x' * 8192]
        for request in cases:
            with self.subTest(request=request[:65]), DirectGateway() as gateway, \
                    patch('drum_score.bbdown_network.public_addresses',
                          side_effect=AssertionError('must reject before DNS')):
                with connect(gateway) as client:
                    client.sendall(request)
                    self.assertIn(b'403 Forbidden', client.recv(4096))
                self.assertEqual(gateway.failure.code, 'unsafe_media_target')

    def test_private_dns_answer_is_rejected_before_connecting_upstream(self):
        error = InputError('unsafe_media_target', 'synthetic nonpublic answer')
        with DirectGateway() as gateway, patch('drum_score.bbdown_network.public_addresses', side_effect=error):
            with connect(gateway) as client:
                client.sendall(b'CONNECT api.bilibili.com:443 HTTP/1.1\r\n\r\n')
                self.assertIn(b'403 Forbidden', client.recv(4096))
            self.assertIs(gateway.failure, error)

    def test_connect_uses_validated_numeric_address_and_preserves_tls_bytes(self):
        # The upstream is deliberately synthetic. Production public_addresses
        # refuses this local address, tested above and by anonymous_network tests.
        opaque = b'\x16\x03\x03\x00\x16SYNTHETIC_TLS_BYTES'

        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.sendall(self.request.recv(4096))

        server = socketserver.TCPServer(('127.0.0.1', 0), Echo)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            numeric = server.server_address
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', numeric)]
            with DirectGateway() as gateway, \
                    patch('drum_score.bbdown_network.public_addresses', return_value=answers) as resolved:
                with connect(gateway) as client:
                    with patch('socket.getaddrinfo', side_effect=AssertionError('must not resolve twice')):
                        client.sendall(b'CONNECT api.bilibili.com:443 HTTP/1.1\r\n\r\n')
                        self.assertIn(b'200 Connection Established', client.recv(4096))
                        client.sendall(opaque)
                        self.assertEqual(client.recv(4096), opaque)
                resolved.assert_called_once_with('api.bilibili.com')
                self.assertIsNone(gateway.failure)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_exit_closes_idle_client_tunnel_and_listening_port(self):
        gateway = DirectGateway()
        with gateway:
            port = urlsplit(gateway.url).port
            pending = connect(gateway)
            deadline = time.monotonic() + 1
            while not gateway.sockets and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(gateway.sockets)
        with pending:
            self.assertEqual(pending.recv(1), b'')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            with self.assertRaises(OSError):
                client.connect(('127.0.0.1', port))


if __name__ == '__main__':
    unittest.main()
