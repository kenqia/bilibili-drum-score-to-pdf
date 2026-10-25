"""Real process and storage boundaries for disposable HTTP printing."""
from pathlib import Path
import os
import json
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PIL import Image, ImageDraw
from drum_score.jobs import Jobs, JobError
from drum_score.core import artifact
from drum_score.print_layout import render
try:
    from fastapi.testclient import TestClient
    from drum_score.web import create_app
except ImportError:
    raise unittest.SkipTest('Install tests/requirements-web.txt for optional website tests')


@unittest.skipUnless(sys.platform == 'linux', 'Linux print process lifecycle')
class PrintLifecycle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.jobs = Jobs(self.root / 'service')
        self.task = self.jobs.enqueue('https://www.bilibili.com/video/BV1rH4y1R7Rk', '192.0.2.1')
        self.row = self.jobs.claim()
        output = self.jobs.register_attempt(self.row) / 'result'
        output.mkdir()
        image = Image.new('RGB', (640, 600), 'white')
        drawing = ImageDraw.Draw(image)
        for top in (80, 280, 480):
            for line in range(5):
                drawing.line((20, top + line * 8, 620, top + line * 8), fill='black')
        result = render(image, output)
        summary = {'status': 'complete', 'reliable': False, 'warnings': [],
                   'page_count': result['page_count'], 'pdf': artifact(output, output / 'score.pdf'),
                   'pages': [artifact(output, p) for p in sorted(output.glob('page-*.png'))]}
        (output / 'manifest.json').write_text(json.dumps(summary))
        self.jobs.remember_result(self.row, summary)
        self.jobs.finishing(self.row, summary)
        self.jobs.settle(self.row, 'complete')
        self.before = self.jobs.view(self.task['id'], self.task['capability'])
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        self.temporary.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.02)
        self.fail('Synthetic print process did not reach expected boundary')

    def block_preview(self):
        binary = self.root / 'bin'
        binary.mkdir()
        command = binary / 'pdftoppm'
        command.write_text('#!' + sys.executable + '\n'
            'import os,time\nfrom pathlib import Path\n'
            'Path(os.environ["PRINT_SENTINEL"]).write_text(str(os.getpid()))\n'
            'while True: time.sleep(.05)\n')
        command.chmod(0o700)
        runner = self.root / 'request.py'
        runner.write_text('from drum_score.jobs import Jobs\n'
            'from drum_score.relayout import delivery\nimport sys\n'
            'delivery(Jobs(sys.argv[1]),sys.argv[2],sys.argv[3],"A4",1)\n')
        environment = {**os.environ,
            'PATH': str(binary) + os.pathsep + os.environ['PATH'],
            'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
            'PRINT_SENTINEL': str(self.root / 'writer')}
        process = subprocess.Popen([sys.executable, str(runner), str(self.jobs.root),
            self.task['id'], self.task['capability']], env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        self.wait_for(lambda: (self.root / 'writer').exists())
        writer = int((self.root / 'writer').read_text())
        staging = next(self.jobs.attempt_root(self.row['id'], self.row['attempt']).glob('.drum-score-job-*'))
        return process, writer, staging

    def test_parent_kill_guardian_stops_writer_and_preserves_default(self):
        process, writer, staging = self.block_preview()
        with TestClient(create_app(self.jobs.root)) as client:
            response = client.post('/api/tasks/' + self.task['id'] + '/layout',
                headers={'Authorization': 'Bearer ' + self.task['capability']}, json={})
            self.assertEqual(response.status_code, 503)
        # Worker startup must not reap the live print staging.
        self.jobs.recover_staging()
        self.assertTrue(staging.exists())
        self.assertGreaterEqual(self.jobs.capacity(), 128 * 1024**2)
        process.kill()
        process.wait()
        def stopped():
            try:
                return Path('/proc', str(writer), 'stat').read_text().rsplit(') ', 1)[1].split()[0] == 'Z'
            except FileNotFoundError:
                return True
        self.wait_for(stopped)
        self.wait_for(lambda: not staging.exists())
        self.jobs.recover_staging()
        self.assertEqual(self.jobs.view(self.task['id'], self.task['capability']), self.before)

    def test_whole_tree_kill_recovers_only_registered_root(self):
        process, writer, staging = self.block_preview()
        children = Path('/proc', str(process.pid), 'task', str(process.pid), 'children').read_text().split()
        guardian = next(int(pid) for pid in children if b'drum_score.guardian' in Path('/proc', pid, 'cmdline').read_bytes())
        os.kill(guardian, signal.SIGKILL)
        process.kill()
        process.wait()
        # The generator and preview are in a separate session.
        parent_pid = int(Path('/proc', str(writer), 'stat').read_text().rsplit(') ', 1)[1].split()[1])
        os.killpg(parent_pid, signal.SIGKILL)
        unknown = staging.parent / '.drum-score-job-unknown'
        unknown.mkdir()
        (unknown / 'keep').write_text('SYNTHETIC UNKNOWN')
        self.jobs.recover_staging()
        self.assertFalse(staging.exists())
        self.assertEqual((unknown / 'keep').read_text(), 'SYNTHETIC UNKNOWN')
        self.assertEqual(self.jobs.view(self.task['id'], self.task['capability']), self.before)

    def test_reservation_prevents_admitting_more_conversion_work(self):
        process, writer, staging = self.block_preview()
        bounded = Jobs(self.jobs.root, retained_bytes=1150 * 1024**2, job_temp_bytes=1024**3)
        with self.assertRaises(JobError) as error:
            bounded.capacity(reserve=True)
        self.assertEqual(error.exception.code, 'storage_full')
        process.kill()
        process.wait()
        self.wait_for(lambda: not staging.exists())
