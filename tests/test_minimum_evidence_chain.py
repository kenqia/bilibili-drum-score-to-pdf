import json
from pathlib import Path
import tempfile
import test_agent_content as content_fixture


class MinimumEvidenceChainTests(content_fixture.ContentChecksTests):
    minimum_chain = True

    def test_existing_clean_long_bridge_is_found_after_many_useless_short_edges(self):
        import copy
        import subprocess
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            _,decision=self.prepare_score(base,variant='stationary_middle_cursor')
            # Only the two endpoints are clear. Thirty-three intervening real frames
            # preserve every instance but have a deliberate cursor over B and C.
            with Image.open(base/'000.png') as image:
                image.save(base/'clean.png')
                masked=image.copy()
                ImageDraw.Draw(masked).rectangle((490,400,506,760),fill='#e05050')
                masked.save(base/'masked.png')
            for i in range(128):
                (base/f'long-{i:03d}.png').write_bytes((base/('clean.png' if i in (0,127) else 'masked.png')).read_bytes())
            video=base/'long.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-framerate','64','-i',str(base/'long-%03d.png'),
                            '-pix_fmt','yuv420p',str(video)],check=True)
            task=base/'long-task'
            state=self.cli(video,'--output',task,'--evidence-mode','lazy','--minimum-evidence-chain')
            self.assertEqual(state['status'],'waiting',state)
            for batch in range(4):
                packet=json.loads((task/'observation.json').read_text())
                supplement=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                    observation_version=state['observation_version'],request_id=f'cursor-gap-{batch}',
                    issue=dict(reason='Controlled cursor gap requires native endpoints.',start=0,end=2),
                    timestamps=[i/64 for i in range(1+batch*8,9+batch*8)])
                path=base/'supplement.json';path.write_text(json.dumps(supplement))
                state=self.cli('--operation','supplement','--task',task,'--decision',path)
                self.assertEqual(state['status'],'waiting',state)
            packet=json.loads((task/'observation.json').read_text())
            materialize=dict(schema_version=1,task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                observation_version=state['observation_version'],source_sha256=packet['source']['sha256'],request_id='long-native',
                reason='Controlled fixture native rows reviewed.',regions=[dict(frame_id=f['id'],frame_sha256=f['sha256'],
                    pts=f['pts'],time_base=f['time_base'],bbox=[0,0,1280,960]) for f in packet['frames']])
            path=base/'materialize-long.json';path.write_text(json.dumps(materialize))
            state=self.cli('--operation','materialize','--task',task,'--decision',path)
            self.assertEqual(state['phase'],'review',state)
            packet=json.loads((task/'observation.json').read_text())
            frames=packet['frames'];self.assertEqual(len(frames),35)
            decision.update(task_id=state['task_id'],observation_sha256=state['observation_sha256'],
                presented_images=[i['id'] for i in packet['images']],
                coverage=dict(first_frame=frames[0]['id'],last_frame=frames[-1]['id'],unresolved=[]))
            part=decision['segments'][0]
            for row in [*part['rows'],part['extras'][0]['region']]:
                row['evidence_images']=[i['id'] for i in packet['images'] if i.get('frame_id')==row['frame_id'] and i['kind']=='native_detail']
            templates=copy.deepcopy(part['observations'][:3])
            part['frames']=[f['id'] for f in frames]
            part['observations']=[dict(copy.deepcopy(s),id=f'{fi}-{s["instance_id"]}',frame_id=f['id'])
                                  for fi,f in enumerate(frames) for s in templates]
            part['transitions']=[dict(from_frame=a['id'],to_frame=b['id'],
                matches=[[f'{fi}-{label}',f'{fi+1}-{label}'] for label in 'ABC'],
                evidence='Controlled stationary ordered correspondences.') for fi,(a,b) in enumerate(zip(frames,frames[1:]))]
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft.get('ready_to_submit'),draft.get('error') or draft.get('unresolved'))
            bridges=[c for c in draft['sources']['content_checks'] if c['scope']=='geometry_established_bridge']
            self.assertEqual({tuple(c['matches']) for c in bridges},{('0-A','34-A'),('0-B','34-B'),('0-C','34-C')})
            self.assertTrue(all(c['status']=='not_contradicted' for c in bridges))

    def test_new_lazy_flag_is_persisted_and_full_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,_=self.prepare_score(base)
            self.assertEqual(json.loads((task/'observation.json').read_text())['minimum_evidence_chain_policy'],'ordered_anchors_v1')
            state=self.cli(base/'input.mp4','--output',base/'full','--minimum-evidence-chain')
            self.assertEqual(state['status'],'failed',state)

    def test_third_native_unknown_or_occluded_region_overrides_pixel_pass_and_wide_clear(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_edge_support')
            original,_=self.reviewed_request(task,decision)
            for field,value in (('occlusion','uncertain'),('occlusion','present'),('cursor','uncertain')):
                with self.subTest(field=field,value=value):
                    request=copy.deepcopy(original)
                    regions=request['review']['native_clean_regions']
                    wide=[]
                    for r in regions:
                        if r['bbox'][1]==612:
                            r[field]=value
                            clear=copy.deepcopy(r);clear.update(bbox=[0,0,1280,960],cursor='clear',occlusion='clear')
                            wide.append(clear)
                    regions.extend(wide)
                    draft=self.build(base,task,request,f'{field}-{value}')
                    self.assertFalse(draft['ready_to_submit'],draft.get('unresolved'))
                    third=[c for c in draft['sources']['content_checks'] if c['matches'] and c['matches'][0].endswith('-C')]
                    self.assertTrue(all(c['status']=='not_contradicted' and c['reason']=='local_ink_not_contradicted' for c in third))
                    self.assertTrue(all(c['blocking'] and c.get('native_blockers') for c in third))
                    path=base/'review.json';path.write_text(json.dumps(request))
                    plan=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/f'plan-{field}-{value}')
                    self.assertEqual(plan['supplement_requests'],[])
                    gaps=plan['summary']['critical_gaps']
                    self.assertTrue(gaps)
                    self.assertTrue(all(f'native_{field}_{value}' in g['reasons'] for g in gaps))
                    self.assertTrue(all(b['instance_id']=='C' for g in gaps for b in g['native_blockers']))
                    self.assertTrue(all('Explicitly revise' in g['next_action'] for g in gaps))

    def test_third_native_bridge_blocker_is_reported_for_all_spanned_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_bridge_cursor')
            request,packet=self.reviewed_request(task,decision)
            last=packet['frames'][-1]['id']
            for r in request['review']['native_clean_regions']:
                if r['frame_id']==last and r['bbox'][1]==612:
                    r['occlusion']='uncertain'
            draft=self.build(base,task,request)
            self.assertFalse(draft['ready_to_submit'],draft.get('unresolved'))
            third=next(c for c in draft['sources']['content_checks'] if c['scope']=='geometry_established_bridge' and c['matches']==['0-C','2-C'])
            self.assertEqual(third['status'],'not_contradicted')
            self.assertTrue(third['blocking'])
            self.assertTrue(third['native_blockers'])
            path=base/'review.json';path.write_text(json.dumps(request))
            plan=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            self.assertEqual(len(plan['summary']['critical_gaps']),2)
            self.assertTrue(all('native_occlusion_uncertain' in g['reasons'] for g in plan['summary']['critical_gaps']))
            self.assertEqual(plan['supplement_requests'],[])

    def test_third_bridge_notation_ambiguity_vetoes_two_trustworthy_bridge_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_bridge_ambiguous')
            request,packet=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertFalse(draft['ready_to_submit'],draft.get('unresolved'))
            third=[c for c in draft['sources']['content_checks'] if c['matches'] and c['matches'][0].endswith('-C')]
            adjacent=[c for c in third if c['scope']=='proposed_geometric_pair_only']
            self.assertTrue(all(c['status']=='not_contradicted' and c['unmatched_ink_fraction']<=.08 for c in adjacent))
            bridge=next(c for c in third if c['scope']=='geometry_established_bridge')
            self.assertEqual(bridge['matches'],['0-C','2-C'])
            self.assertEqual(bridge['reason'],'ambiguous_local_notation')
            self.assertTrue(bridge['blocking'])
            self.assertEqual(bridge['frame_sha256'],[packet['frames'][0]['sha256'],packet['frames'][2]['sha256']])
            self.assertEqual(bridge['pts'],[packet['frames'][0]['pts'],packet['frames'][2]['pts']])
            self.assertEqual(bridge['source_sha256'],packet['source']['sha256'])
            report=self.cli('--operation','report','--task',task)['performance']
            # Two public build-validation passes each read six adjacent and three
            # bridge pairs, at two 1280x144 native windows per comparison.
            self.assertEqual(report['content_validation']['pair_checks'],18)
            self.assertEqual(report['content_validation']['analyzed_pixels'],6635520)
            self.assertEqual(report['content_validation']['uncertain_checks'],10)
            rejected=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertNotEqual(rejected.get('phase'),'accepted')
            exported=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertNotEqual(exported['status'],'success')
            path=base/'review.json';path.write_text(json.dumps(request))
            plan=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            self.assertEqual(len(plan['summary']['critical_gaps']),2)
            self.assertTrue(all('ambiguous_local_notation' in g['reasons'] for g in plan['summary']['critical_gaps']))
            self.assertTrue(all(g['affected_instances']==['C'] and g['content_blockers'][0]['matches']==['0-C','2-C'] for g in plan['summary']['critical_gaps']))
            self.assertEqual(plan['supplement_requests'],[])

    def test_summary_hard_bridge_reason_takes_priority_over_cursor_alternative_action(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_bridge_ambiguous')
            request,_=self.reviewed_request(task,decision)
            for r in request['review']['native_clean_regions']:
                if r['bbox'][1]==612:
                    r.update(cursor='present',bbox=[1000,660,1010,670])
            path=base/'review.json';path.write_text(json.dumps(request))
            plan=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            gaps=plan['summary']['critical_gaps']
            self.assertEqual(len(gaps),2)
            self.assertTrue(all(g['sufficient'] and 'ambiguous_local_notation' in g['reasons'] and 'native_cursor_requires_alternative' in g['reasons'] for g in gaps))
            self.assertTrue(all(g['content_blockers'][0]['matches']==['0-C','2-C'] for g in gaps))
            self.assertTrue(all('listed native correspondences' in g['next_action'] for g in gaps),gaps)
            self.assertTrue(all('two ordered clean witnesses' not in g['next_action'] for g in gaps))
            self.assertEqual(plan['supplement_requests'],[])

    def test_reliable_redundant_instance_without_native_declarations_is_not_an_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_edge_support')
            request,_=self.reviewed_request(task,decision)
            request['review']['native_clean_regions']=[r for r in request['review']['native_clean_regions'] if r['bbox'][1]!=612]
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft.get('unresolved'))
            intervals=[c['evidence_chain'] for c in draft['sources']['content_checks']]
            self.assertTrue(all(w['matches'][0].endswith(('-A','-B')) for i in intervals for w in i['witnesses']))

    def test_third_instance_native_spacing_or_height_mismatch_cannot_borrow_clean_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_edge_support')
            for spacing in (12.09375,12.125):
                with self.subTest(spacing=spacing):
                    next(s for s in decision['segments'][0]['observations'] if s['id']=='1-C')['spacing']=spacing
                    request,_=self.reviewed_request(task,decision)
                    draft=self.build(base,task,request,f'spacing-{spacing}')
                    self.assertFalse(draft['ready_to_submit'],draft.get('unresolved'))
                    third=[c for c in draft['sources']['content_checks'] if c['matches'] and c['matches'][0].endswith('-C')]
                    self.assertTrue(all(c['status']=='uncertain' and c['reason']=='unreliable_alignment' and c['blocking'] for c in third))
                    self.assertTrue(all(c['evidence_chain']['sufficient'] for c in third))
                    rejected=self.cli('--operation','submit','--task',task,'--decision',base/f'spacing-{spacing}/decision.json')
                    self.assertNotEqual(rejected.get('phase'),'accepted')

    def test_native_unknown_outside_analysis_and_crop_does_not_poison_clean_witnesses(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_edge_support')
            request,_=self.reviewed_request(task,decision)
            outside=copy.deepcopy(request['review']['native_clean_regions'][0])
            outside.update(bbox=[0,850,1280,900],cursor='uncertain',occlusion='present')
            request['review']['native_clean_regions'].append(outside)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft.get('unresolved'))
            self.assertTrue(all(not c['native_blockers'] for c in draft['sources']['content_checks']))

    def test_pixel_pass_with_native_cursor_present_needs_authorized_alternative(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_edge_support')
            original,_=self.reviewed_request(task,decision)
            for complete in (False,True):
                with self.subTest(complete=complete):
                    request=copy.deepcopy(original)
                    for r in request['review']['native_clean_regions']:
                        if r['bbox'][1]==612:
                            r['cursor']='present'
                            if not complete:
                                r['bbox']=[1000,660,1010,670]
                    draft=self.build(base,task,request,f'present-{complete}')
                    self.assertEqual(draft['ready_to_submit'],complete,draft.get('unresolved'))
                    third=[c for c in draft['sources']['content_checks'] if c['matches'][0].endswith('-C')]
                    self.assertTrue(all(c['status']=='not_contradicted' for c in third))
                    self.assertTrue(all(c['blocking']==(not complete) for c in third))
                    self.assertTrue(all(w['matches'][0].endswith(('-A','-B')) for c in third for w in c['evidence_chain']['witnesses']))

    def test_two_clean_ordered_anchors_cover_redundant_cursor_pair_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            checks=draft['sources']['content_checks']
            self.assertTrue(any(c['status']=='uncertain' and c.get('blocking') is False for c in checks))
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            out=self.cli('--operation','export','--task',task,'--output',base/'out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(out['status'],'success',out)
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())

    def test_clean_bridge_keeps_every_intermediate_frame_and_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='bridge_cursor')
            request,packet=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            bridges=[c for c in draft['sources']['content_checks'] if c['scope']=='geometry_established_bridge' and c['status']=='not_contradicted']
            self.assertEqual({tuple(c['matches']) for c in bridges},{('0-B','2-B'),('0-C','2-C')})
            self.assertTrue(all(c['covered_frames']==[f['id'] for f in packet['frames']] for c in bridges))
            missing=json.loads(json.dumps(decision))
            missing['segments'][0]['observations']=[s for s in missing['segments'][0]['observations'] if s['id']!='1-C']
            request,_=self.reviewed_request(task,missing)
            rejected=self.build(base,task,request,'missing')
            self.assertFalse(rejected.get('ready_to_submit',False),rejected)

    def reviewed_request(self,task,decision):
        request,packet=super().reviewed_request(task,decision)
        if packet.get('minimum_evidence_chain_policy'):
            records=[]
            for s in decision['segments'][0]['observations']:
                f=next(f for f in packet['frames'] if f['id']==s['frame_id'])
                bbox=[0,s['bbox'][1],f['width'],s['bbox'][3]]
                from PIL import Image
                with Image.open(task/f['path']) as image:
                    # Fixture truth: the only colored pixels are the deliberately drawn cursor.
                    import numpy as np
                    pixels=np.asarray(image.crop(bbox)).astype(int)
                    cursor=bool(((pixels.max(axis=2)-pixels.min(axis=2))>70).any())
                records.append(dict(frame_id=f['id'],frame_sha256=f['sha256'],pts=f['pts'],time_base=f['time_base'],bbox=bbox,
                    evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id')==f['id'] and i['kind']=='native_detail'],
                    cursor='present' if cursor else 'clear',occlusion='clear',evidence='Controlled fixture native row reviewed; deliberate colored cursor only.'))
            request['review']['native_clean_regions']=records
        return request,packet

    def test_missing_native_authority_and_tampered_sidecar_stay_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            good=self.build(base,task,request,'good')
            self.assertTrue(good['ready_to_submit'],good)
            record=json.loads((base/'good/continuity.json').read_text())
            record['source_sha256']='0'*64
            (base/'good/continuity.json').write_text(json.dumps(record))
            rejected=self.cli('--operation','submit','--task',task,'--decision',base/'good/decision.json')
            self.assertNotEqual(rejected.get('phase'),'accepted',rejected)
            request['review']['native_clean_regions']=[]
            missing=self.build(base,task,request,'missing')
            self.assertFalse(missing['ready_to_submit'],missing)

    def test_bound_summary_has_no_redundant_supplements_and_raw_records_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            path=base/'review.json';path.write_text(json.dumps(request))
            result=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            self.assertFalse(result['summary']['critical_gaps'],result)
            self.assertEqual(result['supplement_requests'],[])
            self.assertTrue(result['summary']['existing_alternatives'])
            self.assertNotIn('issues',result)
            self.assertTrue(json.loads((base/'plan/review-plan.json').read_text())['issues'])

    def test_summary_locates_pending_audit_and_groups_diagnostics_without_raw_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_edge_support')
            request,packet=self.reviewed_request(task,decision)
            request['review']['score_audit']['intervals'][1]['status']='pending'
            path=base/'review.json';path.write_text(json.dumps(request))
            plan=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            summary=plan['summary']
            self.assertFalse(summary['draft_ready_to_submit'])
            pending=next(i for i in summary['other_required_actions'] if 'unresolved_sampling_interval' in i.get('reasons',[]))
            self.assertEqual(pending['interval'],dict(from_frame=packet['frames'][1]['id'],to_frame=packet['frames'][2]['id'],start=packet['frames'][1]['timestamp'],end=packet['frames'][2]['timestamp']))
            self.assertEqual(pending['affected_instances'],list('ABC'))
            self.assertEqual(pending['existing_evidence']['coverage_audit_status'],'pending')
            self.assertEqual(pending['existing_evidence']['trusted_content_witness_count'],2)
            self.assertTrue(pending['next_action'])
            categories=[summary['duplicate_candidates'],summary['low_value_diagnostics'],summary['required_native_review']['detector_diagnostic_groups']]
            self.assertTrue(all(categories))
            self.assertNotIn('record_ids',json.dumps(summary))
            for items in categories:
                for item in items:
                    self.assertTrue({'interval','affected_instances','existing_evidence','next_action','count'}<=item.keys(),item)
                    self.assertIsNotNone(item['interval']['from_frame'])
                    if item['affected_instances'] is not None:
                        self.assertTrue(set(item['affected_instances'])<=set('ABC'))
            raw=json.loads((base/'plan/review-plan.json').read_text())
            self.assertTrue(all('id' in i for i in raw['issues']))
            self.assertEqual(len(raw['issues']),summary['raw_diagnostic_count'])

    def test_third_row_conflict_vetoes_two_other_trustworthy_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='third_conflict')
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            conflicts=[c for c in result['sources']['content_checks'] if c['status']=='conflict']
            self.assertTrue(any(c['matches']==['1-D','2-D'] for c in conflicts),conflicts)
            for r in request['review']['native_clean_regions']:
                if r['bbox'][1]==612:
                    r['occlusion']='uncertain'
            path=base/'review.json';path.write_text(json.dumps(request))
            plan=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            last_gap=plan['summary']['critical_gaps'][-1]
            self.assertIn('contradictory_local_notation',last_gap['reasons'])
            self.assertIn('native_occlusion_uncertain',last_gap['reasons'])
            self.assertEqual(plan['supplement_requests'],[])

    def test_only_missing_intervals_generate_one_deduplicated_local_request(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='cursor')
            request,_=self.reviewed_request(task,decision)
            path=base/'review.json';path.write_text(json.dumps(request))
            result=self.cli('--operation','review-plan','--task',task,'--decision',path,'--output',base/'plan')
            self.assertEqual(len(result['summary']['critical_gaps']),2,result)
            self.assertEqual(len(result['supplement_requests']),1,result)
            times=result['supplement_requests'][0]['request']['timestamps']
            self.assertEqual(len(times),2)
            self.assertEqual(len(set(times)),2)

    def test_unknown_occlusion_and_unreviewed_gap_do_not_borrow_anchor_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            for r in request['review']['native_clean_regions']:
                if r['cursor']=='present':
                    r['occlusion']='uncertain'
            rejected=self.build(base,task,request,'unknown')
            self.assertFalse(rejected['ready_to_submit'],rejected)
            request,_=self.reviewed_request(task,decision)
            request['review']['score_audit']['intervals'][1]['status']='pending'
            rejected=self.build(base,task,request,'unreviewed')
            self.assertFalse(rejected['ready_to_submit'],rejected)

    def test_bridge_checks_third_common_instance_before_selecting_two_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_bridge_conflict')
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            checks=result['sources']['content_checks']
            self.assertTrue(any(c['matches']==['0-C','2-C'] and c['scope']=='geometry_established_bridge' and c['status']=='conflict' for c in checks),checks)

    def test_bridge_ineligible_third_common_instance_still_vetoes_conflicting_content(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_bridge_conflict')
            # Each adjacent crop shift is permitted, but accumulated endpoint shift
            # makes C ineligible as a bridge anchor. Its content must still be read.
            for s in decision['segments'][0]['observations']:
                if s['id'] in ('1-C','2-C'):
                    s['bbox'][0]+=4*int(s['id'][0])
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertFalse(draft['ready_to_submit'],draft.get('unresolved'))
            third=next(c for c in draft['sources']['content_checks']
                       if c['scope']=='geometry_established_bridge' and c['matches']==['0-C','2-C'])
            self.assertFalse(third['bridge_eligible'])
            self.assertEqual(third['status'],'conflict')
            self.assertTrue(third['blocking'])

    def test_two_single_anchors_on_different_edges_do_not_form_one_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='single_bridge_cursor')
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            intervals={(c['from_frame'],c['to_frame']):c['evidence_chain'] for c in result['sources']['content_checks'] if 'evidence_chain' in c}
            self.assertEqual(len(intervals),2)
            self.assertTrue(all(not interval['sufficient'] for interval in intervals.values()),intervals)

    def test_large_plan_stdout_is_short_and_retains_raw_diagnostics(self):
        import test_agent_review
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            ordinary=self.cli
            def prepare_chain(*args):
                return ordinary(*args,*(['--minimum-evidence-chain'] if '--script-acceptance' in args else []))
            self.cli=prepare_chain
            task=test_agent_review.ReviewTests.large_task(self,base,5)
            result=self.cli('--operation','review-plan','--task',task,'--output',base/'plan')
            self.assertNotIn('issues',result)
            self.assertLess(len(json.dumps(result).encode()),16000)
            raw=json.loads((base/'plan/review-plan.json').read_text())
            self.assertGreater(len(raw['issues']),250)
            self.assertEqual(raw['supplement_requests'],[])
            self.assertEqual(result['summary']['critical_gaps'],[])
            self.assertFalse(result['summary']['bound_geometry_checked'])
            summary=result['summary']
            groups=[*summary['duplicate_candidates'],*summary['low_value_diagnostics'],*summary['required_native_review']['detector_diagnostic_groups']]
            self.assertTrue(all(i['affected_instances'] is None and i['identity_scope']=='unknown' for i in groups))
            self.assertNotIn('record_ids',json.dumps(summary))
            self.assertEqual(summary['raw_diagnostic_count'],len(raw['issues']))

    def test_supplement_preserves_opt_in_and_rejects_old_decision_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,packet=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            supplemental=dict(schema_version=1,task_id=accepted['task_id'],observation_sha256=accepted['observation_sha256'],
                observation_version=accepted['observation_version'],request_id='new-native-gap',
                issue=dict(reason='required_content_witness',start=0,end=.8),timestamps=[.25])
            path=base/'supplement.json';path.write_text(json.dumps(supplemental))
            changed=self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertNotEqual(changed.get('observation_sha256'),accepted['observation_sha256'],changed)
            self.assertEqual(changed['minimum_evidence_chain_policy'],'ordered_anchors_v1')
            rejected=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertNotEqual(rejected.get('phase'),'accepted',rejected)
            exported=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertNotEqual(exported['status'],'success',exported)

    def test_cursor_reason_cannot_hide_other_endpoint_hard_obstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_mixed_obstruction')
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            pair=next(c for c in result['sources']['content_checks'] if c['matches']==['1-C','2-C'])
            self.assertTrue(pair['blocking'],pair)

    def test_detected_cursor_endpoint_cannot_be_declared_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='redundant_cursor')
            request,_=self.reviewed_request(task,decision)
            for region in request['review']['native_clean_regions']:
                region['cursor']='clear'
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)

    def test_partial_endpoint_cannot_be_hidden_by_other_endpoint_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='stationary_middle_cursor')
            for sighting in decision['segments'][0]['observations']:
                if sighting['id']=='2-C':
                    sighting['complete']=False
            request,_=self.reviewed_request(task,decision)
            result=self.build(base,task,request)
            self.assertFalse(result['ready_to_submit'],result)
            pair=next(c for c in result['sources']['content_checks'] if c['matches']==['1-C','2-C'])
            self.assertEqual(pair['endpoint_reasons'],['cursor_or_obstruction','partial_or_missing_margin'])
            self.assertTrue(pair['blocking'],pair)
            rejected=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertNotEqual(rejected.get('phase'),'accepted',rejected)
