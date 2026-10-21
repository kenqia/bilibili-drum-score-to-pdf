"""Shared conversion entry contracts; synthetic sources are not music acceptance."""
from pathlib import Path
import sys
import tempfile
import subprocess
import json
import os
import time
from PIL import Image, ImageDraw, ImageChops
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import drum_score


class ScriptConversion(unittest.TestCase):
    def test_page_balancing_moves_whole_groups_to_sparse_final_page(self):
        from drum_score.imaging import _page_strips
        groups = [(0, 600), (600, 1200), (1200, 1800), (1800, 2400), (2400, 2700)]
        strips = _page_strips(groups, 2000)
        self.assertEqual(strips, [(0, 1200), (1200, 2700)])
        self.assertEqual(_page_strips([(0, 2200)], 2200), [(0, 2200)])
        self.assertEqual(_page_strips(groups, 3000), [(0, 2700)])

    def test_source_size_limit_is_checked_before_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'large.mp4'
            source.write_bytes(b'12345')
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result', limits={'input_bytes': 4})
            self.assertEqual(caught.exception.code, 'resource_limit')
            self.assertFalse((root / 'result').exists())

    def test_memory_and_temporary_disk_budgets_fail_without_partial_publication(self):
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root)
            before = source.read_bytes()
            for limit in ('rss_bytes', 'temp_bytes'):
                with self.subTest(limit=limit):
                    with self.assertRaises(drum_score.ConversionError) as caught:
                        drum_score.convert(source, root / limit, limits={limit: 1})
                    self.assertEqual(caught.exception.code, 'resource_limit')
                    self.assertFalse((root / limit).exists())
                    self.assertEqual(source.read_bytes(), before)
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_total_deadline_stops_child_decoder_and_cleans_owned_temporary_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'not decoded by the waiting fixture')
            tools = root / 'bin'
            tools.mkdir()
            decoder = tools / 'ffprobe'
            decoder.write_text('#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(root / 'decoder-pid')) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
            decoder.chmod(0o755)
            from unittest.mock import patch
            with patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}):
                with self.assertRaises(drum_score.ConversionError) as caught:
                    drum_score.convert(source, root / 'result', limits={'wall_seconds': .5})
            self.assertEqual(caught.exception.code, 'resource_limit')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(list(root.glob('.drum-score-*')), [])
            self.assertTrue((root / 'decoder-pid').exists())
            pid = int((root / 'decoder-pid').read_text())
            if Path('/proc').is_dir():
                state = Path('/proc') / str(pid) / 'stat'
                self.assertTrue(not state.exists() or state.read_text().split(') ')[1].startswith('Z'))

    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process recovery contract')
    def test_abnormal_conversion_worker_stops_its_independent_session_descendant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'worker exit fixture')
            binaries = root / 'bin'
            binaries.mkdir()
            decoder = binaries / 'ffprobe'
            decoder.write_text('#!/usr/bin/env python3\nimport os,time,signal\nfrom pathlib import Path\nos.setsid()\nPath(' + repr(str(root / 'decoder-pid')) + ').write_text(str(os.getpid()))\ntime.sleep(.2)\nos.kill(os.getppid(),signal.SIGKILL)\ntime.sleep(30)\n')
            decoder.chmod(0o755)
            from unittest.mock import patch
            with patch.dict(os.environ, {'PATH': str(binaries) + os.pathsep + os.environ['PATH']}):
                with self.assertRaises(drum_score.ConversionError) as caught:
                    drum_score.convert(source, root / 'result')
            self.assertEqual(caught.exception.code, 'conversion_failed')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(list(root.glob('.drum-score-*')), [])
            pid = int((root / 'decoder-pid').read_text())
            state = Path('/proc') / str(pid) / 'stat'
            self.assertTrue(not state.exists() or state.read_text().split(') ')[1].startswith('Z'))

    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process recovery contract')
    def test_killed_caller_leaves_no_active_decoder_or_task_temporary_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'waiting decoder fixture')
            binaries = root / 'bin'
            binaries.mkdir()
            decoder = binaries / 'ffprobe'
            decoder.write_text('#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(root / 'decoder-pid')) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
            decoder.chmod(0o755)
            process = subprocess.Popen([sys.executable, '-m', 'drum_score', str(source),
                '--output', str(root / 'result')], env={**os.environ,
                'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
                'PYTHONPATH': os.pathsep.join(sys.path)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not (root / 'decoder-pid').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / 'decoder-pid').exists())
                process.kill()
                process.wait(timeout=5)
                deadline = time.monotonic() + 5
                while list(root.glob('.drum-score-*')) and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(list(root.glob('.drum-score-*')), [])
                pid = int((root / 'decoder-pid').read_text())
                state = Path('/proc') / str(pid) / 'stat'
                self.assertTrue(not state.exists() or state.read_text().split(') ')[1].startswith('Z'))
                self.assertFalse((root / 'result').exists())
                self.assertEqual(source.read_bytes(), b'waiting decoder fixture')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()

    def test_cancelled_conversion_does_not_publish_or_leave_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 520), 'white')
            draw = ImageDraw.Draw(image)
            for top in (120, 300):
                for line in range(5):
                    draw.line((25, top + 8 * line, 615, top + 8 * line), fill='black')
            image.save(root / 'frame.png')
            source = root / 'video.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'frame.png'),
                '-t', '2', '-r', '4', '-c:v', 'ffv1', str(source)], check=True)
            cancelled = False
            def progress(stage):
                nonlocal cancelled
                if stage == 'sampling':
                    cancelled = True
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result', progress=progress, cancel=lambda: cancelled)
            self.assertEqual(caught.exception.code, 'cancelled')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_invalid_input_never_publishes_or_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'invalid.mp4'
            source.write_bytes(b'not a video')
            output = root / 'result'
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, output)
            self.assertEqual(caught.exception.code, 'invalid_input')
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), b'not a video')
            output.mkdir()
            marker = output / 'mine'
            marker.write_bytes(b'existing')
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, output)
            self.assertEqual(caught.exception.code, 'output_exists')
            self.assertEqual(marker.read_bytes(), b'existing')

    def test_cli_errors_are_json_without_private_path_or_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.run([sys.executable, '-m', 'drum_score',
                str(root / 'private-name.mp4'), '--output', str(root / 'result')],
                env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            error = json.loads(result.stdout)
            self.assertEqual(error['error']['code'], 'invalid_input')
            self.assertNotIn('private-name', result.stdout + result.stderr)
            self.assertFalse((root / 'result').exists())

    def test_public_link_validation_retains_partition_and_rejects_nonpublic_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for address in ['http://www.bilibili.com/video/BV1rH4y1R7Rk',
                    'https://127.0.0.1/video/BV1rH4y1R7Rk',
                    'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=0']:
                with self.subTest(address=address), self.assertRaises(drum_score.ConversionError) as caught:
                    drum_score.convert(address, root / 'result')
                self.assertEqual(caught.exception.code, 'invalid_bilibili_url')
                self.assertFalse((root / 'result').exists())

    def test_static_video_produces_complete_a4_pages_and_actual_source_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 520), 'white')
            draw = ImageDraw.Draw(image)
            draw.text((30, 20), 'TITLE / AUTHOR / 120 BPM', fill='black')
            for top in (120, 300):
                for line in range(5):
                    draw.line((25, top + 8 * line, 615, top + 8 * line), fill='black')
                draw.ellipse((90, top + 10, 105, top + 20), fill=(220, 20, 30))
                draw.rectangle((200, top - 20, 202, top + 20), fill='black')
            image.save(root / 'native.png')
            source = root / 'native.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'native.png'),
                '-t', '2', '-r', '4', '-c:v', 'ffv1', str(source)], check=True)
            stages = []
            def progress(stage):
                stages.append(stage)
                if stage == 'complete':
                    raise RuntimeError('SYNTHETIC observer error after publication')
            result = drum_score.convert(source, root / 'result', progress=progress)
            self.assertEqual(result['status'], 'complete')
            self.assertFalse(result['reliable'])
            self.assertGreaterEqual(len(result['warnings']), 1)
            self.assertEqual(stages[-1], 'complete')
            output = root / 'result'
            with Image.open(output / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, image.size)
                self.assertEqual(actual.getpixel((97, 135)), (220, 20, 30))
            self.assertTrue((output / result['pdf']['path']).is_file())
            subprocess.run(['pdfimages', '-png', str(output / result['pdf']['path']), str(root / 'embedded')],
                           check=True, capture_output=True)
            with Image.open(root / 'embedded-000.png') as embedded:
                self.assertEqual(embedded.size, image.size)
                self.assertIsNone(ImageChops.difference(embedded.convert('RGB'), image).getbbox())
            self.assertGreater(len(result['pages']), 0)
            for page in result['pages']:
                with Image.open(output / page['path']) as preview:
                    self.assertAlmostEqual(preview.width / preview.height, 210 / 297, places=2)
            self.assertTrue(all(isinstance(frame['pts'], int) and len(frame['time_base']) == 2
                                and len(frame['sha256']) == 64 for frame in result['samples']))
            self.assertEqual(len(result['source']['sha256']), 64)
            self.assertEqual(result['program']['name'], 'bilibili-drum-score-to-pdf')
            self.assertEqual(len(result['program']['source_sha256']), 64)
            self.assertEqual(result['samples'][0]['timestamp'], 0)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(manifest, result)

    def test_scrolling_preserves_every_position_and_full_endpoints(self):
        from test_longshot_cli import scrolling_video
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, sheet = scrolling_video(root)
            result = drum_score.convert(video, root / 'result')
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, sheet.size)
                for row in range(7):
                    self.assertLess(min(actual.getpixel((50, 197 + row * 180))), 80, row)
            self.assertEqual(result['staff_count'], 7)
            self.assertEqual(result['samples'][0]['timestamp'], 0)
            self.assertEqual(result['samples'][-1]['timestamp'], 23)
            self.assertEqual(result['page_regions'][0][0], 0)
            self.assertEqual(result['page_regions'][-1][1], 1420)
            sheet.close()

    def test_detected_page_flip_does_not_silently_publish_only_first_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(4):
                image = Image.new('RGB', (640, 520), 'white')
                draw = ImageDraw.Draw(image)
                for top in (120, 300):
                    for line in range(5):
                        draw.line((25, top + 8 * line, 615, top + 8 * line), fill='black')
                    for note in range(6):
                        x = 45 + note * 30 + (0 if index < 2 else 250)
                        draw.ellipse((x, top + 10, x + 10, top + 20), fill='black')
                        draw.line((x + 10, top - 30, x + 10, top + 20), fill='black', width=2)
                image.save(root / f'flip-{index}.png')
            source = root / 'flip.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '1', '-i', str(root / 'flip-%d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result')
            self.assertEqual(caught.exception.code, 'discontinuity')
            self.assertFalse((root / 'result').exists())

    def test_identical_music_at_later_scroll_positions_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 1420), 'white')
            draw = ImageDraw.Draw(sheet)
            for row in range(7):
                top = 140 + row * 180
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                for x in (95, 195, 295, 395):
                    draw.ellipse((x, top + 10, x + 10, top + 20), fill='black')
                    draw.line((x + 10, top - 25, x + 10, top + 17), fill='black', width=2)
            for index, shift in enumerate(range(0, 901, 45)):
                sheet.crop((0, shift, 640, shift + 520)).save(root / f'repeat-{index:03d}.png')
            source = root / 'repeat.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(root / 'repeat-%03d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 7)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, (640, 1420))
                self.assertIsNone(ImageChops.difference(actual.convert('RGB'), sheet).getbbox())

    def test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 1420), 'white')
            draw = ImageDraw.Draw(sheet)
            for row in range(7):
                top = 140 + row * 180
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                for x in (95, 195, 295, 395):
                    draw.ellipse((x, top + 10, x + 10, top + 20), fill='black')
                    draw.line((x + 10, top - 25, x + 10, top + 17), fill='black', width=2)
                draw.text((30, top - 15), str(row + 1), fill='black')
            # Each sampled half-second moves one system, with 340px of actual
            # overlap. Tiny measure numbers distinguish otherwise repeated music.
            for index, shift in enumerate(range(0, 901, 12)):
                with sheet.crop((0, shift, 640, shift + 520)) as frame:
                    frame.save(root / f'fast-repeat-{index:03d}.png')
            source = root / 'fast-repeat.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '30',
                            '-i', str(root / 'fast-repeat-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 7)
            self.assertEqual([placement['offset'] for placement in result['placements']],
                             [0, 180, 360, 540, 720, 900])
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, sheet.size)
                self.assertIsNone(ImageChops.difference(actual.convert('RGB'), sheet).getbbox())
            self.assertEqual(result['page_regions'][-1][1], 1420)

    def test_no_safe_gap_preserves_tall_group_without_hard_cut(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 2200), 'white')
            draw = ImageDraw.Draw(image)
            for top in (120, 1900):
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
            # Known colored mark connects the two systems. It must not be cut
            # just because its luminance is lighter than the staff threshold.
            draw.line((10, 0, 10, 2199), fill=(255, 210, 0), width=2)
            image.save(root / 'group.png')
            source = root / 'group.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'group.png'),
                            '-t', '2', '-r', '1', '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 2)
            self.assertEqual(result['page_regions'], [[0, 2200]])
            self.assertEqual(len(result['pages']), 1)
            subprocess.run(['pdfimages', '-png', str(root / 'result' / result['pdf']['path']),
                            str(root / 'group-embedded')], check=True, capture_output=True)
            with Image.open(root / 'group-embedded-000.png') as embedded:
                self.assertEqual(embedded.size, image.size)
                self.assertIsNone(ImageChops.difference(embedded.convert('RGB'), image).getbbox())
