"""HTTPS-only urllib transport; pin the validated origin IP at connect time."""
import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlsplit
import urllib.request
from .public_video import InputError


def public_target(url):
    try:
        parsed = urlsplit(url)
        if any(ord(c) < 33 for c in url) or parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
            raise ValueError
        return parsed.hostname
    except (ValueError, TypeError, AttributeError):
        raise InputError('unsafe_media_target', '获取目标不符合安全要求。请提供清晰的本地视频。') from None


def public_addresses(host, *, family=socket.AF_UNSPEC):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, family=family)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise InputError('unsafe_media_target', '获取目标解析到非公开地址。请提供清晰的本地视频。')
    return addresses


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, resolver=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resolve = resolver or (lambda host: public_addresses(host))

    def connect(self):
        origin = self._tunnel_host or self.host
        addresses = self.resolve(origin)
        # Each attempt uses an already validated numeric IP. An unavailable
        # IPv6 route must not prevent trying a reachable public IPv4 address.
        tunnel_host = self._tunnel_host
        tunnel_headers = self._tunnel_headers
        last_error = None
        for item in addresses:
            address = item[4][0]
            try:
                if tunnel_host:
                    self.sock = self._create_connection((self.host, self.port), self.timeout, self.source_address)
                    self._tunnel_host = address
                    # Python 3.12+ generates Host in set_tunnel(), before we pin
                    # the target. CONNECT and its Host must use the same authority.
                    self._tunnel_headers = {key: value for key, value in tunnel_headers.items()
                                            if key.lower() != 'host'}
                    authority = f'[{address}]' if ':' in address else address
                    self._tunnel_headers['Host'] = f'{authority}:{self._tunnel_port}'
                    self._tunnel()
                else:
                    self.sock = self._create_connection((address, self.port), self.timeout, self.source_address)
                self.sock = self._context.wrap_socket(self.sock, server_hostname=origin)
                return
            except OSError as error:
                last_error = error
                if self.sock:
                    self.sock.close()
                    self.sock = None
            finally:
                self._tunnel_host = tunnel_host
                self._tunnel_headers = tunnel_headers
        raise last_error



class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, *, context=None, resolver=None):
        super().__init__(context=context)
        self.resolve = resolver

    def https_open(self, request):
        return self.do_open(lambda *args, **kwargs: PublicHTTPSConnection(
            *args, resolver=self.resolve, **kwargs), request, context=self._context)


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def __init__(self, check_target=public_target, resolver=None):
        self.check_target = check_target
        self.resolve = resolver or (lambda host: public_addresses(host))

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.resolve(self.check_target(newurl))
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            redirected.remove_header('Proxy-authorization')
        return redirected


class PublicTransport:
    def __init__(self, *, direct=False, check_target=public_target, resolver=None):
        # ProxyHandler follows the environment without persisting or logging it.
        proxy = urllib.request.ProxyHandler({}) if direct else urllib.request.ProxyHandler()
        self.check_target = check_target
        self.resolve = resolver or (lambda host: public_addresses(host))
        self.opener = urllib.request.build_opener(proxy,
            PublicHTTPSHandler(context=ssl.create_default_context(), resolver=self.resolve),
            PublicRedirect(check_target, resolver=self.resolve))
        self.http_status = None
        self.proxy_connect_status = None
        self.failure = None
        self.stage = 'webpage'
        self.backend_error_type = None

    def open(self, url, headers=None, data=None):
        self.proxy_connect_status = None
        self.http_status = None
        parsed = urlsplit(url)
        self.stage = ('media' if parsed.hostname and 'bilivideo' in parsed.hostname
                      else 'playurl' if 'playurl' in parsed.path
                      else 'wbi' if '/wbi/' in parsed.path or parsed.path.endswith('/nav')
                      else 'webpage')
        try:
            self.resolve(self.check_target(url))
            clean = {k: v for k, v in (headers or {}).items() if k.lower() not in {'cookie', 'authorization', 'proxy-authorization', 'accept-encoding'}}
            clean['Accept-Encoding'] = 'identity'
            return self.opener.open(urllib.request.Request(url, data=data, headers=clean), timeout=20)
        except Exception as error:
            self.backend_error_type = (type(error).__name__ if isinstance(error, urllib.error.HTTPError)
                                       else type(getattr(error, 'reason', error)).__name__)
            reason = getattr(error, 'reason', error)
            if not isinstance(error, urllib.error.HTTPError) and isinstance(reason, OSError):
                match = re.match(r'^Tunnel connection failed: ([0-9]{3})(?:\s|$)', str(reason))
                if match:
                    self.proxy_connect_status = int(match[1])
            if isinstance(error, InputError):
                self.failure = error
            raise
