"""New Agent contracts at public boundaries; all review assertions are fixtures."""
import copy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_reconstruction as fixtures
from score_fixtures import CLI, controlled_source_review
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
        review = controlled_source_review(rows, {'viewed_captures': [shot['id']], 'complete': True,
            'notes': 'Controlled source.', 'continuity': 'Controlled sequence.', 'first_last': 'Controlled endpoints.'})
        return shot, rows, review

    def test_default_agent_stage_never_collects_or_approves_sources(self):
        workflow.prepare(self.video, self.task)
        before = (self.task / 'record.json').read_bytes()
        with patch('sparse_navigation.collect', side_effect=AssertionError('unexpected sparse scan')), \
             patch('automatic_score.overview', side_effect=AssertionError('unexpected strict scan')), \
             patch('automatic_score.auto_freeze', side_effect=AssertionError('unexpected automatic approval')):
            for _ in range(2):
                result = workflow.stage(self.task)
                self.assertEqual(result['phase'], 'source')
                self.assertEqual(result['next']['request'], {'seconds': 0})
                self.assertFalse(result['provenance']['reviewed'])
                self.assertFalse(result['provenance']['strict_time_coverage'])
        self.assertEqual((self.task / 'record.json').read_bytes(), before)
        self.assertEqual(workflow.load(self.task)['captures'], [])

    def test_new_review_requires_present_and_source_bound_endpoints(self):
        shot, rows, review = self.source()
        from test_public_contracts import SOURCE_ASSEMBLY_ENTRIES
        for review_entry in SOURCE_ASSEMBLY_ENTRIES:
            with self.subTest(entry=review_entry):
                if review_entry == 'cli':
                    request = self.root / 'source-request.json'
                    request.write_text(json.dumps({'title': 'Synthetic', 'regions': rows, 'review': review}), encoding='utf-8')
                    result = subprocess.run([sys.executable, str(CLI), '--task', str(self.task),
                        '--operation', 'assemble', '--request', str(request)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(json.loads(result.stdout)['error']['code'], 'source_review_required')
                else:
                    owner = {'workflow': workflow, 'task': score_task, 'vector': workflow.local}[review_entry]
                    with self.assertRaises(score_task.ReconstructionError):
                        owner.assemble(self.task, 'Synthetic', rows, review)
        workflow.present(self.task, [shot['id']], 'Controlled actual-view assertion.')
        for field in ('title', 'first', 'last', 'joins'):
            broken = copy.deepcopy(review)
            broken['evidence'].pop(field)
            with self.subTest(field=field), self.assertRaises(score_task.ReconstructionError):
                workflow.assemble(self.task, 'Synthetic', rows, broken)
        stale = copy.deepcopy(review)
        stale['evidence']['last']['bbox'][3] += 1
        with self.assertRaises(score_task.ReconstructionError):
            workflow.assemble(self.task, 'Synthetic', rows, stale)
        record = workflow.assemble(self.task, 'Synthetic', rows, review)
        self.assertEqual(record['freeze']['producer'], 'agent')
        self.assertEqual(workflow.stage(self.task)['phase'], 'generation')

    def test_manual_success_path_skips_scans_and_requires_current_pdf_revision(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled source-view assertion.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        with patch('sparse_navigation.collect', side_effect=AssertionError('unexpected scan')):
            groups = workflow.redraw_inputs(self.task)
            for group in groups:
                workflow.fail_redraw(self.task, group['id'], 'Synthetic host has no image generation.', outcome='unavailable')
            result = workflow.stage(self.task)
            self.assertEqual(result['phase'], 'pdf_review')
            output = result['artifacts']['output']
            self.assertEqual(output['routes'], ['vector'])
            record = workflow.load(self.task)
            self.assertEqual(record['redraw_pages'][0]['attempts'], [])
            self.assertEqual(len(output['previews']), output['page_count'])
            workflow.review_pdf(self.task, list(range(1, output['page_count'] + 1)),
                'Controlled PDF receipt, not an actual human view.', output_revision=output['output_revision'])
            self.assertEqual(workflow.stage(self.task)['phase'], 'complete')

    def test_automatic_doubts_need_individual_dispositions_and_remain_in_original_record(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled presentation.')
        record = workflow.load(self.task)
        original_issue = {'code': 'native_difference_needs_visual_review', 'capture': shot['id']}
        record['program_checks'] = {'unresolved': [original_issue]}
        score_task.save(self.task, record)
        with self.assertRaises(score_task.ReconstructionError):
            workflow.assemble(self.task, 'Synthetic', rows, review)
        inventory = workflow.source_issues(self.task)['issues']
        review['issue_dispositions'] = [{'id': item['id'], 'outcome': 'resolved', 'captures': [shot['id']],
            'notes': 'Controlled fixture difference was checked against synthetic original.'} for item in inventory]
        record = workflow.assemble(self.task, 'Synthetic', rows, review)
        self.assertEqual(record['program_checks']['unresolved'], [original_issue])
        self.assertEqual(workflow.stage(self.task)['phase'], 'generation')
        self.assertEqual(workflow.source_issues(self.task)['issues'], inventory)

    def test_local_replacement_reuses_unaffected_group_and_recovers_unknown_attempt(self):
        shot, rows, review = self.source()
        rows.append({**rows[-1], 'position': 'row-2'})
        review = controlled_source_review(rows, review)
        workflow.present(self.task, [shot['id']], 'Controlled presentation.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        groups = workflow.redraw_inputs(self.task, groups=[[0, 1], [2]])
        attempt = workflow.begin_redraw(self.task, groups[0]['id'], 'Controlled input review.')
        workflow.fail_redraw(self.task, groups[1]['id'], 'Controlled unavailable tool.', outcome='unavailable')
        alternate = workflow.capture(self.task, .4)
        workflow.present(self.task, [alternate['id']], 'Controlled replacement view.')
        revised = copy.deepcopy(rows)
        revised[1]['capture'] = alternate['id']
        new_review = controlled_source_review(revised, {**review, 'viewed_captures': [shot['id'], alternate['id']]})
        patch_review = {'viewed_captures': new_review['viewed_captures'], 'evidence': {
            'first': new_review['evidence']['first'], 'joins': new_review['evidence']['joins']}}
        workflow.revise_selection(self.task, [{'position': 'row-1', 'region': revised[1]}], patch_review)
        changed = workflow.redraw_inputs(self.task)
        self.assertEqual(changed[0]['status'], 'needs_generation')
        self.assertEqual(changed[1]['status'], 'vector')
        workflow.revise_selection(self.task, [{'position': 'row-1', 'region': rows[1]}], {
            'evidence': {'first': review['evidence']['first'], 'joins': review['evidence']['joins']}})
        restored = workflow.redraw_inputs(self.task)
        self.assertEqual(restored[0]['status'], 'calling')
        self.assertEqual(restored[0]['attempts'][0]['request'], attempt['request'])
        self.assertEqual(restored[1]['status'], 'vector')

    def test_overlap_confirmation_keeps_both_sources_without_changing_selection(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled presentation.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        alternative = workflow.capture(self.task, .4)
        workflow.present(self.task, [alternative['id']], 'Controlled alternate view.')
        workflow.review_overlap(self.task, 'row-1', {**rows[1], 'capture': alternative['id']},
            [shot['id'], alternative['id']], 'Controlled same-position assertion.')
        manifest = workflow.row_manifest(self.task)
        self.assertEqual(len(manifest['rows']), 1)
        self.assertEqual(len(manifest['rows'][0]['sources']), 2)
        self.assertEqual(manifest['rows'][0]['selected']['capture'], shot['id'])
        included = workflow.include_candidate(self.task, alternative['id'], 'Controlled local candidate.')
        self.assertFalse(included['strict_time_coverage_added'])
        self.assertFalse(workflow.load(self.task)['overview']['scan']['complete'])
        with self.assertRaises(score_task.ReconstructionError):
            workflow.redraw_inputs(self.task)

    def test_legacy_frozen_task_is_reused_but_changed_workflow_selection_requires_new_evidence(self):
        fixtures.LocalScoreWorkflow.select(self)
        before = workflow.load(self.task)
        self.assertNotIn('agent_review_contract', before)
        with patch('sparse_navigation.collect', side_effect=AssertionError('unexpected scan')):
            self.assertEqual(workflow.stage(self.task)['phase'], 'generation')
        regions = [{**r, 'position': str(i)} for i, r in enumerate(before['regions'])]
        review = {**before['source_review'], 'continuity': 'Controlled.', 'first_last': 'Controlled.'}
        with self.assertRaises(score_task.ReconstructionError):
            workflow.assemble(self.task, before['title'], regions, review)

    def test_legacy_local_upgrade_is_enforced_at_every_assembly_entry(self):
        from test_public_contracts import SOURCE_ASSEMBLY_ENTRIES
        local = workflow.local
        local.prepare(self.video, self.task)
        shot = local.capture(self.task, 0)
        rows = [{'capture': shot['id'], 'bbox': [0, 0, 640, 65], 'kind': 'header', 'position': 'title'}]
        rows += [{'capture': shot['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system',
                  'staff_top': 35, 'staff_spacing': 10, 'position': str(i)} for i in range(3)]
        old_review = {'viewed_captures': [shot['id']], 'complete': True, 'notes': 'Controlled legacy approval.',
                      'continuity': 'Controlled order.', 'first_last': 'Controlled endpoints.'}
        local.assemble(self.task, 'Synthetic', rows, old_review)
        alternate = local.capture(self.task, .4)
        # Only the changed source has a new present receipt. Old sources retain approval.
        workflow.present(self.task, [alternate['id']], 'Controlled replacement view.')
        baseline = workflow.load(self.task)
        revised = copy.deepcopy(rows)
        revised[2]['capture'] = alternate['id']
        complete = controlled_source_review(revised, {**old_review,
            'viewed_captures': [shot['id'], alternate['id']]})
        partial = {**complete, 'evidence': {'joins': complete['evidence']['joins']}}
        for entry in SOURCE_ASSEMBLY_ENTRIES:
            def assemble(review):
                if entry == 'cli':
                    request = self.root / 'legacy-request.json'
                    request.write_text(json.dumps({'title': 'Synthetic', 'regions': revised, 'review': review}), encoding='utf-8')
                    result = subprocess.run([sys.executable, str(CLI), '--task', str(self.task),
                        '--operation', 'assemble', '--request', str(request)], capture_output=True, text=True)
                    if result.returncode:
                        raise score_task.ReconstructionError(result.stdout)
                    return json.loads(result.stdout)
                owner = {'workflow': workflow, 'task': score_task, 'vector': local}[entry]
                return owner.assemble(self.task, 'Synthetic', revised, review)
            with self.subTest(entry=entry):
                score_task.save(self.task, copy.deepcopy(baseline))
                with self.assertRaises(score_task.ReconstructionError):
                    assemble({**old_review, 'viewed_captures': complete['viewed_captures']})
                self.assertEqual(workflow.load(self.task), baseline)
                assemble(partial)
                from automatic_score import require_frozen
                require_frozen(workflow.load(self.task))
                broken = copy.deepcopy(partial)
                broken['evidence']['joins'].pop()
                with self.assertRaises(score_task.ReconstructionError):
                    assemble(broken)

    def test_legacy_trimmed_endpoints_require_new_endpoint_evidence(self):
        local = workflow.local
        local.prepare(self.video, self.task)
        shot = local.capture(self.task, 0)
        rows = [{'capture': shot['id'], 'bbox': [0, 0, 640, 65], 'kind': 'header', 'position': 'title'}]
        rows += [{'capture': shot['id'], 'bbox': [0, 65, 640, 180], 'kind': 'system',
                  'staff_top': 35, 'staff_spacing': 10, 'position': str(i)} for i in range(3)]
        review = {'viewed_captures': [shot['id']], 'complete': True, 'notes': 'Controlled legacy approval.',
                  'continuity': 'Controlled order.', 'first_last': 'Controlled endpoints.'}
        local.assemble(self.task, 'Synthetic', rows, review)
        baseline = workflow.load(self.task)
        for deleted in (1, 3):
            score_task.save(self.task, copy.deepcopy(baseline))
            revised = [r for i, r in enumerate(rows) if i != deleted]
            with self.subTest(deleted=deleted), self.assertRaises(score_task.ReconstructionError):
                workflow.assemble(self.task, 'Synthetic', revised, {**review, 'evidence': {'joins': []}})
            self.assertEqual(workflow.load(self.task), baseline)

    def test_legacy_crop_revision_becomes_pending_agent_review(self):
        fixtures.LocalScoreWorkflow.select(self)
        from automatic_score import revise_crop
        record = revise_crop(self.task, 1, [0, 64, 640, 180])
        self.assertEqual(record['status'], 'needs_source_review')
        self.assertFalse(record['source_review']['complete'])
        self.assertIn('agent_review_contract', record)
        with self.assertRaises(score_task.ReconstructionError):
            workflow.redraw_inputs(self.task)
        self.assertEqual(workflow.stage(self.task)['phase'], 'source')

    def test_summary_counts_all_public_issue_shapes(self):
        from convert import summary
        for payload in ({'issues': [{'code': 'crop_edge'}]},
                        {'checks': {'issues': [{'code': 'crop_edge'}]}},
                        {'unresolved': [{'code': 'unknown_join'}]}):
            with self.subTest(payload=payload):
                self.assertEqual(summary(payload)['issue_count'], 1)

    def test_malformed_local_review_is_a_source_error_and_does_not_publish(self):
        shot, rows, review = self.source()
        workflow.present(self.task, [shot['id']], 'Controlled view.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        before = (self.task / 'record.json').read_bytes()
        for patch in ({'evidence': {'joins': None}}, {'evidence': {'joins': [{}]}},
                      {'issue_dispositions': [None]}, {'evidence': []}):
            with self.subTest(patch=patch), self.assertRaises(score_task.ReconstructionError):
                workflow.revise_selection(self.task, [], patch)
            self.assertEqual((self.task / 'record.json').read_bytes(), before)

    def test_source_approval_does_not_override_a_cut_stem(self):
        shot, rows, review = self.source()
        rows[1]['bbox'][1], rows[1]['staff_top'] = 90, 10
        review = controlled_source_review(rows, review)
        workflow.present(self.task, [shot['id']], 'Controlled presentation.')
        workflow.assemble(self.task, 'Synthetic', rows, review)
        self.assertEqual(workflow.stage(self.task)['checks']['status'], 'blocked')
        with self.assertRaises(score_task.ReconstructionError):
            workflow.export(self.task)

    def test_summary_is_complete_pointer_and_preserves_full_default_json(self):
        workflow.prepare(self.video, self.task)
        command = [sys.executable, str(CLI), '--operation', 'stage', '--task', str(self.task)]
        full = json.loads(subprocess.check_output(command, text=True))
        compact = json.loads(subprocess.check_output(command + ['--summary'], text=True))
        details = json.loads((self.task / compact['details']['path']).read_text(encoding='utf-8'))
        self.assertEqual(details, full)
        self.assertEqual(compact['phase'], full['phase'])
        self.assertEqual(compact['issue_count'], len(full['unresolved']))
        self.assertFalse(compact['complete'])
        self.assertNotIn('review_template', compact['next'])

    def test_unexpected_error_is_internal_and_does_not_leak_synthetic_secrets(self):
        import convert
        for error, expected in ((RuntimeError('SYNTHETIC_TOKEN /private/home/request'), 'internal_error'),
                                (ValueError('SYNTHETIC_TOKEN'), 'internal_error'),
                                (score_task.ReconstructionError('SYNTHETIC_TOKEN'), 'invalid_state')):
            receipt = convert.error_receipt(error, 'stage')
            self.assertEqual(receipt['error']['code'], expected)
            self.assertNotIn('SYNTHETIC_TOKEN', json.dumps(receipt))
            self.assertNotIn('/private/home', json.dumps(receipt))
