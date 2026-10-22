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
from score_fixtures import score_frame, video_from_image


STARTUP = r'''
import io, os, socket, sys, time
from pathlib import Path
from unittest.mock import patch
mode = os.environ['NETWORK_MODE']
marker = Path(os.environ['NETWORK_MARKER'])
sys.path.insert(0, TEST_DIRECTORY)
from bbdown_fixture import install_fake_bbdown, fixture_config
from drum_score import bbdown_cli
config = fixture_config()
if mode in ('extract', 'recovery', 'exit'):
 config.update(marker=str(marker), stall=mode != 'exit', child_stall=mode == 'exit')
base = marker.parent
binary, digest = install_fake_bbdown(base, config)
bbdown_cli.OFFICIAL_SHA256 = digest
os.environ['PATH'] = str(binary.parent) + os.pathsep + os.environ['PATH']
def stall(*args, **kwargs):
 marker.write_text(str(os.getpid()))
 time.sleep(60)
def copy_stall(*args, **kwargs):
 marker.with_name('copy-pid').write_text(str(os.getpid()))
 stall()
def copy_fixture(origin, staging):
 import shutil
 shutil.copyfile(os.environ['FIXTURE_VIDEO'], Path(staging) / 'video.mp4')
 return {'backend': 'controlled-copy-fixture'}
def dns(*args, **kwargs):
 if mode == 'dns': stall()
 return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
class Body(io.BytesIO):
 def read(self, *args):
  if mode == 'download': stall()
  return super().read(*args)
def response(*args, **kwargs):
 if mode == 'connection': stall()
 marker.write_text(str(os.getpid()))
 return Body(Path(os.environ['FIXTURE_VIDEO']).read_bytes() if mode == 'copy' else b'invalid-video')
socket.getaddrinfo = dns
import urllib.request
urllib.request.OpenerDirector.open = response
if mode == 'copy':
 from drum_score import anonymous_backend
 anonymous_backend.download = copy_fixture
 import shutil
 shutil.copyfileobj = copy_stall
'''.replace('TEST_DIRECTORY', repr(str(Path(__file__).parent)))




class AcquisitionLifecycleTests(unittest.TestCase):
    def start(self, base, mode, timeout='2', env=None):
        startup = base / 'startup'
        startup.mkdir()
        (startup / 'sitecustomize.py').write_text(STARTUP)
        repository = Path(__file__).resolve().parents[1]
        return subprocess.Popen([sys.executable, '-m', 'drum_score',
                                 'https://www.bilibili.com/video/BV1b5411x7Ku?p=2',
                                 '--output', str(base / 'result'), '--timeout', timeout],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**(env or os.environ), 'NETWORK_MODE': mode, 'NETWORK_MARKER': str(base / 'pid'),
                 'PYTHONPATH': os.pathsep.join([str(startup), str(repository / 'src')])})

    def assert_stopped(self, path):
        self.assertTrue(path.exists(), 'fixture must reach its actual target phase')
        pid = int(path.read_text())
        deadline = time.monotonic() + 5
        status = Path(f'/proc/{pid}/stat')
        while status.exists() and status.read_text().rsplit(') ', 1)[1].split()[0] != 'Z' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(not status.exists() or status.read_text().rsplit(') ', 1)[1].split()[0] == 'Z')

    def assert_clean(self, base):
        self.assertFalse((base / 'result').exists())
        self.assertEqual(list(base.glob('.drum-score-*')), [])
        self.assertEqual(list(base.rglob('*.partial')), [])

    def test_dns_timeout_stops_real_worker_and_leaves_only_retryable_diagnosis(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            started = time.monotonic()
            process = self.start(base, 'dns')
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 2, stderr)
            result = json.loads(stdout)
            self.assertIn(result['error']['code'], ('network_timeout', 'resource_limit'))
            self.assertLess(time.monotonic() - started, 5)
            self.assert_clean(base)
            self.assert_stopped(base / 'pid')

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
                self.assertEqual(json.loads(stdout)['error']['code'], 'cancelled')
                self.assert_clean(base)
                self.assert_stopped(base / 'pid')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_connections_download_retries_and_process_exit_share_deadline(self):
        for mode in ('extract', 'connection', 'download', 'exit', 'recovery'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                started = time.monotonic()
                process = self.start(base, mode, timeout='2')
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 2, stderr)
                self.assertIn(json.loads(stdout)['error']['code'], ('network_timeout', 'resource_limit'))
                self.assertLess(time.monotonic() - started, 5)
                self.assert_stopped(base / 'pid')
                self.assert_clean(base)
                self.assert_clean(base)

    def test_probe_subprocess_is_stopped_by_overall_deadline(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            tools = base / 'tools'
            tools.mkdir()
            probe = tools / 'ffprobe'
            probe.write_text(f'#!{sys.executable}\nimport os,time\nfrom pathlib import Path\nPath({str(base / "probe-pid")!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n')
            probe.chmod(0o755)
            process = self.start(base, 'probe', timeout='2', env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH']})
            stdout, stderr = process.communicate(timeout=5)
            self.assertIn(json.loads(stdout)['error']['code'], ('network_timeout', 'resource_limit'), stderr)
            self.assertTrue((base / 'probe-pid').exists())
            pid = int((base / 'probe-pid').read_text())
            status = Path(f'/proc/{pid}/status')
            self.assertTrue(not status.exists() or '\nState:\tZ' in status.read_text())
            self.assert_clean(base)

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
            try:
                deadline = time.monotonic() + 12
                while not (base / 'copy-pid').exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((base / 'copy-pid').exists(), 'fixture must reach destination copying')
                copying = time.monotonic()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 2, stderr)
                self.assertIn(json.loads(stdout)['error']['code'], ('network_timeout', 'resource_limit'), stderr)
                self.assertLess(time.monotonic() - copying, 4)
                self.assert_clean(base)
                self.assert_clean(base)
                self.assert_stopped(base / 'copy-pid')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == '__main__':
    unittest.main()
