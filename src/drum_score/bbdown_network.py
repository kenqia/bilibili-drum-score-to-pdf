"""Task-local CONNECT relay: validate and pin direct public API connections.

TLS stays between the pinned upstream and BBDownNext. This relay neither
decrypts responses nor reads system proxy configuration.
"""
import contextlib
import select
import socket
import socketserver
import threading
import time

from .anonymous_network import public_addresses
from .public_video import InputError


API_HOSTS = frozenset(('api.bilibili.com', 'www.bilibili.com'))
MAX_TUNNEL_BYTES = 8 * 1024**2


class _Tunnel(socketserver.BaseRequestHandler):
    def handle(self):
        owner = self.server.owner
        upstream = None
        try:
            with owner.lock:
                if len(owner.sockets) >= 16 or owner.stopping.is_set():
                    return
                owner.sockets.add(self.request)
            self.request.settimeout(5)
            header = bytearray()
            while b'\r\n\r\n' not in header:
                block = self.request.recv(min(4096, 8193 - len(header)))
                if not block:
                    return
                header.extend(block)
                if len(header) > 8192:
                    raise InputError('unsafe_media_target', '匿名解析连接不符合安全要求。')
            request, extra = bytes(header).split(b'\r\n\r\n', 1)
            method, authority, protocol = request.split(b'\r\n', 1)[0].decode('ascii').split(' ')
            # Exact authorities also reject userinfo, trailing dots, alternate
            # ports, IP literals, and host names appended to an allowed suffix.
            if (method != 'CONNECT' or protocol not in ('HTTP/1.0', 'HTTP/1.1')
                    or authority not in {host + ':443' for host in API_HOSTS}):
                raise InputError('unsafe_media_target', '匿名解析连接不符合安全要求。')
            host = authority[:-4]
            addresses = public_addresses(host)
            for family, kind, proto, _, numeric in addresses:
                connection = socket.socket(family, kind, proto)
                try:
                    connection.settimeout(15)
                    # Do not resolve host again after validating every answer.
                    connection.connect(numeric)
                    upstream = connection
                    break
                except OSError:
                    connection.close()
            if upstream is None:
                raise OSError('public connection unavailable')
            with owner.lock:
                owner.sockets.add(upstream)
            if owner.stopping.is_set():
                return
            self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            if extra:
                upstream.sendall(extra)
            total = len(extra)
            idle = time.monotonic()
            peers = {self.request: upstream, upstream: self.request}
            while not owner.stopping.is_set() and time.monotonic() - idle < 20:
                ready, _, _ = select.select(tuple(peers), (), (), .2)
                for source in ready:
                    block = source.recv(65536)
                    if not block:
                        return
                    total += len(block)
                    if total > MAX_TUNNEL_BYTES:
                        raise InputError('download_too_large', '匿名解析响应超过大小上限。')
                    peers[source].sendall(block)
                    idle = time.monotonic()
        except InputError as error:
            with owner.lock:
                owner.failure = owner.failure or error
            with contextlib.suppress(OSError):
                self.request.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
        except (OSError, ValueError, UnicodeError):
            with contextlib.suppress(OSError):
                self.request.sendall(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n')
        finally:
            with owner.lock:
                owner.sockets.discard(self.request)
                owner.sockets.discard(upstream)
            if upstream is not None:
                upstream.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    block_on_close = False

    def verify_request(self, request, address):
        with self.owner.lock:
            return address[0] == '127.0.0.1' and len(self.owner.sockets) < 16

    def handle_error(self, request, address):
        # Default socketserver output may contain private third-party payloads.
        pass


class DirectGateway:
    def __init__(self):
        self.failure = None
        self.lock = threading.Lock()
        self.sockets = set()
        self.stopping = threading.Event()

    def __enter__(self):
        self.server = _Server(('127.0.0.1', 0), _Tunnel)
        self.server.owner = self
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *unused):
        self.stopping.set()
        with self.lock:
            for connection in self.sockets:
                with contextlib.suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
