"""Anonymous admission and bounded history through Jobs and HTTP, synthetic only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.jobs import Jobs, JobError

LINK = 'https://www.bilibili.com/video/BV1rH4y1R7Rk'


@unittest.skipUnless(sys.platform == 'linux', 'Ubuntu anonymous service contract')
class AbusePrevention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'service'
        self.options = dict(min_free_bytes=1, job_temp_bytes=128, retained_bytes=4096)
        self.jobs = Jobs(self.root, **self.options)
        clock_patch = patch('drum_score.jobs.time.time', return_value=1800000000)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def cancelled_submission(self, ip='192.0.2.1'):
        task = self.jobs.enqueue(LINK, ip)
        self.jobs.cancel(task['id'], task['capability'])
        return task

    def assert_blocked(self, action, code):
        with self.assertRaises(JobError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_daily_quota_counts_retries_and_recovers_at_exact_rolling_boundary(self):
        task = self.cancelled_submission()
        for index in range(1, 100):
            self.clock.return_value = 1800000000 + index * 601
            self.jobs.retry(task['id'], task['capability'], '192.0.2.1')
            self.jobs.cancel(task['id'], task['capability'])
        error = self.assert_blocked(lambda: self.jobs.enqueue(LINK, '192.0.2.1'), 'submission_limit')
        self.assertEqual(error.retry_after_seconds, 26901)
        self.clock.return_value = 1800086399
        self.assertEqual(self.assert_blocked(lambda: self.jobs.enqueue(LINK, '192.0.2.1'),
                         'submission_limit').retry_after_seconds, 1)
        self.clock.return_value = 1800086400
        self.cancelled_submission()
        error = self.assert_blocked(lambda: self.jobs.enqueue(LINK, '192.0.2.1'), 'submission_limit')
        self.assertEqual(error.retry_after_seconds, 601)

    def test_rejected_submissions_do_not_spend_quota_and_failure_does_not_refund(self):
        task = self.jobs.enqueue(LINK, '192.0.2.1')
        for _ in range(12):
            self.assert_blocked(lambda: self.jobs.enqueue('file:///synthetic', '192.0.2.1'), 'invalid_bilibili_url')
            self.assert_blocked(lambda: self.jobs.enqueue(LINK, '192.0.2.1'), 'ip_busy')
        row = self.jobs.claim()
        self.jobs.settle(row, 'failed', 'synthetic_failure', 'Synthetic failure')
        for _ in range(9):
            self.jobs.retry(task['id'], task['capability'], '192.0.2.1')
            self.jobs.cancel(task['id'], task['capability'])
        self.assert_blocked(lambda: self.jobs.retry(task['id'], task['capability'], '192.0.2.1'), 'submission_limit')
        self.cancelled_submission('192.0.2.2')

    def test_queue_and_storage_rejection_do_not_spend_quota(self):
        tasks = [self.jobs.enqueue(LINK, f'198.51.100.{i}') for i in range(10)]
        for _ in range(12):
            self.assert_blocked(lambda: self.jobs.enqueue(LINK, '192.0.2.1'), 'queue_full')
        for task in tasks:
            self.jobs.cancel(task['id'], task['capability'])
        limited = Jobs(self.root, min_free_bytes=1, job_temp_bytes=1, retained_bytes=1)
        unknown = self.root / 'attempts' / 'unknown'
        unknown.parent.mkdir()
        unknown.write_bytes(b'SYNTHETIC_UNKNOWN_FILE')
        for _ in range(12):
            self.assert_blocked(lambda: limited.enqueue(LINK, '192.0.2.1'), 'storage_full')
        for _ in range(10):
            self.cancelled_submission()
        self.assertEqual(unknown.read_bytes(), b'SYNTHETIC_UNKNOWN_FILE')

    def test_independent_connections_cannot_overspend_last_submission(self):
        for _ in range(9):
            self.cancelled_submission()
        connections = [Jobs(self.root, **self.options) for _ in range(12)]
        def submit(jobs):
            try:
                task = jobs.enqueue(LINK, '192.0.2.1')
                jobs.cancel(task['id'], task['capability'])
                return 'accepted'
            except JobError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(submit, connections))
        self.assertEqual(results.count('accepted'), 1)
        self.assertEqual(results.count('submission_limit'), 11)

    def test_expired_identity_is_forgotten_after_thirty_days_without_touching_unknown_files(self):
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        task = self.cancelled_submission()
        expiry = self.jobs.view(task['id'], task['capability'])['expires_at']
        row = self.jobs.enqueue(LINK, '192.0.2.2')
        active = self.jobs.claim()
        attempt = self.jobs.register_attempt(active)
        unknown = attempt / 'unknown-user-file'
        unknown.write_bytes(b'SYNTHETIC_KEEP')
        self.jobs.settle(active, 'failed', 'synthetic_failure', 'Synthetic failure')
        auth = {'Authorization': 'Bearer ' + task['capability']}
        with TestClient(create_app(self.root, **self.options)) as client:
            self.clock.return_value = expiry + 30 * 86400 - 1
            self.jobs.cleanup()
            for method, suffix in (('get', ''), ('get', '/pdf'), ('get', '/pages/1'),
                                   ('post', '/cancel'), ('post', '/retry')):
                self.assertEqual(getattr(client, method)('/api/tasks/' + task['id'] + suffix, headers=auth).status_code, 410)
            live = self.jobs.enqueue(LINK, '192.0.2.3')
            self.clock.return_value += 1
            self.jobs.cleanup()
            for method, suffix in (('get', ''), ('get', '/pdf'), ('get', '/pages/1'),
                                   ('post', '/cancel'), ('post', '/retry')):
                self.assertEqual(getattr(client, method)('/api/tasks/' + task['id'] + suffix, headers=auth).status_code, 404)
            self.assertEqual(self.jobs.view(live['id'], live['capability'])['state'], 'queued')
            self.assert_blocked(lambda: self.jobs.view(row['id'], row['capability']), 'not_found')
        self.assertEqual(unknown.read_bytes(), b'SYNTHETIC_KEEP')


if __name__ == '__main__':
    unittest.main()
