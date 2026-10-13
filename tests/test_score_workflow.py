"""New reconstruction workflow boundary; fixtures are not visual acceptance."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'))
import test_reconstruction as fixtures
import score_workflow as workflow

class ScoreWorkflow(unittest.TestCase):
    setUp = fixtures.LocalScoreWorkflow.setUp
    tearDown = fixtures.LocalScoreWorkflow.tearDown
    select = fixtures.LocalScoreWorkflow.select
    def test_navigation_preserves_only_agent_requested_native_captures(self):
        workflow.prepare(self.video, self.task)
        probe = workflow.navigate(self.task, 0, width=240)
        self.assertEqual(probe['width'], 240)
        self.assertEqual(len(workflow.load(self.task)['captures']), 0)
        shot = workflow.capture(self.task, 0)
        workflow.present(self.task, [probe['id'], shot['id']], 'Checked navigation and native notation.')
        record = workflow.load(self.task)
        self.assertEqual(record['metrics']['navigation_probes'], 1)
        self.assertEqual(record['metrics']['native_retained'], 1)
        self.assertEqual(record['metrics']['presented_images'], 2)

    def test_redraw_correction_budget_survives_resume_and_rejection_falls_back(self):
        self.select()
        pages = workflow.redraw_inputs(self.task)
        page = pages[0]
        initial = workflow.begin_redraw(self.task, page['id'], 'Viewed rough; preserve notation.')
        workflow.finish_redraw(self.task, page['id'], initial['request'], self.root / 'score.png', 'host-imagegen', 'actual-tool-receipt')
        workflow.review_redraw(self.task, page['id'], False, 'Beam altered; restore original beam.')
        correction = workflow.begin_redraw(self.task, page['id'], 'Restore beam from original.', correction=True)
        self.assertEqual(workflow.load(self.task)['redraw_pages'][0]['corrections_used'], 1)
        with self.assertRaises(workflow.ReconstructionError):
            workflow.begin_redraw(self.task, page['id'], 'Try again', correction=True)
        workflow.finish_redraw(self.task, page['id'], correction['request'], self.root / 'score.png', 'host-imagegen', 'correction-receipt')
        workflow.review_redraw(self.task, page['id'], False, 'Still altered; use vector.')
        output = workflow.export(self.task)
        self.assertEqual(output['routes'], ['vector'])
        self.assertEqual(output['page_count'], 1)

    def test_distinct_positions_keep_repeated_music_and_same_position_overlap_is_removed(self):
        workflow.prepare(self.video, self.task)
        first = workflow.capture(self.task, 0)
        last = workflow.capture(self.task, .4)
        selections = [
            {'capture': first['id'], 'bbox': [0, 0, 640, 65], 'kind': 'header', 'position': 'title'},
            {'capture': first['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system', 'staff_top': 35, 'staff_spacing': 10, 'position': 'first'},
            {'capture': last['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system', 'staff_top': 35, 'staff_spacing': 10, 'position': 'first'},
            {'capture': last['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system', 'staff_top': 35, 'staff_spacing': 10, 'position': 'later-repeat'}]
        record = workflow.assemble(self.task, 'Repeated score', selections,
            {'viewed_captures': [first['id'], last['id']], 'complete': True,
             'notes': 'Fixture continuity statement, not actual visual evidence.',
             'continuity': 'Same-position overlap omitted; distinct later repetition retained.',
             'first_last': 'Fixture start and ending.'})
        self.assertEqual([r['position'] for r in record['regions']], ['title', 'first', 'later-repeat'])
        for page in workflow.redraw_inputs(self.task):
            workflow.fail_redraw(self.task, page['id'], 'Controlled tool unavailable.')
        self.assertEqual(workflow.export(self.task)['routes'], ['vector'])

    def test_generated_native_content_reflows_after_explicit_boundary_review(self):
        self.select()
        page = workflow.redraw_inputs(self.task)[0]
        request = workflow.begin_redraw(self.task, page['id'], 'Fixture input viewed.')
        workflow.finish_redraw(self.task, page['id'], request['request'], self.root / 'score.png', 'host-imagegen', 'controlled-tool-fixture')
        workflow.review_redraw(self.task, page['id'], True, 'Fixture image accepted.', [[0,0,640,65], [0,65,640,180]])
        output = workflow.export(self.task)
        self.assertEqual(output['routes'], ['imagegen'])
        self.assertEqual(output['page_count'], 1)
        self.assertEqual(workflow.review_pdf(self.task, [1], 'Fixture page reviewed.')['status'], 'reviewed')
        (self.task / workflow.load(self.task)['redraw_pages'][0]['output']['path']).write_bytes(b'broken')
        with self.assertRaises(workflow.ReconstructionError):
            workflow.export(self.task)
