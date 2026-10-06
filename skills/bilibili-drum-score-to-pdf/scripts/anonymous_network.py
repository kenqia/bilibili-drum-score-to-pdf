"""HTTPS-only urllib transport; pin the validated origin IP at connect time."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit
import urllib.request
from public_video import InputError


def public_target(url):
    try:
        parsed = urlsplit(url)
        if any(ord(c) < 33 for c in url) or parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
            raise ValueError
        return parsed.hostname
    except (ValueError, TypeError, AttributeError):
        raise InputError('unsafe_media_target', '获取目标不符合安全要求。请提供清晰的本地视频。') from None


def public_addresses(host):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise InputError('unsafe_media_target', '获取目标解析到非公开地址。请提供清晰的本地视频。')
    return addresses


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        origin = self._tunnel_host or self.host
        addresses = public_addresses(origin)
        # Connect directly to the validated numeric address, never resolve it again.
        address = addresses[0][4][0]
        if self._tunnel_host:
            # The environment proxy is an explicitly configured transport endpoint.
            self.sock = self._create_connection((self.host, self.port), self.timeout, self.source_address)
            self._tunnel_host = address
            self._tunnel()
        else:
            self.sock = self._create_connection((address, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=origin)


class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(PublicHTTPSConnection, request, context=self._context)


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_addresses(public_target(newurl))
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            redirected.remove_header('Proxy-authorization')
        return redirected


class PublicTransport:
    def __init__(self):
        # ProxyHandler follows the environment without persisting or logging it.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler(), PublicHTTPSHandler(context=ssl.create_default_context()), PublicRedirect())
        self.http_status = None
        self.failure = None

    def open(self, url, headers=None, data=None):
        public_addresses(public_target(url))
        clean = {k: v for k, v in (headers or {}).items() if k.lower() not in {'cookie', 'authorization', 'proxy-authorization', 'accept-encoding'}}
        clean['Accept-Encoding'] = 'identity'
        return self.opener.open(urllib.request.Request(url, data=data, headers=clean), timeout=20)
