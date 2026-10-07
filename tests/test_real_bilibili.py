"""Lossless real observations of the user's 1080p acceptance video at the CLI."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from PIL import Image
import test_conversion as base_tests

FIXTURES = Path(__file__).parent / 'fixtures/BV1rH4y1R7Rk'


class RealBilibiliTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli

    def pair(self, base, times):
        for index, timestamp in enumerate(times):
            (base / f'{index}.png').write_bytes((FIXTURES / f'{timestamp:.1f}.png').read_bytes())
        source = base / 'observations.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(base / '%d.png'),
                        '-c:v', 'ffv1', str(source)], check=True)
        return source

    def test_connected_blue_line_does_not_split_held_real_rows(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, .5, 1]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result)
            self.assertEqual(len(result['rows']), 3)
            self.assertFalse(result.get('candidate_rows'))
            self.assertTrue(any(observation['cursor_occluded'] for row in result['rows']
                                for observation in row['observations']))
            # A short slice cannot prove all cursor-hidden content.
            self.assertEqual(result['status'], 'waiting')
            self.assertFalse(result['complete'])

    def test_real_129_pixel_scroll_keeps_three_rows_and_appends_fourth(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [124, 124.5, 125]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result)
            self.assertEqual(len(result['rows']), 4, result)
            seam = result['seams'][0]
            self.assertEqual(seam['overlap_rows'], 3)
            self.assertAlmostEqual(seam['vertical_shift'], 129, delta=2)
            self.assertEqual(len(seam['registrations']), 3)
            for registration in seam['registrations']:
                self.assertAlmostEqual(registration['screen_staff_shift'], -129, delta=2)
            for row in result['rows']:
                observed = Image.open(FIXTURES / f'{[124,124.5,125][int(round(row["timestamp"] * 2))]:.1f}.png').convert('RGB').crop(row['bbox'])
                actual = Image.open(base / 'result' / row['original_image']).convert('RGB')
                np.testing.assert_array_equal(np.asarray(actual), np.asarray(observed))

    def test_real_complementary_cursor_evidence_survives_codec_fringe(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, .5, 1, 1.5, 2, 12, 15, 15.5, 114.5]), base / 'result')
            self.assertTrue(result['rows'][0].get('cursor_recoveries'), result.get('issues'))
            self.assertFalse(any(issue['kind'] == 'cursor_occlusion' and issue['position'] == 0
                                 for issue in result['issues']))

    def test_real_playback_note_at_cursor_edge_does_not_split_rows(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [130.5, 131]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result.get('issues'))
            self.assertEqual(len(result['rows']), 4)

    def test_real_cursor_edge_cannot_hide_added_ghost_note(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = self.pair(base, [130.5, 131])
            altered = Image.open(base / '1.png').convert('RGB')
            ImageDraw.Draw(altered).ellipse((829, 758, 833, 762), fill='black')
            altered.save(base / '1.png')
            source = base / 'altered.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(base / '%d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['error']['code'], 'no_overlap')
            self.assertFalse(result['complete'])

    def test_real_scroll_keeps_completed_stationary_cursor_proof(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, 120, 121, 124, 124.5, 125, 126, 127, 128]), base / 'result')
            self.assertEqual(len(result['rows']), 4, result.get('issues'))
            self.assertGreaterEqual(len(result['rows'][1].get('cursor_recoveries', [])), 2,
                                    result.get('issues'))

    def test_real_scroll_under_translucent_watermark_keeps_visible_stem(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, 144, 144.5]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result.get('issues'))
            self.assertEqual(len(result['rows']), 5)
            self.assertGreaterEqual(result['rows'][0]['staff_top'] - result['rows'][0]['bbox'][1], 260,
                                    'the selected real first row must still contain the title and tempo')
            self.assertEqual(result['seams'][-1]['overlap_rows'], 4)
            self.assertAlmostEqual(result['seams'][-1]['vertical_shift'], 129, delta=2)
            backdrops = result['comparison_backdrop']['references']
            self.assertGreaterEqual(len(backdrops), 2)
            self.assertEqual(len({entry['image'] for entry in backdrops}), len(backdrops))
            for entry in backdrops:
                self.assertTrue((base / 'result' / entry['image']).is_file())
            registration = result['seams'][-1]['registrations'][0]
            self.assertIn(registration['left_backdrop'], backdrops)
            self.assertIn(registration['right_backdrop'], backdrops)

    def test_real_watermark_comparison_cannot_hide_deleted_stem(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            self.pair(base, [0, 144, 144.5])
            altered = Image.open(base / '2.png').convert('RGB')
            ImageDraw.Draw(altered).rectangle((1760, 77, 1763, 92), fill=(249, 249, 249))
            altered.save(base / '2.png')
            source = base / 'altered.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(base / '%d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['error']['code'], 'no_overlap')
            self.assertFalse(result['complete'])

    def test_real_watermark_codec_speck_does_not_create_a_new_row(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, 144, 169.5, 170]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result.get('issues'))
            self.assertEqual(len(result['rows']), 7)

    def test_real_half_pixel_staff_shift_does_not_compare_next_rows_beam(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, 144, 169.5, 177, 177.5, 179.5, 180]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result.get('issues'))
            self.assertEqual(len(result['rows']), 8)
            self.assertLessEqual(result['rows'][-1]['bbox'][3] - result['rows'][-1]['bbox'][1], 210,
                                 'the last printed crop must exclude the next row accent and beams')

    def test_real_watermark_codec_rule_keeps_connected_faint_ghost_note(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            self.pair(base, [0, 144, 169.5, 170])
            altered = Image.open(base / '3.png').convert('RGB')
            ImageDraw.Draw(altered).ellipse((1551, 61, 1555, 65), fill=(209, 209, 209))
            altered.save(base / '3.png')
            source = base / 'altered.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(base / '%d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['error']['code'], 'no_overlap')
            self.assertFalse(result['complete'])

    def test_real_183_second_scroll_keeps_watermark_dimmed_beams(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, 144, 169.5, 177, 177.5, 179.5, 180, 182.5, 183]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result.get('issues'))
            self.assertEqual(result['seams'][-1]['overlap_rows'], 4)

    def test_real_199_second_scroll_keeps_dimmed_small_stem(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, 144, 169.5, 177, 177.5, 180, 183, 198.5, 199]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result.get('issues'))
            self.assertEqual(result['seams'][-1]['overlap_rows'], 4)

    def test_real_played_blue_note_behind_cursor_does_not_split_row(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, 144, 169.5, 177, 177.5, 180, 183, 198.5, 199, 235.5, 236]), base / 'result')
            self.assertNotEqual(result.get('error', {}).get('code'), 'no_overlap', result.get('issues'))
            self.assertEqual(len(result['rows']), 12)
            self.assertFalse(result['complete'])

    def test_real_full_hold_cursor_evidence_keeps_native_blue_rest(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            _, result = self.run_cli(self.pair(base, [0, .5, 1, 1.5, 2, 12, 15, 15.5, 28, 28.5, 40, 43.5, 114.5]), base / 'result')
            self.assertTrue(result['rows'][0].get('cursor_recoveries'), result.get('issues'))
            self.assertFalse(any(issue['kind'] == 'cursor_occlusion' and issue['position'] == 0
                                 for issue in result['issues']))

    def test_real_watermark_fringe_rule_cannot_hide_three_pixel_gray_stroke(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            self.pair(base, [0, 144, 169.5, 177, 177.5, 180, 183, 198.5, 199])
            altered = Image.open(base / '8.png').convert('RGB')
            ImageDraw.Draw(altered).line((300, 78, 302, 78), fill=(223, 223, 223))
            altered.save(base / '8.png')
            source = base / 'altered.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(base / '%d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['error']['code'], 'no_overlap')
            self.assertFalse(result['complete'])
