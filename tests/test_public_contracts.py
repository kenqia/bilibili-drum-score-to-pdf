"""Public entry matrix for shared invariants; all review notes are fixtures."""
import copy
import json
import subprocess
import sys
import unittest

import test_reconstruction as fixtures
from score_fixtures import CLI, controlled_reselection
from test_compact_layout import compact_fixture
from test_host_check import HOST_CHECK_ENTRIES
import reconstruction
import longshot
import score_task
import score_workflow


SCRIPT_CONVERSION_ENTRIES = ('script_core', 'script_cli')

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
LAYOUT_ENTRIES = ('cli', 'workflow', 'task')


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

    def test_continuous_layout_entries_refuse_invalid_cuts_without_revoking_output(self):
        score_workflow.prepare(self.video, self.task)
        score_workflow.stitch(self.task)
        score_workflow.review_longshot(self.task, 'Seam fixture', 'Controlled source review.')
        score_workflow.stage(self.task)
        record = score_task.load(self.task)
        height = record['longshot']['image']['height']
        ink = round(record['regions'][0]['bbox'][1] + record['regions'][0]['staff_top'])
        baseline = (self.task / 'record.json').read_bytes()
        for entry in LAYOUT_ENTRIES:
            for cuts in ([True], [0], [height], [height + 1], [1.5], [ink],
                         [1, 1], [height - 1, 1], 'bad'):
                with self.subTest(entry=entry, cuts=cuts), self.assertRaises(score_task.ReconstructionError):
                    if entry == 'cli':
                        self.cli('layout', {'page_breaks': cuts})
                    else:
                        owner = score_workflow if entry == 'workflow' else score_task
                        owner.layout(self.task, page_breaks=cuts)
                self.assertEqual((self.task / 'record.json').read_bytes(), baseline)
            if entry == 'cli':
                self.cli('layout', {'page_breaks': []})
            else:
                owner = score_workflow if entry == 'workflow' else score_task
                owner.layout(self.task, page_breaks=[])
            output = score_workflow.stage(self.task)['artifacts']['output']
            self.assertEqual(output['page_count'], 1)
            self.assertEqual(output['page_strips'][0]['bbox'][3], height)
            score_task.save(self.task, record)

    def test_direct_exports_share_layout_and_current_page_review_contracts(self):
        score_workflow.prepare(self.video, self.task)
        score_workflow.stitch(self.task)
        score_workflow.review_longshot(self.task, 'Direct fixture', 'Controlled whole-image review.')
        self.cli('layout', {'margin': 32, 'minimum_gap': 40})
        self.check_exports_and_reviews(DIRECT_EXPORT_ENTRIES)
        self.assertEqual(score_task.load(self.task)['redraw_pages'], [])

    def test_direct_export_entries_compact_without_resampling_or_moving_detached_marks(self):
        from PIL import Image, ImageDraw
        from score_fixtures import video_from_image
        fixture = compact_fixture(self.root)
        with Image.open(self.root / fixture['longshot']['image']['path']) as source:
            sheet = source.copy()
        draw = ImageDraw.Draw(sheet)
        draw.ellipse((380, 395, 390, 405), outline=0, width=2)
        draw.line((360, 440, 500, 430), fill=0, width=2)
        draw.line((360, 440, 500, 450), fill=0, width=2)
        video = video_from_image(sheet, self.root, 'compact')
        sheet.close()
        score_workflow.prepare(video, self.task)
        score_workflow.stitch(self.task)
        score_workflow.review_longshot(self.task, 'Compact fixture', 'Controlled source, not music acceptance.')
        baseline = score_task.load(self.task)
        for entry in DIRECT_EXPORT_ENTRIES:
            with self.subTest(entry=entry):
                score_task.save(self.task, copy.deepcopy(baseline))
                output = self.export(entry)
                self.assertEqual(output['page_count'], 2)
                self.assertGreaterEqual(output['print_scale_ratio'], .9)
                self.assertLess(output['print_scale_ratio'], 1)
                self.assertEqual(len({p['scale'] for p in output['placements']}), 1)
                self.assertIn('compact_print_size_needs_visual_review',
                              [w['code'] for w in output['checks']['warnings']])
                self.assertEqual(output['checks']['ordered_source_regions'], list(range(10)))
                self.assertEqual(score_task.load(self.task)['redraw_pages'], [])
                prefix = self.root / ('embedded-' + entry)
                subprocess.run(['pdfimages', '-f', '1', '-l', '1', '-png',
                                str(self.task / output['pdf']), str(prefix)], check=True, capture_output=True)
                native = baseline['longshot']['image']
                with Image.open(self.task / native['path']) as source, Image.open(str(prefix) + '-000.png') as embedded:
                    self.assertEqual(source.convert('L').tobytes(), embedded.convert('L').tobytes())
                    self.assertEqual(source.size, embedded.size)
                raster = self.root / ('raster-' + entry)
                subprocess.run(['pdftoppm', '-f', '1', '-l', '1', '-r', '144', '-png', '-singlefile',
                                str(self.task / output['pdf']), str(raster)], check=True, capture_output=True)
                placement = output['placements'][0]
                scale, left = placement['scale'] * 2, placement['bbox'][0] * 2
                with Image.open(raster.with_suffix('.png')) as page:
                    gray = page.convert('L')
                    for x, y in [(380, 400), (450, 434), (450, 446), (450, 480)]:
                        px, py = round(left + x * scale), round(48 + y * scale)
                        self.assertLess(gray.crop((px-3, py-3, px+4, py+4)).getextrema()[0], 120)
                    for y in range(20, 900, 20):
                        self.assertLess(gray.getpixel((round(left + 5 * scale), round(48 + y * scale))), 253)
                # v1 continuous PDFs must be retained and replaced, then reviewed again.
                record = score_task.load(self.task)
                record['output']['continuous_layout_version'] = 1
                score_task.save(self.task, record)
                fresh = score_workflow.stage(self.task)['artifacts']['output']
                self.assertNotEqual(fresh['output_revision'], output['output_revision'])
                self.assertEqual(fresh['status'], 'needs_pdf_review')
                self.assertTrue((self.task / output['pdf']).is_file())

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
                faults = ['omitted', 'old', 'hash', 'missing-page', 'missing-previews', 'missing-checks', 'corrupt-preview']
                if score_task.delivery_route(pristine) == 'original':
                    faults.extend(['missing-strips', 'strip-gap', 'strip-duplicate'])
                for fault in faults:
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
                        elif fault == 'missing-strips':
                            record['output'].pop('page_strips')
                        elif fault == 'strip-gap':
                            record['output']['page_strips'][0]['bbox'][1] = 1
                        elif fault == 'strip-duplicate':
                            record['output']['page_strips'][0]['source_regions'].append(0)
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


class ScriptPublicContracts(unittest.TestCase):
    def test_script_entries_keep_complete_result_when_temporary_cleanup_fails(self):
        from pathlib import Path
        import tempfile
        import shutil
        import contextlib
        import io
        from unittest.mock import patch
        from score_fixtures import score_frame, video_from_image
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root)
            remove_tree = shutil.rmtree
            def fail_after_removal(*args, **kwargs):
                remove_tree(*args, **kwargs)
                raise OSError('SYNTHETIC_PRIVATE_CLEANUP /private/synthetic')
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry), patch('shutil.rmtree', side_effect=fail_after_removal):
                    output = root / entry
                    if entry == 'script_core':
                        result = drum_score.convert(source, output)
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            self.assertEqual(main([str(source), '--output', str(output)]), 0)
                        result = json.loads(stream.getvalue())
                    self.assertEqual(result['status'], 'complete')
                    self.assertEqual(json.loads((output / 'manifest.json').read_text()), result)
                    self.assertTrue((output / result['pdf']['path']).is_file())
                    self.assertNotIn('SYNTHETIC_PRIVATE_CLEANUP', json.dumps(result))
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_normalize_temporary_allocation_errors(self):
        from pathlib import Path
        import tempfile
        import contextlib
        import io
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'synthetic source unchanged by allocation failure')
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry), patch('tempfile.mkdtemp',
                        side_effect=OSError('SYNTHETIC_PRIVATE_ALLOCATION /private/synthetic')):
                    output = root / entry
                    if entry == 'script_core':
                        with self.assertRaises(drum_score.ConversionError) as caught:
                            drum_score.convert(source, output)
                        code = caught.exception.code
                        diagnostic = str(caught.exception)
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            self.assertEqual(main([str(source), '--output', str(output)]), 2)
                        code = json.loads(stream.getvalue())['error']['code']
                        diagnostic = stream.getvalue()
                    self.assertEqual(code, 'conversion_failed')
                    self.assertNotIn('SYNTHETIC_PRIVATE_ALLOCATION', diagnostic)
                    self.assertNotIn('/private/synthetic', diagnostic)
                    self.assertFalse(output.exists())
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_preserve_specific_error_when_temporary_cleanup_fails(self):
        from pathlib import Path
        import tempfile
        import shutil
        import contextlib
        import io
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'invalid-video.mp4'
            source.write_bytes(b'synthetic invalid video')
            remove_tree = shutil.rmtree
            def fail_after_removal(*args, **kwargs):
                remove_tree(*args, **kwargs)
                raise OSError('SYNTHETIC_PRIVATE_CLEANUP /private/synthetic')
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry), patch('shutil.rmtree', side_effect=fail_after_removal):
                    output = root / entry
                    if entry == 'script_core':
                        with self.assertRaises(drum_score.ConversionError) as caught:
                            drum_score.convert(source, output)
                        code = caught.exception.code
                        diagnostic = str(caught.exception)
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            self.assertEqual(main([str(source), '--output', str(output)]), 2)
                        result = json.loads(stream.getvalue())
                        code = result['error']['code']
                        diagnostic = stream.getvalue()
                    self.assertEqual(code, 'invalid_input')
                    self.assertNotIn('SYNTHETIC_PRIVATE_CLEANUP', diagnostic)
                    self.assertNotIn(str(root), diagnostic)
                    self.assertFalse(output.exists())
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_normalize_output_parent_filesystem_errors(self):
        from pathlib import Path
        import tempfile
        import os
        from score_fixtures import score_frame, video_from_image
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root, name='private-source')
            before = source.read_bytes()
            output = source / 'result'
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry):
                    if entry == 'script_core':
                        with self.assertRaises(drum_score.ConversionError) as caught:
                            drum_score.convert(source, output)
                        code = caught.exception.code
                        diagnostic = str(caught.exception)
                    else:
                        process = subprocess.run([sys.executable, '-m', 'drum_score',
                            str(source), '--output', str(output)], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)})
                        self.assertEqual(process.returncode, 2, process.stderr)
                        result = json.loads(process.stdout)
                        self.assertEqual(result['status'], 'failed')
                        code = result['error']['code']
                        diagnostic = process.stdout + process.stderr
                    self.assertEqual(code, 'conversion_failed')
                    self.assertNotIn(str(root), diagnostic)
                    self.assertNotIn('private-source', diagnostic)
                    self.assertNotIn('Traceback', diagnostic)
                    self.assertEqual(source.read_bytes(), before)
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_apply_input_resource_limit_before_decoding(self):
        from pathlib import Path
        import tempfile
        import contextlib
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        for entry in SCRIPT_CONVERSION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'source.mp4'
                source.write_bytes(b'x' * 2048)
                output = root / 'result'
                if entry == 'script_core':
                    with self.assertRaises(drum_score.ConversionError) as caught:
                        drum_score.convert(source, output, limits={'input_bytes': 1024})
                    code = caught.exception.code
                else:
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        self.assertEqual(main([str(source), '--output', str(output),
                                               '--max-input-mib', str(1/1024)]), 2)
                    code = json.loads(stream.getvalue())['error']['code']
                self.assertEqual(code, 'resource_limit')
                self.assertFalse(output.exists())
                self.assertEqual(source.read_bytes(), b'x' * 2048)
                self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_reject_existing_paths_and_invalid_source(self):
        from pathlib import Path
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        import contextlib
        import io
        for entry in SCRIPT_CONVERSION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'source.mp4'
                source.write_bytes(b'invalid video')
                output = root / 'result'
                def invoke():
                    if entry == 'script_core':
                        try:
                            return drum_score.convert(source, output)
                        except drum_score.ConversionError as error:
                            return {'error': {'code': error.code}}
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        self.assertEqual(main([str(source), '--output', str(output)]), 2)
                    return json.loads(stream.getvalue())
                self.assertEqual(invoke()['error']['code'], 'invalid_input')
                self.assertFalse(output.exists())
                output.mkdir()
                (output / 'mine').write_bytes(b'keep')
                self.assertEqual(invoke()['error']['code'], 'output_exists')
                self.assertEqual((output / 'mine').read_bytes(), b'keep')
                self.assertEqual(source.read_bytes(), b'invalid video')


    def test_script_entries_publish_all_pages_or_no_result_for_black_input(self):
        from pathlib import Path
        import tempfile
        import contextlib
        import io
        from PIL import Image
        from score_fixtures import score_frame, video_from_image
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        for entry in SCRIPT_CONVERSION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for black in (False, True):
                    source = video_from_image(Image.new('RGB', (640, 520), 'black') if black
                                              else score_frame(), root, name=f'input-{black}')
                    before = source.read_bytes()
                    output = root / f'result-{black}'
                    if entry == 'script_core':
                        try:
                            result = drum_score.convert(source, output)
                        except drum_score.ConversionError as error:
                            result = {'status': 'failed', 'error': {'code': error.code}}
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            status = main([str(source), '--output', str(output)])
                        self.assertEqual(status, 2 if black else 0)
                        result = json.loads(stream.getvalue())
                    self.assertEqual(source.read_bytes(), before)
                    if black:
                        self.assertEqual(result['status'], 'failed')
                        self.assertEqual(result['error']['code'], 'unsupported_layout')
                        self.assertFalse(output.exists())
                    else:
                        self.assertEqual(result['status'], 'complete')
                        self.assertFalse(result['reliable'])
                        self.assertTrue(result['warnings'])
                        self.assertGreater(len(result['pages']), 0)
                        self.assertTrue((output / result['pdf']['path']).is_file())
                        for page in result['pages']:
                            self.assertTrue((output / page['path']).is_file())
