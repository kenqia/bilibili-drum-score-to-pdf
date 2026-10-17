"""Public entry matrix for shared invariants; all review notes are fixtures."""
import copy
import json
import subprocess
import sys
import unittest

import test_reconstruction as fixtures
from score_fixtures import CLI
import reconstruction
import score_task
import score_workflow
import automatic_score


EXPORT_ENTRIES = ('cli', 'workflow', 'vector')
REVIEW_ENTRIES = ('cli', 'workflow', 'vector', 'task')
GROUP_ENTRIES = ('cli', 'workflow', 'task')
CROP_ENTRIES = ('cli', 'workflow', 'task')
REQUEST_ENTRIES = ('cli', 'workflow', 'task')
SCAN_ENTRIES = ('cli', 'workflow', 'automatic')
NAVIGATION_ENTRIES = ('cli', 'workflow')


class PublicContracts(unittest.TestCase):
    setUp = fixtures.LocalScoreWorkflow.setUp
    tearDown = fixtures.LocalScoreWorkflow.tearDown
    select = fixtures.LocalScoreWorkflow.select

    def cli(self, operation, payload):
        request = self.root / 'contract-request.json'
        request.write_text(json.dumps(payload))
        result = subprocess.run([sys.executable, str(CLI), '--operation', operation,
            '--task', str(self.task), '--request', str(request)], capture_output=True, text=True)
        if result.returncode:
            self.assertEqual(result.returncode, 2, result.stderr)
            raise score_task.ReconstructionError(result.stdout)
        return json.loads(result.stdout)

    def export(self, entry):
        if entry == 'cli':
            return self.cli('export', {})
        if entry == 'workflow':
            return score_workflow.export(self.task)
        return reconstruction.export_vector(self.task)

    def review(self, entry, payload):
        if entry == 'cli':
            return self.cli('review-pdf', payload)
        owner = {'workflow': score_workflow, 'vector': reconstruction, 'task': score_task}[entry]
        return owner.review_pdf(self.task, **payload)

    def groups(self, entry, groups=None):
        if entry == 'cli':
            return self.cli('redraw-inputs', {} if groups is None else {'groups': groups})
        owner = {'workflow': score_workflow, 'task': score_task}[entry]
        return owner.redraw_inputs(self.task, groups=groups)

    def test_navigation_entries_validate_budget_and_do_not_bypass_source_integrity(self):
        self.select()
        baseline = score_task.load(self.task)
        for entry in NAVIGATION_ENTRIES:
            with self.subTest(entry=entry):
                def call(operation, payload):
                    if entry == 'cli':
                        return self.cli(operation, payload)
                    return getattr(score_workflow, operation.replace('-', '_'))(self.task, **payload)
                for payload in ({'mode': 'fast'}, {'max_observations': 0}, {'max_observations': True}):
                    with self.assertRaises(score_task.ReconstructionError):
                        call('stage', payload)
                with self.assertRaises(score_task.ReconstructionError):
                    call('review-continuity', {'previous_capture': 'missing', 'capture': 'missing',
                        'previous_bars': [1, 4], 'bars': [5, 8], 'viewed_captures': [],
                        'complete_rows': True, 'first_last': 'Controlled.', 'notes': 'Controlled.'})
                for payload in (
                    {'capture': 'missing', 'anchors': [], 'viewed_captures': [], 'notes': 'Controlled.'},
                    {'capture': baseline['captures'][0]['id'], 'anchors': [{'row': True, 'start_bar': 1}],
                     'viewed_captures': [baseline['captures'][0]['id']], 'notes': 'Controlled.'},
                    {'capture': baseline['captures'][0]['id'], 'anchors': [],
                     'viewed_captures': [baseline['captures'][0]['id']], 'notes': 'Controlled.',
                     'fallback_interval': [0, baseline['source']['duration']]},
                ):
                    with self.assertRaises(score_task.ReconstructionError):
                        call('review-row-anchors', payload)
                self.assertEqual(score_task.load(self.task), baseline)
                self.assertTrue(call('row-manifest', {})['continuity_complete'])
        self.video.write_bytes(b'Controlled damaged source.')
        for entry in NAVIGATION_ENTRIES:
            with self.subTest(entry=entry), self.assertRaises(score_task.ReconstructionError):
                if entry == 'cli':
                    self.cli('row-manifest', {})
                else:
                    score_workflow.row_manifest(self.task)
        for entry in NAVIGATION_ENTRIES:
            with self.subTest(entry=entry), self.assertRaises(score_task.ReconstructionError):
                payload = {'capture': baseline['captures'][0]['id'], 'anchors': [{'row': 0, 'start_bar': 1}],
                           'viewed_captures': [baseline['captures'][0]['id']], 'notes': 'Controlled.'}
                if entry == 'cli':
                    self.cli('review-row-anchors', payload)
                else:
                    score_workflow.review_row_anchors(self.task, **payload)

    def test_scan_status_is_explicitly_metadata_only_at_every_entry(self):
        self.select()
        self.video.write_bytes(b'controlled damaged source')
        for entry in SCAN_ENTRIES:
            with self.subTest(entry=entry):
                if entry == 'cli':
                    status = self.cli('scan-status', {})
                else:
                    owner = {'workflow': score_workflow, 'automatic': automatic_score}[entry]
                    status = owner.scan_status(self.task)
                self.assertTrue(status['metadata_only'])
                self.assertFalse(status['complete'])
                self.assertEqual(status['progress'], {})
        with self.assertRaises(score_task.ReconstructionError):
            score_task.load(self.task)

    def test_manual_cut_stem_blocks_every_generation_entry_until_crop_is_repaired(self):
        self.select()
        original = score_task.load(self.task)
        regions = copy.deepcopy(original['regions'])
        regions[1]['bbox'][1] = 90
        regions[1]['staff_top'] = 10
        reconstruction.assemble(self.task, 'Cut stem', regions, original['source_review'])
        group = score_task.redraw_inputs(self.task)[0]
        before = score_task.load(self.task)
        for entry in CROP_ENTRIES:
            with self.subTest(entry=entry):
                if entry == 'cli':
                    checks = self.cli('crop-checks', {})
                    begin = lambda: self.cli('begin-redraw', {
                        'identifier': group['id'], 'viewed_notes': 'Controlled input review.'})
                else:
                    owner = {'workflow': score_workflow, 'task': score_task}[entry]
                    checks = owner.crop_checks(self.task)
                    begin = lambda: owner.begin_redraw(
                        self.task, group['id'], viewed_notes='Controlled input review.')
                self.assertEqual(checks['status'], 'blocked')
                self.assertIn('crop_edge', [issue['code'] for issue in checks['issues']])
                with self.assertRaises(score_task.ReconstructionError):
                    begin()
                self.assertEqual(score_task.load(self.task), before)
        reconstruction.assemble(self.task, 'Cut stem', original['regions'], original['source_review'])
        repaired = score_task.redraw_inputs(self.task)[0]
        self.assertEqual(score_task.crop_checks(self.task)['status'], 'passed')
        score_task.begin_redraw(self.task, repaired['id'], viewed_notes='Controlled repaired review.')

    def test_manual_stem_endpoint_touching_boundary_is_reported(self):
        self.select()
        original = score_task.load(self.task)
        regions = copy.deepcopy(original['regions'])
        regions[1]['bbox'][1] = 85
        regions[1]['staff_top'] = 15
        reconstruction.assemble(self.task, 'Touching stem', regions, original['source_review'])
        for entry in CROP_ENTRIES:
            with self.subTest(entry=entry):
                if entry == 'cli':
                    checks = self.cli('crop-checks', {})
                else:
                    owner = {'workflow': score_workflow, 'task': score_task}[entry]
                    checks = owner.crop_checks(self.task)
                self.assertEqual(checks['status'], 'blocked')
                self.assertIn('top', checks['issues'][0]['edges'])

    def test_every_request_entry_keeps_all_groups_and_preserves_dispatch_state(self):
        self.select()
        score_task.redraw_inputs(self.task, groups=[[0], [1]])
        baseline = score_task.load(self.task)
        for entry in REQUEST_ENTRIES:
            with self.subTest(entry=entry):
                score_task.save(self.task, copy.deepcopy(baseline))
                owner = {'workflow': score_workflow, 'task': score_task}.get(entry)
                def call(operation, payload):
                    if entry == 'cli':
                        return self.cli(operation, payload)
                    return getattr(owner, operation.replace('-', '_'))(self.task, **payload)
                batch = call('redraw-requests', {'viewed_notes': 'Controlled complete input review.'})
                self.assertEqual(batch['group_count'], 2)
                self.assertEqual([h['group'] for h in batch['handoffs']], ['page-1', 'page-2'])
                self.assertEqual(call('redraw-requests', {}), batch)
                request = batch['handoffs'][0]['request']['request']
                call('dispatch-redraw', {'identifier': 'page-1', 'request': request})
                with self.assertRaises(score_task.ReconstructionError):
                    call('cancel-redraw', {'identifier': 'page-1', 'request': request, 'notes': 'Unknown result.'})
                self.assertEqual(call('redraw-requests', {})['handoffs'][0]['status'], 'recover_existing_call')
                pending = batch['handoffs'][1]['request']['request']
                call('cancel-redraw', {'identifier': 'page-2', 'request': pending, 'notes': 'Not submitted.'})
                self.assertEqual(score_task.load(self.task)['redraw_pages'][1]['attempts'][-1]['status'], 'cancelled')

    def test_batch_rejects_duplicate_request_ids_and_wrong_input_hash(self):
        self.select()
        score_task.redraw_inputs(self.task, groups=[[0], [1]])
        score_task.redraw_requests(self.task, viewed_notes='Controlled batch input review.')
        baseline = score_task.load(self.task)
        for entry in REQUEST_ENTRIES:
            for corruption in ('duplicate_id', 'wrong_hash'):
                with self.subTest(entry=entry, corruption=corruption):
                    record = copy.deepcopy(baseline)
                    attempt = record['redraw_pages'][1]['attempts'][-1]
                    if corruption == 'duplicate_id':
                        attempt['request'] = record['redraw_pages'][0]['attempts'][-1]['request']
                    else:
                        attempt['input_sha256'] = '0' * 64
                    score_task.save(self.task, record)
                    with self.assertRaises(score_task.ReconstructionError):
                        if entry == 'cli':
                            self.cli('redraw-requests', {})
                        else:
                            owner = {'workflow': score_workflow, 'task': score_task}[entry]
                            owner.redraw_requests(self.task)

    def test_every_export_obeys_layout_and_every_review_binds_current_previews(self):
        self.select()
        for group in score_workflow.redraw_inputs(self.task):
            score_workflow.fail_redraw(self.task, group['id'], 'Controlled unavailable host.')
        self.cli('layout', {'margin': 32, 'minimum_gap': 40})
        baseline = score_task.load(self.task)
        for export_entry in EXPORT_ENTRIES:
            score_task.save(self.task, copy.deepcopy(baseline))
            old = self.export(export_entry)
            self.cli('layout', {'margin': 32, 'minimum_gap': 40, 'target_pages': 512})
            fresh = self.export(export_entry)
            with self.subTest(export=export_entry):
                self.assertEqual(old['sha256'], fresh['sha256'])
                self.assertNotEqual(old['output_revision'], fresh['output_revision'])
                self.assertTrue((self.task / old['pdf']).is_file())
                self.assertEqual(fresh['placements'][0]['bbox'][0], 32)
                self.assertEqual(fresh['checks']['status'], 'passed')
                self.assertEqual([p['page'] for p in fresh['previews']],
                    list(range(1, fresh['page_count'] + 1)))
            pristine = score_task.load(self.task)
            valid = {'pages': list(range(1, fresh['page_count'] + 1)),
                'notes': 'Controlled offline page review.', 'output_revision': fresh['output_revision']}
            for review_entry in REVIEW_ENTRIES:
                for fault in ('omitted', 'old', 'hash', 'missing-page', 'missing-previews',
                              'missing-checks', 'corrupt-preview'):
                    with self.subTest(export=export_entry, review=review_entry, fault=fault):
                        record, payload = copy.deepcopy(pristine), dict(valid)
                        if fault == 'omitted':
                            payload.pop('output_revision')
                        elif fault in ('old', 'hash'):
                            payload['output_revision'] = old['output_revision'] if fault == 'old' else fresh['sha256']
                        elif fault == 'missing-page':
                            payload['pages'] = []
                        elif fault in ('missing-previews', 'missing-checks'):
                            record['output'].pop(fault.removeprefix('missing-'))
                        else:
                            record['output']['previews'][0]['sha256'] = '0' * 64
                        score_task.save(self.task, record)
                        with self.assertRaises(score_task.ReconstructionError):
                            self.review(review_entry, payload)
                        saved = json.loads((self.task / 'record.json').read_text())
                        self.assertEqual(saved['output']['status'], 'needs_pdf_review')
                score_task.save(self.task, copy.deepcopy(pristine))
                with self.subTest(export=export_entry, review=review_entry, fault='none'):
                    approved = self.review(review_entry, valid)
                    self.assertEqual(approved['status'], 'reviewed')
                    self.assertEqual(approved['review']['preview_hashes'], [p['sha256'] for p in fresh['previews']])

    def test_every_group_entry_splits_defaults_and_rejects_new_oversized_or_unreadable_groups(self):
        import automatic_score
        self.select()
        baseline = score_task.load(self.task)
        system = baseline['regions'][1]
        for entry in GROUP_ENTRIES:
            for case in ('default', 'explicit-oversized', 'default-unreadable', 'explicit-unreadable'):
                with self.subTest(entry=entry, case=case):
                    record = copy.deepcopy(baseline)
                    rows = [dict(system, position=f'ordered-{i}') for i in range(9)]
                    if 'unreadable' in case:
                        rows = [dict(system, staff_spacing=3)]
                    record['regions'] = rows
                    automatic_score.freeze(record, 'agent')
                    score_task.save(self.task, record)
                    groups = [list(range(len(rows)))] if case.startswith('explicit') else None
                    if case == 'default':
                        result = self.groups(entry, groups)
                        self.assertEqual([i for group in result for i in group['regions']], list(range(9)))
                        self.assertTrue(all(len(group['regions']) <= 8 for group in result))
                    else:
                        with self.assertRaises(score_task.ReconstructionError):
                            self.groups(entry, groups)
                        self.assertEqual(score_task.load(self.task), record)


if __name__ == '__main__':
    unittest.main()
