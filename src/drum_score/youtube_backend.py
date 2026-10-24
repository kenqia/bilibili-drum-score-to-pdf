"""Anonymous YouTube metadata through a bounded, pinned-IP HTTPS transport."""
import gzip
import io
import math
import os
import shutil
import socket
import tempfile
from importlib.metadata import PackageNotFoundError, version
from urllib.error import HTTPError

from .anonymous_network import PublicTransport, public_target, public_addresses
from .anonymous_backend import download_formats
from .public_video import InputError, MAX_BYTES

VERSION = '2026.10.21'
MAX_RESPONSE = 8 * 1024**2


def _ipv4_addresses(host):
    return public_addresses(host, family=socket.AF_INET)


def checked_target(url, *, media=False):
    host = public_target(url)
    allowed = host.endswith('.googlevideo.com')
    if not media:
        allowed = allowed or host in {'www.youtube.com', 'youtube.com', 'youtubei.googleapis.com',
                                      'i.ytimg.com', 's.ytimg.com'}
    if not allowed:
        raise InputError('unsafe_media_target', 'YouTube 返回了不支持的获取目标。')
    return host


class _Body(io.IOBase):
    def __init__(self, response, transport, *, decode=True):
        self.response, self.transport, self.total = response, transport, 0
        encoding = response.headers.get('Content-Encoding', '').lower()
        if decode and encoding not in {'', 'identity', 'gzip'}:
            raise InputError('unsupported_stream', 'YouTube 响应编码不受支持。')
        self.reader = (gzip.GzipFile(fileobj=_Body(response, transport, decode=False))
                       if decode and encoding == 'gzip' else response)

    def read(self, size=-1):
        remaining = MAX_RESPONSE + 1 - self.total
        block = self.reader.read(remaining if size is None or size < 0 else min(size, remaining))
        self.total += len(block)
        if self.total > MAX_RESPONSE:
            self.transport.failure = InputError('download_too_large', 'YouTube 解析响应超过大小上限。')
            raise self.transport.failure
        return block

    def readable(self):
        return True

    def close(self):
        if self.reader is not self.response:
            self.reader.close()
        self.response.close()
        super().close()


class _Logger:
    challenge = False

    def debug(self, *args, **kwargs):
        pass

    def warning(self, message):
        self.error(message)

    def error(self, message):
        # Retain only a classification, never exception text or signed addresses.
        if 'not a bot' in message.lower() or 'sign in' in message.lower():
            self.challenge = True


def inspect(origin, staging):
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.extractor.youtube import YoutubeIE
        from yt_dlp.globals import all_plugins_loaded, plugin_dirs
        from yt_dlp.networking import Response
        from yt_dlp.utils import std_headers
        from yt_dlp.version import __version__
    except ImportError:
        raise InputError('dependency_missing', '需要安装网站独立的 yt-dlp 和 yt-dlp-ejs 依赖。') from None
    try:
        ejs_version = version('yt-dlp-ejs')
    except PackageNotFoundError:
        raise InputError('dependency_missing', '需要安装固定的 yt-dlp-ejs 依赖。') from None
    if __version__ != VERSION or ejs_version != '0.8.0':
        raise InputError('backend_version_mismatch', 'yt-dlp 版本与已验证版本不一致。')
    deno = shutil.which('deno')
    if not deno:
        raise InputError('dependency_missing', 'YouTube 获取需要安装 Deno JavaScript 运行时。')
    # The library API does not parse CLI configuration. Disable constructor plugins.
    plugin_dirs.value = []
    all_plugins_loaded.value = True
    transport = PublicTransport(check_target=checked_target, resolver=_ipv4_addresses)
    logger = _Logger()

    class AnonymousDL(YoutubeDL):
        def urlopen(self, request):
            url = request if isinstance(request, str) else request.url
            headers = {**std_headers, **({} if isinstance(request, str) else dict(request.headers))}
            data = None if isinstance(request, str) else request.data
            try:
                response = transport.open(url, headers, data)
                try:
                    body = _Body(response, transport)
                except BaseException:
                    response.close()
                    raise
            except InputError as error:
                transport.failure = error
                raise
            except HTTPError as error:
                transport.http_status = error.code
                error.close()
                raise InputError('http_unavailable', 'YouTube 拒绝了匿名解析请求。') from None
            return Response(body, url=response.geturl(), headers=dict(response.headers), status=response.status)

    options = {'quiet': True, 'no_warnings': True, 'logger': logger, 'noplaylist': True,
               'cachedir': False, 'cookiefile': None, 'cookiesfrombrowser': None, 'usenetrc': False,
               'username': None, 'password': None, 'skip_download': True, 'writeinfojson': False,
               'socket_timeout': 20, 'extractor_retries': 0, 'retries': 0,
               'js_runtimes': {'deno': {'path': deno}}, 'remote_components': [],
               'extractor_args': {'youtube': {'player_client': ['web_embedded']}}}
    # Only this acquisition worker changes environment. Preserve it for its media
    # transport, which uses the already-created opener and explicit proxy settings.
    original = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix='youtube-home-', dir=staging) as home:
            os.environ.clear()
            os.environ.update({'HOME': home, 'XDG_CONFIG_HOME': home, 'XDG_CACHE_HOME': home,
                               'TMPDIR': home, 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
            for client in ('web_embedded', 'default'):
                options['extractor_args']['youtube']['player_client'] = [client]
                try:
                    with AnonymousDL(options, auto_init=False) as backend:
                        backend.add_info_extractor(YoutubeIE())
                        info = backend.extract_info(origin['url'], download=False)
                    break
                except Exception:
                    if transport.failure or client == 'default':
                        raise
    except Exception as cause:
        if transport.failure:
            raise transport.failure from None
        if logger.challenge:
            raise InputError('youtube_challenge', 'YouTube 要求机器人或身份验证，请稍后重试或提供清晰的本地视频。') from None
        error = InputError('public_api_unavailable', 'YouTube 匿名解析失败，请检查服务器出网或稍后重试。')
        error.diagnostics = {'failure_stage': 'metadata',
                             'backend_error_type': transport.backend_error_type or type(cause).__name__}
        if transport.http_status:
            error.http_status = transport.http_status
        raise error from None
    finally:
        os.environ.clear()
        os.environ.update(original)
    if (not isinstance(info, dict) or info.get('id') != origin['video_id']
            or info.get('_type') in {'playlist', 'multi_video'}
            or info.get('live_status') != 'not_live'
            or info.get('availability') not in {None, 'public', 'unlisted'}
            or (info.get('age_limit') or 0) >= 18):
        raise InputError('unsupported_stream', '仅支持无需登录或年龄验证的单条 YouTube 非直播视频。')
    duration = info.get('duration')
    if type(duration) not in {int, float} or not math.isfinite(duration) or duration <= 0:
        raise InputError('incomplete_video', '无法确认 YouTube 视频的完整时长。')
    return info


def download(origin, staging, *, max_bytes=MAX_BYTES):
    info = inspect(origin, staging)
    transport = PublicTransport(check_target=lambda url: checked_target(url, media=True), resolver=_ipv4_addresses)
    return download_formats(info, staging, origin=origin,
        backend_details={'backend': 'yt-dlp', 'backend_version': VERSION,
                         'acquisition_route': 'youtube_anonymous', 'duration_tolerance_seconds': 1.0},
        transport=transport, max_bytes=min(max_bytes, MAX_BYTES),
        check_url=lambda url: checked_target(url, media=True), duration_tolerance=1.0)
