"""Anonymous public Bilibili input. Signed media addresses remain in memory."""
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import urllib.request


class InputError(Exception):
    def __init__(self, code, message, origin=None):
        super().__init__(message)
        self.code, self.origin = code, origin


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise InputError('network_redirect', '公开接口或媒体发生重定向，已停止获取。请提供清晰的本地视频。')


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


def acquire(url, output):
    origin = video_origin(url)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': origin['url']}
    temporary = output / 'anonymous-video.partial'
    # Socket timeout bounds blocking transport operations, not system DNS or total duration.
    deadline = time.monotonic() + 1800
    created_temporary = False

    def read_response(address, limit, destination=None):
        request = urllib.request.Request(address, headers=headers)
        total, blocks = 0, []
        with opener.open(request, timeout=20) as response:
            while True:
                if time.monotonic() > deadline:
                    raise InputError('network_timeout', '匿名获取超过处理时限。请提供清晰的本地视频。')
                block = response.read(min(1024 * 1024, limit + 1 - total))
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise InputError('download_too_large', '公开响应超过处理大小上限。请提供清晰的本地视频。')
                if destination is None:
                    blocks.append(block)
                else:
                    destination.write(block)
        return b''.join(blocks)

    def api(path, parameters):
        data = json.loads(read_response('https://api.bilibili.com/' + path + '?' + urlencode(parameters), 2 * 1024 * 1024))
        if not isinstance(data, dict) or data.get('code') != 0:
            raise InputError('public_api_unavailable', '匿名公开接口拒绝请求或视频不可用。请提供清晰的本地视频。')
        if not isinstance(data.get('data'), dict):
            raise ValueError
        return data['data']

    try:
        view = api('x/web-interface/view', {'bvid': origin['bvid']})
        page = next((page for page in view['pages'] if page['page'] == origin['page']), None)
        if page is None:
            raise InputError('unavailable_page', '目标分 P 不存在。请检查 p 参数，或提供该分 P 的清晰本地视频。')
        cid = page['cid']
        if type(cid) is not int or cid <= 0:
            raise ValueError
        origin['cid'] = cid
        stream = api('x/player/playurl', {'bvid': origin['bvid'], 'cid': cid, 'qn': 80, 'fnval': 1, 'fnver': 0})
        origin['api_quality'] = stream['quality']
        if type(origin['api_quality']) is not int:
            raise ValueError
        if not isinstance(stream.get('durl'), list) or len(stream['durl']) != 1:
            raise InputError('unsupported_stream', '匿名接口未提供单文件 MP4 流。请提供清晰的本地视频。')
        address = checked_media_url(stream['durl'][0]['url'])
        # Exclusive temporary creation avoids overwriting a user's file.
        with temporary.open('xb') as destination:
            created_temporary = True
            read_response(address, 2 * 1024**3, destination)
        source = output / f"{origin['bvid']}-p{origin['page']}.mp4"
        if source.exists():
            raise InputError('source_exists', '结果目录已有下载视频，请使用新的结果目录或直接转换已有本地视频。')
        source.hardlink_to(temporary)
        return source, origin
    except InputError as error:
        error.origin = origin
        raise
    except urllib.error.HTTPError as error:
        failure = InputError('http_unavailable', '匿名获取被公开接口或媒体服务器拒绝。请提供清晰的本地视频。', origin)
        failure.http_status = int(error.code)
        error.close()
        raise failure from None
    except (TimeoutError, OSError, urllib.error.URLError):
        raise InputError('network_unavailable', '匿名获取失败，网络不可用、请求超时或访问受限。请提供清晰的本地视频。', origin) from None
    except (ValueError, KeyError, TypeError, StopIteration):
        raise InputError('invalid_public_response', '匿名公开接口返回了不支持的响应。请提供清晰的本地视频。', origin) from None
    finally:
        # Only delete the partial file created by this invocation.
        if created_temporary and temporary.exists():
            temporary.unlink()
