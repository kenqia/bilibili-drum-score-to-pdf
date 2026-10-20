"""Agent source review boundaries; all image-review assertions are fixtures."""
import copy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_reconstruction as fixtures
from score_fixtures import CLI
import score_workflow as workflow
import score_task


class AgentSourceTests(unittest.TestCase):
    setUp = fixtures.LocalScoreWorkflow.setUp
    tearDown = fixtures.LocalScoreWorkflow.tearDown

    def source(self):
        workflow.prepare(self.video, self.task)
        shot = workflow.capture(self.task, 0)
        rows = [{'capture': shot['id'], 'bbox': [0, 0, 640, 65], 'kind': 'header', 'position': 'title'},
                {'capture': shot['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system',
                 'staff_top': 35, 'staff_spacing': 10, 'position': 'row-1'}]
        review = {'viewed_captures': [shot['id']], 'complete': True, 'unresolved': [],
                  'notes': 'Controlled title assertion.', 'continuity': 'Controlled single-image order.',
                  'first_last': 'Controlled complete start and ending.'}
        return shot, rows, review

    def test_stage_builds_longshot_without_claiming_overall_agent_approval(self):
        workflow.prepare(self.video, self.task)
        result = workflow.stage(self.task)
        self.assertEqual(result['phase'], 'longshot_review')
        record = workflow.load(self.task)
        self.assertIsNone(record['longshot']['review'])
        self.assertNotIn('freeze', record)
        self.assertEqual(record['captures'], [])
        with self.assertRaises(score_task.ReconstructionError):
            workflow.redraw_requests(self.task)
        before = (self.task / 'record.json').read_bytes()
        self.assertEqual(workflow.stage(self.task), result)
        self.assertEqual((self.task / 'record.json').read_bytes(), before)

    def test_all_assembly_entries_require_present_but_accept_one_concrete_review(self):
        shot, rows, review = self.source()
        from test_public_contracts import SOURCE_ASSEMBLY_ENTRIES
        for entry in SOURCE_ASSEMBLY_ENTRIES:
            def assemble(payload):
                if entry == 'cli':
                    path = self.root / 'review.json'
                    path.write_text(json.dumps({'title': 'Synthetic', 'regions': rows, 'review': payload}))
                    result = subprocess.run([sys.executable, str(CLI), '--task', str(self.task),
                        '--operation', 'assemble', '--request', str(path)], capture_output=True, text=True)
                    if result.returncode:
                        raise score_task.ReconstructionError(result.stdout)
                    return json.loads(result.stdout)
                owner = {'workflow': workflow, 'task': score_task, 'vector': workflow.local}[entry]
                return owner.assemble(self.task, 'Synthetic', rows, payload)
            with self.subTest(entry=entry):
                baseline = workflow.load(self.task)
                baseline.pop('presentations', None)
                score_task.save(self.task, baseline)
                with self.assertRaises(score_task.ReconstructionError):
                    assemble(review)
                workflow.present(self.task, [shot['id']], 'Controlled native-image view assertion.')
                for field in ('notes', 'continuity', 'first_last'):
                    with self.subTest(field=field), self.assertRaises(score_task.ReconstructionError):
                        assemble({**review, field: ''})
                result = assemble(review)
                self.assertEqual(result['freeze']['producer'], 'agent')
                self.assertNotIn('evidence', result['source_review'])
                self.assertNotIn('source_issue_history', result)

    def test_unresolved_actual_source_problem_blocks_generation_until_reconfirmed(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled native-image view assertion.')
        workflow.assemble(self.task, 'Synthetic', rows, {**review, 'unresolved': ['Ending hidden.']})
        self.assertEqual(workflow.stage(self.task)['status'], 'blocked')
        with self.assertRaises(score_task.ReconstructionError):
            workflow.redraw_inputs(self.task)
        workflow.assemble(self.task, 'Synthetic', rows, review)
        self.assertEqual(workflow.stage(self.task)['phase'], 'generation')

    def test_manual_path_exports_vector_without_fake_calls_and_reviews_current_revision(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled source-view assertion.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        for group in workflow.redraw_inputs(self.task):
            workflow.fail_redraw(self.task, group['id'], 'Synthetic unavailable host.', outcome='unavailable')
        result = workflow.stage(self.task)
        self.assertEqual(result['phase'], 'pdf_review')
        output = result['artifacts']['output']
        self.assertEqual(output['routes'], ['vector'])
        self.assertEqual(workflow.load(self.task)['redraw_pages'][0]['attempts'], [])
        workflow.review_pdf(self.task, list(range(1, output['page_count'] + 1)),
            'Controlled final-page review.', output_revision=output['output_revision'])
        self.assertEqual(workflow.stage(self.task)['phase'], 'complete')

    def test_local_replacement_and_return_preserve_unknown_call_and_unaffected_group(self):
        shot, rows, review = self.source()
        rows.append({**rows[-1], 'position': 'row-2'})
        workflow.present(self.task, [shot['id']], 'Controlled source view.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        groups = workflow.redraw_inputs(self.task, groups=[[0, 1], [2]])
        attempt = workflow.begin_redraw(self.task, groups[0]['id'], 'Controlled input review.')
        workflow.fail_redraw(self.task, groups[1]['id'], 'Controlled unavailable host.', outcome='unavailable')
        alternate = workflow.capture(self.task, .4)
        replacement = {**rows[1], 'capture': alternate['id']}
        # A retained frame is not an actual-view receipt.
        with self.assertRaises(score_task.ReconstructionError):
            workflow.revise_selection(self.task, [{'position': 'row-1', 'region': replacement}],
                {**review, 'viewed_captures': [shot['id'], alternate['id']]})
        workflow.present(self.task, [alternate['id']], 'Controlled replacement view.')
        changed_review = {**review, 'viewed_captures': [shot['id'], alternate['id']],
                          'notes': 'Controlled replacement and unchanged title.'}
        workflow.revise_selection(self.task, [{'position': 'row-1', 'region': replacement}], changed_review)
        changed = workflow.redraw_inputs(self.task)
        self.assertEqual(changed[0]['status'], 'needs_generation')
        self.assertEqual(changed[1]['status'], 'vector')
        workflow.revise_selection(self.task, [{'position': 'row-1', 'region': rows[1]}], review)
        restored = workflow.redraw_inputs(self.task)
        self.assertEqual(restored[0]['status'], 'calling')
        self.assertEqual(restored[0]['attempts'][0]['request'], attempt['request'])
        self.assertEqual(restored[1]['status'], 'vector')

    def test_crop_revision_requires_explicit_review_and_keeps_last_valid_state_on_error(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled view.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        before = (self.task / 'record.json').read_bytes()
        with self.assertRaises(score_task.ReconstructionError):
            workflow.revise_crop(self.task, 1, [0, -1, 640, 180])
        self.assertEqual((self.task / 'record.json').read_bytes(), before)
        record = workflow.revise_crop(self.task, 1, [0, 64, 640, 180])
        self.assertFalse(record['source_review']['complete'])
        self.assertEqual(record['regions'][1]['staff_top'], 36)
        with self.assertRaises(score_task.ReconstructionError):
            workflow.redraw_inputs(self.task)
        self.assertEqual(workflow.stage(self.task)['phase'], 'source')

    def test_partial_review_does_not_carry_approval_to_changed_selection(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled source view.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        replacement = {**rows[1], 'bbox': [0, 64, 640, 180], 'staff_top': 36}
        changed = workflow.revise_selection(self.task,
            [{'position': 'row-1', 'region': replacement}], {'notes': 'Controlled crop update only.'})
        self.assertFalse(changed['source_review']['complete'])
        with self.assertRaises(score_task.ReconstructionError):
            workflow.redraw_inputs(self.task)
        workflow.revise_selection(self.task, [], {'complete': True, 'unresolved': [],
            'notes': 'Controlled review of changed crop and original sequence.'})
        self.assertEqual(workflow.stage(self.task)['phase'], 'generation')

    def test_source_approval_does_not_override_cut_stem_or_changed_review(self):
        shot, rows, review = self.source()
        rows[1]['bbox'][1], rows[1]['staff_top'] = 90, 10
        workflow.present(self.task, [shot['id']], 'Controlled view.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        self.assertEqual(workflow.stage(self.task)['checks']['status'], 'blocked')
        with self.assertRaises(score_task.ReconstructionError):
            workflow.export(self.task)
        record = workflow.load(self.task)
        record['source_review']['continuity'] = 'Changed after approval.'
        with self.assertRaises(score_task.ReconstructionError):
            score_task.require_frozen(record)

    def test_summary_preserves_complete_default_receipt_in_task_file(self):
        workflow.prepare(self.video, self.task)
        command = [sys.executable, str(CLI), '--operation', 'stage', '--task', str(self.task)]
        full = json.loads(subprocess.check_output(command, text=True))
        compact = json.loads(subprocess.check_output(command + ['--summary'], text=True))
        details = json.loads((self.task / compact['details']['path']).read_text())
        self.assertEqual(details, full)
        self.assertEqual(compact['phase'], 'longshot_review')
