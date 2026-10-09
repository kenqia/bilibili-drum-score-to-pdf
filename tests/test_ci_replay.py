"""Exercise the same offline replay command that the hosted workflow runs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CIReplayTests(unittest.TestCase):
    def test_offline_replay_produces_bounded_sanitized_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'evidence'
            result = subprocess.run([sys.executable, str(ROOT / 'ci/verify_agent_replay.py'),
                                     '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(summary['status'], 'passed')
            self.assertEqual(summary['row_count'], 3)
            self.assertEqual(summary['negative_cases'], {
                'unknown_version': 'invalid_decision', 'out_of_bounds': 'invalid_decision',
                'corrupt_image': 'source_mismatch'})
            self.assertTrue(summary['native_crops_equal'])
            self.assertTrue(summary['replay_pdf_equal'])
            self.assertEqual(summary['pdf_pages'], 1)
            self.assertGreaterEqual(summary['minimum_effective_dpi'], 150)
            files = list(output.iterdir())
            self.assertEqual({p.name for p in files}, {'summary.json', 'fixture-score.pdf'})
            self.assertLess(sum(p.stat().st_size for p in files), 5 * 1024 * 1024)
            self.assertNotIn(directory, (output / 'summary.json').read_text())

    def test_failure_evidence_excludes_subprocess_paths_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'evidence'
            environment = {**os.environ, 'PATH': directory}
            result = subprocess.run([sys.executable, str(ROOT / 'ci/verify_agent_replay.py'),
                                     '--output', str(output)], env=environment,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(summary['status'], 'failed')
            self.assertEqual(summary['failure_type'], 'FileNotFoundError')
            self.assertNotIn(directory, (output / 'summary.json').read_text())
            self.assertEqual([p.name for p in output.iterdir()], ['summary.json'])
