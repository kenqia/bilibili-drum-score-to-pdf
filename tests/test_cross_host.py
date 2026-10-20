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

    def test_native_read_uses_selected_frame_sync_options(self):
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
                with patch.object(video_seek, 'frame_sync_args', return_value=options), \
                     patch.object(video_seek.subprocess, 'run', side_effect=run):
                    position, image = reader.read_record(0)
                    image.close()
                    self.assertEqual(position['pts'], 0)
                for command in commands:
                    index = command.index(options[0])
                    self.assertEqual(tuple(command[index:index + 2]), options)




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
