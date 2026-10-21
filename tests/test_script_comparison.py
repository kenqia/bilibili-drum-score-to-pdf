"""Comparison tools must reject changed fixed inputs before execution."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ScriptComparison(unittest.TestCase):
    def test_existing_results_are_preserved_and_deadline_stops_program(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'synthetic local input')
            manifest = root / 'inputs.json'
            manifest.write_text(json.dumps({'inputs': [{'name': 'fixture',
                'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]}))
            program = root / 'slow.py'
            program.write_text('import time\ntime.sleep(60)\n')
            output = root / 'comparison'
            command = [sys.executable,
                str(Path(__file__).resolve().parents[1] / 'tools/compare_script_core.py'),
                '--manifest', str(manifest), '--output', str(output),
                '--program', 'attachment', '--attachment', str(program),
                '--attachment-sha256', hashlib.sha256(program.read_bytes()).hexdigest(),
                '--seconds', '0.1']
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads((output / 'comparison.json').read_text())[0]
            self.assertEqual(report['failure'], 'deadline')
            self.assertEqual(report['pdfs'], [])
            before = (output / 'comparison.json').read_bytes()
            again = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(again.returncode, 2)
            self.assertEqual((output / 'comparison.json').read_bytes(), before)

    def test_changed_fixed_input_is_refused_without_starting_program(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'changed')
            manifest = root / 'inputs.json'
            manifest.write_text(json.dumps({'inputs': [{'name': 'fixture',
                'path': str(source), 'sha256': hashlib.sha256(b'original').hexdigest()}]}))
            result = subprocess.run([sys.executable,
                str(Path(__file__).resolve().parents[1] / 'tools/compare_script_core.py'),
                '--manifest', str(manifest), '--output', str(root / 'comparison'),
                '--program', 'main', '--checkout', str(root), '--versions', str(root / 'versions.json')],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('input_changed', result.stdout)
            self.assertFalse((root / 'comparison').exists())
