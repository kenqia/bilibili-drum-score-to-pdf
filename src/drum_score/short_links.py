"""Resolve anonymous b23.tv redirects inside the supervised acquisition worker."""
import ssl
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .anonymous_network import PublicHTTPSHandler, public_addresses, public_target
from .public_video import InputError, video_origin


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve(url):
    origin = video_origin(url)
    if origin['kind'] != 'bilibili_short':
        return origin
    # No environment proxies, cookie jar, user configuration or automatic
    # redirects. Close responses without reading potentially large bodies.
    opener = build_opener(ProxyHandler({}),
        PublicHTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
    try:
        for _ in range(5):
            public_addresses(public_target(origin['url']))
            try:
                response = opener.open(Request(origin['url'], headers={
                    'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'}), timeout=10)
            except HTTPError as error:
                try:
                    location = error.headers.get('Location', '')
                    if error.code not in {301, 302, 303, 307, 308} or not location or len(location) > 2048:
                        raise ValueError
                    target = urljoin(origin['url'], location)
                finally:
                    error.close()
            else:
                response.close()
                raise ValueError
            origin = video_origin(target)
            public_addresses(public_target(origin['url']))
            if origin['kind'] == 'bilibili':
                return origin
    except InputError as error:
        if error.code == 'unsafe_media_target':
            raise
    except (OSError, ValueError, TypeError):
        pass
    raise InputError('short_link_unavailable', '短链接未能跳转到公开 BV 视频，请重新复制链接或使用完整 BV 链接。') from None
