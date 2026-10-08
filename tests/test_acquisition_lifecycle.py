"""Real CLI processes with controlled network/tool boundaries and real OS signals."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from score_fixtures import CLI, score_frame, video_from_image


LAUNCHER = '''
import contextlib, io, os, runpy, socket, sys, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv.pop(1))
mode = sys.argv.pop(1)
marker = Path(sys.argv.pop(1))
sys.argv.pop(0)
from yt_dlp import YoutubeDL
info = {'id': 'BV1b5411x7Ku_p2', 'formats': [{'url': 'https://cdn.bilivideo.com/video', 'vcodec': 'avc1', 'acodec': 'none'}]}
def stall(*args, **kwargs):
    marker.write_text(str(os.getpid()))
    time.sleep(60)
def copy_stall(*args, **kwargs):
    marker.with_name('copy-pid').write_text(str(os.getpid()))
    stall()
def dns(*args, **kwargs):
    if mode == 'dns': stall()
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
def extract(*args, **kwargs):
    if mode == 'extract': stall()
    if mode == 'exit':
        import multiprocessing
        multiprocessing.get_context('fork').Process(target=stall).start()
    return info
class Body(io.BytesIO):
    def read(self, *args):
        if mode == 'download': stall()
        return super().read(*args)
def response(*args, **kwargs):
    if mode == 'connection': stall()
    marker.write_text(str(os.getpid()))
    return Body(Path(os.environ['FIXTURE_VIDEO']).read_bytes() if mode == 'copy' else b'invalid-video')
with patch.object(YoutubeDL, 'extract_info', side_effect=extract), patch('socket.getaddrinfo', side_effect=dns), patch('urllib.request.OpenerDirector.open', side_effect=response), (patch('shutil.copyfileobj', side_effect=copy_stall) if mode == 'copy' else contextlib.nullcontext()):
    runpy.run_path(sys.argv[0], run_name='__main__')
'''


class AcquisitionLifecycleTests(unittest.TestCase):
    def start(self, base, mode, timeout='0.4', env=None):
        launcher = base / 'launcher.py'
        launcher.write_text(LAUNCHER)
        return subprocess.Popen([sys.executable, str(launcher), str(CLI.parent), mode,
                                 str(base / 'pid'), str(CLI),
                                 'https://www.bilibili.com/video/BV1b5411x7Ku?p=2',
                                 '--output', str(base / 'result'), '--acquisition-timeout', timeout],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)

    def test_dns_timeout_stops_real_worker_and_leaves_only_retryable_diagnosis(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            started = time.monotonic()
            process = self.start(base, 'dns')
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 2, stderr)
            result = json.loads(stdout)
            self.assertEqual(result['error']['code'], 'network_timeout')
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual({p.name for p in (base / 'result').iterdir()}, {'manifest.json'})
            with self.assertRaises(ProcessLookupError):
                os.kill(int((base / 'pid').read_text()), 0)

    def test_sigterm_stops_worker_and_returns_sanitized_retryable_failure(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            process = self.start(base, 'download', timeout='30')
            try:
                deadline = time.monotonic() + 5
                while not (base / 'pid').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((base / 'pid').exists())
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 2, stderr)
                self.assertEqual(json.loads(stdout)['error']['code'], 'acquisition_interrupted')
                self.assertEqual({p.name for p in (base / 'result').iterdir()}, {'manifest.json'})
                with self.assertRaises(ProcessLookupError):
                    os.kill(int((base / 'pid').read_text()), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_connections_download_retries_and_process_exit_share_deadline(self):
        for mode in ('extract', 'connection', 'download', 'exit'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                started = time.monotonic()
                process = self.start(base, mode, timeout='0.8')
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 2, stderr)
                self.assertEqual(json.loads(stdout)['error']['code'], 'network_timeout')
                self.assertLess(time.monotonic() - started, 4)
                self.assertEqual({p.name for p in (base / 'result').iterdir()}, {'manifest.json'})
                self.assertFalse([p for p in base.iterdir() if p.is_dir() and p.name not in {'result', 'tools'}])

    def test_probe_subprocess_is_stopped_by_overall_deadline(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            tools = base / 'tools'
            tools.mkdir()
            probe = tools / 'ffprobe'
            probe.write_text(f'#!{sys.executable}\nimport os,time\nfrom pathlib import Path\nPath({str(base / "probe-pid")!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n')
            probe.chmod(0o755)
            process = self.start(base, 'probe', timeout='0.8', env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH']})
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(json.loads(stdout)['error']['code'], 'network_timeout', stderr)
            self.assertTrue((base / 'probe-pid').exists())
            pid = int((base / 'probe-pid').read_text())
            status = Path(f'/proc/{pid}/status')
            self.assertTrue(not status.exists() or '\nState:\tZ' in status.read_text())
            self.assertFalse([p for p in base.iterdir() if p.is_dir() and p.name not in {'result', 'tools'}])

    def test_killed_cli_never_leaves_partial_in_final_directory(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            process = self.start(base, 'download', timeout='30')
            try:
                deadline = time.monotonic() + 5
                while not (base / 'pid').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((base / 'pid').exists())
                worker = int((base / 'pid').read_text())
                process.kill()
                process.communicate(timeout=5)
                self.assertFalse((base / 'result').exists())
                deadline = time.monotonic() + 2
                status = Path(f'/proc/{worker}/status')
                while status.exists() and '\nState:\tZ' not in status.read_text() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(not status.exists() or '\nState:\tZ' in status.read_text())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_destination_copy_is_inside_deadline_and_cleans_its_staging(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            video = video_from_image(score_frame(), base)
            process = self.start(base, 'copy', timeout='2', env={**os.environ, 'FIXTURE_VIDEO': str(video)})
            stdout, stderr = process.communicate(timeout=6)
            self.assertTrue((base / 'copy-pid').exists(), 'fixture must reach destination copying')
            self.assertEqual(json.loads(stdout)['error']['code'], 'network_timeout', stderr)
            self.assertEqual({p.name for p in (base / 'result').iterdir()}, {'manifest.json'})
            self.assertFalse([p for p in base.iterdir() if p.is_dir() and p.name not in {'result', 'tools'}])


if __name__ == '__main__':
    unittest.main()
