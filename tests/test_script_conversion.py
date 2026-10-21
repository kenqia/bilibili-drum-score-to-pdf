"""Shared conversion entry contracts; synthetic sources are not music acceptance."""
from pathlib import Path
import sys
import tempfile
import subprocess
import json
import os
from PIL import Image, ImageDraw, ImageChops
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import drum_score


class ScriptConversion(unittest.TestCase):
    def test_final_progress_failure_does_not_report_failure_after_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'fixed source')
            metadata = {'duration': 1, 'width': 640, 'height': 480}

            def fake_process(_source, output, _metadata, _emit):
                pdf = output / 'score.pdf'
                pdf.write_bytes(b'%PDF-test')
                page = output / 'page-1.png'
                page.write_bytes(b'preview')
                return {'pdf': drum_score.core.artifact(output, pdf),
                        'pages': [drum_score.core.artifact(output, page)]}

            def progress(stage):
                if stage == 'complete':
                    raise RuntimeError('notification failed')

            with mock.patch('drum_score.core.video_seek.probe_video', return_value=metadata), \
                    mock.patch('drum_score.core._process', side_effect=fake_process):
                result = drum_score.convert(source, root / 'result', progress=progress)

            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['program']['name'], 'bilibili-drum-score-to-pdf')
            self.assertEqual(len(result['program']['source_sha256']), 64)
            self.assertTrue((root / 'result' / 'score.pdf').is_file())
            self.assertEqual(json.loads((root / 'result' / 'manifest.json').read_text()), result)

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
            result = drum_score.convert(source, root / 'result', progress=stages.append)
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
