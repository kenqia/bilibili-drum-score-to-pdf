"""Optional MIDI tests; run in the isolated Mido environment."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/bilibili-drum-score-to-pdf/scripts'))

@unittest.skipUnless(importlib.util.find_spec('mido'), 'optional Mido dependency absent')
class MidiExportTests(unittest.TestCase):
    def test_written_file_preserves_exact_events_tempo_channel_and_silence(self):
        from midi_export import export_midi, inspect_midi
        score = {'tempo_bpm': 200, 'beats': '8', 'unresolved': [], 'events': [
            {'beat': '7/2', 'duration': '1/4', 'note': 36, 'velocity': 96},
            {'beat': '15/4', 'duration': '1/4', 'note': 36, 'velocity': 96},
            {'beat': '13/3', 'duration': '1/3', 'note': 48, 'velocity': 72},
        ]}
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'excerpt.mid'
            export_midi(score, output)
            actual = inspect_midi(output)
        self.assertEqual(actual, {'ticks_per_beat': 480, 'end_tick': 3840,
            'tempos': [[0, 300000]], 'time_signatures': [[0, 4, 4]],
            'events': [
                {'tick': 1680, 'duration_ticks': 120, 'note': 36, 'velocity': 96, 'channel': 9},
                {'tick': 1800, 'duration_ticks': 120, 'note': 36, 'velocity': 96, 'channel': 9},
                {'tick': 2080, 'duration_ticks': 160, 'note': 48, 'velocity': 72, 'channel': 9},
            ]})

    def test_unresolved_source_symbols_do_not_create_or_replace_midi(self):
        from midi_export import export_midi
        score = {'tempo_bpm': 200, 'beats': '4', 'events': [],
                 'unresolved': [{'measure': 75, 'symbol': 'grace'}]}
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'existing.mid'
            output.write_bytes(b'prior delivery')
            with self.assertRaisesRegex(ValueError, 'unresolved'):
                export_midi(score, output)
            self.assertEqual(output.read_bytes(), b'prior delivery')

    def test_overlapping_same_note_cannot_pass_note_pairing(self):
        from midi_export import export_midi
        score = {'tempo_bpm': 200, 'beats': '4', 'unresolved': [], 'events': [
            {'beat': '0', 'duration': '1', 'note': 38, 'velocity': 96},
            {'beat': '1/2', 'duration': '1/2', 'note': 38, 'velocity': 96}]}
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'invalid.mid'
            with self.assertRaisesRegex(ValueError, 'overlapping'):
                export_midi(score, output)
            self.assertFalse(output.exists())

    def test_boolean_velocity_is_rejected_without_touching_delivery(self):
        from midi_export import export_midi
        score = {'tempo_bpm': 200, 'beats': '4', 'unresolved': [], 'events': [
            {'beat': '0', 'duration': '1', 'note': 38, 'velocity': True}]}
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'existing.mid'
            output.write_bytes(b'prior delivery')
            with self.assertRaisesRegex(ValueError, 'velocity'):
                export_midi(score, output)
            self.assertEqual(output.read_bytes(), b'prior delivery')

    def test_independent_fifteen_measure_candidate_matches_source_under_declared_mapping(self):
        from midi_export import export_midi, inspect_midi
        from fractions import Fraction
        from collections import Counter
        import json
        evidence = ROOT / 'docs/experiments/issue-55-midi'
        source = json.loads((evidence / 'source-benchmark.json').read_text())
        candidate = json.loads((evidence / 'agent-candidate.json').read_text())
        # Two separate visual readings, original crops vs rendered PDF. The
        # notation-to-GM policy is explicit and does not resolve author intent.
        expected = Counter()
        for index, measure in enumerate(source['measures']):
            for event in measure['events']:
                expected[(int((index * 4 + Fraction(event['beat'])) * 480),
                          int(Fraction(event['duration']) * 480), event['note'],
                          event['velocity'], 9)] += 1
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'pilot.mid'
            export_midi(candidate, output, experimental=True)
            actual = inspect_midi(output)
        observed = Counter((e['tick'], e['duration_ticks'], e['note'],
                            e['velocity'], e['channel']) for e in actual['events'])
        self.assertEqual(observed, expected)
        self.assertEqual(len(actual['events']), 141)
        self.assertEqual(actual['end_tick'], 28800)
        self.assertEqual(actual['tempos'], [[0, 300000]])
        self.assertFalse(candidate['reliable'])
        self.assertTrue(source['unresolved'])

    def test_unresolved_author_mapping_requires_explicit_experimental_export(self):
        from midi_export import export_midi
        score = {'tempo_bpm': 200, 'beats': '4', 'unresolved': [], 'events': [],
                 'author_mapping_unresolved': ['ride or crash']}
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'trial.mid'
            with self.assertRaisesRegex(ValueError, 'mapping'):
                export_midi(score, output)
            self.assertFalse(output.exists())
