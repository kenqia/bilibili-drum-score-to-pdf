"""Operator records through queue and HTTP interfaces; synthetic inputs only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drum_score.jobs import Jobs, JobError

URL = 'https://www.bilibili.com/video/BV1rH4y1R7Rk'


class ProcessingRecords(unittest.TestCase):
    def test_conversion_location_survives_verified_backup_and_restore(self):
        from drum_score.maintenance import backup, restore
        task = self.jobs.enqueue(URL, '192.0.2.1')
        row = self.jobs.claim()
        self.jobs.stage(row, 'registering')
        details = {'code': 'incomplete_score', 'range_seconds': [1, 2],
                   'message': '合成谱面边缘未补全。'}
        self.jobs.settle(row, 'failed', 'incomplete_score', '未发布结果。',
                         details={'conversion_failure': details})
        original = self.jobs.records.query(task=task['id'])
        self.assertEqual(original[0]['error']['conversion_failure'], details)
        snapshot = Path(self.temporary.name) / 'scope-snapshot'
        backup(self.jobs.root, snapshot, services_stopped=True, min_free_bytes=1)
        target = Path(self.temporary.name) / 'scope-restored'
        restore(snapshot, target, min_free_bytes=1)
        self.assertEqual(Jobs(target).records.query(task=task['id']), original)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.jobs = Jobs(Path(self.temporary.name) / 'service', min_free_bytes=1,
                         job_temp_bytes=128, retained_bytes=4096)

    def test_retry_keeps_original_failure_and_normalized_input_without_capability(self):
        task = self.jobs.enqueue(URL + '?p=2&tracking=SYNTHETIC_PRIVATE#SYNTHETIC_FRAGMENT', '192.0.2.1')
        row = self.jobs.claim()
        self.jobs.stage(row, 'sampling')
        self.jobs.settle(row, 'failed', 'discontinuity', '处理失败。')
        self.jobs.retry(task['id'], task['capability'], '192.0.2.1')
        records = self.jobs.records.query(task=task['id'])
        self.assertEqual(len(records), 2)
        failed = next(record for record in records if record['status'] == 'failed')
        queued = next(record for record in records if record['status'] == 'queued')
        self.assertEqual(failed['input']['url'], URL + '?p=2')
        self.assertEqual(failed['error']['code'], 'discontinuity')
        self.assertEqual(failed['error']['stage'], 'sampling')
        self.assertEqual(failed['expires_at'] - failed['finished_at'], 604800)
        self.assertEqual(queued['operation'], 'retry')
        self.assertNotEqual(failed['id'], queued['id'])
        self.assertIsNotNone(failed['program']['version'])
        serialized = json.dumps(records)
        for secret in (task['capability'], 'SYNTHETIC_PRIVATE', 'SYNTHETIC_FRAGMENT', '192.0.2.1'):
            self.assertNotIn(secret, serialized)

    def test_record_expiry_is_independent_and_does_not_refresh_on_reopen(self):
        task = self.jobs.enqueue(URL, '192.0.2.1')
        row = self.jobs.claim()
        self.jobs.settle(row, 'failed', 'discontinuity', '处理失败。')
        record = self.jobs.records.query(task=task['id'])[0]
        with patch('time.time', return_value=record['finished_at'] + 3601):
            self.jobs.cleanup()
            reopened = Jobs(self.jobs.root, min_free_bytes=1)
            self.assertEqual(reopened.records.query(task=task['id'])[0], record)
            with self.assertRaises(JobError) as caught:
                reopened.view(task['id'], task['capability'])
            self.assertEqual(caught.exception.status, 410)
        with patch('time.time', return_value=record['expires_at']):
            self.assertEqual(self.jobs.records.query(), [])
            self.jobs.cleanup()
        # Moving the synthetic clock back proves physical deletion, not filtering.
        self.assertEqual(self.jobs.records.query(), [])

    def test_log_capacity_refuses_new_work_without_evicting_unexpired_records(self):
        from drum_score.processing_records import MAX_RECORD_BYTES
        self.jobs.record_bytes = MAX_RECORD_BYTES
        first = self.jobs.enqueue(URL, '192.0.2.1')
        with self.assertRaises(JobError) as caught:
            self.jobs.enqueue(URL, '192.0.2.2')
        self.assertEqual(caught.exception.code, 'records_full')
        self.assertEqual(self.jobs.view(first['id'], first['capability'])['state'], 'queued')
        self.jobs.cancel(first['id'], first['capability'])
        self.assertEqual(len(self.jobs.records.query()), 1)
        # A terminal small record releases its previously reserved manifest budget.
        self.jobs.record_bytes += 4096
        self.jobs.enqueue(URL, '192.0.2.2')

    def test_disk_admission_sums_conversion_and_log_budgets(self):
        from types import SimpleNamespace
        # Enough for the conversion's reservation alone, not its log/journal.
        space = SimpleNamespace(f_bavail=1, f_frsize=self.jobs.job_temp_bytes + self.jobs.min_free_bytes + 1)
        with patch('os.statvfs', return_value=space):
            with self.assertRaises(JobError) as caught:
                self.jobs.enqueue(URL, '192.0.2.1')
        self.assertEqual(caught.exception.code, 'storage_full')
        self.assertEqual(self.jobs.records.query(), [])

    def test_manifest_read_fault_cannot_undo_completed_publication(self):
        import os
        from drum_score.core import artifact
        from drum_score.worker import validate_result, recover
        task = self.jobs.enqueue(URL, '192.0.2.1')
        row = self.jobs.claim()
        root = self.jobs.register_attempt(row) / 'result'
        root.mkdir()
        (root / 'score.pdf').write_bytes(b'%PDF-synthetic')
        (root / 'page-1.png').write_bytes(b'synthetic-page')
        manifest = dict(status='complete', reliable=False, warnings=[], source={}, program={}, resources={},
                        pdf=artifact(root, root / 'score.pdf'), pages=[artifact(root, root / 'page-1.png')])
        (root / 'manifest.json').write_text(json.dumps(manifest))
        self.jobs.remember_result(row, manifest)
        summary = validate_result(self.jobs, row)
        original_open = os.open
        def fail_manifest(path, *args, **kwargs):
            if path == 'manifest.json':
                raise OSError('SYNTHETIC_MANIFEST_READ_FAILURE')
            return original_open(path, *args, **kwargs)
        with patch('os.open', side_effect=fail_manifest):
            self.assertTrue(self.jobs.finishing(row, summary))
            self.jobs.settle(row, 'complete')
        self.assertEqual(self.jobs.view(task['id'], task['capability'])['state'], 'complete')
        descriptor, _ = self.jobs.open_artifact(task['id'], task['capability'])
        os.close(descriptor)
        failed = self.jobs.records.query(task=task['id'])[0]
        self.assertEqual(failed['status'], 'record_failed')
        recover(self.jobs)
        repaired = self.jobs.records.query(task=task['id'])[0]
        self.assertEqual(repaired['output'], manifest)
        self.assertEqual(repaired['expires_at'], failed['expires_at'])

    def test_http_rejections_keep_categories_without_raw_request_or_credentials(self):
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        with TestClient(create_app(self.jobs.root, min_free_bytes=1), client=('192.0.2.1', 2000)) as client:
            response = client.post('/api/tasks', json={'url': URL, 'private': 'SYNTHETIC_BODY'},
                                   headers={'Authorization': 'Bearer SYNTHETIC_HEADER'})
            self.assertEqual(response.status_code, 422)
            first = client.post('/api/tasks', json={'url': URL})
            self.assertEqual(first.status_code, 201)
            self.assertEqual(client.post('/api/tasks', json={'url': URL}).status_code, 429)
        records = self.jobs.records.query()
        self.assertEqual({record['error']['code'] for record in records if record['error']},
                         {'invalid_request', 'ip_busy'})
        payload = json.dumps(records)
        for secret in ('SYNTHETIC_BODY', 'SYNTHETIC_HEADER', first.json()['capability']):
            self.assertNotIn(secret, payload)

    def test_local_cli_exports_records_without_creating_missing_data_roots(self):
        import os
        import subprocess
        import sys
        task = self.jobs.enqueue(URL, '192.0.2.1')
        self.jobs.cancel(task['id'], task['capability'])
        command = [sys.executable, '-m', 'drum_score.processing_records', '--data-root', str(self.jobs.root),
                   '--task', task['id'], '--status', 'cancelled']
        response = subprocess.run(command, capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': 'src'})
        self.assertEqual(response.returncode, 0, response.stderr)
        exported = [json.loads(line) for line in response.stdout.splitlines()]
        self.assertEqual(exported, self.jobs.records.query(task=task['id'], status='cancelled'))
        missing = Path(self.temporary.name) / 'missing'
        command[command.index('--data-root') + 1] = str(missing)
        response = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(response.returncode, 2)
        self.assertFalse(missing.exists())

    def test_backup_and_v3_upgrade_preserve_deadlines_and_refuse_implicit_upgrade(self):
        import hashlib
        import sqlite3
        from drum_score.maintenance import backup, restore
        task = self.jobs.enqueue(URL, '192.0.2.1')
        self.jobs.cancel(task['id'], task['capability'])
        original = self.jobs.records.query(task=task['id'])
        snapshot = Path(self.temporary.name) / 'snapshot'
        backup(self.jobs.root, snapshot, services_stopped=True, min_free_bytes=1)
        restored = Path(self.temporary.name) / 'restored'
        restore(snapshot, restored, min_free_bytes=1)
        self.assertEqual(Jobs(restored).records.query(task=task['id']), original)
        with sqlite3.connect(snapshot / 'tasks.sqlite3') as db:
            db.execute('DROP TABLE processing_records')
            db.execute('DROP TABLE video_cache')
            db.execute('ALTER TABLE tasks DROP COLUMN options')
            db.execute('PRAGMA user_version=3')
        index = json.loads((snapshot / 'snapshot.json').read_text())
        index['schema'] = 3
        entry = next(item for item in index['files'] if item['path'] == 'tasks.sqlite3')
        entry.update(bytes=(snapshot / 'tasks.sqlite3').stat().st_size,
                     sha256=hashlib.sha256((snapshot / 'tasks.sqlite3').read_bytes()).hexdigest())
        (snapshot / 'snapshot.json').write_text(json.dumps(index))
        before = (snapshot / 'tasks.sqlite3').read_bytes()
        with self.assertRaises(ValueError):
            Jobs(snapshot)
        upgraded = Path(self.temporary.name) / 'upgraded'
        restore(snapshot, upgraded, upgrade_from_v3=True, min_free_bytes=1)
        current = Jobs(upgraded)
        self.assertEqual(current.records.query(), [])
        self.assertEqual(current.view(task['id'], task['capability'])['expires_at'],
                         self.jobs.view(task['id'], task['capability'])['expires_at'])
        self.assertEqual((snapshot / 'tasks.sqlite3').read_bytes(), before)

    def test_log_write_fault_preserves_terminal_task_and_blocks_new_work_until_repair(self):
        import sqlite3
        from drum_score.worker import recover
        task = self.jobs.enqueue(URL, '192.0.2.1')
        row = self.jobs.claim()
        with sqlite3.connect(self.jobs.database) as db:
            db.execute("CREATE TRIGGER synthetic_record_fault BEFORE UPDATE OF content ON processing_records BEGIN SELECT RAISE(FAIL,'synthetic write fault'); END")
        self.jobs.settle(row, 'failed', 'discontinuity', '处理失败。')
        self.assertEqual(self.jobs.view(task['id'], task['capability'])['state'], 'failed')
        failed = self.jobs.records.query(task=task['id'])[0]
        self.assertEqual(failed['status'], 'record_failed')
        with self.assertRaises(JobError) as caught:
            self.jobs.enqueue(URL, '192.0.2.2')
        self.assertEqual(caught.exception.code, 'records_unavailable')
        with sqlite3.connect(self.jobs.database) as db:
            db.execute('DROP TRIGGER synthetic_record_fault')
        recover(self.jobs)
        repaired = self.jobs.records.query(task=task['id'])[0]
        self.assertEqual(repaired['status'], 'failed')
        self.assertEqual(repaired['error']['code'], 'discontinuity')
        self.assertEqual(repaired['expires_at'], failed['expires_at'])
        self.jobs.enqueue(URL, '192.0.2.2')
