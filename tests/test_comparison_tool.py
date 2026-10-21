"""Frozen comparison programs reject changed actual source trees without decoding."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


class ComparisonTool(unittest.TestCase):
    def test_public_tool_freezes_each_programs_actual_tracked_and_untracked_sources(self):
        tool = Path(__file__).resolve().parents[1] / 'tools/compare_script_core.py'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / 'checkout'
            checkout.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(checkout), *args], text=True).strip()
            git('init', '-q')
            paths = ['skills/bilibili-drum-score-to-pdf/scripts/score_workflow.py', 'src/drum_score/__init__.py', 'pyproject.toml']
            for name in paths:
                path = checkout / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# synthetic frozen source\n')
            git('add', '.')
            git('-c', 'user.name=Synthetic Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic frozen source')
            commit = git('rev-parse', 'HEAD')
            manifest, versions = root / 'inputs.json', root / 'versions.json'
            manifest.write_text(json.dumps({'inputs': []}))
            versions.write_text(json.dumps({'main': {'commit': commit}}))
            for program, targets in [('main', [paths[0], 'skills/bilibili-drum-score-to-pdf/scripts/shadow.py']), ('optimized', [paths[1], paths[2], 'src/drum_score/shadow.py'])]:
                clean = root / (program + '-clean')
                args = [sys.executable, str(tool), '--manifest', str(manifest), '--versions', str(versions), '--program', program, '--checkout', str(checkout), '--version', commit]
                result = subprocess.run([*args, '--output', str(clean)], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertTrue(clean.is_dir())
                for index, name in enumerate(targets):
                    with self.subTest(program=program, source=name):
                        path = checkout / name
                        existed = path.exists()
                        original = path.read_bytes() if existed else None
                        path.write_text('# synthetic modified or shadow source\n')
                        output = root / (program + '-' + str(index))
                        try:
                            result = subprocess.run([*args, '--output', str(output)], capture_output=True, text=True, timeout=5)
                            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                            self.assertEqual(json.loads(result.stdout)['error'], program + '_version_changed')
                            self.assertFalse(output.exists())
                        finally:
                            if existed:
                                path.write_bytes(original)
                            else:
                                path.unlink()
