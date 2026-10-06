"""Edge classification through the agreed conversion CLI."""
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from test_ordered_conversion import window, sequence_video, FONT
import test_conversion as base_tests


def card(text='Fixture title'):
    image = Image.new('RGB', (1280, 960), '#303030')
    ImageDraw.Draw(image).text((420, 400), text, font=ImageFont.truetype(FONT, 40), fill='white')
    return image


class EdgeCardTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli

    def test_title_and_end_cards_keep_complete_score_and_actual_end(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([card(), window('ABC'), card('End credits')], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['rows']), 3)
            self.assertEqual(result['boundaries']['end']['timestamp'], 5.75)
            self.assertEqual([x['edge'] for x in result['ignored_edges']], ['start', 'end'])
            self.assertEqual(result['ignored_edges'][0]['start_timestamp'], 0)
            self.assertEqual(result['ignored_edges'][1]['end_timestamp'], 5.75)
            for edge in result['ignored_edges']:
                for item in edge['observations']:
                    self.assertTrue((base / 'result' / item['image']).exists())
            self.assertTrue((base / 'result/score.pdf').exists())

    def test_non_score_preroll_and_postroll_do_not_become_missing_score(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            plain = Image.new('RGB', (1280, 960), '#303030')
            source = sequence_video([plain, window('ABC'), plain], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['rows']), 3)
            self.assertEqual([edge['edge'] for edge in result['ignored_edges']], ['start', 'end'])
            self.assertEqual(result['ignored_edges'][0]['start_timestamp'], 0)
            self.assertEqual(result['boundaries']['end']['timestamp'], 5.75)
            self.assertTrue((base / 'result/score.pdf').exists())

    def test_middle_card_and_uncertain_edges_stay_waiting(self):
        partial = card()
        for y in (220, 232, 244):
            ImageDraw.Draw(partial).line((400, y, 500, y), fill='white', width=2)
        faint = Image.new('RGB', (1280, 960), '#303030')
        ImageDraw.Draw(faint).line((100, 220, 1180, 220), fill='#383838', width=2)
        scenarios = [
            [faint, window('ABC')],
            [Image.new('RGB', (1280, 960), '#303030'), window('ABC', partial_top=True)],
            [window('ABC', partial_bottom=True), Image.new('RGB', (1280, 960), '#303030')],
            [window('ABC'), card(), window('ABC')],
            [partial, window('ABC')],
            [window('ABC'), partial],
            [window('ABC', partial_bottom=True), card()],
            [card().filter(ImageFilter.GaussianBlur(5)), window('ABC')],
            [window('ABC'), window('ABC').filter(ImageFilter.GaussianBlur(3))],
            [window('ABC'), Image.new('RGB', (1280, 960), '#303030'), window('ABC')],
        ]
        for index, images in enumerate(scenarios):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                source = sequence_video(images, base)
                _, result = self.run_cli(source, base / 'result')
                self.assertEqual(result['status'], 'waiting', result)
                self.assertFalse(result['complete'])
                self.assertFalse((base / 'result/score.pdf').exists())

    def test_cards_only_cannot_succeed(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            source = sequence_video([Image.new('RGB', (1280, 960), '#303030'), card('End credits')], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertNotEqual(result['status'], 'success', result)
            self.assertFalse((base / 'result/score.pdf').exists())
