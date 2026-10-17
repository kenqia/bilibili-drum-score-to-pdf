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

    def test_numbered_join_requires_actual_source_references_and_preserves_coverage_truth(self):
        from PIL import ImageDraw
        from score_fixtures import score_frame
        first = score_frame()
        last = first.copy()
        ImageDraw.Draw(last).rectangle((995, 240, 1005, 250), fill='black')
        self.sequence([first] * 4 + [last] * 4)
        left = self.call('capture', {'seconds': 0})
        right = self.call('capture', {'seconds': 1})
        payload = {'previous_capture': left['id'], 'capture': right['id'],
                   'previous_bars': [17, 20], 'bars': [21, 24],
                   'viewed_captures': [left['id'], right['id']], 'complete_rows': True,
                   'first_last': 'Controlled full boundaries and adjacent bar marks.',
                   'notes': 'Controlled Agent reading, not program OCR.'}
        self.call('review-continuity', {**payload, 'bars': [22, 24]}, success=False)
        self.call('review-continuity', {**payload, 'viewed_captures': [left['id']]}, success=False)
        saved = self.call('review-continuity', payload)
        self.assertEqual(saved['producer'], 'agent')
        record = self.call('resume')
        self.assertNotIn('freeze', record)
        self.assertFalse(record.get('overview', {}).get('scan', {}).get('complete', False))
        self.assertEqual(record['continuity_reviews'][0]['bars'], [21, 24])

    def test_inserted_observation_keeps_row_ids_and_pending_generation_requests(self):
        self.prepare()
        first = self.call('stage')
        rows = self.call('row-manifest')['rows']
        self.call('resample', {'intervals': [[.75, 1.25]], 'reason': 'Controlled extra observation.'})
        self.call('auto-freeze')
        after = self.call('stage')
        self.assertEqual([r['id'] for r in self.call('row-manifest')['rows']], [r['id'] for r in rows])
        self.assertEqual(after['handoffs'], first['handoffs'])

    def test_partial_navigation_is_resumable_and_cannot_freeze(self):
        from score_fixtures import score_frame
        self.sequence([score_frame()] * 24)
        first = self.call('stage', {'max_observations': 1})
        self.assertEqual(first['phase'], 'source')
        self.assertEqual(first['status'], 'pending')
        self.assertFalse(self.call('row-manifest')['continuity_complete'])
        self.call('redraw-inputs', success=False)
        final = self.call('stage')
        self.assertEqual(final['phase'], 'generation')
        self.assertFalse(self.call('resume')['overview']['scan']['complete'])

    def test_later_discovery_splits_provisional_same_picture_occurrences(self):
        from PIL import ImageDraw
        from score_fixtures import score_frame
        first = score_frame()
        second = first.copy()
        for top in (220, 440, 660):
            ImageDraw.Draw(second).rectangle((995, top + 20, 1005, top + 30), fill='black')
        self.sequence([first] * 16 + [second] * 16 + [first] * 16)
        self.assertEqual(self.call('stage', {'max_observations': 1})['status'], 'pending')
        result = self.call('stage')
        self.assertEqual(result['phase'], 'generation', result.get('unresolved'))
        rows = self.call('row-manifest')['rows']
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({row['id'] for row in rows}), 9)

    def test_same_position_selects_clearer_source_and_keeps_alternates(self):
        from PIL import ImageFilter
        from score_fixtures import score_frame
        clear = score_frame()
        blurred = clear.filter(ImageFilter.GaussianBlur(.55))
        self.sequence([blurred] * 4 + [clear] * 4)
        result = self.call('stage')
        self.assertEqual(result['phase'], 'generation', result.get('unresolved'))
        rows = self.call('row-manifest')['rows']
        self.assertEqual(len(rows), 3)
        for row in rows:
            selected = next(s for s in row['sources'] if s['capture'] == row['selected']['capture'])
            self.assertGreaterEqual(selected['timestamp'], 1)
            self.assertGreater(len(row['sources']), 1)
            self.assertIn('quality', selected)

    def test_manual_selection_and_withdrawal_refresh_the_same_manifest(self):
        self.prepare()
        self.call('stage')
        record = self.call('resume')
        regions = record['regions'][:2]
        review = {'viewed_captures': list({r['capture'] for r in regions}), 'complete': True,
                  'notes': 'Controlled manual selection.', 'continuity': 'Controlled order.',
                  'first_last': 'Controlled endpoints.'}
        self.call('assemble', {'title': 'Manual', 'regions': regions, 'review': review})
        manifest = self.call('row-manifest')
        self.assertEqual(len(manifest['rows']), 1)
        self.assertEqual(manifest['rows'][0]['position'], regions[1]['position'])
        self.call('assemble', {'title': 'Manual', 'regions': regions,
                  'review': {**review, 'complete': False, 'unresolved': [{'code': 'controlled_doubt'}]}})
        self.assertFalse(self.call('row-manifest')['continuity_complete'])

    def test_tiny_native_difference_requests_vision_without_repeated_scanning(self):
        from PIL import ImageDraw
        from score_fixtures import score_frame
        first = score_frame()
        changed = first.copy()
        ImageDraw.Draw(changed).point((1050, 152), fill='black')
        self.sequence([first] * 4 + [changed] * 4)
        result = self.call('stage')
        self.assertEqual(result['phase'], 'source')
        record = self.call('resume')
        self.assertFalse(record['row_manifest']['continuity_complete'])
        self.assertEqual(record['overview']['scan']['frames_observed'], 0)
        self.assertIn('native_difference_needs_visual_review', [issue['code'] for issue in result['unresolved']])

    def test_numbered_complete_rows_can_join_without_overlap_or_strict_scan(self):
        from PIL import ImageDraw
        from score_fixtures import score_frame
        first = score_frame()
        second = first.copy()
        for top in (220, 440, 660):
            ImageDraw.Draw(second).rectangle((995, top + 20, 1005, top + 30), fill='black')
        self.sequence([first] * 4 + [second] * 4)
        left = self.call('capture', {'seconds': .5})
        right = self.call('capture', {'seconds': 1.35})
        self.call('review-continuity', {'previous_capture': left['id'], 'capture': right['id'],
                  'previous_bars': [1, 12], 'bars': [13, 24],
                  'viewed_captures': [left['id'], right['id']], 'complete_rows': True,
                  'first_last': 'Controlled full row boundaries.', 'notes': 'Controlled bar reading.'})
        result = self.call('stage')
        self.assertEqual(result['phase'], 'generation', result.get('unresolved'))
        record = self.call('resume')
        self.assertEqual(record['overview']['scan']['frames_observed'], 0)
        self.assertFalse(record['overview']['scan']['complete'])
        self.assertEqual(len(record['row_manifest']['rows']), 6)
        self.assertTrue(any(e.get('numbered_continuation') for e in record['program_checks']['events']))


if __name__ == '__main__':
    unittest.main()
