"""Managed filesystem, explicit schema and storage boundaries (synthetic data only)."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.jobs import Jobs, JobError, SCHEMA_VERSION

LINK = 'https://www.bilibili.com/video/BV1rH4y1R7Rk'


@unittest.skipUnless(sys.platform == 'linux', 'Ubuntu managed service contract')
class ProductLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.jobs = Jobs(self.root / 'service', job_temp_bytes=128, retained_bytes=4096, min_free_bytes=1)

    def tearDown(self):
        self.temp.cleanup()

    def complete(self):
        created = self.jobs.enqueue(LINK, '192.0.2.1')
        row = self.jobs.claim()
        attempt = self.jobs.register_attempt(row)
        result = attempt / 'result'
        result.mkdir()
        (result / 'score.pdf').write_bytes(b'%PDF-synthetic')
        (result / 'page-001.png').write_bytes(b'synthetic page')
        refs = [dict(path=name, bytes=(result / name).stat().st_size,
                sha256=hashlib.sha256((result / name).read_bytes()).hexdigest())
                for name in ('score.pdf', 'page-001.png')]
        summary = dict(pdf=refs[0], pages=refs[1:], page_count=1)
        (result / 'manifest.json').write_text(json.dumps(summary))
        self.jobs.remember_result(row, summary)
        self.assertTrue(self.jobs.finishing(row, summary))
        self.jobs.settle(row, 'complete')
        return created, row, result

    def test_schema_is_explicit_and_unknown_or_unversioned_database_is_refused(self):
        with sqlite3.connect(self.jobs.database) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
        for version in (0, SCHEMA_VERSION + 1):
            with self.subTest(version=version):
                target = self.root / str(version)
                target.mkdir()
                with sqlite3.connect(target / 'tasks.sqlite3') as db:
                    db.execute('CREATE TABLE unknown(sentinel TEXT)')
                    db.execute('INSERT INTO unknown VALUES(?)', ('synthetic',))
                    db.execute(f'PRAGMA user_version={version}')
                before = (target / 'tasks.sqlite3').read_bytes()
                with self.assertRaises(ValueError):
                    Jobs(target)
                self.assertEqual((target / 'tasks.sqlite3').read_bytes(), before)

    def test_expiry_cleanup_preserves_open_download_and_never_refreshes_deadline(self):
        created, row, result = self.complete()
        view = self.jobs.view(created['id'], created['capability'])
        descriptor, _ = self.jobs.open_artifact(created['id'], created['capability'])
        reopened = Jobs(self.jobs.root)
        self.assertEqual(reopened.view(created['id'], created['capability'])['expires_at'], view['expires_at'])
        with patch('drum_score.jobs.time.time', return_value=view['expires_at'] + 1):
            reopened.cleanup()
            self.assertFalse(result.exists())
            self.assertEqual(os.read(descriptor, 100), b'%PDF-synthetic')
            for operation in (reopened.view, reopened.cancel, reopened.open_artifact):
                with self.assertRaises(JobError) as caught:
                    operation(created['id'], created['capability'])
                self.assertEqual(caught.exception.code, 'expired')
            with self.assertRaises(JobError) as caught:
                reopened.retry(created['id'], created['capability'], '192.0.2.1')
            self.assertEqual(caught.exception.code, 'expired')
        os.close(descriptor)

    def test_cleanup_preserves_unknown_files_replaced_inodes_and_external_symlinks(self):
        created, row, result = self.complete()
        (result / 'unknown.txt').write_text('user sentinel')
        (result / 'score.pdf').unlink()
        (result / 'score.pdf').write_text('replaced inode sentinel')
        external = self.root / 'outside.png'
        external.write_text('outside sentinel')
        (result / 'page-001.png').unlink()
        (result / 'page-001.png').symlink_to(external)
        expires = self.jobs.view(created['id'], created['capability'])['expires_at']
        with patch('drum_score.jobs.time.time', return_value=expires + 1):
            self.jobs.cleanup()
        self.assertEqual(external.read_text(), 'outside sentinel')
        self.assertEqual((result / 'unknown.txt').read_text(), 'user sentinel')
        self.assertEqual((result / 'score.pdf').read_text(), 'replaced inode sentinel')
        self.assertTrue((result / 'page-001.png').is_symlink())
        self.assertFalse((result / 'manifest.json').exists())

    def test_cleanup_rejects_replaced_attempt_and_parent_symlink(self):
        created, row, result = self.complete()
        attempt = result.parent
        moved = self.root / 'kept'
        attempt.rename(moved)
        attempt.symlink_to(moved, target_is_directory=True)
        self.jobs.discard(row)
        self.assertTrue((moved / 'result' / 'score.pdf').exists())
        self.assertTrue(attempt.is_symlink())
        attempt.unlink()
        attempt.mkdir()
        (attempt / 'unknown').write_text('new inode')
        self.jobs.discard(row)
        self.assertEqual((attempt / 'unknown').read_text(), 'new inode')

    def test_capacity_applies_to_admission_retry_claim_and_running_without_deleting_live_results(self):
        created, row, result = self.complete()
        with patch('drum_score.jobs.os.statvfs') as fs:
            fs.return_value.f_bavail = 0
            fs.return_value.f_frsize = 4096
            with self.assertRaises(JobError) as caught:
                self.jobs.enqueue(LINK, '192.0.2.2')
            self.assertEqual(caught.exception.code, 'storage_full')
            with self.assertRaises(JobError):
                self.jobs.capacity()
            self.assertTrue((result / 'score.pdf').exists())
        retry = self.jobs.enqueue(LINK, '192.0.2.2')
        self.jobs.cancel(retry['id'], retry['capability'])
        self.jobs.retained_bytes = 1
        with self.assertRaises(JobError):
            self.jobs.retry(retry['id'], retry['capability'], '192.0.2.2')
        self.jobs.retained_bytes = 4096
        queued = self.jobs.enqueue(LINK, '192.0.2.3')
        self.jobs.retained_bytes = 1
        self.assertIsNone(self.jobs.claim())
        self.assertEqual(self.jobs.view(queued['id'], queued['capability'])['error']['code'], 'storage_full')
        self.assertTrue((result / 'score.pdf').exists())

    def test_diagnostics_have_ttl_global_byte_limit_and_no_raw_exception_data(self):
        self.jobs.diagnostic_bytes = 1
        created = self.jobs.enqueue(LINK, '192.0.2.1')
        row = self.jobs.claim()
        self.jobs.register_attempt(row)
        self.jobs.settle(row, 'failed', 'conversion_failed', '转换失败。')
        self.jobs.cleanup()
        view = self.jobs.view(created['id'], created['capability'])
        self.assertIsNone(view['error'])
        self.assertIsNotNone(view['expires_at'])
        with patch('drum_score.jobs.time.time', return_value=view['expires_at'] + 1):
            self.jobs.cleanup()
            with self.assertRaises(JobError) as caught:
                self.jobs.view(created['id'], created['capability'])
            self.assertEqual(caught.exception.status, 410)

    def test_corrupt_same_size_artifact_is_not_served(self):
        created, row, result = self.complete()
        (result / 'score.pdf').write_bytes(b'%PDF-corrupted')
        with self.assertRaises(JobError) as caught:
            self.jobs.open_artifact(created['id'], created['capability'])
        self.assertEqual(caught.exception.code, 'result_unavailable')
