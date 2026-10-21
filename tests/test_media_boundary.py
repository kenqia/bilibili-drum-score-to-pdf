"""Acquisition and decoding protections retained across workflow replacement."""
import json
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
    def test_decode_failure_preserves_existing_output_and_charges_attempt_budget(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            video = video_from_image(score_frame(), base)
            before = video.read_bytes()
            preserved = base / 'previous-result'
            preserved.mkdir()
            (preserved / 'score.pdf').write_bytes(b'user result')
            metrics = []
            def fail(reader, interval, consume, **kwargs):
                reader.metrics['decode_elapsed'] += 60
                reader.metrics['seek_count'] += 1
                metrics.append(dict(reader.metrics))
                raise ConversionError('decode_failed', 'Controlled decode deadline.')
            with patch.object(VideoReader, 'sample_records', fail):
                with self.assertRaises(ConversionError):
                    _convert(video, base / 'new-result')
            self.assertEqual(metrics[0]['decode_elapsed'], 60)
            self.assertEqual(metrics[0]['seek_count'], 1)
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
