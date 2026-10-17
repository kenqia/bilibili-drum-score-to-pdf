"""Sparse navigation through the agreed CLI seam; images are synthetic."""
import unittest

import test_automatic_score as fixtures


class SparseNavigationTests(unittest.TestCase):
    setUp = fixtures.AutomaticScoreTests.setUp
    tearDown = fixtures.AutomaticScoreTests.tearDown
    prepare = fixtures.AutomaticScoreTests.prepare
    sequence = fixtures.AutomaticScoreTests.sequence
    call = fixtures.AutomaticScoreTests.call

    def test_default_stage_observes_endpoints_without_claiming_continuous_coverage(self):
        self.prepare()
        result = self.call('stage', {'title': 'Sparse fixture'})
        self.assertEqual(result['phase'], 'generation', result)
        record = self.call('resume')
        self.assertFalse(record['overview']['scan']['complete'])
        self.assertEqual(record['overview']['scan']['frames_observed'], 0)
        self.assertTrue(record['navigation']['endpoints']['first'])
        self.assertTrue(record['navigation']['endpoints']['last'])
        self.assertTrue(record['row_manifest']['continuity_complete'])
        self.assertEqual(len(record['row_manifest']['rows']), 3)
        self.assertLess(self.call('cache-report')['actual_decodes'], 8)
        self.assertFalse(record.get('presentations'))
        self.assertEqual(self.call('stage')['handoffs'], result['handoffs'])

    def test_explicit_strict_mode_scans_even_after_sparse_freeze(self):
        self.prepare()
        self.call('stage')
        self.call('stage', {'mode': 'strict'})
        record = self.call('resume')
        self.assertTrue(record['overview']['scan']['complete'])
        self.assertEqual(record['overview']['scan']['frames_observed'], 8)
        self.call('stage', {'mode': 'invalid'}, success=False)

    def test_gap_backtracking_preserves_later_repeated_music(self):
        from PIL import ImageDraw
        from score_fixtures import score_frame
        first = score_frame()
        second = first.copy()
        for top in (220, 440, 660):
            ImageDraw.Draw(second).rectangle((995, top + 20, 1005, top + 30), fill='black')
        self.sequence([first] * 4 + [second] * 4 + [first] * 4)
        result = self.call('stage')
        self.assertEqual(result['phase'], 'generation', result.get('unresolved'))
        record = self.call('resume')
        rows = record['row_manifest']['rows']
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({row['id'] for row in rows}), 9)
        decisions = record['navigation']['decisions']
        self.assertTrue(any(d['action'] in ('backtrack', 'local_scan') for d in decisions))
        self.assertTrue(all('new_complete_rows' in d for d in decisions if d['action'] == 'adjust_step'))
        self.assertTrue(record['row_manifest']['continuity_complete'])


if __name__ == '__main__':
    unittest.main()
