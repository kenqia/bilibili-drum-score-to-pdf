"""Navigation repair contracts at the workflow and comparison boundaries."""
import unittest
import sys
from pathlib import Path

from PIL import Image, ImageDraw

import test_automatic_score as fixtures
from score_fixtures import score_frame
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'))
import score_task
import sparse_navigation
import automatic_score


class NavigationRepairTests(unittest.TestCase):
    setUp = fixtures.AutomaticScoreTests.setUp
    tearDown = fixtures.AutomaticScoreTests.tearDown
    prepare = fixtures.AutomaticScoreTests.prepare
    sequence = fixtures.AutomaticScoreTests.sequence
    call = fixtures.AutomaticScoreTests.call

    def numbered(self, values=(1, 7, 11)):
        from PIL import ImageFont
        image = score_frame()
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
        for top, value in zip((220, 440, 660), values):
            ImageDraw.Draw(image).text((110, top-50), str(value), font=font, fill='black')
        return image

    def test_unproved_identity_does_not_report_detected_rows_as_new(self):
        first = score_frame()
        changed = first.copy()
        draw = ImageDraw.Draw(changed)
        for top in (220, 440, 660):
            draw.rectangle((995, top + 20, 1005, top + 30), fill='black')
        self.sequence([first] * 4 + [changed] * 4)
        old = self.call('capture', {'seconds': 0})
        new = self.call('capture', {'seconds': 1})
        result = sparse_navigation.compare(self.task, score_task.load(self.task), old, new)
        self.assertFalse(result['proved'])
        self.assertIsNone(result['new_complete_rows'])
        self.assertEqual(result['detected_complete_rows'], 3)

    def test_cursor_crossing_rows_preserves_identity_but_not_an_added_symbol(self):
        first = score_frame()
        second = first.copy()
        ImageDraw.Draw(first).line((950, 175, 950, 300), fill='#447fbb', width=3)
        ImageDraw.Draw(second).line((1020, 395, 1020, 520), fill='#447fbb', width=3)
        changed = second.copy()
        ImageDraw.Draw(changed).rectangle((1070, 680, 1075, 686), fill='black')
        self.sequence([first] * 3 + [second] * 3 + [changed] * 2)
        shots = [self.call('capture', {'seconds': t}) for t in (0, .75, 1.5)]
        record = score_task.load(self.task)
        match = sparse_navigation.compare(self.task, record, shots[0], shots[1])
        self.assertTrue(match['proved'], match)
        self.assertEqual(match['new_complete_rows'], 0)
        difference = sparse_navigation.compare(self.task, record, shots[0], shots[2])
        self.assertFalse(difference['proved'], difference)
        self.assertIsNone(difference['new_complete_rows'])
        self.call('overview')
        result = self.call('auto-freeze')
        self.assertGreater(len([r for r in result['regions'] if r['kind'] == 'system']), 3)

    def test_agent_single_row_correction_clears_derived_conflicts_and_caches(self):
        from unittest.mock import patch
        import row_anchors
        self.prepare(self.numbered())
        shot = self.call('capture', {'seconds': 0})
        record = score_task.load(self.task)
        image = self.numbered()
        regions = automatic_score.detect(image)[0]
        bad = row_anchors.read(image, regions)
        for anchor, value in zip(bad, (1, 11, 7)):
            anchor.update(start_bar=value, conflict='nonincreasing_printed_bars')
        record['row_manifest'] = {'observations': {'dependent': {'anchors': bad}}}
        score_task.save(self.task, record)
        self.call('review-row-anchors', {'capture': shot['id'],
            'anchors': [{'row': 1, 'start_bar': 4}], 'viewed_captures': [shot['id']],
            'notes': 'Synthetic correction of the middle reading.'})
        record = score_task.load(self.task)
        self.assertNotIn('anchors', record['row_manifest']['observations']['dependent'])
        with patch.object(row_anchors, 'read', return_value=bad):
            result = row_anchors.readings(record, shot, image, regions)
        self.assertEqual([a['start_bar'] for a in result], [1, 4, 7])
        self.assertEqual(row_anchors.missing(record, shot, result), [])

    def test_crop_risk_only_marks_the_intersecting_row(self):
        image = score_frame()
        ImageDraw.Draw(image).line((1100, 860, 1100, 910), fill='black', width=3)
        self.prepare(image)
        result = self.call('auto-freeze')
        self.assertEqual(result['status'], 'blocked')
        rows = self.call('row-manifest')['rows']
        self.assertEqual(rows[0]['status'], 'complete', rows[0]['issues'])
        self.assertEqual(rows[0]['issues'], [])
        self.assertEqual(rows[-1]['status'], 'unresolved')

    def test_ending_bracket_is_owned_by_its_row_and_fragments_stay_local(self):
        image = score_frame()
        draw = ImageDraw.Draw(image)
        draw.line((700, 568, 1100, 568), fill='black', width=2)
        draw.line((700, 568, 700, 588), fill='black', width=2)
        for y in (882, 894):
            draw.line((110, y, 1170, y), fill='black', width=2)
        regions, risks, partial = automatic_score.detect(image)
        self.assertEqual([p['lines'] for p in partial], [[882, 894]])
        rows = [r for r in regions if r['kind'] == 'system']
        self.assertLess(rows[2]['bbox'][1], 568)
        self.assertLessEqual(rows[1]['bbox'][3], 568)
        self.assertEqual(rows[2]['evidence']['associated_horizontal_lines'], [568])

    def test_bracket_more_than_eight_spaces_above_staff(self):
        image = score_frame()
        draw = ImageDraw.Draw(image)
        # Native raster rounding can put the bracket just beyond eight spaces.
        draw.line((700, 562, 1100, 562), fill='black', width=2)
        draw.line((700, 562, 700, 588), fill='black', width=2)
        regions, _, partial = automatic_score.detect(image)
        self.assertEqual(partial, [])
        rows = [r for r in regions if r['kind'] == 'system']
        self.assertEqual(rows[2]['evidence']['associated_horizontal_lines'], [562])
        self.assertLessEqual(rows[1]['bbox'][3], 562)

    def test_clipped_bracket_leg_at_viewport_top_belongs_to_first_staff(self):
        image = score_frame()
        draw = ImageDraw.Draw(image)
        draw.line((700, 127, 1100, 127), fill='black', width=2)
        draw.line((700, 127, 700, 170), fill='black', width=2)
        shifted = Image.new('RGB', image.size, '#303030')
        shifted.paste(image, (0, -150))
        regions, risks, _ = automatic_score.detect(shifted)
        self.assertFalse(any(r['kind'] == 'header' for r in regions))
        first = next(r for r in regions if r['kind'] == 'system')
        self.assertEqual(first['bbox'][1], 0)
        self.assertTrue(any(r['code'] == 'crop_edge' and r['bbox'] == first['bbox'] for r in risks))

    def test_missing_numbers_pause_until_explicit_agent_fallback(self):
        self.prepare()
        first = self.call('stage')
        self.assertEqual(first['phase'], 'source')
        self.assertEqual(first['status'], 'blocked')
        self.assertIn('row_anchor_missing', [i['code'] for i in first['unresolved']])
        record = self.call('resume')
        self.assertFalse(any(d.get('reason') == 'forward_search' for d in record['navigation']['decisions']))
        before = len(record['captures'])
        self.call('stage')
        self.assertEqual(len(self.call('resume')['captures']), before)
        shots = record['overview']['candidates']
        self.call('review-row-anchors', {'capture': shots[0]['id'], 'anchors': [],
            'fallback_interval': [0, record['source']['duration']],
            'viewed_captures': [s['id'] for s in shots],
            'notes': 'Synthetic unnumbered score: complete identical rows establish position.'})
        self.assertEqual(self.call('stage')['phase'], 'generation')

    def test_printed_bars_are_read_and_same_page_cursor_adds_no_rows(self):
        first = self.numbered()
        second = first.copy()
        ImageDraw.Draw(first).line((950, 175, 950, 300), fill='#447fbb', width=3)
        ImageDraw.Draw(second).line((1020, 395, 1020, 520), fill='#447fbb', width=3)
        self.sequence([first] * 4 + [second] * 4)
        result = self.call('stage')
        self.assertEqual(result['phase'], 'generation', result.get('unresolved'))
        record = self.call('resume')
        readings = record['row_manifest']['observations'][record['navigation']['endpoints']['first']['capture']]['anchors']
        self.assertEqual([a['start_bar'] for a in readings], [1, 7, 11])
        self.assertTrue(all(a['producer'] == 'program' for a in readings))
        self.assertEqual(len(record['row_manifest']['rows']), 3)
        self.assertFalse(any(d['action'] in ('backtrack', 'local_scan') for d in record['navigation']['decisions']))

    def test_original_problem_survives_restarts_and_stops_after_two_stalled_samples(self):
        first = score_frame()
        second = first.copy()
        for top in (220, 440, 660):
            ImageDraw.Draw(second).rectangle((990, top+10, 1030, top+40), fill='black')
        self.sequence([first] * 4 + [second] * 4)
        left = self.call('capture', {'seconds': 0})
        right = self.call('capture', {'seconds': 1.75})
        self.call('review-row-anchors', {'capture': left['id'], 'anchors': [],
            'viewed_captures': [left['id'], right['id']], 'fallback_interval': [0, 2],
            'notes': 'Synthetic unnumbered geometry fallback with distinct complete observations.'})
        self.call('stage', {'max_observations': 1})
        # A stalled acquisition adapter returns an existing PTS. It supplies no
        # new picture or proof; retrying must not manufacture a new problem.
        sparse_navigation.refine(self.task, lambda seconds, reason: left, 1)
        first_problem = score_task.load(self.task)['navigation']['problems'][0]
        self.assertEqual(first_problem['no_gain_streak'], 1)
        sparse_navigation.refine(self.task, lambda seconds, reason: left, 1)
        after = score_task.load(self.task)['navigation']['problems'][0]
        self.assertEqual(after['id'], first_problem['id'])
        self.assertEqual(after['no_gain_streak'], 2)
        self.assertEqual(after['status'], 'needs_review')
        self.assertEqual(after['attempts'], 2)
        sparse_navigation.refine(self.task, lambda seconds, reason: self.fail('Must stop retrying'), 5)
        self.assertEqual(score_task.load(self.task)['navigation']['problems'][0]['attempts'], 2)

    def test_numbered_scroll_reuses_positions_and_adds_only_the_new_row(self):
        first = self.numbered()
        second = first.copy()
        for top in (440, 660):
            second.paste(first.crop((70, top-65, 1211, top+150)), (70, top-285))
        new_row = self.numbered((16, 20, 25))
        second.paste(new_row.crop((70, 155, 1211, 370)), (70, 595))
        self.sequence([first] * 4 + [second] * 4)
        result = self.call('stage')
        self.assertEqual(result['phase'], 'generation', result.get('unresolved'))
        record = self.call('resume')
        self.assertEqual(len(record['row_manifest']['rows']), 4)
        adjustments = [d for d in record['navigation']['decisions'] if d['action'] == 'adjust_step']
        self.assertTrue(any(d['reason'] == 'printed_bar_overlap' and d['new_complete_rows'] == 1 for d in adjustments))

    def test_agent_start_anchor_carries_to_verified_same_page_only(self):
        first = self.numbered()
        ImageDraw.Draw(first).rectangle((100, 165, 145, 205), fill='white')
        second = first.copy()
        ImageDraw.Draw(first).line((950, 175, 950, 300), fill='#447fbb', width=3)
        ImageDraw.Draw(second).line((1020, 395, 1020, 520), fill='#447fbb', width=3)
        self.sequence([first] * 4 + [second] * 4)
        blocked = self.call('stage')
        self.assertEqual(blocked['phase'], 'source')
        record = self.call('resume')
        capture = record['navigation']['endpoints']['first']['capture']
        self.call('review-row-anchors', {'capture': capture, 'anchors': [{'row': 0, 'start_bar': 1}],
            'viewed_captures': [capture], 'notes': 'Synthetic first music has an implicit bar-one start.'})
        result = self.call('stage')
        self.assertEqual(result['phase'], 'generation', result.get('unresolved'))
        after = self.call('resume')
        last = after['navigation']['endpoints']['last']['capture']
        anchor = after['row_manifest']['observations'][last]['anchors'][0]
        self.assertEqual(anchor['start_bar'], 1)
        self.assertEqual(anchor['method'], 'verified_same_page_anchor')
        self.assertEqual(anchor['reference_capture'], capture)

    def test_new_numbered_row_with_crop_risk_is_not_counted_as_complete(self):
        first = self.numbered()
        second = first.copy()
        for top in (440, 660):
            second.paste(first.crop((70, top-65, 1211, top+150)), (70, top-285))
        source = self.numbered((16, 20, 25))
        second.paste(source.crop((70, 155, 1211, 370)), (70, 595))
        ImageDraw.Draw(second).line((1100, 860, 1100, 910), fill='black', width=3)
        self.sequence([first]*4+[second]*4)
        self.assertEqual(self.call('stage')['phase'], 'source')
        decisions = self.call('resume')['navigation']['decisions']
        overlap = next(d for d in decisions if d.get('reason') == 'printed_bar_overlap')
        self.assertEqual(overlap['new_complete_rows'], 0)

    def test_source_freezing_rebuilds_without_loading_navigation(self):
        from unittest.mock import patch
        self.prepare(self.numbered())
        self.assertEqual(self.call('stage')['phase'], 'generation')
        record = score_task.load(self.task)
        positions = [row['position'] for row in record['regions']]
        record.pop('freeze')
        score_task.save(self.task, record)
        with patch.dict(sys.modules, {'sparse_navigation': None}):
            result = automatic_score.auto_freeze(self.task)
            self.assertEqual(result['status'], 'frozen')
            automatic_score.require_frozen(score_task.load(self.task))
        self.assertEqual([row['position'] for row in result['regions']], positions)

    def test_same_printed_bars_with_changed_ink_do_not_approve_source(self):
        import score_continuity
        first = self.numbered()
        second = first.copy()
        ImageDraw.Draw(second).rectangle((1070, 680, 1075, 686), fill='black')
        self.sequence([first] * 4 + [second] * 4)
        result = self.call('stage')
        self.assertEqual((result['phase'], result['status']), ('source', 'blocked'))
        record = score_task.load(self.task)
        shots = {shot['id']: shot for shot in record['captures']}
        endpoints = record['navigation']['endpoints']
        comparison = score_continuity.compare(self.task, record,
            shots[endpoints['first']['capture']], shots[endpoints['last']['capture']])
        self.assertEqual(comparison['reason'], 'printed_bar_content_conflict')
        self.assertFalse(comparison['proved'])
        self.assertIsNone(comparison['new_complete_rows'])
        with self.assertRaises(score_task.ReconstructionError):
            automatic_score.require_frozen(record)
        self.assertEqual(self.call('auto-freeze')['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
