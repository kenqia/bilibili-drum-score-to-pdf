"""Synthetic external BBDown process, never connected to a live service."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch

BV = 'BV1b5411x7Ku'
URL = f'https://www.bilibili.com/video/{BV}?p=2'
MEDIA = 'https://cdn.bilivideo.com/video?sign=DO_NOT_SAVE_TEST_SENTINEL'
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]


def fixture_config(*, view=None, play=None, player=None, **extra):
    return {'view': view if view is not None else {'bvid': BV, 'aid': 44, 'title': 'Fixture',
        'rights': {'is_stein_gate': 0}, 'pages': [{'page': 1, 'cid': 11, 'duration': 2},
        {'page': 2, 'cid': 22, 'duration': 2}]},
        'player': player if player is not None else {'aid': 44, 'cid': 22, 'is_upower_exclusive': False},
        'play': play if play is not None else {'timelength': 2000, 'is_preview': False,
        'dash': {'video': [{'id': 80, 'baseUrl': MEDIA, 'width': 1280, 'height': 960,
        'codecs': 'avc1', 'frameRate': '4/1'}]}}, **extra}


def install_fake_bbdown(base, config):
    directory = Path(base) / 'fake-tool'
    directory.mkdir(exist_ok=True)
    binary = directory / 'BBDown'
    script = '''import json, os, sys, time
from pathlib import Path
config = CONFIG
args = sys.argv
work = Path(args[args.index('--work-dir') + 1])
if config.get('marker'):
 Path(config['marker']).write_text(str(os.getpid()))
if config.get('stall'):
 time.sleep(60)
if config.get('child_stall'):
 import subprocess
 subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
 time.sleep(60)
if config.get('assert_isolation'):
 assert not any(k in os.environ for k in ['BBDOWN_INSECURE_TLS', 'SSL_CERT_FILE', 'NETRC', 'PYTHONPATH', 'ALL_PROXY'])
 assert os.environ['HOME'] != config['assert_isolation']
 assert Path(args[0]).parent != Path(config['assert_isolation'])
 assert not (Path(args[0]).parent / 'BBDown.data').exists()
 assert not (Path(args[0]).parent / 'BBDown.config').exists()
 assert Path(args[args.index('--config') + 1]).read_bytes() == b''
 assert os.environ['https_proxy'].startswith('http://127.0.0.1:')
 assert '--no-force-http' in args
if config.get('exit'):
 print('HTTP 412 DO_NOT_SAVE_TEST_SENTINEL'); sys.exit(1)
for data in config.get('responses', [{'code': 0, 'data': config['view']}, {'code': 0, 'data': config['player']}]):
 print('[DEBUG] Response: ' + json.dumps(data))
print('[DEBUG] 获取网页内容：Url: https://api.bilibili.com/x/player/wbi/playurl?' + config.get('query', 'avid=44&cid=22') + ', Headers: Referer: https://www.bilibili.com')
if config.get('extra_stdout'):
 print(config['extra_stdout'])
for i in range(config.get('files', 1)):
 (work / ('debug_' + str(i) + '.json')).write_text(json.dumps({'code': 0, 'data': config['play']}))
'''.replace('CONFIG', repr(config))
    binary.write_text('#!' + sys.executable + '\n' + script)
    binary.chmod(0o755)
    return binary, hashlib.sha256(binary.read_bytes()).hexdigest()


@contextlib.contextmanager
def configured_fake(base, config, video=None, *, response=None, dns=None, real_transport=False):
    from drum_score import bbdown_cli
    binary, digest = install_fake_bbdown(base, config)
    with patch.dict(os.environ, {'PATH': str(binary.parent) + os.pathsep + os.environ['PATH']}), \
         patch.object(bbdown_cli, 'OFFICIAL_SHA256', digest), \
         patch('socket.getaddrinfo', side_effect=dns, return_value=PUBLIC_DNS), \
         (contextlib.nullcontext() if real_transport else patch('urllib.request.OpenerDirector.open', side_effect=response or (lambda *a, **k: io.BytesIO(video.read_bytes())))):
        yield binary
