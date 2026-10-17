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


if __name__ == '__main__':
    unittest.main()
