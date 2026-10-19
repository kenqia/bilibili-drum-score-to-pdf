"""Synthetic cross-host boundaries. No host credentials or real task data."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'
sys.path.insert(0, str(SCRIPTS))
import score_continuity
import video_seek
import host_check


class SeekCompatibility(unittest.TestCase):
    def tearDown(self):
        video_seek.frame_sync_args.cache_clear()

    def test_capability_matrix_and_bounded_failure_fallback(self):
        for help_text, expected in ((b' -vsync sync\n', ('-vsync', '0')),
                                    (b' -fps_mode mode\n', ('-fps_mode', 'passthrough'))):
            with self.subTest(help=help_text):
                video_seek.frame_sync_args.cache_clear()
                result = subprocess.CompletedProcess([], 0, b'', help_text)
                with patch.object(video_seek.subprocess, 'run', return_value=result) as run:
                    self.assertEqual(video_seek.frame_sync_args(), expected)
                    self.assertEqual(video_seek.frame_sync_args(), expected)
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.kwargs['timeout'], 5)
        video_seek.frame_sync_args.cache_clear()
        with patch.object(video_seek.subprocess, 'run', side_effect=OSError('synthetic')):
            self.assertEqual(video_seek.frame_sync_args(), ('-vsync', '0'))

    def test_scan_and_read_use_identical_selected_options(self):
        from io import BytesIO
        for options in (('-vsync', '0'), ('-fps_mode', 'passthrough')):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                metrics = dict(seek_count=0, decode_elapsed=0, decoded_reported_frames=0, peak_temp_disk=0)
                reader = video_seek.VideoReader(Path(temporary) / 'fixture',
                    dict(duration=1, width=2, height=2, frame_duration=1), metrics)
                self.addCleanup(reader.close)
                commands = []
                def run(command, **kwargs):
                    commands.append(command)
                    Image.new('RGB', (2, 2)).save(Path(reader.scratch.name) / 'frame.png')
                    return subprocess.CompletedProcess(command, 0, b'', b'config in time_base: 1/1\npts: 0\n')
                from unittest.mock import MagicMock
                process = MagicMock()
                process.stdout = BytesIO(bytes(12))
                process.stderr = BytesIO(b'config in time_base: 1/1\npts: 0\n')
                process.wait.return_value = 0
                process.poll.return_value = 0
                def popen(command, **kwargs):
                    commands.append(command)
                    return process
                with patch.object(video_seek, 'frame_sync_args', return_value=options), \
                     patch.object(video_seek.subprocess, 'run', side_effect=run), \
                     patch.object(video_seek.subprocess, 'Popen', side_effect=popen):
                    position, image = reader.read_record(0)
                    image.close()
                    self.assertEqual(position['pts'], 0)
                    frames = list(reader.scan())
                    self.assertEqual(frames[0][0]['pts'], 0)
                    frames[0][1].close()
                for command in commands:
                    index = command.index(options[0])
                    self.assertEqual(tuple(command[index:index + 2]), options)


class MixedAnchors(unittest.TestCase):
    def test_partial_fallback_numbers_report_unknown_instead_of_mixed_max(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new('RGB', (200, 200), 'white').save(root / 'source.png')
            rows = [dict(kind='system', bbox=[0, i*50, 200, i*50+40], staff_spacing=5) for i in range(3)]
            observations = {name: dict(regions=rows, risks=[], anchors=[{'start_bar': v} for v in values])
                            for name, values in (('old', [None, 7, 11]), ('new', [7, 11, 15]))}
            record = dict(row_manifest=dict(observations=observations), captures=[], continuity_reviews=[])
            with patch.object(score_continuity.state, 'artifact', return_value=root / 'source.png'), \
                 patch.object(score_continuity.row_anchors, 'fallback_allowed', side_effect=[True, False]), \
                 patch.object(score_continuity.row_anchors, 'missing', return_value=[]), \
                 patch.object(score_continuity.score_geometry, 'same_observation', return_value=False), \
                 patch.object(score_continuity.score_geometry, 'row_signature', return_value=None), \
                 patch.object(score_continuity.score_geometry, 'signature', return_value=None), \
                 patch.object(score_continuity.score_geometry, 'same_row', return_value=True):
                result = score_continuity.compare(root, record, {'id': 'old'}, {'id': 'new'})
            self.assertFalse(result['proved'])
            self.assertIsNone(result['new_complete_rows'])
            self.assertEqual(result['anchors']['previous'], [None, 7, 11])
            self.assertTrue(result['visual_review_needed'])

    def test_numbered_overlap_excludes_a_residual_row_and_rejects_nonincreasing_numbers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new('RGB', (200, 200), 'white').save(root / 'source.png')
            rows = [dict(kind='system', bbox=[0, i*50, 200, i*50+40], staff_spacing=5) for i in range(3)]
            old = dict(regions=rows, risks=[], anchors=[{'start_bar': v} for v in [1, 7, 11]])
            new = dict(regions=rows, risks=[{'bbox': rows[2]['bbox']}],
                       anchors=[{'start_bar': v} for v in [7, 11, 15]])
            record = dict(row_manifest=dict(observations={'old': old, 'new': new}), continuity_reviews=[], captures=[])
            shots = [{'id': name} for name in ('old', 'new')]
            with patch.object(score_continuity.state, 'artifact', return_value=root / 'source.png'), \
                 patch.object(score_continuity.row_anchors, 'missing', return_value=[]), \
                 patch.object(score_continuity.score_geometry, 'same_observation', return_value=False), \
                 patch.object(score_continuity.score_geometry, 'row_signature', return_value=None), \
                 patch.object(score_continuity.score_geometry, 'signature', return_value=None), \
                 patch.object(score_continuity.score_geometry, 'same_row', return_value=True):
                result = score_continuity.compare(root, record, *shots)
                self.assertTrue(result['proved'])
                self.assertEqual(result['new_complete_rows'], 0)
                new['anchors'][2]['start_bar'] = 10
                result = score_continuity.compare(root, record, *shots)
                self.assertFalse(result['proved'])
                self.assertEqual(result['reason'], 'row_anchor_conflict')


class HostDiscovery(unittest.TestCase):
    def test_unreadable_unrelated_skill_warns_and_valid_target_is_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('bad', 'good'):
                (root / name).mkdir()
                (root / name / 'SKILL.md').write_text('name: bilibili-drum-score-to-pdf', encoding='utf-8')
            (root / 'auth.json').write_text('synthetic-do-not-read', encoding='utf-8')
            original = Path.read_text
            def read(path, *args, **kwargs):
                self.assertNotEqual(path.name, 'auth.json')
                if path.parent.name == 'bad':
                    raise PermissionError('synthetic private path must not be printed')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'read_text', read):
                result = host_check.check([root])
            self.assertEqual(result['discovery'][0]['entries'], [str(root / 'good/SKILL.md')])
            self.assertEqual(result['warnings'][0]['code'], 'skill_entry_unreadable')
            self.assertEqual(result['decode_probe']['status'], 'not_run')
            self.assertEqual(result['runtime_ready'], result['prerequisites_ready'])

    def test_explicit_function_probe_uses_real_synthetic_pts(self):
        result = host_check.decode_probe()
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['pts'], 0)
        self.assertGreater(result['time_base'][1], 0)


if __name__ == '__main__':
    unittest.main()
