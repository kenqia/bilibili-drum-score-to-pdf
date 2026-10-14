"""Public stage/revision behavior; receipts are controlled offline evidence."""
import copy
import unittest
import test_native_cache_cli as fixtures

class RevisionCLI(unittest.TestCase):
    setUp=fixtures.NativeCacheCLI.setUp
    tearDown=fixtures.NativeCacheCLI.tearDown
    cli=fixtures.NativeCacheCLI.cli

    def selection(self):
        self.cli('prepare')
        shot=self.cli('capture',seconds=0)
        rows=[{'capture':shot['id'],'bbox':[0,0,640,65],'kind':'header','position':'title'},
            {'capture':shot['id'],'bbox':[0,65,640,180],'kind':'system','staff_top':35,'staff_spacing':10,'position':'row-1'},
            {'capture':shot['id'],'bbox':[0,65,640,180],'kind':'system','staff_top':35,'staff_spacing':10,'position':'row-2'}]
        self.review={'viewed_captures':[shot['id']],'complete':True,'notes':'Controlled review.',
            'continuity':'Controlled ordered source.','first_last':'Controlled endpoints.'}
        self.cli('assemble',title='Synthetic',regions=rows,review=self.review)
        return rows

    def test_local_source_revision_and_return_restore_unknown_call_and_other_group(self):
        rows=self.selection()
        groups=self.cli('redraw-inputs',groups=[[0,1],[2]])
        pending=self.cli('begin-redraw',identifier=groups[0]['id'],viewed_notes='Controlled input.')
        self.cli('fail-redraw',identifier=groups[1]['id'],notes='Controlled unavailable host.')
        changed=copy.deepcopy(rows);changed[1]['bbox'][3]=181
        self.cli('assemble',title='Synthetic',regions=changed,review=self.review)
        revised=self.cli('redraw-inputs')
        self.assertEqual(revised[1]['status'],'vector')
        self.assertEqual(revised[0]['status'],'needs_generation')
        restored_rows=copy.deepcopy(rows)
        restored_rows[1]['staff_top']=35.0
        restored_rows[1]['staff_spacing']=10.0
        self.cli('assemble',title='Synthetic',regions=restored_rows,review=self.review)
        restored=self.cli('redraw-inputs')
        self.assertEqual(restored[0]['status'],'calling')
        self.assertEqual(restored[0]['attempts'][0]['request'],pending['request'])

    def test_layout_reuses_materials_and_renders_every_revision_page(self):
        self.selection()
        groups=self.cli('redraw-inputs',groups=[[0,1],[2]])
        for group in groups:
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        old=self.cli('export')
        self.cli('review-pdf',pages=list(range(1,old['page_count']+1)),notes='Controlled full review.')
        self.cli('layout',margin=32,minimum_gap=60,target_pages=1)
        fresh=self.cli('export')
        self.assertNotEqual(old['pdf'],fresh['pdf'])
        self.assertTrue((self.task/old['pdf']).is_file())
        self.assertEqual(len(fresh['previews']),fresh['page_count'])
        self.assertEqual(fresh['checks']['status'],'passed')
        self.assertEqual([g['attempts'] for g in self.cli('redraw-inputs')],[g['attempts'] for g in groups])
        boxes=[p['bbox'] for p in fresh['placements']]
        self.assertGreaterEqual(boxes[0][1]-boxes[1][3],60)

    def test_stage_advances_synthetic_video_and_never_reissues_pending_host_call(self):
        self.cli('prepare')
        first=self.cli('stage',title='Synthetic stage')
        self.assertEqual(first['phase'],'generation')
        self.assertEqual(first['status'],'pending')
        second=self.cli('stage')
        self.assertEqual(first['handoffs'][0]['request']['request'],second['handoffs'][0]['request']['request'])
        self.assertEqual(second['handoffs'][0]['status'],'recover_existing_call')
        for group in self.cli('redraw-inputs'):
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        printed=self.cli('stage')
        self.assertEqual(printed['phase'],'pdf_review')
        output=printed['artifacts']['output']
        self.cli('review-pdf',pages=printed['next']['pages'],output_revision=output['sha256'],notes='Controlled complete preview review.')
        self.assertEqual(self.cli('stage')['phase'],'complete')

    def test_regrouping_restores_exact_membership_and_spent_version_budget(self):
        rows=self.selection()
        groups=self.cli('redraw-inputs',groups=[[0,1],[2]])
        first=groups[0]['id']
        for correction in (False,True):
            request=self.cli('begin-redraw',identifier=first,viewed_notes='Controlled correction.',correction=correction)
            self.cli('finish-redraw',identifier=first,request=request['request'],output=str(self.root/'score.png'),tool='host-imagegen',receipt='Controlled offline result.')
            self.cli('review-redraw',identifier=first,accepted=False,notes='Controlled notation mismatch.')
        changed=copy.deepcopy(rows);changed[1]['bbox'][3]=181
        self.cli('assemble',title='Synthetic',regions=changed,review=self.review)
        self.assertEqual(self.cli('redraw-inputs')[0]['corrections_used'],0)
        self.cli('assemble',title='Synthetic',regions=rows,review=self.review)
        regrouped=self.cli('redraw-inputs',groups=[[0],[1],[2]])
        self.assertEqual(regrouped[0]['status'],'needs_generation')
        restored=self.cli('redraw-inputs',groups=[[0,1],[2]])
        self.assertEqual(restored[0]['status'],'vector')
        self.assertEqual(restored[0]['corrections_used'],1)
        self.assertEqual(len(restored[0]['attempts']),2)

    def test_manual_frozen_stage_requires_genuine_input_review_without_new_scan(self):
        self.selection()
        result=self.cli('stage')
        self.assertEqual(result['handoffs'][0]['status'],'needs_input_review')
        record=self.cli('resume')
        self.assertNotIn('overview',record)
        self.assertEqual(record['redraw_pages'][0]['attempts'],[])

    def test_exact_history_membership_remaps_accepted_rows_after_insertion(self):
        rows=self.selection()
        groups=self.cli('redraw-inputs',groups=[[0,1],[2]])
        request=self.cli('begin-redraw',identifier=groups[0]['id'],viewed_notes='Controlled input.')
        self.cli('finish-redraw',identifier=groups[0]['id'],request=request['request'],output=str(self.root/'score.png'),tool='host-imagegen',receipt='Controlled offline result.')
        self.cli('review-redraw',identifier=groups[0]['id'],accepted=True,notes='Controlled boundaries.',boundaries=[[0,0,640,65],[0,65,640,180]])
        inserted=copy.deepcopy(rows[0]);inserted['position']='new-title'
        self.cli('assemble',title='Synthetic',regions=[inserted]+rows,review=self.review)
        restored=self.cli('redraw-inputs',groups=[[0],[1,2],[3]])
        self.assertEqual(restored[1]['status'],'accepted')
        self.assertEqual([r['source_region'] for r in restored[1]['row_materials']],[1,2])
        self.assertEqual(restored[1]['output']['sha256'],self.cli('resume')['generation_history'][groups[0]['input_identity']]['output']['sha256'])

    def test_publication_failure_keeps_valid_selection_and_pending_budget(self):
        from unittest.mock import patch
        import score_workflow as workflow
        rows=self.selection()
        groups=self.cli('redraw-inputs')
        pending=self.cli('begin-redraw',identifier=groups[0]['id'],viewed_notes='Controlled input.')
        before=self.cli('resume')
        changed=copy.deepcopy(rows);changed[1]['bbox'][3]=181
        with patch('score_task.save',side_effect=OSError('Controlled publication interruption')):
            with self.assertRaises(OSError):
                workflow.assemble(self.task,'Synthetic',changed,self.review)
        self.assertEqual(self.cli('resume'),before)
        self.assertEqual(self.cli('redraw-inputs')[0]['attempts'][0]['request'],pending['request'])

    def test_preview_failure_does_not_publish_an_unreviewable_pdf(self):
        from unittest.mock import patch
        import score_workflow as workflow
        self.selection()
        for group in self.cli('redraw-inputs'):
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        old=self.cli('export')
        self.cli('layout',minimum_gap=40)
        before=self.cli('resume')
        with patch('subprocess.run',side_effect=OSError('Controlled Poppler failure')):
            with self.assertRaises(OSError):
                workflow.export(self.task)
        self.assertEqual(self.cli('resume'),before)
        self.assertTrue((self.task/old['pdf']).is_file())
        fresh=self.cli('export')
        self.assertNotEqual(old['pdf'],fresh['pdf'])

    def test_regrouping_after_final_review_invalidates_pdf_and_keeps_exact_group(self):
        self.selection()
        groups=self.cli('redraw-inputs',groups=[[0,1],[2]])
        for group in groups:
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        output=self.cli('export')
        self.cli('review-pdf',pages=list(range(1,output['page_count']+1)),notes='Controlled full review.')
        changed=self.cli('redraw-inputs',groups=[[0],[1],[2]])
        self.assertEqual(changed[2]['status'],'vector')
        self.assertNotIn('output',self.cli('resume'))
        self.assertTrue((self.task/output['pdf']).is_file())
