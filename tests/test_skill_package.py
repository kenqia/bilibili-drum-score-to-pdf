"""The public Skill must run without its source repository."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/bilibili-drum-score-to-pdf'
SPEC = importlib.util.spec_from_file_location('sync_skill_references', ROOT / 'tools/sync_skill_references.py')
syncer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(syncer)


class SkillPackageTests(unittest.TestCase):
    def test_protocols_are_current_and_all_local_links_stay_in_package(self):
        self.assertEqual(syncer.sync(check=True), [], 'Regenerate Skill references before publishing.')
        for doc in [SKILL / 'SKILL.md', *sorted((SKILL / 'references').glob('*.md'))]:
            for target in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
                if '://' in target or target.startswith('#'):
                    continue
                path = (doc.parent / target.split('#')[0]).resolve()
                with self.subTest(document=doc.name, target=target):
                    self.assertTrue(path.is_relative_to(SKILL.resolve()))
                    self.assertTrue(path.is_file())
        text = (SKILL / 'SKILL.md').read_text()
        for name in (*syncer.PROTOCOLS, 'support'):
            self.assertIn(f'references/{name}.md', text)
            self.assertTrue((SKILL / f'references/{name}.md').is_file())
        self.assertNotIn('/absolute/repository', text)
        self.assertNotIn('skills/bilibili-drum-score-to-pdf/scripts', text)
        self.assertEqual((SKILL / 'LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())

    def test_detached_directory_cli_and_synthetic_pdf_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            detached = base / 'host/skills/drum-score'
            shutil.copytree(SKILL, detached, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            subprocess.run([sys.executable, str(detached / 'scripts/convert.py'), '--help'],
                           cwd=base, check=True, capture_output=True, timeout=30)
            host = subprocess.run([sys.executable, str(detached / 'scripts/host_check.py'),
                                   '--skills-root', str(detached.parent)],
                                  cwd=base, check=True, capture_output=True, text=True, timeout=30)
            readiness = json.loads(host.stdout)
            self.assertTrue(readiness['protocol_present'])
            self.assertEqual(readiness['discovery'][0]['entries'], [str(detached / 'SKILL.md')])
            # Reuse the existing synthetic acceptance harness against only the
            # copied package scripts. No source-repository imports are allowed.
            replay = (ROOT / 'ci/verify_agent_replay.py').read_text()
            needle = "sys.path.insert(0, str(ROOT / 'skills/bilibili-drum-score-to-pdf/scripts'))"
            self.assertEqual(replay.count(needle), 1)
            replay = replay.replace(needle, f'sys.path.insert(0, {str(detached / "scripts")!r})')
            replay = replay.replace('import score_workflow as workflow',
                'import score_workflow as workflow\n'
                f'assert Path(workflow.__file__).resolve().is_relative_to(Path({str(detached)!r}))')
            runner = base / 'replay.py'
            runner.write_text(replay)
            evidence = base / 'evidence'
            subprocess.run([sys.executable, str(runner), '--output', str(evidence)],
                           cwd=base, check=True, capture_output=True, timeout=120)
            self.assertTrue((evidence / 'fixture-score.pdf').is_file())
            self.assertTrue((evidence / 'summary.json').is_file())
            self.assertFalse((detached / 'docs').exists())
            self.assertFalse((detached / 'skills').exists())


if __name__ == '__main__':
    unittest.main()
