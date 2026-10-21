"""Real worker/core/process tests, replacing only the anonymous network boundary."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import asyncio
import socket
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
try:
    import httpx
    from fastapi.testclient import TestClient
except ImportError:
    raise unittest.SkipTest('Install tests/requirements-web.txt for optional website tests')
from drum_score.web import create_app
from score_fixtures import score_frame, video_from_image


BACKEND = '''from pathlib import Path
import os, shutil, subprocess, sys, time
MAX_BYTES = 2 * 1024**3
def download(origin, target):
    fixture = Path(os.environ['SYNTHETIC_NETWORK_ROOT'])
    mode = (fixture / 'mode').read_text()
    if mode == 'fail':
        raise RuntimeError('SYNTHETIC_SIGNED_ADDRESS_AND_PRIVATE_PATH')
    if mode == 'wait':
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])
        (fixture / 'writers').write_text(str(os.getpid()) + ',' + str(child.pid))
        while not (fixture / 'release').exists():
            time.sleep(.02)
        child.terminate()
        child.wait()
    shutil.copyfile(fixture / 'input.mp4', target / 'video.mp4')
    return {'title': 'Synthetic public video', 'authenticated': False}
'''

# Fault injection at SQLite's external commit boundary, using a real database.
# The worker is frozen only AFTER a durable finishing decision, then OS-killed.
DATABASE_FAULT = '''from pathlib import Path
import os, sqlite3, time
fixture = Path(os.environ['SYNTHETIC_NETWORK_ROOT'])
original = sqlite3.connect
class Connection(sqlite3.Connection):
    def commit(self):
        super().commit()
        if (fixture / 'trap-finishing').exists():
            try:
                finishing = self.execute("SELECT 1 FROM tasks WHERE state='finishing'").fetchone()
            except sqlite3.Error:
                finishing = None
            if finishing:
                (fixture / 'finishing-committed').write_text('durable')
                while (fixture / 'trap-finishing').exists():
                    time.sleep(.01)
def connect(database, *args, **kwargs):
    if str(database).endswith('tasks.sqlite3'):
        kwargs.setdefault('factory', Connection)
    return original(database, *args, **kwargs)
sqlite3.connect = connect
'''


@unittest.skipUnless(Path('/proc').is_dir(), 'Linux website process lifecycle contract')
class WebsiteWorker(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / 'service'
        self.network = self.root / 'network'
        self.network.mkdir()
        video_from_image(score_frame(), self.network)
        (self.network / 'anonymous_backend.py').write_text(BACKEND)
        (self.network / 'mode').write_text('ready')
        self.client = TestClient(create_app(self.data), client=('192.0.2.10', 2000))
        self.processes = []
        repository = Path(__file__).resolve().parents[1]
        self.env = {**os.environ, 'SYNTHETIC_NETWORK_ROOT': str(self.network),
            'PYTHONPATH': os.pathsep.join(map(str, (self.network, repository / 'src',
                repository / 'skills/bilibili-drum-score-to-pdf/scripts'))),
            'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']}

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.client.close()
        self.temp.cleanup()

    def submit(self, client=None):
        response = (client or self.client).post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2'})
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        return task['id'], {'Authorization': 'Bearer ' + task['capability']}

    def worker(self, *, once=False):
        args = [sys.executable, '-m', 'drum_score.worker', '--data-root', str(self.data), '--poll-interval', '.02']
        if once:
            args.append('--once')
        process = subprocess.Popen(args, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        return process

    def state(self, task, headers):
        response = self.client.get('/api/tasks/' + task, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def until(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(.03)
        self.fail('Timed out waiting for public worker/process behavior')

    def test_real_conversion_survives_http_restart_and_downloads_every_page(self):
        task, auth = self.submit()
        worker = self.worker(once=True)
        self.client.close()
        self.client = TestClient(create_app(self.data), client=('192.0.2.10', 2000))
        self.assertEqual(worker.wait(timeout=30), 0)
        state = self.state(task, auth)
        self.assertEqual(state['state'], 'complete', state)
        self.assertFalse(state['result']['reliable'])
        pdf = self.client.get('/api/tasks/' + task + '/pdf', headers=auth)
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF-'))
        for page in range(1, state['result']['page_count'] + 1):
            response = self.client.get(f'/api/tasks/{task}/pages/{page}', headers=auth)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b'\x89PNG'))
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pages/999', headers=auth).status_code, 404)
        self.assertEqual(self.client.post(f'/api/tasks/{task}/cancel', headers=auth).json()['state'], 'complete')
        self.assertEqual(list(self.data.rglob('.drum-score-*')), [])

    def waiting(self):
        (self.network / 'mode').write_text('wait')
        task, auth = self.submit()
        worker = self.worker()
        self.until(lambda: (self.network / 'writers').exists())
        writers = [int(value) for value in (self.network / 'writers').read_text().split(',')]
        self.assertEqual(self.state(task, auth)['state'], 'running')
        return task, auth, worker, writers

    @staticmethod
    def alive(pid):
        try:
            return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[0] != 'Z'
        except FileNotFoundError:
            return False

    def test_cancel_stops_real_network_tree_before_terminal_state_and_allows_retry(self):
        task, auth, worker, writers = self.waiting()
        response = self.client.post(f'/api/tasks/{task}/cancel', headers=auth)
        self.assertIn(response.json()['state'], ('cancelling', 'cancelled'))
        self.until(lambda: self.state(task, auth)['state'] == 'cancelled')
        self.assertTrue(all(not self.alive(pid) for pid in writers))
        self.assertEqual(list(self.data.rglob('.drum-score-*')), [])
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf', headers=auth).status_code, 409)
        (self.network / 'mode').write_text('ready')
        self.assertEqual(self.client.post(f'/api/tasks/{task}/retry', headers=auth).status_code, 200)
        self.until(lambda: self.state(task, auth)['state'] == 'complete')
        self.assertIsNone(worker.poll())

    def test_sigterm_interrupts_actual_tree_and_restart_preserves_queued_task(self):
        task, auth, worker, writers = self.waiting()
        with TestClient(create_app(self.data), client=('192.0.2.20', 2000)) as other:
            queued, queued_auth = self.submit(other)
        worker.terminate()
        self.assertEqual(worker.wait(timeout=15), 0)
        self.assertEqual(self.state(task, auth)['state'], 'interrupted')
        self.assertTrue(all(not self.alive(pid) for pid in writers))
        self.assertEqual(self.state(queued, queued_auth)['state'], 'queued')
        (self.network / 'mode').write_text('ready')
        restarted = self.worker(once=True)
        self.assertEqual(restarted.wait(timeout=30), 0)
        self.assertEqual(self.state(queued, queued_auth)['state'], 'complete')
        self.assertEqual(self.state(task, auth)['state'], 'interrupted')

    def guardian(self, worker):
        lock = (self.data / 'worker.lock').stat()
        for entry in Path('/proc').glob('[0-9]*'):
            if int(entry.name) == worker.pid:
                continue
            try:
                fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
                if int(fields[1]) != worker.pid:
                    continue
                for descriptor in (entry / 'fd').iterdir():
                    metadata = descriptor.stat()
                    if (metadata.st_dev, metadata.st_ino) == (lock.st_dev, lock.st_ino):
                        return int(entry.name)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
        return None

    def test_sigkill_guardian_holds_lock_until_cleanup_then_restart_marks_interrupted(self):
        task, auth, worker, writers = self.waiting()
        guardian = self.until(lambda: self.guardian(worker))
        os.kill(guardian, signal.SIGSTOP)
        try:
            worker.kill()
            worker.wait(timeout=5)
            # The old worker is gone, but its guardian still holds the OS lease.
            competitor = self.worker(once=True)
            self.assertEqual(competitor.wait(timeout=5), 2)
            self.assertEqual(self.state(task, auth)['state'], 'running')
        finally:
            os.kill(guardian, signal.SIGCONT)
        self.until(lambda: not self.alive(guardian))
        self.assertTrue(all(not self.alive(pid) for pid in writers))
        (self.network / 'mode').write_text('ready')
        restarted = self.worker(once=True)
        self.assertEqual(restarted.wait(timeout=10), 0)
        self.assertEqual(self.state(task, auth)['state'], 'interrupted')
        self.assertEqual(list(self.data.rglob('.drum-score-*')), [])

    def test_second_worker_is_rejected_and_ten_waiting_plus_one_active_are_allowed(self):
        task, auth, worker, _ = self.waiting()
        competitor = self.worker(once=True)
        self.assertEqual(competitor.wait(timeout=5), 2)
        for index in range(10):
            with TestClient(create_app(self.data), client=(f'198.51.100.{index + 1}', 2000)) as other:
                self.submit(other)
        with TestClient(create_app(self.data), client=('198.51.100.100', 2000)) as other:
            full = other.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk'})
            self.assertEqual(full.status_code, 429)
            self.assertEqual(full.json()['error']['code'], 'queue_full')
        self.assertEqual(self.state(task, auth)['state'], 'running')

    def test_durable_finishing_wins_cancel_and_recovers_after_real_sigkill(self):
        (self.network / 'sitecustomize.py').write_text(DATABASE_FAULT)
        (self.network / 'trap-finishing').touch()
        task, auth = self.submit()
        worker = self.worker(once=True)
        self.until(lambda: (self.network / 'finishing-committed').exists())
        finishing = self.state(task, auth)
        self.assertEqual(finishing['state'], 'finishing')
        for _ in range(2):
            response = self.client.post(f'/api/tasks/{task}/cancel', headers=auth)
            self.assertEqual(response.json()['state'], 'finishing')
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf', headers=auth).status_code, 409)
        worker.kill()
        worker.wait(timeout=5)
        (self.network / 'trap-finishing').unlink()
        restarted = self.worker(once=True)
        self.assertEqual(restarted.wait(timeout=10), 0)
        completed = self.state(task, auth)
        self.assertEqual(completed['state'], 'complete')
        self.assertEqual(completed['completed_at'], finishing['completed_at'])
        self.assertEqual(completed['expires_at'], finishing['expires_at'])
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf', headers=auth).status_code, 200)

    def test_lost_database_commit_acknowledgement_cannot_delete_committed_result(self):
        fault = DATABASE_FAULT.replace("(fixture / 'finishing-committed').write_text('durable')", "raise sqlite3.OperationalError('synthetic lost commit acknowledgement')")
        (self.network / 'sitecustomize.py').write_text(fault)
        (self.network / 'trap-finishing').touch()
        task, auth = self.submit()
        worker = self.worker(once=True)
        self.assertEqual(worker.wait(timeout=30), 2)
        self.assertEqual(self.state(task, auth)['state'], 'finishing')
        (self.network / 'trap-finishing').unlink()
        self.assertEqual(self.worker(once=True).wait(timeout=15), 0)
        self.assertEqual(self.state(task, auth)['state'], 'complete')
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf', headers=auth).status_code, 200)

    def test_authenticated_open_fd_survives_unlink_but_new_expired_requests_fail(self):
        task, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30), 0)
        state = self.state(task, auth)
        expected = self.client.get(f'/api/tasks/{task}/pdf', headers=auth).content
        pdf = next(self.data.rglob('score.pdf'))
        app = create_app(self.data)
        messages = []
        async def request():
            scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                'http_version': '1.1', 'method': 'GET', 'scheme': 'http',
                'path': f'/api/tasks/{task}/pdf', 'raw_path': f'/api/tasks/{task}/pdf'.encode(),
                'query_string': b'', 'root_path': '', 'server': ('127.0.0.1', 8000),
                'client': ('192.0.2.10', 2000),
                'headers': [(b'authorization', auth['Authorization'].encode())]}
            received = False
            async def receive():
                nonlocal received
                if not received:
                    received = True
                    return {'type': 'http.request', 'body': b'', 'more_body': False}
                await asyncio.Event().wait()
            async def send(message):
                messages.append(message)
                if message['type'] == 'http.response.start':
                    self.assertEqual(message['status'], 200)
                    pdf.unlink()
            await app(scope, receive, send)
        asyncio.run(request())
        self.assertEqual(b''.join(message.get('body', b'') for message in messages), expected)
        with patch('time.time', return_value=state['expires_at'] + 1):
            for method, suffix in [('get', ''), ('get', '/pdf'), ('get', '/pages/1'), ('post', '/cancel'), ('post', '/retry')]:
                response = getattr(self.client, method)(f'/api/tasks/{task}' + suffix, headers=auth)
                self.assertEqual(response.status_code, 410)
            self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf').status_code, 404)

    def test_artifact_symlink_is_refused_without_reading_outside_task(self):
        task, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30), 0)
        pdf = next(self.data.rglob('score.pdf'))
        outside = self.root / 'unrelated.pdf'
        outside.write_bytes(b'SYNTHETIC_UNRELATED_PRIVATE_FILE')
        pdf.unlink()
        pdf.symlink_to(outside)
        response = self.client.get(f'/api/tasks/{task}/pdf', headers=auth)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('SYNTHETIC_UNRELATED', response.text)
        self.assertEqual(outside.read_bytes(), b'SYNTHETIC_UNRELATED_PRIVATE_FILE')

    def test_disconnect_before_first_artifact_chunk_closes_open_descriptor(self):
        task, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=30), 0)
        pdf = next(self.data.rglob('score.pdf'))
        identity = pdf.stat()
        def descriptors():
            matches = []
            for descriptor in Path('/proc/self/fd').iterdir():
                try:
                    current = descriptor.stat()
                    if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                        matches.append(descriptor.name)
                except FileNotFoundError:
                    pass
            return matches
        async def disconnect():
            scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                'http_version': '1.1', 'method': 'GET', 'scheme': 'http',
                'path': f'/api/tasks/{task}/pdf', 'query_string': b'', 'root_path': '',
                'server': ('127.0.0.1', 8000), 'client': ('192.0.2.10', 2000),
                'headers': [(b'authorization', auth['Authorization'].encode())]}
            async def receive():
                await asyncio.Event().wait()
            async def send(message):
                if message['type'] == 'http.response.start':
                    raise OSError('synthetic disconnected socket before body')
            try:
                await create_app(self.data)(scope, receive, send)
            except Exception:
                pass
        self.assertEqual(descriptors(), [])
        asyncio.run(disconnect())
        self.assertEqual(descriptors(), [])

    def test_sigterm_and_http_cancel_together_still_stop_worker_before_next_claim(self):
        task, auth, worker, writers = self.waiting()
        with TestClient(create_app(self.data), client=('192.0.2.20', 2000)) as other:
            queued, queued_auth = self.submit(other)
        os.kill(worker.pid, signal.SIGSTOP)
        try:
            self.assertEqual(self.client.post(f'/api/tasks/{task}/cancel', headers=auth).json()['state'], 'cancelling')
            worker.terminate()
        finally:
            os.kill(worker.pid, signal.SIGCONT)
        self.assertEqual(worker.wait(timeout=10), 0)
        self.assertEqual(self.state(task, auth)['state'], 'cancelled')
        self.assertEqual(self.state(queued, queued_auth)['state'], 'queued')
        self.assertTrue(all(not self.alive(pid) for pid in writers))

    def test_real_acquisition_failure_is_sanitized_and_releases_attempt_resources(self):
        (self.network / 'mode').write_text('fail')
        task, auth = self.submit()
        self.assertEqual(self.worker(once=True).wait(timeout=20), 0)
        state = self.state(task, auth)
        self.assertEqual(state['state'], 'failed')
        self.assertEqual(state['error']['code'], 'public_api_unavailable')
        self.assertNotIn('SYNTHETIC_SIGNED', json.dumps(state))
        self.assertEqual(list(self.data.rglob('.drum-score-*')), [])
        self.assertEqual(list(self.data.rglob('video.mp4')), [])
        self.assertEqual(self.client.get(f'/api/tasks/{task}/pdf', headers=auth).status_code, 409)

    def test_actual_uvicorn_entry_ignores_forged_forwarding_until_explicitly_trusted(self):
        def start(trusted=False):
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            args = [sys.executable, '-m', 'drum_score.web', '--data-root', str(self.data), '--port', str(port)]
            if trusted:
                args.extend(['--trusted-proxy', '127.0.0.1'])
            process = subprocess.Popen(args, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes.append(process)
            client = httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=3)
            def ready():
                try:
                    return client.get('/').status_code == 200
                except httpx.HTTPError:
                    return False
            self.until(ready)
            return process, client
        process, client = start()
        try:
            first = client.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk'}, headers={'X-Forwarded-For': '198.51.100.1'})
            self.assertEqual(first.status_code, 201)
            forged = client.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk'}, headers={'X-Forwarded-For': '198.51.100.2'})
            self.assertEqual(forged.status_code, 429)
            self.assertEqual(forged.json()['error']['code'], 'ip_busy')
        finally:
            client.close()
        process.terminate()
        self.assertIn(process.wait(timeout=5), (0, -signal.SIGTERM))
        process, client = start(trusted=True)
        try:
            for ip in ('198.51.100.1', '198.51.100.2'):
                response = client.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk'}, headers={'X-Forwarded-For': ip})
                self.assertEqual(response.status_code, 201)
        finally:
            client.close()
