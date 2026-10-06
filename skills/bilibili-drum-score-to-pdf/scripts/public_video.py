"""Anonymous public Bilibili input. Signed media addresses remain in memory."""
from pathlib import Path
import re
import multiprocessing
import os
import shutil
import signal
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit


class InputError(Exception):
    def __init__(self, code, message, origin=None):
        super().__init__(message)
        self.code, self.origin = code, origin


def video_origin(url):
    try:
        if any(ord(character) < 33 for character in url):
            raise ValueError
        parsed = urlsplit(url)
        match = re.fullmatch(r'/video/(BV[0-9A-Za-z]{10})/?', parsed.path)
        if parsed.scheme != 'https' or parsed.hostname not in {'www.bilibili.com', 'bilibili.com'} or parsed.username is not None or parsed.password is not None or parsed.port not in {None, 443} or not match:
            raise ValueError
        pages = parse_qs(parsed.query, keep_blank_values=True).get('p', ['1'])
        if len(pages) != 1 or not re.fullmatch(r'[1-9][0-9]{0,5}', pages[0]):
            raise ValueError
        page = int(pages[0])
        bvid = match.group(1)
        return {'kind': 'bilibili', 'bvid': bvid, 'page': page, 'url': f'https://www.bilibili.com/video/{bvid}?p={page}', 'authenticated': False}
    except ValueError:
        raise InputError('invalid_bilibili_url', '请提供 https://www.bilibili.com/video/BV… 格式链接，分 P 使用单个正整数 p；也可提供清晰的本地视频。') from None


def checked_media_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if not isinstance(url, str) or any(ord(character) < 33 for character in url) or parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None or parsed.port not in {None, 443} or not any(host == domain or host.endswith('.' + domain) for domain in ('bilivideo.com', 'bilivideo.cn')):
            raise ValueError
        return url
    except (ValueError, TypeError, AttributeError):
        raise InputError('unsafe_media_target', '公开接口返回的媒体目标不在支持范围，已停止获取。请提供清晰的本地视频。') from None


# The parent deadline includes DNS, extraction, transfer and decoder subprocesses.
ACQUISITION_SECONDS = 1800
MAX_BYTES = 2 * 1024**3


def _worker(url, staging, connection):
    # Third-party exceptions and output can contain signed addresses. Never forward them.
    if hasattr(os, 'setsid'):
        os.setsid()
    with open(os.devnull, 'w') as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')
    try:
        from anonymous_backend import download
        origin = video_origin(url)
        details = download(origin, Path(staging))
        connection.send({'ok': True, 'origin': {**origin, **details}})
    except InputError as error:
        result = {'ok': False, 'code': error.code, 'message': str(error), 'origin': error.origin or video_origin(url)}
        if hasattr(error, 'http_status'):
            result['http_status'] = error.http_status
        connection.send(result)
    except BaseException:
        connection.send({'ok': False, 'code': 'public_api_unavailable', 'message': '匿名获取失败，接口受限或格式不可用。请提供清晰的本地视频。'})
    finally:
        connection.close()


def acquire(url, output):
    origin = video_origin(url)
    output = Path(output)
    # Linux uses fork so controlled third-party backends remain usable in CLI tests.
    context = multiprocessing.get_context('fork' if 'fork' in multiprocessing.get_all_start_methods() else 'spawn')
    with tempfile.TemporaryDirectory(prefix='anonymous-video-') as staging:
        parent, child = context.Pipe(duplex=False)
        process = context.Process(target=_worker, args=(origin['url'], staging, child))
        process.start()
        child.close()
        try:
            if not parent.poll(ACQUISITION_SECONDS):
                raise InputError('network_timeout', '匿名获取超过处理时限。请提供清晰的本地视频。', origin)
            try:
                result = parent.recv()
            except EOFError:
                raise InputError('public_api_unavailable', '匿名获取进程未完成。请提供清晰的本地视频。', origin) from None
            if not result['ok']:
                error = InputError(result['code'], result['message'], result.get('origin') or origin)
                if 'http_status' in result:
                    error.http_status = result['http_status']
                raise error
            origin = result['origin']
            output.mkdir(parents=True, exist_ok=True)
            source = output / f"{origin['bvid']}-p{origin['page']}.mp4"
            if source.exists():
                raise InputError('source_exists', '结果目录已有下载视频，请选择新的结果目录。', origin)
            # Copy onto the destination filesystem before an exclusive atomic publication.
            descriptor, publish = tempfile.mkstemp(prefix='.anonymous-publish-', dir=output)
            try:
                with os.fdopen(descriptor, 'wb') as destination, (Path(staging) / 'video.mp4').open('rb') as downloaded:
                    shutil.copyfileobj(downloaded, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                os.link(publish, source)
            finally:
                Path(publish).unlink(missing_ok=True)
            return source, origin
        finally:
            parent.close()
            if process.is_alive():
                if hasattr(os, 'killpg'):
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        process.terminate()
                else:
                    process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                if hasattr(os, 'killpg'):
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.join(timeout=5)
