"""Pinned, isolated BBDownNext metadata process; raw responses never leave this module."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

from .public_video import InputError
from .bbdown_network import DirectGateway

# Provenance only: the official build lacks the required 2 MiB response ceiling.
OFFICIAL_SHA256 = '8e149b6d90a48bd3665b9c7efb5056e443e4a5c6d04313b8c4d21cfc6e70d114'
METADATA_SHA256 = 'd5fe48f6c2bf2e388937d3c8985c1e3dcca678e5a8d8345fa5c31e36793baf0a'
MAX_METADATA = 2 * 1024**2


def _invalid(code='unavailable_page'):
    return InputError(code, '匿名播放信息无法完整验证。请提供清晰的本地视频。')


def _json():
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    return json.JSONDecoder(object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _responses(output):
    if len(output.encode('utf-8')) > MAX_METADATA:
        raise _invalid('download_too_large')
    decoder = _json()
    values = []
    for match in re.finditer(r'Response: ', output):
        try:
            value, end = decoder.raw_decode(output, match.end())
            if end - match.end() > MAX_METADATA:
                raise _invalid('download_too_large')
            if isinstance(value, dict):
                values.append(value)
        except (ValueError, json.JSONDecodeError):
            continue
    return values


def _metadata(output, work, origin):
    responses = _responses(output)
    views = [r for r in responses if isinstance(r.get('data'), dict) and 'bvid' in r['data'] and 'pages' in r['data']]
    if len(views) != 1 or type(views[0].get('code')) is not int or views[0]['code'] != 0:
        raise _invalid()
    data = views[0]['data']
    if data.get('bvid') != origin['bvid'] or type(data.get('aid')) is not int or data['aid'] <= 0:
        raise _invalid()
    rights = data.get('rights')
    if not isinstance(rights, dict) or type(rights.get('is_stein_gate')) not in (bool, int):
        raise _invalid()
    if (rights['is_stein_gate'] or data.get('redirect_url') or data.get('is_upower_exclusive')
            or data.get('is_upower_play')):
        raise _invalid('unsupported_stream')
    if not isinstance(data.get('pages'), list) or not all(isinstance(p, dict) for p in data['pages']):
        raise _invalid()
    pages = [p for p in data['pages'] if type(p.get('page')) is int and p['page'] == origin['page']]
    if len(pages) != 1 or type(pages[0].get('cid')) is not int or pages[0]['cid'] <= 0:
        raise _invalid()
    page = pages[0]
    if not _positive(page.get('duration')):
        raise _invalid('incomplete_video')
    players = [r for r in responses if isinstance(r.get('data'), dict) and 'is_upower_exclusive' in r['data'] and 'cid' in r['data'] and 'pages' not in r['data']]
    if len(players) != 1 or type(players[0].get('code')) is not int or players[0]['code'] != 0:
        raise _invalid()
    player = players[0]['data']
    if (type(player.get('cid')) is not int or type(player.get('aid')) is not int
            or player['cid'] != page['cid'] or player['aid'] != data['aid']
            or type(player.get('is_upower_exclusive')) is not bool):
        raise _invalid()
    if player['is_upower_exclusive']:
        raise _invalid('unsupported_stream')
    requests = []
    for match in re.finditer(r'获取网页内容：Url: ([^\s,]+), Headers:', output):
        parsed = urlsplit(match.group(1))
        if parsed.path == '/x/player/wbi/playurl':
            if parsed.scheme != 'https' or parsed.hostname != 'api.bilibili.com':
                raise _invalid()
            requests.append(parse_qs(parsed.query, keep_blank_values=True))
    if len(requests) != 1:
        raise _invalid()
    query = requests[0]
    if query.get('cid') != [str(page['cid'])]:
        raise _invalid()
    identities = [key for key in ('avid', 'aid', 'bvid') if key in query]
    if not identities or any(query[key] != [origin['bvid'] if key == 'bvid' else str(data['aid'])] for key in identities):
        raise _invalid()
    files = list(work.glob('debug_*.json'))
    if len(files) != 1:
        raise _invalid()
    raw = files[0]
    try:
        if not stat.S_ISREG(raw.lstat().st_mode):
            raise ValueError
        descriptor = os.open(raw, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError
            payload = source.read(MAX_METADATA + 1)
        if len(payload) > MAX_METADATA:
            raise _invalid('download_too_large')
        play_response = _json().decode(payload.decode('utf-8'))
    finally:
        raw.unlink(missing_ok=True)
    if not isinstance(play_response, dict) or type(play_response.get('code')) is not int or play_response['code'] != 0:
        raise _invalid()
    nodes = [play_response[key] for key in ('data', 'result') if isinstance(play_response.get(key), dict)]
    if len(nodes) != 1:
        raise _invalid()
    play = nodes[0]
    milliseconds = play.get('timelength')
    if (play.get('is_preview') or play.get('is_upower_exclusive') or play.get('is_upower_play')
            or not _positive(milliseconds) or abs(milliseconds / 1000 - page['duration']) > 1):
        raise _invalid('incomplete_video')
    return {'play': play, 'cid': page['cid'], 'aid': data['aid'], 'duration': milliseconds / 1000}


def _run(binary, args, env):
    process = subprocess.Popen([str(binary), *args], cwd=binary.parent, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    chunks = bytearray()
    deadline = time.monotonic() + 120
    try:
        with selectors.DefaultSelector() as selected:
            selected.register(process.stdout, selectors.EVENT_READ)
            while selected.get_map():
                if time.monotonic() > deadline:
                    raise InputError('network_timeout', '匿名获取播放信息超时。')
                for key, _ in selected.select(.2):
                    block = os.read(key.fileobj.fileno(), 65536)
                    if not block:
                        selected.unregister(key.fileobj)
                        break
                    chunks.extend(block)
                    if len(chunks) > MAX_METADATA:
                        raise _invalid('download_too_large')
            process.wait(timeout=max(.01, deadline - time.monotonic()))
        if process.returncode:
            error = InputError('http_unavailable', '匿名公开接口拒绝请求或视频不可用。请提供清晰的本地视频。')
            if re.search(rb'(?<![0-9])412(?![0-9])', chunks):
                error.http_status = 412
            raise error
        return chunks.decode('utf-8', errors='strict')
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def inspect(origin, staging):
    location = shutil.which('BBDown')
    if location is None:
        raise InputError('dependency_missing', '需要安装已验证的 BBDownNext 2.3.0 metadata-bounded.1 构建。')
    try:
        with tempfile.TemporaryDirectory(prefix='bbdown-', dir=staging) as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            binary = root / 'BBDown'
            digest = hashlib.sha256()
            with open(location, 'rb') as source, binary.open('xb') as target:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode) or os.fstat(source.fileno()).st_size > 512 * 1024**2:
                    raise _invalid('backend_version_mismatch')
                total = 0
                while block := source.read(1024**2):
                    total += len(block)
                    if total > 512 * 1024**2:
                        raise _invalid('backend_version_mismatch')
                    digest.update(block)
                    target.write(block)
            build = 'metadata-bounded.1'
            if digest.hexdigest() != METADATA_SHA256:
                raise InputError('backend_version_mismatch', 'BBDownNext 可执行文件与已验证的 2.3.0 构建不一致。')
            binary.chmod(0o700)
            config = root / 'empty.config'
            config.touch(mode=0o600)
            env = {'HOME': str(root), 'XDG_CONFIG_HOME': str(root), 'XDG_CACHE_HOME': str(root),
                   'XDG_DATA_HOME': str(root), 'TMPDIR': str(root), 'LANG': 'C.UTF-8',
                   'PATH': '/usr/bin:/bin', 'DOTNET_CLI_HOME': str(root),
                   'DOTNET_BUNDLE_EXTRACT_BASE_DIR': str(root / 'bundle')}
            with DirectGateway() as gateway:
                env.update({'http_proxy': gateway.url, 'https_proxy': gateway.url, 'no_proxy': '',
                            'HTTP_PROXY': gateway.url, 'HTTPS_PROXY': gateway.url, 'NO_PROXY': ''})
                args = [origin['url'], '--info-only', '--debug', '--all', '--hide-streams', '--api', 'web',
                        '-g', 'v', '--max-retry', '0', '-p', str(origin['page']), '--no-force-http',
                        '--config', str(config), '--work-dir', str(root)]
                try:
                    output = _run(binary, args, env)
                except InputError:
                    if gateway.failure:
                        raise gateway.failure from None
                    raise
                if gateway.failure:
                    raise gateway.failure
            return {**_metadata(output, root, origin), 'backend_build': build, 'backend_sha256': digest.hexdigest()}
    except InputError as error:
        error.diagnostics = {'failure_stage': 'metadata', 'backend_error_type': type(error).__name__}
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        raise _invalid() from None
