"""New reconstruction workflow boundary; fixtures are not visual acceptance."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills/bilibili-drum-score-to-pdf/scripts'))
import test_reconstruction as fixtures
import score_workflow as workflow

class ScoreWorkflow(unittest.TestCase):
    setUp = fixtures.LocalScoreWorkflow.setUp
    tearDown = fixtures.LocalScoreWorkflow.tearDown
    select = fixtures.LocalScoreWorkflow.select
    def assemble(self, task, title, regions, review, owner=workflow):
        from score_fixtures import controlled_source_review
        record = workflow.load(task)
        viewed = review['viewed_captures']
        if not set(viewed).issubset({i for p in record.get('presentations', []) for i in p['images']}):
            workflow.present(task, viewed, 'Controlled synthetic presentation.')
        review = controlled_source_review(regions, review)
        return owner.assemble(task, title, regions, review)

    def test_resolved_source_review_restores_same_selection_export(self):
        self.select()
        source=workflow.load(self.task)
        regions=[{**r,'position':str(i)} for i,r in enumerate(source['regions'])]
        review={**source['source_review'],'continuity':'Complete fixture.','first_last':'Whole fixture.'}
        blocked=self.assemble(self.task,source['title'],regions,{**review,'unresolved':['Hidden note needs review.']})
        self.assertEqual(blocked['status'],'needs_source_review')
        with self.assertRaises(workflow.ReconstructionError):
            workflow.redraw_inputs(self.task)
        resolved=self.assemble(self.task,source['title'],regions,{**review,'unresolved':[]})
        self.assertEqual(resolved['status'],'ready_to_redraw')
        page=workflow.redraw_inputs(self.task)[0]
        workflow.fail_redraw(self.task,page['id'],'No host tool in fixture.')
        self.assertEqual(workflow.export(self.task)['page_count'],1)

    def test_same_selection_withdrawal_preserves_consumed_correction(self):
        self.select();record=workflow.load(self.task)
        regions=[{**r,'position':str(i)} for i,r in enumerate(record['regions'])]
        review={**record['source_review'],'continuity':'Static source.','first_last':'Whole fixture.'}
        self.assemble(self.task,record['title'],regions,review)
        page=workflow.redraw_inputs(self.task)[0]
        for correction in (False,True):
            req=workflow.begin_redraw(self.task,page['id'],'Controlled reviewed input.',correction=correction)
            workflow.finish_redraw(self.task,page['id'],req['request'],self.root/'score.png','host-imagegen','fixture')
            workflow.review_redraw(self.task,page['id'],False,'Controlled refusal.')
        before=workflow.load(self.task)['redraw_pages']
        self.assemble(self.task,record['title'],regions,{**review,'unresolved':['New source question.']})
        with self.assertRaises(workflow.ReconstructionError):workflow.export(self.task)
        self.assemble(self.task,record['title'],regions,review)
        after=workflow.redraw_inputs(self.task)
        self.assertEqual(after,before)
        self.assertEqual(after[0]['corrections_used'],1)
        with self.assertRaises(workflow.ReconstructionError):
            workflow.begin_redraw(self.task,page['id'],'No second correction.',correction=True)

    def test_local_reselection_preserves_same_budget_and_invalidates_changed_material(self):
        self.select()
        selected = workflow.load(self.task)
        regions = [{**r, 'position': str(i)} for i, r in enumerate(selected['regions'])]
        review = {**selected['source_review'], 'continuity': 'Synthetic full systems.',
                  'first_last': 'Synthetic start and ending.'}
        self.assemble(self.task, selected['title'], regions, review)
        page = workflow.redraw_inputs(self.task)[0]
        for correction in (False, True):
            request = workflow.begin_redraw(self.task, page['id'], 'Synthetic input viewed.',
                correction=correction)
            workflow.finish_redraw(self.task, page['id'], request['request'],
                self.root / 'score.png', 'host-imagegen', 'controlled-fixture')
            workflow.review_redraw(self.task, page['id'], False, 'Synthetic rejection.')
        output = workflow.export(self.task)
        workflow.review_pdf(self.task, [1], 'Synthetic PDF reviewed.', output_revision=output['output_revision'])
        same = self.assemble(self.task, selected['title'], regions, review, owner=workflow.local)
        self.assertEqual(same['output']['sha256'], output['sha256'])
        self.assertEqual(same['output']['status'], 'reviewed')
        self.assertEqual(same['redraw_pages'][0]['corrections_used'], 1)
        changed = [{**regions[0], 'bbox': [0, 0, 640, 60]}, regions[1]]
        revised = self.assemble(self.task, selected['title'], changed, review, owner=workflow.local)
        self.assertNotIn('output', revised)
        self.assertEqual(revised['redraw_pages'], [])
        refreshed = workflow.redraw_inputs(self.task)[0]
        self.assertEqual(refreshed['corrections_used'], 0)
        self.assertNotEqual(refreshed['input']['sha256'], page['input']['sha256'])
        self.assertEqual((self.task / output['pdf']).is_file(), True)

    def test_default_generation_groups_are_independent_of_print_pages(self):
        self.select()
        record = workflow.load(self.task)
        regions = [record['regions'][0]] + [
            {**record['regions'][1], 'position': f'row-{i}'} for i in range(12)]
        review = {**record['source_review'], 'continuity': 'Ordered synthetic rows.',
            'first_last': 'Synthetic whole source.'}
        regions[0] = {**regions[0], 'position': 'title'}
        self.assemble(self.task, record['title'], regions, review)
        groups = workflow.redraw_inputs(self.task)
        self.assertEqual([p['regions'] for p in groups],
            [list(range(9)), list(range(9, 13))])

    def test_withdrawn_source_review_blocks_new_host_calls(self):
        self.select()
        record = workflow.load(self.task)
        regions = [{**r, 'position': str(i)} for i,r in enumerate(record['regions'])]
        review = {**record['source_review'], 'continuity': 'Synthetic source.',
            'first_last': 'Whole source.'}
        self.assemble(self.task, record['title'], regions, review)
        page = workflow.redraw_inputs(self.task)[0]
        self.assemble(self.task, record['title'], regions,
            {**review, 'unresolved': ['Hidden symbol.']})
        with self.assertRaises(workflow.ReconstructionError):
            workflow.begin_redraw(self.task, page['id'], 'Must not call tool.')

    def test_interrupted_capture_publication_preserves_orphan_and_can_resume(self):
        workflow.prepare(self.video, self.task)
        original_replace = Path.replace
        calls = 0
        def interrupt_final_publish(temporary, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('Controlled publication interruption')
            return original_replace(temporary, target)
        with patch.object(Path, 'replace', autospec=True, side_effect=interrupt_final_publish):
            with self.assertRaises(RuntimeError):
                workflow.capture(self.task, 0)
        orphan = self.task / 'captures/capture-0001.png'
        preserved = orphan.read_bytes()
        workflow.prepare(self.video, self.task)
        recovered = workflow.capture(self.task, 0)
        self.assertNotEqual(recovered['path'], str(orphan.relative_to(self.task)))
        self.assertEqual(orphan.read_bytes(), preserved)
        self.assertEqual(workflow.load(self.task)['captures'][0], recovered)

    def test_custom_redraw_group_cannot_bypass_pixel_limit(self):
        self.select();record=workflow.load(self.task)
        region=record['regions'][1]
        regions=[{**region,'position':str(i)} for i in range(4)]
        review={**record['source_review'],'continuity':'Repeated fixture.','first_last':'All systems.'}
        with patch.object(workflow.local,'ROUGH_PIXELS',100000):
            self.assemble(self.task,record['title'],regions,review)
            with self.assertRaises(workflow.ReconstructionError):
                workflow.redraw_inputs(self.task,[[0,1,2,3]])
            pages=workflow.redraw_inputs(self.task)
            self.assertEqual(len(pages),4)

    def test_late_notation_rejection_invalidates_approved_pdf_and_preserves_one_correction(self):
        self.select()
        original = workflow.load(self.task)
        selections = [{**r, 'position': str(i)} for i, r in enumerate(original['regions'])]
        review = {**original['source_review'], 'continuity': 'Complete fixture.', 'first_last': 'Start and ending.'}
        self.assemble(self.task, original['title'], selections, review)
        page = workflow.redraw_inputs(self.task)[0]
        request = workflow.begin_redraw(self.task, page['id'], 'Fixture viewed.')
        workflow.finish_redraw(self.task, page['id'], request['request'], self.root / 'score.png', 'host-imagegen', 'fixture')
        workflow.review_redraw(self.task, page['id'], True, 'Accepted fixture.', [[0,0,640,65], [0,65,640,180]])
        output = workflow.export(self.task)
        workflow.review_pdf(self.task, [1], 'Fixture PDF viewed.', output_revision=output['output_revision'])
        old_pdf = (self.task / output['pdf']).read_bytes()
        before = (self.task / 'record.json').read_bytes()
        with self.assertRaises(workflow.ReconstructionError):
            workflow.reject_accepted_redraw(self.task, page['id'], '   ')
        self.assertEqual((self.task / 'record.json').read_bytes(), before)
        rejected = workflow.reject_accepted_redraw(self.task, page['id'], 'Independent check: crossed hi-hat head replaced with kick oval.')
        self.assertEqual(rejected['status'], 'needs_correction')
        self.assertEqual(rejected['corrections_used'], 0)
        self.assertEqual(len(rejected['attempts']), 1)
        self.assertEqual(len(rejected['reviews']), 1)
        self.assertEqual(rejected['rejections'][0]['output'], rejected['output'])
        self.assertEqual(rejected['rejections'][0]['pdf']['status'], 'reviewed')
        self.assertNotIn('output', workflow.load(self.task))
        self.assertEqual((self.task / output['pdf']).read_bytes(), old_pdf)
        with self.assertRaises(workflow.ReconstructionError):
            workflow.export(self.task)
        with self.assertRaises(workflow.ReconstructionError):
            workflow.review_pdf(self.task, [1], 'Cannot approve rejected output.', output_revision=output['output_revision'])
        workflow.prepare(self.video, self.task)
        self.assemble(self.task, original['title'], selections, review)
        correction = workflow.begin_redraw(self.task, page['id'], 'Restore crossed head.', correction=True)
        workflow.prepare(self.video, self.task)
        self.assemble(self.task, original['title'], selections, review)
        self.assertEqual(workflow.redraw_inputs(self.task)[0]['corrections_used'], 1)
        with self.assertRaises(workflow.ReconstructionError):
            workflow.begin_redraw(self.task, page['id'], 'Second correction forbidden.', correction=True)
        workflow.finish_redraw(self.task, page['id'], correction['request'], self.root / 'score.png', 'host-imagegen', 'corrected-fixture')
        workflow.review_redraw(self.task, page['id'], True, 'Corrected fixture.', [[0,0,640,65], [0,65,640,180]])
        corrected = workflow.export(self.task)
        self.assertNotEqual(corrected['pdf'], output['pdf'])
        self.assertEqual(corrected['status'], 'needs_pdf_review')

    def test_late_rejection_after_consumed_correction_exports_vector_without_budget_reset(self):
        self.select()
        page = workflow.redraw_inputs(self.task)[0]
        request = workflow.begin_redraw(self.task, page['id'], 'Fixture viewed.')
        workflow.finish_redraw(self.task, page['id'], request['request'], self.root / 'score.png', 'host-imagegen', 'fixture')
        workflow.review_redraw(self.task, page['id'], False, 'Crossed head lost.')
        correction = workflow.begin_redraw(self.task, page['id'], 'Restore crossed head.', correction=True)
        workflow.finish_redraw(self.task, page['id'], correction['request'], self.root / 'score.png', 'host-imagegen', 'corrected-fixture')
        workflow.review_redraw(self.task, page['id'], True, 'Corrected fixture accepted.', [[0,0,640,65], [0,65,640,180]])
        old_output = workflow.export(self.task)
        workflow.review_pdf(self.task, [1], 'Fixture PDF viewed.', output_revision=old_output['output_revision'])
        rejected = workflow.reject_accepted_redraw(self.task, page['id'], 'Independent check: dotted crossed head lost its dot.')
        self.assertEqual(rejected['status'], 'vector')
        self.assertEqual(rejected['corrections_used'], 1)
        self.assertEqual(len(rejected['attempts']), 2)
        self.assertEqual(len(rejected['reviews']), 2)
        with self.assertRaises(workflow.ReconstructionError):
            workflow.reject_accepted_redraw(self.task, page['id'], 'Duplicate rejection.')
        workflow.prepare(self.video, self.task)
        self.assertEqual(workflow.redraw_inputs(self.task)[0]['corrections_used'], 1)
        with self.assertRaises(workflow.ReconstructionError):
            workflow.begin_redraw(self.task, page['id'], 'Cannot reset budget.', correction=True)
        output = workflow.export(self.task)
        self.assertEqual(output['routes'], ['vector'])
        self.assertNotEqual(output['pdf'], old_output['pdf'])
        self.assertTrue((self.task / old_output['pdf']).exists())
        self.assertEqual(output['status'], 'needs_pdf_review')
        self.assertEqual(workflow.review_pdf(self.task, [1], 'Vector fixture checked.', output_revision=output['output_revision'])['status'], 'reviewed')

    def test_same_selection_resume_keeps_consumed_correction_and_accepted_output(self):
        self.select()
        original = workflow.load(self.task)
        selections = [{**r, 'position': str(i)} for i, r in enumerate(original['regions'])]
        review = {**original['source_review'], 'continuity': 'Complete fixture.', 'first_last': 'Start and ending.'}
        self.assemble(self.task, original['title'], selections, review)
        page = workflow.redraw_inputs(self.task)[0]
        request = workflow.begin_redraw(self.task, page['id'], 'Fixture viewed.')
        workflow.finish_redraw(self.task, page['id'], request['request'], self.root / 'score.png', 'host-imagegen', 'fixture')
        workflow.review_redraw(self.task, page['id'], False, 'Restore beam.')
        correction = workflow.begin_redraw(self.task, page['id'], 'Restore beam.', correction=True)
        self.assemble(self.task, original['title'], selections, review)
        self.assertEqual(workflow.load(self.task)['redraw_pages'][0]['corrections_used'], 1)
        workflow.finish_redraw(self.task, page['id'], correction['request'], self.root / 'score.png', 'host-imagegen', 'fixture-correction')
        workflow.review_redraw(self.task, page['id'], True, 'Accepted fixture.', [[0,0,640,65], [0,65,640,180]])
        output = workflow.export(self.task)
        self.assemble(self.task, original['title'], selections, review)
        self.assertEqual(workflow.export(self.task)['sha256'], output['sha256'])
        with self.assertRaises(workflow.ReconstructionError):
            workflow.fail_redraw(self.task, page['id'], 'Late failure must not downgrade accepted output.')

    def test_changed_selection_cannot_resume_old_accepted_redraw_after_interruption(self):
        self.select()
        original = workflow.load(self.task)
        selections = [{**r, 'position': str(i)} for i, r in enumerate(original['regions'])]
        review = {**original['source_review'], 'continuity': 'Complete fixture.', 'first_last': 'Start and ending.'}
        self.assemble(self.task, original['title'], selections, review)
        page = workflow.redraw_inputs(self.task)[0]
        request = workflow.begin_redraw(self.task, page['id'], 'Fixture viewed.')
        workflow.finish_redraw(self.task, page['id'], request['request'], self.root / 'score.png', 'host-imagegen', 'controlled-fixture')
        workflow.review_redraw(self.task, page['id'], True, 'Accepted fixture.', [[0,0,640,65], [0,65,640,180]])
        prior = (self.task / 'record.json').read_bytes()
        invalid = [{**selections[0], 'bbox': [0,0,641,65]}, selections[1]]
        with self.assertRaises(workflow.ReconstructionError):
            self.assemble(self.task, original['title'], invalid, review)
        self.assertEqual((self.task / 'record.json').read_bytes(), prior)
        selections[0] = {**selections[0], 'bbox': [0,0,640,60]}
        with patch.object(Path, 'replace', autospec=True,
                          side_effect=RuntimeError('Interrupted record publication')):
            with self.assertRaises(RuntimeError):
                self.assemble(self.task, original['title'], selections, review)
        self.assertEqual((self.task / 'record.json').read_bytes(), prior)
        self.assertEqual(workflow.load(self.task)['redraw_pages'][0]['status'], 'accepted')
        replace = Path.replace
        calls = 0
        def interrupted_replace(temporary, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('Interrupted publication')
            return replace(temporary, target)
        with patch.object(Path, 'replace', autospec=True, side_effect=interrupted_replace):
            self.assemble(self.task, original['title'], selections, review)
        self.assertEqual(calls, 1)
        resumed = workflow.load(self.task)
        self.assertEqual(resumed['regions'][0]['bbox'], [0,0,640,60])
        self.assertEqual(resumed['redraw_pages'], [])
        self.assemble(self.task, original['title'], selections, review)
        refreshed = workflow.redraw_inputs(self.task)[0]
        self.assertEqual(refreshed['status'], 'needs_generation')
        self.assertNotEqual(refreshed['input']['sha256'], page['input']['sha256'])

    def test_final_pdf_approval_rejects_corrupt_generated_or_navigation_artifacts(self):
        for corrupt in ('generated', 'navigation'):
            with self.subTest(artifact=corrupt):
                self.task = self.root / corrupt
                self.select()
                probe = workflow.navigate(self.task, 0)
                page = workflow.redraw_inputs(self.task)[0]
                request = workflow.begin_redraw(self.task, page['id'], 'Fixture viewed.')
                result = workflow.finish_redraw(self.task, page['id'], request['request'], self.root / 'score.png', 'host-imagegen', 'controlled-fixture')
                workflow.review_redraw(self.task, page['id'], True, 'Accepted fixture.', [[0,0,640,65], [0,65,640,180]])
                output = workflow.export(self.task)
                before = (self.task / 'record.json').read_bytes()
                reference = result['output'] if corrupt == 'generated' else probe
                (self.task / reference['path']).write_bytes(b'broken')
                with self.assertRaises(workflow.ReconstructionError):
                    workflow.review_pdf(self.task, [1], 'Final PDF fixture viewed.', output_revision=output['output_revision'])
                self.assertEqual((self.task / 'record.json').read_bytes(), before)

    def test_local_entry_validates_workflow_artifacts_before_resume_or_approval(self):
        self.select()
        probe = workflow.navigate(self.task, 0)
        page = workflow.redraw_inputs(self.task)[0]
        request = workflow.begin_redraw(self.task, page['id'], 'Synthetic input viewed.')
        generated = workflow.finish_redraw(self.task, page['id'], request['request'],
            self.root / 'score.png', 'host-imagegen', 'controlled-fixture')
        workflow.review_redraw(self.task, page['id'], True, 'Synthetic image accepted.',
            [[0, 0, 640, 65], [0, 65, 640, 180]])
        output = workflow.export(self.task)
        prior = (self.task / 'record.json').read_bytes()
        for reference in (probe, generated['output']):
            with self.subTest(artifact=reference['path']):
                path = self.task / reference['path']
                intact = path.read_bytes()
                path.write_bytes(b'synthetic corruption')
                try:
                    for action in (lambda: workflow.local.load(self.task),
                                   lambda: workflow.local.review_pdf(self.task, [1], 'Synthetic PDF review.', output_revision=output['output_revision'])):
                        with self.assertRaises(workflow.ReconstructionError):
                            action()
                    self.assertEqual((self.task / 'record.json').read_bytes(), prior)
                finally:
                    path.write_bytes(intact)

    def test_mixed_routes_preserve_long_score_order_and_unresolved_sources_block_export(self):
        self.select()
        original = workflow.load(self.task)
        selections = [{**original['regions'][0], 'position': 'title'}] + [
            {**original['regions'][1], 'position': f'row-{i}'} for i in range(12)]
        review = {**original['source_review'], 'continuity': 'Ordered full systems.', 'first_last': 'Complete fixture.'}
        self.assemble(self.task, 'Mixed score', selections, review)
        pages = workflow.redraw_inputs(self.task, [[0,1]] + [[i] for i in range(2,13)])
        request = workflow.begin_redraw(self.task, pages[0]['id'], 'Fixture rough viewed.')
        workflow.finish_redraw(self.task, pages[0]['id'], request['request'], self.root / 'score.png', 'host-imagegen', 'controlled-fixture')
        workflow.review_redraw(self.task, pages[0]['id'], True, 'Fixture accepted.', [[0,0,640,65], [0,65,640,180]])
        for page in pages[1:]:
            request = workflow.begin_redraw(self.task, page['id'], 'Fixture rough viewed.')
            workflow.fail_redraw(self.task, page['id'], 'Controlled tool call failure.')
        output = workflow.export(self.task)
        self.assertEqual(output['page_count'], 2)
        counts = [sum(p['page'] == page and p['region'] > 0 for p in output['placements']) for page in (1, 2)]
        self.assertLessEqual(abs(counts[0] - counts[1]), 1)
        self.assertEqual(output['routes'], ['imagegen'] + ['vector'] * 11)
        self.assertEqual([p['region'] for p in output['placements']], list(range(13)))
        record = self.assemble(self.task, 'Mixed score', selections,
            {**review, 'complete': False, 'unresolved': ['Unconfirmed ordered page transition.']})
        self.assertEqual(len(record['redraw_pages']),len(pages))
        with self.assertRaises(workflow.ReconstructionError):
            workflow.redraw_inputs(self.task)

    def test_generated_pages_with_different_native_resolutions_share_source_print_width(self):
        self.select()
        original = workflow.load(self.task)
        selections = [{**original['regions'][1], 'position': f'row-{i}'} for i in range(2)]
        review = {**original['source_review'], 'continuity': 'Two complete systems.', 'first_last': 'Complete fixture.'}
        self.assemble(self.task, 'Resolution fixture', selections, review)
        pages = workflow.redraw_inputs(self.task, [[0], [1]])
        for page, size, box in zip(pages, [(640,320),(320,160)], [[0,65,640,180],[0,32,320,90]]):
            image = self.root / (page['id'] + '.png')
            with fixtures.Image.open(self.root / 'score.png') as source:
                source.resize(size).save(image)
            request = workflow.begin_redraw(self.task, page['id'], 'Fixture viewed.')
            workflow.finish_redraw(self.task, page['id'], request['request'], image, 'host-imagegen', 'controlled-fixture')
            workflow.review_redraw(self.task, page['id'], True, 'Fixture accepted.', [box])
        output = workflow.export(self.task)
        widths = [p['bbox'][2]-p['bbox'][0] for p in output['placements']]
        self.assertAlmostEqual(widths[0], widths[1])
        second = output['placements'][1]
        self.assertAlmostEqual((second['bbox'][3]-second['bbox'][1]) / widths[1], 58/320)
        import subprocess
        listed = subprocess.run(['pdfimages', '-list', str(self.task / output['pdf'])], check=True, capture_output=True, text=True).stdout
        self.assertIn('640   320', listed)
        self.assertIn('320   160', listed)

    def test_url_resume_normalizes_equivalent_public_urls_without_acquisition(self):
        url = 'https://www.bilibili.com/video/BV15crrYUEPA/'
        with patch.object(workflow, 'acquire', return_value=(self.video, workflow.video_origin(url))) as acquire:
            workflow.prepare(url, self.task)
            workflow.prepare(url, self.task)
            workflow.prepare(url + '?p=1', self.task)
        self.assertEqual(acquire.call_count, 1)

    def test_large_rough_is_chunked_without_dropping_systems(self):
        self.select()
        record = workflow.load(self.task)
        selections = []
        for i in range(4):
            selections.append({**record['regions'][1], 'position': str(i)})
        with patch.object(workflow.local, 'ROUGH_PIXELS', 100_000, create=True):
            record = self.assemble(self.task, 'Long fixture', selections,
                {**record['source_review'], 'continuity': 'Distinct later positions.', 'first_last': 'Entire fixture.'})
        self.assertEqual(len(record['rough_chunks']), 4)
        self.assertEqual(len(record['regions']), 4)
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
        review = {'viewed_captures': [first['id'], last['id']], 'complete': True,
                  'notes': 'Controlled overlap choice.', 'continuity': 'Controlled.', 'first_last': 'Controlled.'}
        with self.assertRaises(workflow.ReconstructionError):
            self.assemble(self.task, 'Repeated score', selections, review)
        # The Agent explicitly chooses the preferred first source for this position.
        selections = [selections[0], selections[1], selections[3]]
        record = self.assemble(self.task, 'Repeated score', selections,
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
        self.assertEqual(workflow.review_pdf(self.task, [1], 'Fixture page reviewed.', output_revision=output['output_revision'])['status'], 'reviewed')
        (self.task / workflow.load(self.task)['redraw_pages'][0]['output']['path']).write_bytes(b'broken')
        with self.assertRaises(workflow.ReconstructionError):
            workflow.export(self.task)
