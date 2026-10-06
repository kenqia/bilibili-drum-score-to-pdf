"""Built-in yt-dlp Bilibili extractor with anonymous, bounded media acquisition."""
import json
import io
import subprocess
from urllib.error import HTTPError
from public_video import InputError, MAX_BYTES, checked_media_url
from anonymous_network import PublicTransport


class BoundedBody(io.IOBase):
    def __init__(self, response, transport, limit=2 * 1024**2):
        self.response, self.transport, self.limit, self.total = response, transport, limit, 0

    def read(self, size=-1):
        size = -1 if size is None else size
        amount = self.limit + 1 - self.total
        block = self.response.read(amount if size < 0 else min(size, amount))
        self.total += len(block)
        if self.total > self.limit:
            self.transport.failure = InputError('download_too_large', '公开响应超过大小上限。请提供清晰的本地视频。')
            raise self.transport.failure
        return block

    def readable(self):
        return True

    def close(self):
        self.response.close()
        super().close()


class SilentLogger:
    def debug(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass


def download(origin, staging):
    from yt_dlp import YoutubeDL
    from yt_dlp.globals import all_plugins_loaded, plugin_dirs
    from yt_dlp.extractor.bilibili import BiliBiliIE
    from yt_dlp.networking import Response
    from yt_dlp.version import __version__
    # The Python API does not parse CLI config files. Prevent constructor plugin load.
    plugin_dirs.value = []
    all_plugins_loaded.value = True
    transport = PublicTransport()

    class AnonymousBiliIE(BiliBiliIE):
        def extract_formats(self, play_info):
            formats = super().extract_formats(play_info)
            dash = (play_info or {}).get('dash') or {}
            streams = list(dash.get('video') or []) + list((play_info or {}).get('durl') or [])
            for fmt in formats:
                for stream in streams:
                    if fmt.get('url') == (stream.get('baseUrl') or stream.get('base_url') or stream.get('url')):
                        fmt['backup_urls'] = stream.get('backupUrl') or stream.get('backup_url') or []
                        if stream in (dash.get('video') or []):
                            fmt['acodec'] = 'none'
            return formats

    class AnonymousDL(YoutubeDL):
        def urlopen(self, request):
            url = request if isinstance(request, str) else request.url
            headers = {} if isinstance(request, str) else dict(request.headers)
            data = None if isinstance(request, str) else request.data
            try:
                response = transport.open(url, headers, data)
            except HTTPError as error:
                transport.http_status = error.code
                raise
            return Response(BoundedBody(response, transport), url=response.geturl(), headers=dict(response.headers), status=response.status)

    options = {'quiet': True, 'no_warnings': True, 'logger': SilentLogger(), 'noplaylist': True,
               'cachedir': False, 'cookiefile': None, 'cookiesfrombrowser': None, 'usenetrc': False,
               'username': None, 'password': None, 'skip_download': True, 'extract_flat': False,
               'socket_timeout': 20, 'extractor_retries': 1, 'retries': 1, 'writeinfojson': False}
    try:
        with AnonymousDL(options, auto_init=False) as backend:
            backend.add_info_extractor(AnonymousBiliIE())
            info = backend.extract_info(origin['url'], download=False)
    except InputError:
        raise
    except Exception:
        if transport.failure:
            raise transport.failure from None
        error = InputError('http_unavailable' if transport.http_status else 'public_api_unavailable', '匿名公开接口拒绝请求或视频不可用。请提供清晰的本地视频。')
        if transport.http_status:
            error.http_status = transport.http_status
        raise error from None
    expected = origin['bvid'] + '_p' + str(origin['page'])
    if not isinstance(info, dict) or info.get('_type') in {'playlist', 'multi_video'} or info.get('id') not in {expected, origin['bvid'] if origin['page'] == 1 else expected}:
        raise InputError('unavailable_page', '无法确认目标分 P。请检查 p 参数或提供清晰的本地视频。')
    formats = [f for f in info.get('formats', []) if f.get('vcodec') != 'none' and f.get('url') and not f.get('fragments') and f.get('protocol', 'https') in {'https', 'http'}]
    independent = [f for f in formats if f.get('acodec') == 'none']
    candidates = independent or formats
    candidates.sort(key=lambda f: (f.get('height') or 0, f.get('width') or 0, f.get('fps') or 0, str(f.get('vcodec', '')).lower().startswith(('avc', 'h264')), f.get('tbr') or 0), reverse=True)
    if not candidates:
        raise InputError('unsupported_stream', '匿名接口未提供支持的视频轨。请提供清晰的本地视频。')
    destination = staging / 'video.mp4'
    last_error = None
    for attempt, fmt in enumerate(candidates[:3], 1):
        if (fmt.get('filesize') or 0) > MAX_BYTES:
            raise InputError('download_too_large', '视频超过大小上限。请提供清晰的本地视频。')
        addresses = [fmt['url']] + list(fmt.get('backup_urls') or [])[:2]
        for backup, address in enumerate(addresses):
            try:
                checked_media_url(address)
                total = 0
                with transport.open(address, {**info.get('http_headers', {}), **fmt.get('http_headers', {})}) as response, destination.open('wb') as target:
                    while block := response.read(min(1024 * 1024, MAX_BYTES + 1 - total)):
                        total += len(block)
                        if total > MAX_BYTES:
                            raise InputError('download_too_large', '视频超过大小上限。请提供清晰的本地视频。')
                        target.write(block)
                probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,codec_name,r_frame_rate', '-of', 'json', str(destination)], capture_output=True, timeout=30)
                stream = json.loads(probe.stdout)['streams'][0]
                if probe.returncode or not stream.get('width') or not stream.get('height'):
                    raise ValueError
                decode = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(destination), '-map', '0:v:0', '-frames:v', '1', '-f', 'null', '-'], capture_output=True, timeout=30)
                if decode.returncode:
                    raise ValueError
                if stream['width'] < (fmt.get('width') or 0) or stream['height'] < (fmt.get('height') or 0):
                    raise InputError('media_resolution_mismatch', '视频实测分辨率低于公开格式标记。请提供清晰的本地视频。', {**origin, 'backend': 'yt-dlp', 'backend_version': __version__, 'anonymous': True, 'actual_video': stream})
                return {'backend': 'yt-dlp', 'backend_version': __version__, 'anonymous': True,
                        'single_file_fallback': not bool(independent), 'actual_video': stream,
                        'format_attempts': attempt, 'backup_used': bool(backup),
                        'selected_format': {'width': fmt.get('width'), 'height': fmt.get('height'), 'fps': fmt.get('fps'), 'quality': fmt.get('quality')}}
            except InputError:
                raise
            except HTTPError as error:
                last_error = InputError('http_unavailable', '媒体服务器拒绝匿名获取。请提供清晰的本地视频。')
                last_error.http_status = int(error.code)
                error.close()
            except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
                last_error = InputError('undecodable_video', '视频获取失败或无法解码。请提供清晰的本地视频。')
    raise last_error or InputError('unsupported_stream', '没有可解码视频轨。请提供清晰的本地视频。')
