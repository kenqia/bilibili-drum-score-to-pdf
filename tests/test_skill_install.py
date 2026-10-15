"""Committed snapshot installation, failure recovery and task preservation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('install_skill',
    Path(__file__).resolve().parents[1] / 'tools/install_skill.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / 'source'
        self.repo.mkdir()
        self.target = root / 'host/skills/drum-score'
        canonical = self.repo / installer.CANONICAL
        (canonical / 'scripts').mkdir(parents=True)
        (canonical / 'SKILL.md').write_text('---\nname: drum-score\n---\n/absolute/skill\n')
        (canonical / 'scripts/convert.py').write_text('print("fixture CLI")\n')
        (canonical / 'scripts/requirements.txt').write_text('# fixture\n')
        doc = canonical / 'references/stage-recovery-layout.md'
        doc.parent.mkdir(parents=True)
        doc.write_text('fixture protocol\n')
        self.git('init', '-q')
        self.first = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'Controlled install fixture')
        return self.git('rev-parse', 'HEAD')

    def change(self):
        (self.repo / installer.CANONICAL / 'scripts/convert.py').write_text('print("new fixture CLI")\n')
        return self.commit()

    def test_committed_snapshot_single_entry_and_repeat_is_noop(self):
        (self.repo / installer.CANONICAL / 'scripts/convert.py').write_text('uncommitted edit')
        (self.repo / 'untracked.txt').write_text('untracked edit')
        first = installer.install(self.repo, self.first, self.target)
        self.assertEqual(first['status'], 'installed')
        self.assertEqual(list(self.target.rglob('SKILL.md')), [self.target / 'SKILL.md'])
        self.assertNotIn('uncommitted', (self.target / 'scripts/convert.py').read_text())
        self.assertFalse((self.target / 'untracked.txt').exists())
        self.assertFalse((self.target / 'docs').exists())
        self.assertTrue((self.target / 'references/stage-recovery-layout.md').is_file())
        self.assertIn(str(self.target), (self.target / 'SKILL.md').read_text())
        inode = (self.target / installer.MANIFEST).stat().st_ino
        second = installer.install(self.repo, self.first, self.target)
        self.assertEqual(second['status'], 'unchanged')
        self.assertEqual((self.target / installer.MANIFEST).stat().st_ino, inode)

    def test_source_symlink_rejected_without_replacing_valid_install(self):
        installer.install(self.repo, self.first, self.target)
        link = self.repo / installer.CANONICAL / 'references/linked.md'
        link.symlink_to('stage-recovery-layout.md')
        with self.assertRaisesRegex(ValueError, '不支持的文件类型'):
            installer.install(self.repo, self.commit(), self.target)
        self.assertEqual(installer.verify(self.target)['source_commit'], self.first)

    def test_update_preserves_tasks_and_rollback_restores_old_version(self):
        installer.install(self.repo, self.first, self.target)
        task = self.target / 'work/task/record.json'
        task.parent.mkdir(parents=True)
        task.write_text('controlled task')
        inode = task.stat().st_ino
        updated = installer.install(self.repo, self.change(), self.target)
        backup = Path(updated['backup'])
        self.assertFalse(backup.is_relative_to(self.target.parent))
        self.assertEqual(task.stat().st_ino, inode)
        restored = installer.rollback(self.target, backup)
        self.assertEqual(restored['source_commit'], self.first)
        self.assertEqual(task.read_text(), 'controlled task')
        self.assertEqual(task.stat().st_ino, inode)
        self.assertTrue(Path(restored['backup']).exists())

    def test_failed_publication_restores_install_and_unmanaged_tasks(self):
        installer.install(self.repo, self.first, self.target)
        task = self.target / 'work/record.json'
        task.parent.mkdir()
        task.write_text('controlled task')
        real_rename = Path.rename
        def interrupted(path, destination):
            if '-staging-' in path.name and Path(destination) == self.target:
                raise OSError('controlled publication interruption')
            return real_rename(path, destination)
        with patch.object(Path, 'rename', interrupted):
            with self.assertRaises(OSError):
                installer.install(self.repo, self.change(), self.target)
        self.assertEqual(installer.verify(self.target)['source_commit'], self.first)
        self.assertEqual(task.read_text(), 'controlled task')
        self.assertFalse(list(self.target.parent.glob('.*-staging-*')))

    def test_legacy_duplicate_layout_migrates_with_original_backup(self):
        installer.install(self.repo, self.first, self.target)
        canonical = self.target / installer.CANONICAL
        canonical.mkdir(parents=True)
        (canonical / 'SKILL.md').write_text('legacy duplicate entry')
        data = installer.manifest(self.target)
        data['files_sha256'][str(installer.CANONICAL / 'SKILL.md')] = installer.digest(canonical / 'SKILL.md')
        (self.target / installer.MANIFEST).write_text(json.dumps(data))
        updated = installer.install(self.repo, self.first, self.target)
        self.assertEqual(updated['skill_entries'], 1)
        self.assertTrue((Path(updated['backup']) / installer.CANONICAL / 'SKILL.md').exists())

    def test_failed_restoration_keeps_user_task_in_recoverable_staging(self):
        installer.install(self.repo, self.first, self.target)
        task = self.target / 'work/record.json'
        task.parent.mkdir()
        task.write_text('controlled task')
        fresh = self.change()
        real_rename = Path.rename
        def interrupted(path, destination):
            if '-staging-' in path.name or (path.name == 'work' and '-staging-' in str(path)):
                raise OSError('controlled disk failure during publish and restoration')
            return real_rename(path, destination)
        with patch.object(Path, 'rename', interrupted):
            with self.assertRaises(OSError):
                installer.install(self.repo, fresh, self.target)
        staging = list(self.target.parent.glob('.*-staging-*'))
        self.assertEqual(len(staging), 1)
        self.assertTrue((staging[0] / '.recovery-required').exists())
        self.assertEqual((staging[0] / 'work/record.json').read_text(), 'controlled task')
        backups = list((self.target.parent.parent / 'skill-backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(installer.verify(backups[0])['source_commit'], self.first)

    def test_rollback_rejects_a_backup_for_another_installation(self):
        installer.install(self.repo, self.first, self.target)
        updated = installer.install(self.repo, self.change(), self.target)
        other = self.target.parent / 'another-skill'
        with self.assertRaisesRegex(ValueError, '另一安装目标'):
            installer.rollback(other, Path(updated['backup']))
        self.assertFalse(other.exists())
        self.assertEqual(installer.verify(self.target)['source_commit'], updated['source_commit'])

    def test_corrupt_managed_file_is_reported_instead_of_noop(self):
        installer.install(self.repo, self.first, self.target)
        (self.target / 'scripts/convert.py').write_text('controlled corruption')
        with self.assertRaisesRegex(ValueError, '受管理文件'):
            installer.install(self.repo, self.first, self.target)

    def test_manifest_escape_symlink_and_unmanaged_collision_leave_old_install(self):
        installer.install(self.repo, self.first, self.target)
        with self.assertRaises(ValueError):
            installer.managed_path(self.target, '../outside')
        external = self.target.parent / 'linked'
        external.symlink_to(self.target, target_is_directory=True)
        with self.assertRaises(ValueError):
            installer.verify(external)
        (self.target / 'future.txt').write_text('user file')
        (self.repo / installer.CANONICAL / 'future.txt').write_text('new managed file')
        with self.assertRaisesRegex(ValueError, '冲突'):
            installer.install(self.repo, self.commit(), self.target)
        self.assertEqual((self.target / 'future.txt').read_text(), 'user file')
        self.assertEqual(installer.verify(self.target)['source_commit'], self.first)


if __name__ == '__main__':
    unittest.main()
