"""Conservative recovery regressions observed through the conversion CLI."""
from pathlib import Path
import json
import tempfile
import unittest
from PIL import ImageDraw, ImageFilter
import test_conversion as base_tests
import test_resume_conversion as resume_tests
from test_ordered_conversion import window, sequence_video


class ReviewRegressionTests(unittest.TestCase):
    run_cli = base_tests.ConversionTests.run_cli
    invoke = resume_tests.ResumeTests.invoke

    def test_small_notation_changes_require_confirmation(self):
        for mark in ('dot', 'stem', 'blue', 'staff_dot'):
            with self.subTest(mark=mark), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                original = window('ABC')
                changed = original.copy()
                draw = ImageDraw.Draw(changed)
                if mark == 'stem':
                    draw.line((750, 204, 750, 239), fill='black', width=2)
                elif mark == 'staff_dot':
                    draw.ellipse((700, 230, 704, 234), fill='black')
                else:
                    draw.ellipse((700, 236, 704, 240), fill=(40, 110, 220) if mark == 'blue' else 'black')
                source = sequence_video([original, changed], base)
                _, result = self.run_cli(source, base / 'result')
                self.assertEqual(result['status'], 'waiting', result)
                self.assertFalse(result['complete'])
                self.assertTrue(result['issues'])
                self.assertFalse((base / 'result/score.pdf').exists())

    def test_accepted_blur_gap_replays_into_the_next_unconfirmed_transition(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            clear = window('ABC')
            source = sequence_video([clear, clear.filter(ImageFilter.GaussianBlur(3)), window('DEF')], base)
            output = base / 'result'
            _, waiting = self.run_cli(source, output)
            answers = base / 'answers.json'
            answers.write_text(json.dumps({waiting['issues'][0]['id']: {'action': 'accept_missing'}}))
            _, resumed = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(resumed['status'], 'waiting', resumed)
            self.assertEqual(resumed['issues'][0]['timestamp'], 4.0)
            self.assertEqual(resumed['issues'][0]['kind'], 'no_overlap')
            self.assertEqual(len(resumed['gaps']), 1)
            self.assertFalse(resumed['complete'])
            answers.write_text(json.dumps({resumed['issues'][0]['id']: {'action': 'confirm_join'}}))
            _, completed = self.invoke('--resume', output, '--answers', answers)
            self.assertEqual(completed['status'], 'success', completed)
            self.assertFalse(completed['complete'])
            self.assertEqual(len(completed['rows']), 6)
            self.assertEqual(completed['boundaries']['end']['timestamp'], 5.75)
            self.assertEqual(completed['gaps'][0]['position'], 3)
            self.assertEqual(len(completed['unreadable_observations']), 4)
            for item in completed['unreadable_observations']:
                self.assertTrue((output / item['image']).exists())

    def test_clear_bracket_recovers_only_the_same_observed_window(self):
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            clear = window('ABC')
            source = sequence_video([clear, clear.filter(ImageFilter.GaussianBlur(3)), clear], base)
            _, result = self.run_cli(source, base / 'result')
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['rows']), 3)
            self.assertEqual(result['boundaries']['end']['timestamp'], 5.75)
            recoveries = result['recoveries']
            self.assertEqual(len(recoveries), 1)
            self.assertEqual([item['timestamp'] for item in recoveries[0]['observations']], [2.0, 2.5, 3.0, 3.5])
            for item in recoveries[0]['observations']:
                self.assertTrue((base / 'result' / item['image']).exists())

    def test_tiny_hidden_dot_and_severe_blur_cannot_be_declared_recovered(self):
        for radius in (6, 3):
            with self.subTest(radius=radius), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                clear = window('ABC')
                changed = clear.copy()
                ImageDraw.Draw(changed).ellipse((700, 236, 702, 238), fill='black')
                source = sequence_video([clear, changed.filter(ImageFilter.GaussianBlur(radius)), clear], base)
                _, result = self.run_cli(source, base / 'result')
                self.assertEqual(result['status'], 'waiting', result)
                self.assertFalse(result['complete'])
                self.assertFalse((base / 'result/score.pdf').exists())

    def test_unproven_blur_transitions_and_boundaries_stay_waiting(self):
        clear = window('ABC')
        changed = clear.copy()
        ImageDraw.Draw(changed).ellipse((700, 236, 704, 240), fill='black')
        blur = clear.filter(ImageFilter.GaussianBlur(3))
        scenarios = [
            ('different_after', [clear, blur, window('DEF')], 2.0),
            ('hidden_dot', [clear, changed.filter(ImageFilter.GaussianBlur(3)), clear], 2.0),
            ('intro', [blur, clear], 0.0),
            ('outro', [clear, blur], 2.0),
        ]
        for name, images, stop in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as scratch:
                base = Path(scratch)
                source = sequence_video(images, base)
                _, result = self.run_cli(source, base / 'result')
                self.assertEqual(result['status'], 'waiting', result)
                self.assertFalse(result['complete'])
                self.assertEqual(result['issues'][0]['kind'], 'unreadable_window')
                self.assertEqual(result['issues'][0]['timestamp'], stop)
                self.assertTrue((base / 'result' / result['issues'][0]['image']).exists())
                self.assertFalse((base / 'result/score.pdf').exists())

