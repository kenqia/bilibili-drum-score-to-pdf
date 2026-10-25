"""BBDownNext anonymous metadata with anonymous, bounded media acquisition."""
import json
import math
import re
from fractions import Fraction
import subprocess
from urllib.error import HTTPError
from .public_video import InputError, MAX_BYTES, checked_media_url
from .anonymous_network import PublicTransport


def download(origin, staging):
    from .bbdown_cli import inspect
    details = inspect(origin, staging)
    play = details.pop('play')
    formats = []
    videos = (play.get('dash') or {}).get('video') or []
    for stream in videos:
        if not isinstance(stream, dict):
            raise InputError('unsupported_stream', '匿名接口视频轨格式无效。')
        quality = stream.get('id')
        if isinstance(quality, str) and re.fullmatch(r'[0-9]{1,5}', quality):
            quality = int(quality)
        if quality is not None and (type(quality) is not int or not 0 <= quality <= 99999):
            raise InputError('unsupported_stream', '匿名接口视频格式标记无效。')
        rate = stream.get('frameRate') or stream.get('frame_rate')
        try:
            rate = float(Fraction(str(rate))) if rate is not None else None
            if rate is not None and (not math.isfinite(rate) or not 0 < rate <= 1000):
                raise ValueError
        except (ValueError, ZeroDivisionError):
            raise InputError('unsupported_stream', '匿名接口视频帧率标记无效。') from None
        for dimension in ('width', 'height'):
            value = stream.get(dimension)
            if value is not None and (type(value) is not int or not 0 < value <= 32768):
                raise InputError('unsupported_stream', '匿名接口视频尺寸标记无效。')
        bandwidth = stream.get('bandwidth')
        if bandwidth is not None and (type(bandwidth) is not int or bandwidth < 0):
            raise InputError('unsupported_stream', '匿名接口视频码率标记无效。')
        formats.append({'url': stream.get('baseUrl') or stream.get('base_url'),
            'backup_urls': stream.get('backupUrl') or stream.get('backup_url') or [],
            'vcodec': stream.get('codecs') or 'unknown', 'acodec': 'none',
            'width': stream.get('width'), 'height': stream.get('height'),
            'format_id': str(quality) if quality is not None else None, 'quality': quality,
            'fps': rate, 'tbr': bandwidth})
    if not formats:
        segments = play.get('durl') or []
        if len(segments) != 1 or not isinstance(segments[0], dict):
            raise InputError('unsupported_stream', '仅支持独立视频轨或单段完整视频。')
        stream = segments[0]
        formats.append({'url': stream.get('url'), 'backup_urls': stream.get('backup_url') or [],
                        'vcodec': 'unknown', 'acodec': 'unknown', 'filesize': stream.get('size')})
    info = {'formats': formats, 'duration': details['duration'],
            'http_headers': {'Referer': origin['url'], 'Origin': 'https://www.bilibili.com',
                             'User-Agent': 'Mozilla/5.0'}}
    transport = PublicTransport(direct=True)
    formats = [f for f in info.get('formats', []) if f.get('vcodec') != 'none' and f.get('url') and not f.get('fragments') and f.get('protocol', 'https') in {'https', 'http'}]
    independent = [f for f in formats if f.get('acodec') == 'none']
    candidates = independent or formats
    candidates.sort(key=lambda f: (f.get('height') or 0, f.get('width') or 0, str(f.get('vcodec', '')).lower().startswith(('avc', 'h264')), f.get('fps') or 0, f.get('tbr') or 0), reverse=True)
    transport.stage = 'formats'
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
                transport.stage = 'media'
                checked_media_url(address)
                total = 0
                with transport.open(address, {**info.get('http_headers', {}), **fmt.get('http_headers', {})}) as response, destination.open('wb') as target:
                    while block := response.read(min(1024 * 1024, MAX_BYTES + 1 - total)):
                        total += len(block)
                        if total > MAX_BYTES:
                            raise InputError('download_too_large', '视频超过大小上限。请提供清晰的本地视频。')
                        target.write(block)
                transport.stage = 'probe'
                probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,codec_name,r_frame_rate:format=duration', '-of', 'json', str(destination)], capture_output=True, timeout=30)
                metadata = json.loads(probe.stdout)
                stream = metadata['streams'][0]
                if probe.returncode or not stream.get('width') or not stream.get('height'):
                    raise ValueError
                decode = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(destination), '-map', '0:v:0', '-frames:v', '1', '-f', 'null', '-'], capture_output=True, timeout=30)
                if decode.returncode:
                    raise ValueError
                actual_duration = float(metadata.get('format', {}).get('duration', 'nan'))
                if not math.isfinite(actual_duration) or abs(actual_duration - info['duration']) > 0.5:
                    raise InputError('incomplete_video', '下载文件时长与目标分 P 不一致。')
                if stream['width'] < (fmt.get('width') or 0) or stream['height'] < (fmt.get('height') or 0):
                    raise InputError('media_resolution_mismatch', '视频实测分辨率低于公开格式标记。请提供清晰的本地视频。', {**origin, 'backend': 'BBDownNext', 'backend_version': '2.3.0', 'anonymous': True, 'actual_video': stream})
                return {'backend': 'BBDownNext', 'backend_version': '2.3.0', 'anonymous': True,
                        'backend_build': details['backend_build'], 'backend_sha256': details['backend_sha256'],
                        'acquisition_route': 'bbdown_direct', 'cid': details['cid'], 'aid': details['aid'],
                        'full_duration': info['duration'], 'single_file_fallback': not bool(independent), 'actual_video': stream,
                        'format_attempts': attempt, 'backup_used': bool(backup),
                        'selected_format': {'format_id': fmt.get('format_id'), 'width': fmt.get('width'), 'height': fmt.get('height'), 'fps': fmt.get('fps'), 'quality': fmt.get('quality')}}
            except InputError as error:
                error.diagnostics = {'failure_stage': transport.stage, 'backend_error_type': type(error).__name__}
                if error.code == 'unsafe_media_target':
                    # Reject this address, then validate the next bounded candidate.
                    # Size, duration and resolution failures remain terminal.
                    last_error = error
                    continue
                raise
            except HTTPError as error:
                last_error = InputError('http_unavailable', '媒体服务器拒绝匿名获取。请提供清晰的本地视频。')
                last_error.diagnostics = {'failure_stage': 'media', 'backend_error_type': 'HTTPError'}
                last_error.http_status = int(error.code)
                error.close()
            except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as cause:
                last_error = InputError('undecodable_video', '视频获取失败或无法解码。请提供清晰的本地视频。')
                last_error.diagnostics = {'failure_stage': transport.stage,
                                          'backend_error_type': transport.backend_error_type or type(cause).__name__,
                                          'proxy_connect_status': transport.proxy_connect_status}
    raise last_error or InputError('unsupported_stream', '没有可解码视频轨。请提供清晰的本地视频。')
