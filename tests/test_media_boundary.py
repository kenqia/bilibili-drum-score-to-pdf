"""Acquisition and decoding protections retained across workflow replacement."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from score_fixtures import score_frame, video_from_image
import test_link_input
import score_workflow
from video_seek import ConversionError, VideoReader, probe_video

class MediaBoundaryTests(unittest.TestCase):
    def test_failed_longshot_retry_keeps_decode_budget_and_previous_materials(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            score_workflow.prepare(video, task)
            original = score_workflow.stitch(task)
            before = score_workflow.load(task)
            def fail(reader, interval, consume):
                reader.metrics['decode_elapsed'] += 60
                reader.metrics['seek_count'] += 1
                raise ConversionError('decode_failed', 'Controlled decode deadline.')
            with patch.object(VideoReader, 'sample_records', fail):
                with self.assertRaises(ConversionError):
                    score_workflow.stitch(task)
            after = score_workflow.load(task)
            self.assertEqual(after['longshot'], original)
            self.assertEqual(after['regions'], before['regions'])
            self.assertEqual(after['metrics']['decode_elapsed'], before['metrics']['decode_elapsed'] + 60)
            self.assertEqual(after['metrics']['seek_count'], before['metrics']['seek_count'] + 1)

    def test_url_and_local_use_same_original_and_native_capture(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); video=video_from_image(score_frame(),base)
            code,record,_=test_link_input.LinkInputTests().invoke(base/'url',video)
            self.assertEqual(code,0,record)
            local=score_workflow.prepare(video,base/'local')
            self.assertEqual(record['source']['sha256'],local['source']['sha256'])
            first=score_workflow.capture(base/'url',.31)
            second=score_workflow.capture(base/'local',.31)
            self.assertEqual(first['sha256'],second['sha256'])
            self.assertEqual(first['pts'],second['pts'])

    def test_oversized_media_does_not_publish_video_and_can_retry_locally(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); video=video_from_image(score_frame(),base); task=base/'task'
            with patch('anonymous_backend.MAX_BYTES',10):
                code,r,logs=test_link_input.LinkInputTests().invoke(task,video)
            self.assertEqual(r['error']['code'],'download_too_large')
            self.assertEqual({p.name for p in task.iterdir()},{'manifest.json'})
            self.assertFalse(list(base.glob('task-source-*')))
            score_workflow.prepare(video,task)
            self.assertEqual(json.loads((task/'record.json').read_text())['source']['width'],1280)

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
