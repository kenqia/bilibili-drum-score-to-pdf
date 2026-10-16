"""Discovery uses only explicit public Skill entries and never executes them."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / 'skills/bilibili-drum-score-to-pdf/scripts/host_check.py'


class HostCheckTests(unittest.TestCase):
    def test_explicit_root_reports_duplicate_entries_and_unknown_capabilities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('first', 'second'):
                entry = root / name
                entry.mkdir()
                (entry / 'SKILL.md').write_text('---\nname: bilibili-drum-score-to-pdf\n---\n')
            (root / 'auth.json').write_text('synthetic-do-not-read')
            result = subprocess.run([sys.executable, str(CHECK), '--skills-root', str(root)],
                                    text=True, capture_output=True, check=True)
            data = json.loads(result.stdout)
            self.assertEqual(result.stderr, '')
            self.assertTrue(data['discovery'][0]['duplicate'])
            self.assertEqual(len(data['discovery'][0]['entries']), 2)
            self.assertTrue(data['protocol_present'])
            self.assertEqual(data['host_imagegen'], 'unverified')
            self.assertNotIn('synthetic-do-not-read', result.stdout)
