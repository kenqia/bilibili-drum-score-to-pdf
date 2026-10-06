"""Central obstruction recovery through the confirmed conversion CLI seam."""
from pathlib import Path
import tempfile
import subprocess
import unittest
import numpy as np
from PIL import Image, ImageDraw
import test_conversion as base_tests
from test_cursor_quality import cursor_window


def sequence_video(windows, base):
    for index, image in enumerate(windows):
        image.save(base / f'window-{index:02d}.png')
    source = base / 'sequence.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '1/2', '-i',
                    str(base / 'window-%02d.png'), '-r', '4', '-crf', '0',
                    '-pix_fmt', 'yuv420p', str(source)], check=True)
    return source


def clean():
    image = cursor_window()
    ImageDraw.Draw(image).ellipse((700, 236, 704, 240), fill="black")
    return image


def blocked(x):
    image = clean()
    ImageDraw.Draw(image).rectangle((x, 40, x + 240, 910), fill='#303030')
    return image


class CentralObstructionTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli

    def test_complementary_split_white_windows_recover_only_actual_clean_rows(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([clean(), blocked(420), blocked(760), clean()], base)
            run, result = self.run_cli(source, base / 'result')
            self.assertEqual(run.returncode, 0, result)
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(len(result['rows']), 3)
            recovery = next(r for r in result['recoveries'] if r['policy'] == 'complementary_split_white_windows_then_actual_clean_rows')
            self.assertTrue(recovery['coverage_complete'])
            self.assertEqual(recovery['row_ids'], ['row-0001', 'row-0002', 'row-0003'])
            for observation in recovery['observations']:
                self.assertTrue((base / 'result' / observation['image']).exists())
                self.assertEqual(observation['registration']['dx'], 0)
                self.assertEqual(len(observation['occluded_bbox']), 4)
            row = result['rows'][0]
            pixels = np.asarray(Image.open(base / 'result' / row['original_image']))
            x, y, _, _ = row['bbox']
            self.assertLess(int(pixels[238-y, 702-x].min()), 40, 'known small mark must remain')
            blue = result['rows'][1]
            pixels = np.asarray(Image.open(base / 'result' / blue['original_image']))
            x, y, _, _ = blue['bbox']
            self.assertGreater(int(pixels[409-y, 900-x, 2]), int(pixels[409-y, 900-x, 0]) + 80)

    def test_persistent_or_reappearing_obstruction_cannot_supply_missing_pixels(self):
        for images in ([clean(), blocked(420), blocked(420), clean()],
                       [clean(), blocked(420), blocked(420)]):
            with self.subTest(length=len(images)), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                source = sequence_video(images, base)
                run, result = self.run_cli(source, base / 'result')
                self.assertEqual(run.returncode, 2)
                self.assertEqual(result['status'], 'waiting', result)
                self.assertFalse(result['complete'])
                self.assertFalse((base / 'result/score.pdf').exists())
                self.assertFalse(result['recoveries'])

    def test_small_visible_change_during_complementary_observation_is_not_erased(self):
        changed = blocked(760)
        ImageDraw.Draw(changed).ellipse((700, 253, 704, 257), fill='black')
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([clean(), blocked(420), changed, clean()], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'waiting', result)
            self.assertFalse(result['complete'])
            self.assertFalse(result['recoveries'])

    def test_later_repeat_with_new_row_identity_does_not_resolve_previous_obstruction(self):
        from test_ordered_conversion import window
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([clean(), blocked(420), blocked(760), window('CDA')], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'waiting', result)
            self.assertFalse(result['complete'])
            self.assertFalse(result['recoveries'])

    def test_never_clean_split_window_reports_waiting_with_original_evidence(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([blocked(420), blocked(760)], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'failed', result)
            self.assertFalse(result['complete'])
            self.assertEqual(result['error']['code'], 'central_obstruction')
