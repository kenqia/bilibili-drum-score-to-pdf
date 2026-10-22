"""Discovery uses only explicit public Skill entries and never executes them."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / 'skills/bilibili-drum-score-to-pdf/scripts/host_check.py'

HOST_CHECK_ENTRIES = ('module', 'cli')


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

    def test_runtime_version_policy_at_both_host_check_entries(self):
        spec = importlib.util.spec_from_file_location('runtime_host_check', CHECK)
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        dependencies = dict(line.split('==') for line in
                            (CHECK.parent / 'requirements.txt').read_text().splitlines() if line.strip())
        with tempfile.TemporaryDirectory() as temporary:
            for entry in HOST_CHECK_ENTRIES:
                for minor, supported in ((11, False), (12, True), (13, False), (14, False)):
                    with self.subTest(entry=entry, python=f'3.{minor}'), patch.object(
                        host.sys, 'version_info', (3, minor, 0)), patch.object(
                            host.shutil, 'which', return_value='/synthetic/tool'), patch.object(
                                host.importlib.metadata, 'version', side_effect=dependencies.__getitem__):
                        if entry == 'module':
                            result = host.check([temporary])
                        else:
                            output = io.StringIO()
                            with patch.object(sys, 'argv', [str(CHECK), '--skills-root', temporary]), contextlib.redirect_stdout(output):
                                host.main()
                            result = json.loads(output.getvalue())
                        self.assertEqual(result['runtime_ready'], supported)

    def test_every_ci_job_uses_the_supported_python_minor(self):
        workflow = (ROOT / '.github/workflows/skill.yml').read_text()
        versions = re.findall(r"python-version:\s*'([^']+)'", workflow)
        self.assertTrue(versions, 'CI must explicitly select its Python version')
        self.assertEqual(set(versions), {'3.12'})
