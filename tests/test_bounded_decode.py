"""Bounded temporary decoding observed through the conversion CLI."""
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from test_conversion import CLI, score_frame


class BoundedDecodeTests(unittest.TestCase):
    def test_long_hold_does_not_accumulate_all_sampled_frames(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            cache = root / 'temporary'
            cache.mkdir()
            score_frame().save(root / 'source.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'source.png'), '-t', '32', '-r', '4', '-pix_fmt', 'yuv420p', str(root / 'source.mp4')], check=True)
            env = dict(os.environ, TMPDIR=str(cache), TEMP=str(cache), TMP=str(cache))
            process = subprocess.Popen([sys.executable, str(CLI), str(root / 'source.mp4'), '--output', str(root / 'result')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            peak = 0
            try:
                deadline = time.monotonic() + 180
                while process.poll() is None:
                    peak = max(peak, len(list(cache.glob('drum-score-*/*.png'))))
                    if time.monotonic() > deadline:
                        self.fail('conversion did not finish')
                    time.sleep(.02)
                stdout, stderr = process.communicate()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            result = json.loads(stdout)
            self.assertEqual(result['status'], 'success', stderr + stdout)
            self.assertEqual(len(result['rows']), 3)
            self.assertEqual(result['boundaries']['end']['timestamp'], 31.75)
            self.assertTrue((root / 'result/score.pdf').exists())
            self.assertGreater(peak, 0, 'monitor must observe the decoder cache')
            self.assertLessEqual(peak, 32, 'ordinary sampled PNGs must not accumulate with duration')
            self.assertEqual(list(cache.glob('drum-score-*')), [])

    def test_variable_frame_rate_keeps_actual_last_timestamp(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            score_frame().save(root / 'source.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-framerate', '4', '-i', str(root / 'source.png'), '-t', '12', '-vf', "select='not(eq(mod(n,3),1))'", '-vsync', 'vfr', '-pix_fmt', 'yuv420p', str(root / 'source.mp4')], check=True)
            run = subprocess.run([sys.executable, str(CLI), str(root / 'source.mp4'), '--output', str(root / 'result')], capture_output=True, text=True, timeout=120)
            result = json.loads(run.stdout)
            self.assertEqual(result['status'], 'success', run.stderr + run.stdout)
            self.assertEqual(result['boundaries']['end']['timestamp'], 11.75)
            self.assertEqual(len(result['rows']), 3)

    def test_interrupt_removes_temporary_decoder_frames(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            cache = root / 'temporary'
            cache.mkdir()
            score_frame().save(root / 'source.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'source.png'), '-t', '32', '-r', '4', '-threads', '1', '-pix_fmt', 'yuv420p', str(root / 'source.mp4')], check=True)
            env = dict(os.environ, TMPDIR=str(cache), TEMP=str(cache), TMP=str(cache))
            process = subprocess.Popen([sys.executable, str(CLI), str(root / 'source.mp4'), '--output', str(root / 'result')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            try:
                deadline = time.monotonic() + 60
                while not list(cache.glob('drum-score-*/*.png')):
                    if process.poll() is not None or time.monotonic() > deadline:
                        self.fail('decoder did not enter its temporary stage')
                    time.sleep(.02)
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=15)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(list(cache.glob('drum-score-*')), [])
                self.assertFalse((root / 'result/score.pdf').exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
