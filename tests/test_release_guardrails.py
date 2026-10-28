"""Synthetic deployment identities, packaging corruption and real file rollback."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from service_baseline import collect, check, schema_identity
from build_release import verify_artifacts
from deploy_release import Switch
from drum_score.schema import SCHEMA_STATEMENTS


def database(path):
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        for statement in SCHEMA_STATEMENTS:
            db.execute(statement)
        db.execute('INSERT INTO submission_control VALUES(1,0)')
        db.execute('PRAGMA user_version=5')


class BaselineTests(unittest.TestCase):
    def test_same_version_different_structure_and_missing_database_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'root/tasks.sqlite3'
            database(db)
            self.assertEqual(schema_identity(db)['version'], 5)
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE unexpected(value TEXT)')
            with self.assertRaises(ValueError):
                schema_identity(db)
            missing = db.with_name('missing')
            with self.assertRaises(sqlite3.OperationalError):
                schema_identity(missing)
            self.assertFalse(missing.exists())

    def test_changed_config_and_nonancestor_commit_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root / 'data/tasks.sqlite3')
            (root / 'release-identity.json').write_text(json.dumps({'commit': 'a'*40}))
            config = root / 'profile'
            config.write_text('SYNTHETIC_PRIVATE_CONFIG')
            baseline = collect(root, root / 'data/tasks.sqlite3', [config])
            self.assertNotIn('SYNTHETIC_PRIVATE_CONFIG', json.dumps(baseline))
            config.write_text('changed')
            with self.assertRaises(ValueError):
                check(collect(root, root / 'data/tasks.sqlite3', [config]), baseline)
            with patch('service_baseline.subprocess.run', return_value=subprocess.CompletedProcess([], 1)):
                with self.assertRaises(ValueError):
                    check(baseline, baseline, root, 'candidate')


class PackagingTests(unittest.TestCase):
    def test_stale_extra_missing_and_modified_package_files_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            (source / 'src/drum_score').mkdir(parents=True)
            (source / 'src/drum_score/__init__.py').write_bytes(b'expected')
            wheel, sdist = root / 'test.whl', root / 'test.tar.gz'
            with tarfile.open(sdist, 'w:gz') as archive:
                item = tarfile.TarInfo('package/src/drum_score/__init__.py')
                item.size = 8
                archive.addfile(item, io.BytesIO(b'expected'))
            for payload in ({'__init__.py': b'expected'},
                            {'__init__.py': b'expected', 'youtube_backend.py': b'stale'},
                            {}, {'__init__.py': b'modified'}):
                with zipfile.ZipFile(wheel, 'w') as archive:
                    for name, data in payload.items():
                        archive.writestr('drum_score/' + name, data)
                if payload == {'__init__.py': b'expected'}:
                    self.assertEqual(len(verify_artifacts(source, wheel, sdist)), 1)
                else:
                    with self.assertRaises(ValueError):
                        verify_artifacts(source, wheel, sdist)
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('drum_score/__init__.py', b'expected')
            with tarfile.open(sdist, 'w:gz') as archive:
                item = tarfile.TarInfo('package/src/drum_score/stale.py')
                item.size = 5
                archive.addfile(item, io.BytesIO(b'stale'))
            with self.assertRaises(ValueError):
                verify_artifacts(source, wheel, sdist)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        old, new = self.root / 'old', self.root / 'new'
        old.mkdir()
        new.mkdir()
        package = new / 'venv/lib/python3.12/site-packages/drum_score'
        package.mkdir(parents=True)
        (package / '__init__.py').write_bytes(b'synthetic')
        old_identity = {'commit': 'a'*40}
        new_identity = {'commit': 'b'*40, 'package_files': {
            'drum_score/__init__.py': hashlib.sha256(b'synthetic').hexdigest()}}
        (old / 'release-identity.json').write_text(json.dumps(old_identity))
        (new / 'release-identity.json').write_text(json.dumps(new_identity))
        current = self.root / 'current'
        current.symlink_to(old)
        self.profiles = []
        for name in ('web', 'worker'):
            path = self.root / (name + '.conf')
            path.write_text('old synthetic config')
            private, public = self.root / (name + '.private'), self.root / (name + '.public')
            for p in (private, public):
                p.write_text(str(current) + ' --data-root ' + str(self.root / 'new-data') + ' ' + p.suffix)
            self.profiles.append({'path': str(path), 'private': str(private), 'public': str(public)})
        old_db, new_db = self.root / 'old-data/tasks.sqlite3', self.root / 'new-data/tasks.sqlite3'
        database(old_db)
        database(new_db)
        baselines = []
        for release, db, configs in ((old, old_db, [x['path'] for x in self.profiles]),
                                     (new, new_db, [x[k] for x in self.profiles for k in ('private', 'public')])):
            baseline = collect(release, db, configs, fingerprint_data=True)
            baseline['database_sha256'] = hashlib.sha256(db.read_bytes()).hexdigest()
            baselines.append(baseline)
        self.plan = {'old': baselines[0], 'new': baselines[1], 'current': str(current),
                     'profiles': self.profiles, 'private_port': 8792, 'public_port': 8791,
                     'private_check': ['/synthetic/private-acceptance']}
        self.calls = []
        self.switch = Switch(self.plan, self.root / 'report.json', run=self.calls.append)
        self.switch.health = lambda port: None

    def assert_restored(self):
        self.assertEqual(Path(self.plan['current']).resolve(), self.root / 'old')
        for item in self.profiles:
            self.assertEqual(Path(item['path']).read_text(), 'old synthetic config')
        self.assertTrue((self.root / 'new-data/tasks.sqlite3').exists())

    def test_preflight_is_read_only_and_success_keeps_matching_code_config_data(self):
        # baseline metadata includes a digest used only after the stop barrier.
        with patch('deploy_release.check', side_effect=lambda actual, expected: check(
                actual, expected)):
            self.switch.preflight()
            self.assertEqual(self.calls, [])
            self.assertFalse(self.switch.report.exists())
            self.switch.execute()
        self.assertEqual(Path(self.plan['current']).resolve(), self.root / 'new')
        for item in self.profiles:
            self.assertEqual(Path(item['path']).read_bytes(), Path(item['public']).read_bytes())
        self.assertIn(['/synthetic/private-acceptance'], self.calls)

    def run_fault(self, mode):
        original_atomic = self.switch.atomic
        if mode == 'fsync':
            from deploy_release import sync_directory
            failed = False
            def injected(path):
                nonlocal failed
                if self.switch.changed and not failed:
                    failed = True
                    raise OSError('synthetic post-publication fsync')
                sync_directory(path)
            context = patch('deploy_release.sync_directory', side_effect=injected)
        else:
            def broken_event(name):
                raise OSError('synthetic report failure')
            def atomic(path, data, track=True):
                original_atomic(path, data, track)
                if track:
                    self.switch.event = broken_event
                    raise RuntimeError('synthetic private failure')
            context = patch.object(self.switch, 'atomic', side_effect=atomic)
        with patch('deploy_release.check', side_effect=lambda actual, expected: check(
                actual, expected)), context:
            with self.assertRaises((OSError, RuntimeError)):
                self.switch.execute()
        self.assert_restored()
        self.assertIn(['systemctl', 'start', 'drum-score-web.service', 'drum-score-worker.service'], self.calls)

    def test_parent_fsync_after_profile_publication_restores_old_triple(self):
        self.run_fault('fsync')

    def test_report_failure_cannot_prevent_rollback(self):
        self.run_fault('report')

    def test_private_acceptance_failure_after_link_flip_restores_old_triple(self):
        def run(command):
            self.calls.append(command)
            if command == self.plan['private_check']:
                raise RuntimeError('synthetic acceptance failure')
        self.switch.run = run
        with patch('deploy_release.check', side_effect=lambda actual, expected: check(
                actual, expected)):
            with self.assertRaises(RuntimeError):
                self.switch.execute()
        self.assert_restored()

    def test_public_failure_preserves_new_root_and_stops_admission(self):
        def health(port):
            if port == self.plan['public_port']:
                raise RuntimeError('synthetic public failure')
        self.switch.health = health
        with patch('deploy_release.check', side_effect=lambda actual, expected: check(
                actual, expected)):
            with self.assertRaises(RuntimeError):
                self.switch.execute()
        self.assertEqual(Path(self.plan['current']).resolve(), self.root / 'new')
        self.assertEqual(self.calls[-1], ['systemctl', 'stop', 'drum-score-web.service'])


if __name__ == '__main__':
    unittest.main()
