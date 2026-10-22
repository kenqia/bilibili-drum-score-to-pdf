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

    def test_batch_requests_include_new_prepared_and_legacy_calling_groups(self):
        rows = self.selection()
        self.cli('redraw-inputs', groups=[[0], [1], [2]])
        legacy = self.cli('begin-redraw', identifier='page-2', viewed_notes='Controlled legacy dispatch.')
        first = self.cli('redraw-requests', viewed_notes='Controlled review of every input.')
        self.assertEqual(first['group_count'], 3)
        self.assertEqual([h['group'] for h in first['handoffs']], ['page-1', 'page-2', 'page-3'])
        self.assertEqual([h['status'] for h in first['handoffs']],
                         ['ready_to_dispatch', 'recover_existing_call', 'ready_to_dispatch'])
        self.assertEqual(first['handoffs'][1]['request']['request'], legacy['request'])
        again = self.cli('redraw-requests')
        self.assertEqual(again['handoffs'], first['handoffs'])
        pending = first['handoffs'][0]['request']['request']
        self.cli('cancel-redraw', identifier='page-1', request=pending,
                 notes='Controlled crop correction before host submission.')
        cancelled = self.cli('resume')['redraw_pages'][0]
        self.assertEqual(cancelled['attempts'][0]['status'], 'cancelled')
        self.assertEqual(cancelled['corrections_used'], 0)
        fresh = self.cli('redraw-requests', viewed_notes='Controlled repaired input.')
        replacement = fresh['handoffs'][0]['request']['request']
        self.assertNotEqual(replacement, pending)
        self.cli('dispatch-redraw', identifier='page-1', request=replacement)
        resumed = self.cli('redraw-requests')
        self.assertEqual(resumed['handoffs'][0]['status'], 'recover_existing_call')
        import score_workflow
        with self.assertRaises(score_workflow.ReconstructionError):
            score_workflow.cancel_redraw(self.task, 'page-1', replacement, 'Cannot cancel an unknown call.')
        self.assertEqual(self.cli('resume')['redraw_pages'][0]['attempts'][-1]['status'], 'calling')

    def test_crop_change_cancels_only_unsubmitted_history(self):
        rows = self.selection()
        self.cli('redraw-inputs', groups=[[0], [1], [2]])
        batch = self.cli('redraw-requests', viewed_notes='Controlled original input review.')
        request = batch['handoffs'][0]['request']['request']
        rows[0]['bbox'][0] += 1
        self.cli('assemble', title='Revision', regions=rows,
                 review=self.review)
        record = self.cli('resume')
        old = record['generation_history'][batch['handoffs'][0]['input_identity']]
        self.assertEqual(old['attempts'][-1]['request'], request)
        self.assertEqual(old['attempts'][-1]['status'], 'cancelled')
        self.assertEqual(old['status'], 'needs_generation')
        unchanged = record['generation_history'][batch['handoffs'][1]['input_identity']]
        self.assertEqual(unchanged['status'], 'prepared')

    def test_layout_reuses_materials_and_renders_every_revision_page(self):
        self.selection()
        groups=self.cli('redraw-inputs',groups=[[0,1],[2]])
        for group in groups:
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        old=self.cli('export')
        self.cli('review-pdf',pages=list(range(1,old['page_count']+1)),output_revision=old['output_revision'],notes='Controlled full review.')
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
        self.selection()
        first = self.cli('redraw-requests', viewed_notes='Controlled complete rough review.')
        first = self.cli('stage')
        self.assertEqual(first['phase'],'generation')
        self.assertEqual(first['status'],'pending')
        second=self.cli('stage')
        self.assertEqual(first['handoffs'][0]['request']['request'],second['handoffs'][0]['request']['request'])
        self.assertEqual(second['handoffs'][0]['status'], 'ready_to_dispatch')
        self.cli('dispatch-redraw', identifier=second['handoffs'][0]['group'],
                 request=second['handoffs'][0]['request']['request'])
        self.assertEqual(self.cli('stage')['handoffs'][0]['status'], 'recover_existing_call')
        for group in self.cli('redraw-inputs'):
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        printed=self.cli('stage')
        self.assertEqual(printed['phase'],'pdf_review')
        output=printed['artifacts']['output']
        self.cli('review-pdf',pages=printed['next']['pages'],output_revision=output['output_revision'],notes='Controlled complete preview review.')
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
                workflow.assemble(self.task,'Synthetic',changed,
                    __import__('score_fixtures').controlled_source_review(changed,self.review))
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
        self.cli('review-pdf',pages=list(range(1,output['page_count']+1)),output_revision=output['output_revision'],notes='Controlled full review.')
        changed=self.cli('redraw-inputs',groups=[[0],[1],[2]])
        self.assertEqual(changed[2]['status'],'vector')
        self.assertNotIn('output',self.cli('resume'))
        self.assertTrue((self.task/output['pdf']).is_file())

    def test_pdf_review_requires_explicit_current_revision_after_layout_change(self):
        import json, subprocess, sys
        self.selection()
        for group in self.cli('redraw-inputs'):
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        old=self.cli('export')
        self.cli('layout',margin=32)
        fresh=self.cli('export')
        for revision in (None,old['output_revision']):
            payload={'pages':list(range(1,fresh['page_count']+1)),'notes':'Review of previous fixture.'}
            if revision is not None:
                payload['output_revision']=revision
            request=self.root/'request.json';request.write_text(json.dumps(payload))
            result=subprocess.run([sys.executable,str(fixtures.SCRIPT),'--operation','review-pdf','--task',str(self.task),'--request',str(request)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stdout)
            self.assertEqual(self.cli('resume')['output']['status'],'needs_pdf_review')
        reviewed=self.cli('review-pdf',pages=list(range(1,fresh['page_count']+1)),output_revision=fresh['output_revision'],notes='Controlled current preview review.')
        self.assertEqual(reviewed['review']['output_revision'],fresh['output_revision'])

    def test_public_vector_export_obeys_layout_and_produces_reviewable_pages(self):
        import reconstruction, score_task
        self.selection()
        self.cli('layout',margin=32,minimum_gap=60,target_pages=1)
        output=reconstruction.export_vector(self.task)
        self.assertEqual(output['placements'][0]['bbox'][0],32)
        boxes=[p['bbox'] for p in output['placements']]
        self.assertGreaterEqual(boxes[0][1]-boxes[1][3],60)
        self.assertEqual([p['page'] for p in output['previews']],list(range(1,output['page_count']+1)))
        self.assertEqual(output['checks']['status'],'passed')
        reviewed=score_task.review_pdf(self.task,list(range(1,output['page_count']+1)),
            'Controlled vector previews viewed.',output_revision=output['output_revision'])
        self.assertEqual(reviewed['status'],'reviewed')

    def test_legacy_pdf_without_all_previews_or_checks_cannot_be_approved(self):
        import score_task, reconstruction
        self.selection()
        output=reconstruction.export_vector(self.task)
        pristine=score_task.load(self.task)
        for field in ('previews','checks'):
            legacy=copy.deepcopy(pristine)
            legacy['output'].pop(field,None)
            score_task.save(self.task,legacy)
            with self.assertRaises(score_task.ReconstructionError):
                score_task.review_pdf(self.task,[1],'Controlled legacy review.',output_revision=output['output_revision'])
        missing_page=copy.deepcopy(pristine)
        missing_page['output']['previews']=[]
        score_task.save(self.task,missing_page)
        with self.assertRaises(score_task.ReconstructionError):
            score_task.review_pdf(self.task,[1],'Controlled absent page review.',output_revision=output['output_revision'])
        refreshed=reconstruction.export_vector(self.task)
        self.assertNotEqual(refreshed['pdf'],output['pdf'])
        self.assertTrue((self.task/output['pdf']).is_file())
        self.assertEqual(len(refreshed['previews']),refreshed['page_count'])

    def test_new_explicit_group_and_single_unreadable_row_reject_host_input(self):
        import json, subprocess, sys
        rows=self.selection()
        rows=[rows[0]]+[dict(rows[1],position=f'ordered-{i}') for i in range(110)]
        self.cli('assemble',title='Synthetic',regions=rows,review=self.review)
        request=self.root/'request.json'
        for payload in ({'groups':[list(range(len(rows)))]},):
            request.write_text(json.dumps(payload))
            result=subprocess.run([sys.executable,str(fixtures.SCRIPT),'--operation','redraw-inputs','--task',str(self.task),'--request',str(request)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stdout)
        narrow=[dict(rows[1],staff_spacing=3)]
        self.cli('assemble',title='Synthetic',regions=narrow,review=self.review)
        request.write_text('{}')
        result=subprocess.run([sys.executable,str(fixtures.SCRIPT),'--operation','redraw-inputs','--task',str(self.task),'--request',str(request)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2,result.stdout)
        self.assertNotIn('redraw_pages', {k:v for k,v in self.cli('resume').items() if v})

    def test_same_pdf_bytes_new_export_rejects_old_revision_token(self):
        import score_task, reconstruction
        self.selection()
        old=reconstruction.export_vector(self.task)
        self.cli('layout',target_pages=512)
        fresh=reconstruction.export_vector(self.task)
        self.assertEqual(old['sha256'],fresh['sha256'])
        self.assertNotEqual(old['output_revision'],fresh['output_revision'])
        with self.assertRaises(score_task.ReconstructionError):
            score_task.review_pdf(self.task,[1],'Controlled old preview review.',output_revision=old['output_revision'])
        with self.assertRaises(score_task.ReconstructionError):
            score_task.review_pdf(self.task,[1],'Hash cannot identify a revision.',output_revision=fresh['sha256'])
        approved=score_task.review_pdf(self.task,[1],'Controlled new preview review.',output_revision=fresh['output_revision'])
        self.assertEqual(approved['review']['output_revision'],fresh['output_revision'])

    def test_legacy_large_accepted_identity_retains_materials_and_spent_budget(self):
        import score_task
        from PIL import Image
        rows=self.selection()
        rows=[rows[0]]+[dict(rows[1],position=f'legacy-{i}') for i in range(9)]
        self.cli('assemble',title='Synthetic',regions=rows,review=self.review)
        record=score_task.load(self.task)
        indices=list(range(len(rows)))
        # A saved pre-limit task fixture, with controlled offline image evidence.
        image=Image.new('RGB',(640,1100),'white')
        boundaries=[];top=0
        for region in record['regions']:
            with Image.open(self.task/region['path']) as crop:
                image.paste(crop,(0,top))
            boundaries.append([0,top,640,top+region['height']]);top+=region['height']
        path=self.task/'legacy-input.png';image.save(path)
        reference={'path':'legacy-input.png','sha256':score_task.digest(path)}
        legacy={'id':'page-1','input_identity':score_task.input_identity(record,indices),
            'regions':indices,'input':reference,'output':reference,'status':'accepted',
            'freeze_id':record['freeze']['id'],'corrections_used':1,'boundaries':boundaries,
            'attempts':[{'request':'legacy-initial','status':'returned','output':reference},
                        {'request':'legacy-correction','status':'returned','output':reference}]}
        record['redraw_pages']=[legacy]
        score_task.save(self.task,record)
        # Moving to a new membership then returning must recover the old identity.
        self.cli('redraw-inputs',groups=[[0,1,2,3,4],[5,6,7,8,9]])
        restored=self.cli('redraw-inputs',groups=[indices])[0]
        self.assertEqual(restored['status'],'accepted')
        self.assertEqual(restored['corrections_used'],1)
        self.assertEqual(restored['attempts'],legacy['attempts'])
        self.assertEqual(restored['output'],reference)

    def test_stage_upgrades_legacy_hash_review_and_requires_new_page_review(self):
        import score_task
        self.selection()
        for group in self.cli('redraw-inputs'):
            self.cli('fail-redraw',identifier=group['id'],notes='Controlled unavailable host.')
        output=self.cli('export')
        pristine=score_task.load(self.task)
        for preserve_output_token in (False,True):
            record=copy.deepcopy(pristine)
            if not preserve_output_token:
                record['output'].pop('output_revision')
            record['output']['status']='reviewed'
            record['output']['review']={'output_revision':output['sha256'],'pages':[1],'notes':'Controlled old hash review.'}
            record['status']='reviewed'
            score_task.save(self.task,record)
            stage=self.cli('stage')
            self.assertEqual(stage['phase'],'pdf_review')
            fresh=stage['artifacts']['output']
            self.assertNotEqual(fresh['output_revision'],output['output_revision'])
            self.assertEqual(stage['next']['output_revision'],fresh['output_revision'])
            self.assertTrue((self.task/output['pdf']).is_file())
