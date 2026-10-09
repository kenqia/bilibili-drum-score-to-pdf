"""Lifecycle reports observed at the unified CLI boundary."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from score_fixtures import CLI, score_frame, video_from_image


class PerformanceTests(unittest.TestCase):
    def cli(self, *args):
        process = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)
        self.assertTrue(process.stdout, process.stderr)
        return json.loads(process.stdout)

    def test_prepare_resume_and_report_include_wait_without_recounting(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            prepared = self.cli(video, '--output', task)
            report = prepared['performance']
            self.assertEqual(report['task_status'], 'waiting')
            self.assertIsNone(report['first_deliverable_at'])
            self.assertIsNone(report['model_tokens'])
            self.assertEqual(report['operations'][0]['operation'], 'prepare')
            self.assertGreater(report['operations'][0]['elapsed_seconds'], 0)
            time.sleep(0.05)
            resumed = self.cli('--operation', 'resume', '--task', task)['performance']
            self.assertEqual(report['submitted_at'], resumed['submitted_at'])
            self.assertGreater(resumed['wall_elapsed_seconds'], report['wall_elapsed_seconds'] + 0.05)
            self.assertEqual(len(resumed['operations']), 2)
            rebuilt = self.cli('--operation', 'report', '--task', task)['performance']
            again = self.cli('--operation', 'report', '--task', task)['performance']
            self.assertEqual(rebuilt['operations'], again['operations'])
            self.assertEqual(rebuilt['stages'], again['stages'])
            self.assertEqual(rebuilt['source']['sha256'], json.loads((task / 'observation.json').read_text())['source']['sha256'])
            self.assertEqual(rebuilt['metrics']['analyzed_frames'], 3)
