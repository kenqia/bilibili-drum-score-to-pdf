"""Anonymous HTTP contract; only synthetic links and local temporary task data."""
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
import sys
import asyncio
import json
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
try:
    from fastapi.testclient import TestClient
except ImportError:
    raise unittest.SkipTest('Install tests/requirements-web.txt for optional website tests')
from drum_score.web import create_app


LINK = 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2'


class WebsiteHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'service'
        self.app = create_app(self.root)
        self.client = TestClient(self.app, client=('203.0.113.1', 1234))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def submit(self, client=None):
        response = (client or self.client).post('/api/tasks', json={'url': LINK})
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        return data['id'], {'Authorization': 'Bearer ' + data['capability']}, data

    def test_presence_deduplicates_and_expires_without_task_access(self):
        with patch('drum_score.presence.monotonic', return_value=100) as clock:
            first = self.client.post('/api/presence', json={'visitor': 'a' * 32})
            self.assertEqual(first.json(), {'online': 1})
            self.assertEqual(self.client.post('/api/presence', json={'visitor': 'a' * 32}).json(), {'online': 1})
            self.assertEqual(self.client.post('/api/presence', json={'visitor': 'b' * 32}).json(), {'online': 2})
            clock.return_value = 160
            self.assertEqual(self.client.post('/api/presence', json={'visitor': 'b' * 32}).json(), {'online': 1})
        self.assertEqual(self.client.post('/api/presence', json={'visitor': 'bad'}).status_code, 422)
        self.assertEqual(first.headers['cache-control'], 'no-store')

    def test_private_link_persists_and_every_operation_requires_capability(self):
        task, headers, created = self.submit()
        self.assertGreaterEqual(len(created['capability']), 43)
        self.assertEqual(created['link'], '/task/' + task + '#' + created['capability'])
        # A new HTTP application can read the persistent task without its creator.
        with TestClient(create_app(self.root)) as reopened:
            state = reopened.get('/api/tasks/' + task, headers=headers)
            self.assertEqual(state.status_code, 200)
            self.assertEqual(state.json()['state'], 'queued')
            self.assertEqual(state.json()['source']['page'], 2)
            for method, suffix in [('get', ''), ('get', '/pdf'), ('get', '/pages/1'),
                                   ('post', '/cancel'), ('post', '/retry')]:
                with self.subTest(method=method, suffix=suffix):
                    request = getattr(reopened, method)
                    missing = request('/api/tasks/missing' + suffix)
                    bad = request('/api/tasks/' + task + suffix,
                                  headers={'Authorization': 'Bearer synthetic-wrong'})
                    self.assertEqual(bad.status_code, 404)
                    self.assertEqual(bad.json(), missing.json())
                    self.assertEqual(bad.headers['cache-control'], 'no-store')
        self.assertNotIn(created['capability'], state.text)

    def test_cancel_does_not_refund_rolling_quota_and_restart_does_not_reset_it(self):
        with patch('drum_score.jobs.time.time', return_value=1800000000) as clock:
            for _ in range(10):
                task, headers, _ = self.submit()
                self.assertEqual(self.client.post('/api/tasks/' + task + '/cancel', headers=headers).status_code, 200)
            with TestClient(create_app(self.root), client=('203.0.113.1', 1234)) as restarted:
                blocked = restarted.post('/api/tasks', json={'url': LINK})
                self.assertEqual(blocked.status_code, 429)
                self.assertEqual(blocked.json()['error']['code'], 'submission_limit')
                self.assertEqual(blocked.headers['retry-after'], '600')
                self.assertEqual(blocked.json()['error']['retry_after_seconds'], 600)
                clock.return_value += 599
                blocked = restarted.post('/api/tasks', json={'url': LINK})
                self.assertEqual(blocked.headers['retry-after'], '1')
                clock.return_value += 1
                self.submit(restarted)

    def test_atomic_queue_limit_and_shared_network_limit_ignore_forged_proxy(self):
        def submit(index):
            with TestClient(self.app, client=(f'203.0.113.{index + 1}', 1000)) as client:
                response = client.post('/api/tasks', json={'url': LINK}, headers={'X-Forwarded-For': f'198.51.100.{index}'})
                return response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=16) as pool:
            responses = list(pool.map(submit, range(16)))
        self.assertEqual(sum(code == 201 for code, _ in responses), 10)
        self.assertEqual(sum(code in (429, 503) for code, _ in responses), 6)
        # Cancellation is idempotent and frees a queued slot, but never reveals another task.
        accepted = next(data for code, data in responses if code == 201)
        auth = {'Authorization': 'Bearer ' + accepted['capability']}
        for _ in range(2):
            response = self.client.post('/api/tasks/' + accepted['id'] + '/cancel', headers=auth)
            self.assertEqual(response.json()['state'], 'cancelled')
        with TestClient(self.app, client=('192.0.2.20', 2000)) as shared:
            self.submit(shared)
            second = shared.post('/api/tasks', json={'url': LINK}, headers={'X-Forwarded-For': '198.51.100.250'})
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.json()['error']['code'], 'ip_busy')

    def test_explicit_proxy_chain_and_input_boundary(self):
        with TestClient(create_app(self.root, trusted_proxies=('127.0.0.1',)), client=('127.0.0.1', 2000)) as proxy:
            for ip in ('192.0.2.30', '192.0.2.31'):
                response = proxy.post('/api/tasks', json={'url': LINK}, headers={'X-Forwarded-For': ip})
                self.assertEqual(response.status_code, 201)
            bad = proxy.post('/api/tasks', json={'url': LINK}, headers={'X-Forwarded-For': 'unknown'})
            self.assertEqual(bad.status_code, 400)
            malformed = proxy.post('/api/tasks', json={'url': LINK}, headers={'X-Forwarded-For': 'unknown, 192.0.2.90'})
            self.assertEqual(malformed.status_code, 400)
        for url in ('file:///tmp/test.mp4', 'http://www.bilibili.com/video/BV1rH4y1R7Rk',
                    'https://127.0.0.1/video/BV1rH4y1R7Rk', LINK + '&p=3'):
            with self.subTest(url=url):
                response = self.client.post('/api/tasks', json={'url': url})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(url, response.text)
        with self.assertRaises(ValueError):
            create_app(self.root, trusted_proxies=('*',))

    def test_short_link_enqueues_without_external_resolution(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError('HTTP must only enqueue')):
            response = self.client.post('/api/tasks', json={'url': 'https://b23.tv/Synthetic7?share_source=test'})
        self.assertEqual(response.status_code, 201)
        created = response.json()
        auth = {'Authorization': 'Bearer ' + created['capability']}
        state = self.client.get('/api/tasks/' + created['id'], headers=auth).json()
        self.assertEqual(state['state'], 'queued')
        self.assertEqual(state['source']['url'], 'https://b23.tv/Synthetic7')
        self.assertIsNone(state['source']['bvid'])

    def test_retry_uses_original_capability_and_current_ip_quota(self):
        task, headers, _ = self.submit()
        self.client.post('/api/tasks/' + task + '/cancel', headers=headers)
        other, _, _ = self.submit()
        blocked = self.client.post('/api/tasks/' + task + '/retry', headers=headers)
        self.assertEqual(blocked.status_code, 429)
        with TestClient(self.app, client=('192.0.2.40', 2000)) as client:
            retried = client.post('/api/tasks/' + task + '/retry', headers=headers)
            self.assertEqual(retried.status_code, 200)
            self.assertEqual(retried.json()['state'], 'queued')
        self.assertEqual(self.client.get('/api/tasks/' + other).status_code, 404)

    def test_body_limit_precedes_json_parser_for_regular_and_chunked_requests(self):
        payload = b'{"url":"' + b'X' * 9000 + b'"}'
        for body in (payload, iter((payload[:4096], payload[4096:]))):
            response = self.client.post('/api/tasks', content=body, headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.json()['error']['code'], 'request_too_large')
            self.assertNotIn('XXXXX', response.text)

    def test_chinese_pages_and_assets_are_same_origin_and_do_not_expose_task_data(self):
        task, _, created = self.submit()
        for path in ('/', '/task/' + task):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('鼓谱', response.text)
            self.assertIn('lang="zh-CN"', response.text)
            self.assertNotIn(created['capability'], response.text)
            self.assertIn("script-src 'self'", response.headers['content-security-policy'])
            self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertEqual(self.client.get('/assets/app.js').status_code, 200)
        self.assertEqual(self.client.get('/assets/style.css').status_code, 200)
        for name, kind in (('icon.svg', 'image/svg+xml'), ('example-video.jpg', 'image/jpeg'),
                           ('example-page.jpg', 'image/jpeg')):
            response = self.client.get('/assets/' + name)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['content-type'], kind)
        self.assertEqual(self.client.get('/assets/../worker.py').status_code, 404)
        self.assertEqual(self.client.get('/api/tasks').status_code, 405)

    def test_chunked_body_has_total_deadline_even_when_each_chunk_arrives_in_time(self):
        body = json.dumps({'url': LINK}).encode()
        now = [0.0]
        messages = []
        async def request():
            scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
                'path': '/api/tasks', 'query_string': b'', 'root_path': '',
                'server': ('127.0.0.1', 8000), 'client': ('192.0.2.100', 2000),
                'headers': [(b'content-type', b'application/json')]}
            chunks = iter((body[:20], body[20:]))
            count = [0]
            async def receive():
                if count[0] >= 2:
                    await asyncio.Event().wait()
                count[0] += 1
                now[0] += 6  # Each chunk is within 10 s; two chunks exceed the total.
                return {'type': 'http.request', 'body': next(chunks), 'more_body': count[0] == 1}
            async def send(message):
                messages.append(message)
            await self.app(scope, receive, send)
        with patch('drum_score.web.monotonic', side_effect=lambda: now[0], create=True):
            asyncio.run(request())
        self.assertEqual(next(message['status'] for message in messages if message['type'] == 'http.response.start'), 408)
