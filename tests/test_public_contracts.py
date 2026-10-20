"""Public entry matrix for shared invariants; all review notes are fixtures."""
import copy
import json
import subprocess
import sys
import unittest

import test_reconstruction as fixtures
from score_fixtures import CLI, controlled_reselection
from test_host_check import HOST_CHECK_ENTRIES
import reconstruction
import longshot
import score_task
import score_workflow


ACQUISITION_ENTRIES = ('cli', 'workflow', 'acquire')
EXPORT_ENTRIES = ('cli', 'workflow', 'vector')
REVIEW_ENTRIES = ('cli', 'workflow', 'vector', 'task')
GROUP_ENTRIES = ('cli', 'workflow', 'task')
CROP_ENTRIES = ('cli', 'workflow', 'task')
REQUEST_ENTRIES = ('cli', 'workflow', 'task')
SOURCE_ASSEMBLY_ENTRIES = ('cli', 'workflow', 'task', 'vector')
SOURCE_RECOVERY_ENTRIES = ('cli', 'workflow')
LONGSHOT_ENTRIES = ('cli', 'workflow')
DIRECT_EXPORT_ENTRIES = ('cli', 'workflow')
PRINT_MUTATION_ENTRIES = ('cli', 'workflow', 'module')


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

    def test_longshot_entries_share_overall_review_and_source_integrity_contracts(self):
        for entry in LONGSHOT_ENTRIES:
            with self.subTest(entry=entry):
                self.task = self.root / ('longshot-' + entry)
                score_workflow.prepare(self.video, self.task)
                def call(operation, payload):
                    if entry == 'cli':
                        return self.cli(operation, payload)
                    return getattr(score_workflow, operation.replace('-', '_'))(self.task, **payload)
                stitched = call('stitch', {})
                with self.assertRaises(score_task.ReconstructionError):
                    call('review-longshot', {'title': 'Fixture', 'notes': ''})
                call('review-longshot', {'title': 'Fixture', 'notes': 'Controlled overall review.', 'accepted': False})
                with self.assertRaises(score_task.ReconstructionError):
                    score_workflow.redraw_requests(self.task)
                call('review-longshot', {'title': 'Fixture', 'notes': 'Controlled acceptance with local ambiguity.'})
                self.assertEqual(score_workflow.stage(self.task)['phase'], 'pdf_review')
                before = (self.task / 'record.json').read_bytes()
                (self.task / stitched['samples']['path']).write_text('controlled corrupted source mapping')
                with self.assertRaises(score_task.ReconstructionError):
                    call('review-longshot', {'title': 'Fixture', 'notes': 'Must refuse corrupt provenance.'})
                self.assertEqual((self.task / 'record.json').read_bytes(), before)

    def test_removed_routes_and_stage_modes_cannot_mutate_existing_task(self):
        self.select()
        before = (self.task / 'record.json').read_bytes()
        for operation in ('overview', 'resample', 'auto-freeze', 'scan-status', 'row-manifest',
                          'review-row-anchors', 'review-continuity', 'source-issues',
                          'include-candidate', 'review-overlap', 'midi-request', 'midi-submit',
                          'midi-playable', 'midi-export', 'midi-resume'):
            with self.subTest(operation=operation), self.assertRaises(score_task.ReconstructionError):
                self.cli(operation, {})
            self.assertEqual((self.task / 'record.json').read_bytes(), before)

        for mode in ('sparse', 'strict'):
            with self.subTest(mode=mode), self.assertRaises(score_task.ReconstructionError):
                self.cli('stage', {'mode': mode})
            self.assertEqual((self.task / 'record.json').read_bytes(), before)

    def test_print_mutations_share_boundaries_and_source_integrity(self):
        for entry in PRINT_MUTATION_ENTRIES:
            with self.subTest(entry=entry):
                self.task = self.root / ('print-mutation-' + entry)
                score_workflow.prepare(self.video, self.task)
                score_workflow.stitch(self.task)
                record = score_workflow.review_longshot(self.task, 'Print', 'Controlled source view.')
                shot = score_workflow.capture(self.task, 0)
                def call(operation, payload):
                    if entry == 'cli':
                        return self.cli(operation, payload)
                    if entry == 'module':
                        function = {'clean-watermark': longshot.clean_watermark,
                                    'repair-longshot': longshot.repair_longshot,
                                    'pdf-route': score_task.set_pdf_route, 'export': score_workflow.export}[operation]
                        return function(self.task, **payload)
                    return getattr(score_workflow, operation.replace('-', '_'))(self.task, **payload)
                source = record['longshot']['image']
                cleanup = {'rectangles': [[580, 20, 610, 30]], 'source_sha256': source['sha256'],
                           'notes': 'Controlled blank area.', 'confirmed_safe': True}
                repair = {'capture': shot['id'], 'bbox': [580, 20, 610, 30],
                          'target_bbox': [580, 20, 610, 30], 'source_sha256': source['sha256'],
                          'notes': 'Controlled source replacement.'}
                invalid = [
                    ('clean-watermark', {**cleanup, 'confirmed_safe': False}),
                    ('clean-watermark', {**cleanup, 'source_sha256': '0' * 64}),
                    ('clean-watermark', {**cleanup, 'rectangles': [[0, 0, 641, 30]]}),
                    ('clean-watermark', {**cleanup, 'rectangles': [[False, 0, 5, 5]]}),
                    ('clean-watermark', {**cleanup, 'notes': ''}),
                    ('repair-longshot', {**repair, 'capture': 'missing'}),
                    ('repair-longshot', {**repair, 'source_sha256': '0' * 64}),
                    ('repair-longshot', {**repair, 'bbox': [0, 0, 31, 10]}),
                    ('repair-longshot', {**repair, 'target_bbox': [0, 0, 700, 10]}),
                    ('pdf-route', {'route': 'unknown', 'notes': 'Controlled request.'}),
                    ('pdf-route', {'route': 'vector', 'notes': ''}),
                ]
                before = (self.task / 'record.json').read_bytes()
                for operation, payload in invalid:
                    with self.subTest(operation=operation, payload=payload), self.assertRaises(score_task.ReconstructionError):
                        call(operation, payload)
                    self.assertEqual((self.task / 'record.json').read_bytes(), before)
                cleaned = call('clean-watermark', cleanup)
                current = (self.task / 'record.json').read_bytes()
                (self.task / cleaned['image']['path']).write_bytes(b'controlled damaged cleanup')
                for operation, payload in [('clean-watermark', cleanup), ('repair-longshot', repair),
                                           ('pdf-route', {'route': 'vector', 'notes': 'Controlled request.'}),
                                           ('export', {})]:
                    with self.subTest(operation=operation), self.assertRaises(score_task.ReconstructionError):
                        call(operation, payload)
                    self.assertEqual((self.task / 'record.json').read_bytes(), current)

    def test_legacy_longshot_keeps_unknown_request_and_route_changes_wait_for_recovery(self):
        for entry in PRINT_MUTATION_ENTRIES:
            with self.subTest(entry=entry):
                self.task = self.root / ('legacy-route-' + entry)
                score_workflow.prepare(self.video, self.task)
                score_workflow.stitch(self.task)
                record = score_workflow.review_longshot(self.task, 'Legacy', 'Controlled historic review.')
                record.pop('pdf_route')
                score_task.save(self.task, record)
                first = score_workflow.stage(self.task)['handoffs'][0]
                request = first['request']['request']
                score_workflow.dispatch_redraw(self.task, first['group'], request)
                before = (self.task / 'record.json').read_bytes()
                payload = {'route': 'original', 'notes': 'Controlled request while call is unknown.'}
                with self.assertRaises(score_task.ReconstructionError):
                    if entry == 'cli':
                        self.cli('pdf-route', payload)
                    else:
                        function = score_task.set_pdf_route if entry == 'module' else score_workflow.pdf_route
                        function(self.task, **payload)
                self.assertEqual((self.task / 'record.json').read_bytes(), before)
                resumed = score_workflow.stage(self.task)['handoffs'][0]
                self.assertEqual(resumed['status'], 'recover_existing_call')
                self.assertEqual(resumed['request']['request'], request)

    def test_explicit_redraw_entries_select_route_and_expose_unknown_calls(self):
        for entry in REQUEST_ENTRIES:
            with self.subTest(entry=entry):
                self.task = self.root / ('explicit-redraw-' + entry)
                score_workflow.prepare(self.video, self.task)
                score_workflow.stitch(self.task)
                score_workflow.review_longshot(self.task, 'Explicit redraw', 'Controlled source view.')
                if entry == 'cli':
                    first = self.cli('redraw-requests', {})['handoffs'][0]
                else:
                    owner = score_workflow if entry == 'workflow' else score_task
                    first = owner.redraw_requests(self.task)['handoffs'][0]
                self.assertEqual(score_task.load(self.task)['pdf_route'], 'redraw')
                request = first['request']['request']
                score_workflow.dispatch_redraw(self.task, first['group'], request)
                resumed = score_workflow.stage(self.task)
                self.assertEqual(resumed['phase'], 'generation')
                self.assertEqual(resumed['handoffs'][0]['status'], 'recover_existing_call')
                self.assertEqual(resumed['handoffs'][0]['request']['request'], request)
                self.assertNotIn('output', score_task.load(self.task))
                # A partially upgraded historic record may still say original.
                record = score_task.load(self.task)
                record['pdf_route'] = 'original'
                score_task.save(self.task, record)
                recovered = score_workflow.stage(self.task)
                self.assertEqual(recovered['phase'], 'generation')
                self.assertEqual(recovered['handoffs'][0]['request']['request'], request)
                self.assertEqual(score_task.load(self.task)['pdf_route'], 'original')

    def test_manual_source_revision_preserves_explicit_vector_route(self):
        self.select()
        record = score_task.load(self.task)
        controlled_reselection(self.task, 'Vector source', record['regions'], record['source_review'])
        score_workflow.pdf_route(self.task, 'vector', 'Controlled explicit vector request.')
        score_workflow.revise_crop(self.task, 1, [0, 65, 640, 185])
        revised = score_task.load(self.task)
        self.assertEqual(revised['pdf_route'], 'vector')
        review = {**revised['source_review'], 'complete': True, 'unresolved': []}
        controlled_reselection(self.task, 'Vector source', revised['regions'], review)
        output = score_workflow.stage(self.task)['artifacts']['output']
        self.assertEqual(output['routes'], ['vector'])
        self.assertEqual(score_task.load(self.task)['redraw_pages'], [])

    def test_explicit_vector_export_selects_route_instead_of_being_replaced_by_stage(self):
        score_workflow.prepare(self.video, self.task)
        score_workflow.stitch(self.task)
        score_workflow.review_longshot(self.task, 'Explicit vector', 'Controlled source view.')
        output = reconstruction.export_vector(self.task)
        self.assertEqual(score_task.load(self.task)['pdf_route'], 'vector')
        staged = score_workflow.stage(self.task)['artifacts']['output']
        self.assertEqual(staged['output_revision'], output['output_revision'])
        self.assertEqual(staged['render_route'], 'vector')
    def test_windows_utf8_bom_request_uses_the_same_stage_contract(self):
        self.select()
        request = self.root / 'bom-request.json'
        request.write_text('{}', encoding='utf-8-sig')
        result = subprocess.run([sys.executable, str(CLI), '--operation', 'stage',
            '--task', str(self.task), '--request', str(request)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['phase'], 'generation')

    def test_source_recovery_entries_refuse_corrupt_sources_without_mutation(self):
        self.select()
        before = (self.task / 'record.json').read_bytes()
        self.video.write_bytes(b'Controlled damaged source.')
        operations = {'revise-selection': {'changes': []}, 'revise-crop': {'index': 0, 'bbox': [0, 0, 10, 10]}}
        for entry in SOURCE_RECOVERY_ENTRIES:
            for operation, payload in operations.items():
                with self.subTest(entry=entry, operation=operation), self.assertRaises(score_task.ReconstructionError):
                    if entry == 'cli':
                        self.cli(operation, payload)
                    else:
                        getattr(score_workflow, operation.replace('-', '_'))(self.task, **payload)
                self.assertEqual((self.task / 'record.json').read_bytes(), before)



    def test_manual_cut_stem_blocks_every_generation_entry_until_crop_is_repaired(self):
        self.select()
        original = score_task.load(self.task)
        regions = copy.deepcopy(original['regions'])
        regions[1]['bbox'][1] = 90
        regions[1]['staff_top'] = 10
        controlled_reselection(self.task, 'Cut stem', regions, original['source_review'])
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
        controlled_reselection(self.task, 'Cut stem', original['regions'], original['source_review'])
        repaired = score_task.redraw_inputs(self.task)[0]
        self.assertEqual(score_task.crop_checks(self.task)['status'], 'passed')
        score_task.begin_redraw(self.task, repaired['id'], viewed_notes='Controlled repaired review.')

    def test_manual_stem_endpoint_touching_boundary_is_reported(self):
        self.select()
        original = score_task.load(self.task)
        regions = copy.deepcopy(original['regions'])
        regions[1]['bbox'][1] = 85
        regions[1]['staff_top'] = 15
        controlled_reselection(self.task, 'Touching stem', regions, original['source_review'])
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
        self.check_exports_and_reviews(EXPORT_ENTRIES)

    def test_direct_exports_share_layout_and_current_page_review_contracts(self):
        score_workflow.prepare(self.video, self.task)
        score_workflow.stitch(self.task)
        score_workflow.review_longshot(self.task, 'Direct fixture', 'Controlled whole-image review.')
        self.cli('layout', {'margin': 32, 'minimum_gap': 40})
        self.check_exports_and_reviews(DIRECT_EXPORT_ENTRIES)
        self.assertEqual(score_task.load(self.task)['redraw_pages'], [])

    def check_exports_and_reviews(self, entries):
        baseline = score_task.load(self.task)
        for export_entry in entries:
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
                    score_task.freeze(record, 'agent')
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
