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
from service_baseline import collect, check, check_candidate, schema_identity
from build_release import verify_artifacts
from deploy_release import Switch, profile_command
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

    def test_transferred_baseline_checks_local_candidate_without_server_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / 'data/tasks.sqlite3'
            database(db)
            (root / 'release-identity.json').write_text(json.dumps({'commit': 'a'*40}))
            config = root / 'profile'
            config.write_text('synthetic')
            baseline = collect(root, db, [config])
            repository = Path(__file__).resolve().parents[1]
            candidate = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD']).decode().strip()
            baseline['commit'] = candidate
            check_candidate(baseline, repository, candidate)
            baseline['schema']['sha256'] = '0'*64
            with self.assertRaises(ValueError):
                check_candidate(baseline, repository, candidate)



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
                port = '8792' if p == private else '8791'
                command = str(current) + '/venv/bin/drum-score-' + name + ' --data-root ' + str(self.root / 'new-data')
                if name == 'web':
                    command += ' --host 127.0.0.1 --port ' + port
                p.write_text('[Service]\nExecStart=\nExecStart=' + command + '\n')
            self.profiles.append({'role': name, 'path': str(path), 'private': str(private), 'public': str(public)})
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
        self.switch.verify_effective = lambda phase: None

    def assert_restored(self):
        self.assertEqual(Path(self.plan['current']).resolve(), self.root / 'old')
        for item in self.profiles:
            self.assertEqual(Path(item['path']).read_text(), 'old synthetic config')
        self.assertTrue((self.root / 'new-data/tasks.sqlite3').exists())

    def test_preflight_is_read_only_and_success_keeps_matching_code_config_data(self):
        # baseline metadata includes a digest used only after the stop barrier.
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
        with context:
            with self.assertRaises((OSError, RuntimeError)):
                self.switch.execute()
        self.assert_restored()
        self.assertIn(['systemctl', 'start', 'drum-score-web.service', 'drum-score-worker.service'], self.calls)

    def test_parent_fsync_after_profile_publication_restores_old_triple(self):
        self.run_fault('fsync')

    def test_parent_fsync_after_link_publication_restores_old_triple(self):
        from deploy_release import sync_directory
        failed = False
        def injected(path):
            nonlocal failed
            if self.switch.link_changed and not failed:
                failed = True
                raise OSError('synthetic post-link-publication fsync')
            sync_directory(path)
        with patch('deploy_release.sync_directory', side_effect=injected):
            with self.assertRaises(OSError):
                self.switch.execute()
        self.assertTrue(failed)
        self.assert_restored()

    def test_report_failure_cannot_prevent_rollback(self):
        self.run_fault('report')

    def test_private_acceptance_failure_after_link_flip_restores_old_triple(self):
        def run(command):
            self.calls.append(command)
            if command == self.plan['private_check']:
                raise RuntimeError('synthetic acceptance failure')
        self.switch.run = run
        with self.assertRaises(RuntimeError):
            self.switch.execute()
        self.assert_restored()

    def test_existing_report_and_symlink_are_never_overwritten(self):
        sentinel = self.root / 'unrelated'
        sentinel.write_text('SYNTHETIC_KEEP')
        for symlink in (False, True):
            if symlink:
                self.switch.report.symlink_to(sentinel)
            else:
                self.switch.report.write_text('SYNTHETIC_KEEP')
            with self.assertRaises(FileExistsError):
                self.switch.execute()
            self.assertEqual(sentinel.read_text(), 'SYNTHETIC_KEEP')
            self.assertEqual(self.calls, [])
            self.switch.report.unlink()

    def test_external_release_replacement_is_preserved(self):
        external = self.root / 'external'
        external.mkdir()
        def run(command):
            self.calls.append(command)
            if command == ['systemctl', 'stop', 'drum-score-web.service', 'drum-score-worker.service']:
                current = Path(self.plan['current'])
                current.unlink()
                current.symlink_to(external)
        self.switch.run = run
        with self.assertRaises(ValueError):
            self.switch.execute()
        self.assertEqual(Path(self.plan['current']).resolve(), external)
        self.assertNotIn(['systemctl', 'start', 'drum-score-web.service', 'drum-score-worker.service'], self.calls)
        for item in self.profiles:
            self.assertEqual(Path(item['path']).read_text(), 'old synthetic config')

    def test_external_equal_bytes_profile_replacement_is_preserved(self):
        path = Path(self.profiles[0]['path'])
        replacement_identity = None
        def run(command):
            nonlocal replacement_identity
            self.calls.append(command)
            if replacement_identity is None and command == ['systemctl', 'stop', 'drum-score-web.service', 'drum-score-worker.service']:
                temporary = path.with_suffix('.external')
                temporary.write_bytes(path.read_bytes())
                temporary.replace(path)
                replacement_identity = path.stat().st_ino
        self.switch.run = run
        with self.assertRaises(ValueError):
            self.switch.execute()
        self.assertEqual(path.stat().st_ino, replacement_identity)
        self.assertNotIn(['systemctl', 'start', 'drum-score-web.service', 'drum-score-worker.service'], self.calls)
        self.assertEqual(Path(self.plan['current']).resolve(), self.root / 'old')

    def test_report_replacement_after_stop_does_not_touch_external_file_or_block_rollback(self):
        sentinel = self.root / 'unrelated'
        sentinel.write_text('SYNTHETIC_KEEP')
        def run(command):
            self.calls.append(command)
            if command == self.plan['private_check']:
                self.switch.report.unlink()
                self.switch.report.symlink_to(sentinel)
        self.switch.run = run
        with self.assertRaises(ValueError):
            self.switch.execute()
        self.assert_restored()
        self.assertEqual(sentinel.read_text(), 'SYNTHETIC_KEEP')

    def test_wrong_private_host_port_root_and_worker_profile_are_refused(self):
        from service_baseline import collect
        for old, new in (('--port 8792', '--port 8791'),
                         ('--host 127.0.0.1', '--host 0.0.0.0'),
                         ('--data-root ' + str(self.root / 'new-data'), '--data-root /unrelated')):
            path = Path(self.profiles[0]['private'])
            original = path.read_text()
            path.write_text(original.replace(old, new))
            self.plan['new'] = collect(self.root / 'new', self.root / 'new-data/tasks.sqlite3',
                [item[k] for item in self.profiles for k in ('private', 'public')], fingerprint_data=True)
            with self.assertRaises(ValueError):
                self.switch.preflight()
            path.write_text(original)
        path = Path(self.profiles[1]['public'])
        path.write_text(path.read_text() + '# changed worker budget\n')
        self.plan['new'] = collect(self.root / 'new', self.root / 'new-data/tasks.sqlite3',
            [item[k] for item in self.profiles for k in ('private', 'public')], fingerprint_data=True)
        with self.assertRaises(ValueError):
            self.switch.preflight()
        self.assertEqual(self.calls, [])

    def test_effective_systemd_override_is_refused_before_start(self):
        del self.switch.verify_effective
        def run(command):
            self.calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=b'{ argv[]=unexpected ; }')
        self.switch.run = run
        with self.assertRaises(ValueError):
            self.switch.execute()
        self.assert_restored()
        self.assertNotIn('private_acceptance_passed', self.switch.events)

    def test_public_failure_preserves_new_root_and_stops_admission(self):
        def health(port):
            if port == self.plan['public_port']:
                raise RuntimeError('synthetic public failure')
        self.switch.health = health
        with self.assertRaises(RuntimeError):
            self.switch.execute()
        self.assertEqual(Path(self.plan['current']).resolve(), self.root / 'new')
        self.assertEqual(self.calls[-1], ['systemctl', 'stop', 'drum-score-web.service'])


if __name__ == '__main__':
    unittest.main()
