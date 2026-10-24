"""Offline YouTube extractor and media boundary using only synthetic data."""
import contextlib
import io
from pathlib import Path
import socket
import sys
from unittest.mock import patch

MEDIA = 'https://r1.googlevideo.com/video?signature=SYNTHETIC_DO_NOT_PUBLISH'
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]


def info(**changes):
    return {'id': 'dQw4w9WgXcQ', 'title': 'Synthetic score', 'duration': 2,
            'live_status': 'not_live', 'age_limit': 0, 'availability': 'public',
            'formats': [{'url': MEDIA, 'width': 1280, 'height': 960,
                         'vcodec': 'h264', 'acodec': 'none', 'format_id': 'synthetic'}], **changes}


@contextlib.contextmanager
def configured(video, metadata=None, dns=None):
    from yt_dlp.extractor.youtube import YoutubeIE
    from drum_score import youtube_backend
    original = youtube_backend.shutil.which
    with patch.object(YoutubeIE, '_real_extract', return_value=metadata or info()), \
         patch('shutil.which', side_effect=lambda name, *a, **k:
               sys.executable if name == 'deno' else original(name, *a, **k)), \
         patch('socket.getaddrinfo', return_value=dns or PUBLIC_DNS), \
         patch('urllib.request.OpenerDirector.open', side_effect=lambda *a, **k: io.BytesIO(Path(video).read_bytes())):
        yield


def startup(video):
    """Persist a synthetic external boundary for independent public entry processes."""
    return ('import io,socket,sys,shutil\nfrom pathlib import Path\n'
            'from yt_dlp.extractor.youtube import YoutubeIE\n'
            f'YoutubeIE._real_extract=lambda self,url: {info()!r}\n'
            'original=shutil.which\n'
            'shutil.which=lambda name,*a,**k: sys.executable if name=="deno" else original(name,*a,**k)\n'
            f'socket.getaddrinfo=lambda *a,**k: {PUBLIC_DNS!r}\n'.replace(
                '<AddressFamily.AF_INET: 2>', 'socket.AF_INET').replace(
                '<SocketKind.SOCK_STREAM: 1>', 'socket.SOCK_STREAM') +
            'import urllib.request\n'
            f'urllib.request.OpenerDirector.open=lambda *a,**k: io.BytesIO(Path({str(video)!r}).read_bytes())\n')
