"""Acquisition and decoding protections retained across workflow replacement."""
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from score_fixtures import score_frame, video_from_image
import test_link_input
from drum_score.core import _convert, convert
from drum_score.video_seek import ConversionError, VideoReader, probe_video

class MediaBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Executable decoder fixture')
    def test_contended_decoder_can_use_remaining_cumulative_budget(self):
        import subprocess
        import threading
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'tools'
            tools.mkdir()
            executable = tools / 'ffmpeg'
            executable.write_text('#!' + sys.executable + '\n' +
                'import sys,time\nfrom PIL import Image\n' +
                'if "-h" in sys.argv:\n print("-fps_mode mode"); sys.exit(0)\n' +
                'time.sleep(.7)\n' +
                'if "rawvideo" in sys.argv:\n' +
                ' sys.stderr.write("metadata@motion frame:0 pts:0\\nmetadata@motion lavfi.signalstats.YDIF=0\\nshowinfo@sample config in time_base: 1/1\\nshowinfo@sample n:0 pts:0\\n")\n' +
                ' sys.stdout.buffer.write(bytes([1,2,3])*4)\n' +
                'else:\n' +
                ' Image.new("RGB",(2,2),(1,2,3)).save(sys.argv[-1])\n' +
                ' sys.stderr.write("config in time_base: 1/1\\npts: 0\\n")\n')
            executable.chmod(0o755)
            timer, run = threading.Timer, subprocess.run
            # Accelerate actual child termination by 120x: the old 60-second
            # per-call timer expires at .5s; the 600-second total still allows 5s.
            # This is a synthetic boundary replay, not measured 60s CPU work.
            def scaled_run(*args, **kwargs):
                if 'timeout' in kwargs:
                    kwargs['timeout'] /= 120
                return run(*args, **kwargs)
            for operation in ('sample', 'tail'):
                with self.subTest(operation=operation):
                    metrics = dict(seek_count=0, decode_elapsed=0,
                                   decoded_reported_frames=0, peak_temp_disk=0)
                    reader = VideoReader(root / 'synthetic-video',
                        dict(width=2, height=2, duration=1, frame_duration=1), metrics)
                    try:
                        with patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}), \
                             patch('drum_score.video_seek.frame_sync_args', return_value=('-fps_mode', 'passthrough')), \
                             patch('drum_score.video_seek.threading.Timer', side_effect=lambda seconds, *a, **kw: timer(seconds / 120, *a, **kw)), \
                             patch('drum_score.video_seek.subprocess.run', side_effect=scaled_run):
                            if operation == 'sample':
                                pixels = []
                                records = reader.sample_records(.5,
                                    lambda _, image: pixels.append(image.getpixel((0, 0))), verify_motion=True)
                                self.assertEqual(pixels, [(1, 2, 3)])
                                self.assertEqual(records[0]['time_base'], [1, 1])
                            else:
                                record, image = reader.read_record()
                                with image:
                                    self.assertEqual(image.getpixel((0, 0)), (1, 2, 3))
                                self.assertEqual(record['pts'], 0)
                        self.assertGreaterEqual(metrics['decode_elapsed'], .7)
                    finally:
                        reader.close()

    def test_decode_failure_preserves_existing_output_and_charges_attempt_budget(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            video = video_from_image(score_frame(), base)
            before = video.read_bytes()
            preserved = base / 'previous-result'
            preserved.mkdir()
            (preserved / 'score.pdf').write_bytes(b'user result')
            metrics = []
            before_debit = []
            def fail(reader, interval, consume, **kwargs):
                before_debit.append(dict(reader.metrics))
                reader.metrics['decode_elapsed'] += 60
                reader.metrics['seek_count'] += 1
                metrics.append(dict(reader.metrics))
                raise ConversionError('decode_failed', 'Controlled decode deadline.')
            with patch.object(VideoReader, 'sample_records', fail):
                with self.assertRaises(ConversionError):
                    _convert(video, base / 'new-result')
            self.assertEqual(metrics[0]['decode_elapsed'] - before_debit[0]['decode_elapsed'], 60)
            self.assertEqual(metrics[0]['seek_count'] - before_debit[0]['seek_count'], 1)
            self.assertFalse((base / 'new-result').exists())
            self.assertEqual((preserved / 'score.pdf').read_bytes(), b'user result')
            self.assertEqual(video.read_bytes(), before)

    def test_failed_decoders_charge_real_elapsed_and_exhaust_remaining_budget(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            source = video_from_image(score_frame(), base)
            original = source.read_bytes()
            metadata = probe_video(source)
            tools = base / 'tools'
            tools.mkdir()
            marker = base / 'decoder-starts'
            executable = tools / 'ffmpeg'
            executable.write_text('#!' + sys.executable + '\n' +
                'from pathlib import Path\nimport sys,time\n' +
                'if "-h" in sys.argv:\n print("-fps_mode mode"); sys.exit(0)\n' +
                'marker=Path(' + repr(str(marker)) + ')\n' +
                'count=int(marker.read_text()) if marker.exists() else 0\n' +
                'marker.write_text(str(count+1))\n' +
                'time.sleep(.15 if count == 0 else 10)\nsys.exit(1)\n')
            executable.chmod(0o755)
            # Seed only prior usage. New charges are measured by production monotonic time.
            metrics = dict(seek_count=0, decode_elapsed=599.5,
                           decoded_reported_frames=0, peak_temp_disk=0)
            reader = VideoReader(source, metadata, metrics)
            scratch = Path(reader.scratch.name)
            try:
                with patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}):
                    began = time.monotonic()
                    with self.assertRaises(ConversionError):
                        reader.sample_records(.5, lambda *_: self.fail('Failed decoder emitted a frame'))
                    first = metrics['decode_elapsed']
                    self.assertGreaterEqual(first - 599.5, .15)
                    self.assertLess(first, 600)
                    with self.assertRaises(ConversionError):
                        reader.read_record(0)
                    self.assertGreaterEqual(metrics['decode_elapsed'], 600)
                    self.assertLess(time.monotonic() - began, 3)
                    self.assertEqual(marker.read_text(), '2')
                    with self.assertRaises(ConversionError):
                        reader.read_record(0)
                    self.assertEqual(marker.read_text(), '2')
                    self.assertFalse((scratch / 'frame.png').exists())
            finally:
                reader.close()
            self.assertFalse(scratch.exists())
            self.assertEqual(source.read_bytes(), original)

    def test_url_and_local_use_same_original_and_native_capture(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            video = video_from_image(score_frame(), base)
            code, acquired, _ = test_link_input.LinkInputTests().invoke(base / 'url', video)
            self.assertEqual(code, 0, acquired)
            downloaded = Path(acquired['source']['path'])
            self.assertEqual(downloaded.read_bytes(), video.read_bytes())
            remote = convert(downloaded, base / 'remote-result')
            local = convert(video, base / 'local-result')
            self.assertEqual(remote['source']['sha256'], local['source']['sha256'])
            self.assertEqual([(r['sha256'], r['pts'], r['time_base']) for r in remote['samples']],
                             [(r['sha256'], r['pts'], r['time_base']) for r in local['samples']])

    def test_oversized_media_does_not_publish_video_and_can_retry_locally(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            with patch('drum_score.anonymous_backend.MAX_BYTES', 10):
                code, result, _ = test_link_input.LinkInputTests().invoke(task, video)
            self.assertEqual(result['error']['code'], 'download_too_large')
            self.assertFalse(task.exists())
            local = convert(video, task)
            self.assertEqual(local['source']['metadata']['width'], 1280)

    def test_installed_reader_decodes_real_synthetic_pts(self):
        with tempfile.TemporaryDirectory() as d:
            source = video_from_image(score_frame(), Path(d))
            metrics = dict(seek_count=0, decode_elapsed=0, decoded_reported_frames=0, peak_temp_disk=0)
            reader = VideoReader(source, probe_video(source), metrics)
            try:
                record, image = reader.read_record(0)
                image.close()
                self.assertEqual(record['pts'], 0)
                self.assertGreater(record['time_base'][1], 0)
            finally:
                reader.close()

    def test_actual_pts_tail_and_temporary_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            source=video_from_image(score_frame(),Path(d))
            metrics=dict(seek_count=0,decode_elapsed=0,decoded_reported_frames=0,peak_temp_disk=0)
            reader=VideoReader(source,probe_video(source),metrics)
            directory=Path(reader.scratch.name)
            try:
                pts,image=reader.read(.31)
                self.assertAlmostEqual(pts,.5)
                self.assertEqual(image.size,(1280,960))
                pts,_=reader.read()
                self.assertAlmostEqual(pts,1.75)
                self.assertEqual(len(list(directory.iterdir())),1)
                self.assertGreater(metrics['peak_temp_disk'],0)
            finally:
                reader.close()
            self.assertFalse(directory.exists())
