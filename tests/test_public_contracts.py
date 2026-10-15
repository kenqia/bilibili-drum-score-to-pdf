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


EXPORT_ENTRIES = ('cli', 'workflow', 'vector')
REVIEW_ENTRIES = ('cli', 'workflow', 'vector', 'task')
GROUP_ENTRIES = ('cli', 'workflow', 'task')


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
