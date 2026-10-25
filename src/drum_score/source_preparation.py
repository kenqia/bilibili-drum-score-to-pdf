"""Private, supervised source preparation; signed addresses never enter manifests."""
import hashlib
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from .core import ConversionError, digest
from .public_video import InputError, checked_media_url


def prepare(operation, source, output, limits, inspection=None):
    from . import anonymous_backend, video_seek
    try:
        if operation == 'inspect':
            from .short_links import resolve
            origin = resolve(source)
            if origin['kind'] != 'bilibili':
                return None  # Other providers retain their existing acquisition path.
            inspection = anonymous_backend.inspect_source(origin, Path(output).parent)
            duration = inspection['info'].get('duration')
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                raise InputError('incomplete_video', '无法核验原来源完整时长。')
            if duration > 600:
                raise InputError('resource_limit', '原来源视频超过600秒，选择短片段也不能绕过时长限制。')
            formats = [f for f in inspection['info']['formats'] if f.get('vcodec') != 'none' and f.get('url') and not f.get('fragments')]
            independent = [f for f in formats if f.get('acodec') == 'none']
            formats = independent or formats
            formats.sort(key=lambda f: (f.get('height') or 0, f.get('width') or 0, str(f.get('vcodec', '')).lower().startswith(('avc', 'h264')), f.get('fps') or 0, f.get('tbr') or 0), reverse=True)
            inspection['version'] = None
            if formats:
                fmt = formats[0]
                address = fmt['url']
                checked_media_url(address)
                # Validator failure only disables cache reuse, not ordinary acquisition.
                try:
                    with anonymous_backend.PublicTransport(direct=True).open(address, {**inspection['info'].get('http_headers', {}), 'Range': 'bytes=0-0'}) as response:
                        etag = response.headers.get('ETag', '')
                        match = re.fullmatch(r'bytes 0-0/([1-9][0-9]*)', response.headers.get('Content-Range', ''))
                        if response.status == 206 and match and len(etag) <= 512 and re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag):
                            parsed = urlsplit(address)
                            version = {'etag_sha256': hashlib.sha256(etag.encode()).hexdigest(),
                                'resource_sha256': hashlib.sha256((parsed.hostname + parsed.path).encode()).hexdigest(),
                                'bytes': int(match.group(1)), 'format_id': fmt.get('format_id')}
                            inspection['version'] = version
                            # Bind full transfer to this exact inspected representation.
                            inspection['info']['formats'] = [fmt]
                            fmt['_cache_version'] = version
                except Exception:
                    pass
            return inspection
        output = Path(output)
        output.mkdir()
        details = anonymous_backend.download_inspected(inspection, output, max_bytes=int(limits['input_bytes']))
        local = output / 'video.mp4'
        metadata = video_seek.probe_video(local)
        if metadata['duration'] > 600 or abs(metadata['duration'] - inspection['info']['duration']) > .5:
            raise InputError('incomplete_video', '下载文件时长与目标视频不一致。')
        return {'origin': {**inspection['origin'], **details}, 'sha256': digest(local),
            'metadata': metadata, 'bytes': local.stat().st_size, 'metrics': {}}
    except InputError as error:
        raise ConversionError(error.code, str(error)) from None
