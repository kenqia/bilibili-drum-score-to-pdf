"""Automatic source checks at the agreed unified CLI boundary, no vision claims."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from score_fixtures import CLI, score_frame, video_from_image


class AutomaticScoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.task = self.base / 'task'

    def tearDown(self):
        self.temp.cleanup()

    def call(self, operation, payload=None, success=True):
        if operation == 'assemble':
            from score_fixtures import controlled_source_review
            import score_workflow
            payload = dict(payload)
            payload['review'] = controlled_source_review(payload['regions'], payload['review'])
            viewed = payload['review']['viewed_captures']
            score_workflow.present(self.task, viewed, 'Controlled synthetic presentation.')
            payload['review']['issue_dispositions'] = [
                {'id': issue['id'], 'outcome': 'resolved', 'captures': viewed,
                 'notes': 'Controlled synthetic resolution, not a live visual claim.'}
                for issue in score_workflow.source_issues(self.task)['issues']]
        request = self.base / 'request.json'
        request.write_text(json.dumps(payload or {}))
        run = subprocess.run([sys.executable, str(CLI), '--operation', operation,
            '--task', str(self.task), '--request', str(request)], capture_output=True, text=True)
        result = json.loads(run.stdout) if run.stdout else {}
        self.assertEqual(run.returncode, 0 if success else 2, (run.stderr, result))
        return result

    def prepare(self, image=None):
        video = video_from_image(image or score_frame(), self.base)
        run = subprocess.run([sys.executable, str(CLI), str(video), '--output', str(self.task)],
            capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_static_video_automatically_crops_and_freezes_without_agent_assertions(self):
        self.prepare()
        overview = self.call('overview')
        self.assertTrue(overview['scan']['complete'])
        self.assertEqual(overview['scan']['frames_observed'], 8)
        self.assertTrue(overview['panels'])
        self.assertLess(overview['candidates'][-1]['requested_seconds'], 2)
        result = self.call('auto-freeze', {'title': 'Fixture song'})
        self.assertEqual(result['status'], 'frozen')
        self.assertEqual(result['checks']['producer'], 'program')
        self.assertEqual(len([r for r in result['regions'] if r['kind'] == 'system']), 3)
        self.assertTrue((self.task / result['rough_chunks'][0]['path']).is_file())
        resumed = self.call('resume')
        self.assertFalse(resumed.get('presentations'))
        self.assertNotIn('viewed_captures', resumed['source_review'])
        groups = self.call('redraw-inputs')
        self.assertEqual(groups[0]['freeze_id'], result['freeze']['id'])

    def sequence(self, images, fps=4, crf=0):
        for index,image in enumerate(images):
            image.save(self.base/f'frame-{index:03d}.png')
        video=self.base/'sequence.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-framerate',str(fps),'-i',str(self.base/'frame-%03d.png'),
            '-c:v','libx264','-crf',str(crf),'-pix_fmt','yuv420p',str(video)],check=True)
        run=subprocess.run([sys.executable,str(CLI),str(video),'--output',str(self.task)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_short_page_and_later_repeated_music_survive_continuous_scan(self):
        from PIL import ImageDraw
        a=score_frame(); b=score_frame()
        ImageDraw.Draw(b).ellipse((1000,230,1020,250),fill='black')
        self.sequence([a,a,b,a,a])
        overview=self.call('overview')
        self.assertEqual(overview['scan']['frames_observed'],5)
        self.assertEqual(len(overview['candidates']),3)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        systems=[r for r in result['regions'] if r['kind']=='system']
        self.assertEqual(len(systems),9)
        self.assertEqual(len({r['position'] for r in systems}),9)
        self.assertEqual([e['pts'] for e in result['checks']['events']], [0,8192,12288])

    def test_high_off_staff_and_header_changes_survive_later_return(self):
        from PIL import ImageDraw
        for y in (154, 110):
            with self.subTest(y=y):
                self.task = self.base / f'task-{y}'
                a=score_frame()
                ImageDraw.Draw(a).line((300,145,300,240),fill='black',width=3)
                b=a.copy()
                ImageDraw.Draw(b).rectangle((390,y,393,y+3),fill='black')
                self.sequence([a,b,a])
                observed=self.call('overview')
                self.assertEqual(len(observed['candidates']),3)
                result=self.call('auto-freeze')
                self.assertEqual(result['status'],'frozen')
                self.assertTrue(any(r['capture']==observed['candidates'][1]['id']
                    for r in result['regions']),result['regions'])

    def test_invalid_crop_preserves_freeze_and_valid_revision_blocks_all_generation(self):
        self.prepare()
        result=self.call('auto-freeze')
        groups=self.call('redraw-inputs')
        region=next(r for r in result['regions'] if r['kind']=='system')
        self.call('revise-crop',{'index':1,'bbox':[-1,0,10,10]},success=False)
        resumed=self.call('resume')
        self.assertEqual(resumed['freeze'],result['freeze'])
        self.assertEqual(resumed['regions'][1]['sha256'],region['sha256'])
        box=region['bbox']; box[0]+=1
        revised=self.call('revise-crop',{'index':1,'bbox':box})
        self.assertNotIn('freeze',revised)
        self.call('redraw-inputs',success=False)
        self.call('begin-redraw',{'identifier':groups[0]['id'],'viewed_notes':'controlled assertion'},success=False)

    def test_native_spatial_scroll_keeps_rows_but_retains_new_off_staff_ink(self):
        from PIL import Image, ImageDraw
        a=score_frame()
        ImageDraw.Draw(a).line((300,145,300,240),fill='black',width=3)
        b=Image.new('RGB',a.size,'#303030')
        b.paste(a,(0,-80))
        self.sequence([a,b])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        self.assertEqual(len([r for r in result['regions'] if r['kind']=='system']),3)
        self.task=self.base/'changed-scroll'
        ImageDraw.Draw(b).rectangle((390,74,393,77),fill='black')
        self.sequence([a,b])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        self.assertEqual(len([r for r in result['regions'] if r['kind']=='system']),4)
        # Also protect ink outside the original row bbox, without a long stem
        # pre-expanding that bbox. Two unchanged lower anchors are insufficient.
        self.task=self.base/'expanded-scroll'
        a=score_frame();b=Image.new('RGB',a.size,'#303030');b.paste(a,(0,-80))
        ImageDraw.Draw(b).rectangle((390,74,393,77),fill='black')
        self.sequence([a,b])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        self.assertTrue(any(r['capture']==result['checks']['last']['capture']
            for r in result['regions']))

    def test_native_scroll_uses_earlier_complete_source_for_clipped_upper_row(self):
        from PIL import Image, ImageDraw
        a=score_frame()
        ImageDraw.Draw(a).line((300,145,300,240),fill='black',width=3)
        b=Image.new('RGB',a.size,'#303030')
        b.paste(a,(0,-210))
        self.sequence([a,b])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen',result.get('checks'))
        rows=[r for r in result['regions'] if r['kind']=='system']
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['capture'],result['checks']['first']['capture'])

    def test_interval_validation_and_resume_reuse_completed_scan(self):
        self.prepare()
        self.call('resample',{'intervals':[[0,2.1]],'reason':'invalid'},success=False)
        partial=self.call('resample',{'intervals':[[0,.5]],'reason':'suspected gap'})
        self.assertFalse(partial['scan']['complete'])
        self.assertEqual(partial['resamples'][-1]['reason'],'suspected gap')
        full=self.call('overview')
        self.assertTrue(full['scan']['complete'])
        again=self.call('overview')
        self.assertEqual(again['scan']['frames_observed'],full['scan']['frames_observed'])
        self.assertEqual(len(again['candidates']),len(full['candidates']))

    def test_off_staff_marks_short_row_and_true_edge_risk(self):
        from PIL import ImageDraw
        image=score_frame()
        draw=ImageDraw.Draw(image)
        draw.ellipse((380,153,398,171),outline='black',width=3)
        draw.line((500,168,510,159,520,168),fill='black',width=3)
        draw.ellipse((548,178,554,184),fill='black')
        # A genuinely short final staff and music width.
        draw.rectangle((820,640,1190,880),fill='white')
        self.prepare(image)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        rows=[r for r in result['regions'] if r['kind']=='system']
        self.assertLessEqual(rows[0]['bbox'][1],153)
        self.assertLess(rows[-1]['width'],rows[0]['width'])
        from PIL import Image
        with Image.open(self.task/rows[0]['path']) as crop:
            self.assertLess(crop.getpixel((389-rows[0]['bbox'][0],154-rows[0]['bbox'][1]))[0],170)

    def test_crop_revision_is_rechecked_and_preserved_when_refrozen(self):
        self.prepare()
        original=self.call('auto-freeze')
        index=next(i for i,r in enumerate(original['regions']) if r['kind']=='system')
        box=list(original['regions'][index]['bbox']); box[0]+=1
        self.call('revise-crop',{'index':index,'bbox':box})
        checked=self.call('auto-freeze')
        self.assertEqual(checked['status'],'frozen')
        self.assertEqual(checked['regions'][index]['bbox'],box)
        self.assertNotEqual(checked['freeze']['id'],original['freeze']['id'])
        stable=self.call('auto-freeze')
        self.assertEqual(stable['freeze'],checked['freeze'])

    def test_unrecovered_partial_final_system_blocks_freeze(self):
        from PIL import ImageDraw
        image=score_frame(); draw=ImageDraw.Draw(image)
        for yy in (890,902,914):
            draw.line((110,yy,1170,yy),fill='black',width=2)
        self.prepare(image)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'blocked')
        self.assertIn('incomplete_system',[r['code'] for r in result['checks']['unresolved']])
        self.call('redraw-inputs',success=False)

    def test_true_edge_and_white_music_occlusion_are_blocked(self):
        from PIL import ImageDraw
        image=score_frame(); draw=ImageDraw.Draw(image)
        for yy in (220,232,244,256,268):
            draw.line((70,yy,1170,yy),fill='black',width=2)
        draw.rectangle((390,205,480,280),fill='white')
        self.prepare(image)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'blocked')
        codes={r['code'] for r in result['checks']['unresolved']}
        self.assertIn('crop_edge',codes)
        self.assertIn('unreadable_music',codes)
        resumed=self.call('resume')
        self.assertEqual(resumed['automatic_resampling'][-1]['outcome'],'no_new_temporal_evidence')
        self.assertTrue(resumed['regions'])
        self.call('redraw-inputs',success=False)

    def test_program_freeze_can_begin_host_request_without_claiming_agent_view(self):
        self.prepare()
        frozen=self.call('auto-freeze')
        groups=self.call('redraw-inputs')
        request=self.call('begin-redraw',{'identifier':groups[0]['id']})
        self.assertEqual(request['approval']['producer'],'program')
        self.assertEqual(request['approval']['freeze_id'],frozen['freeze']['id'])
        self.assertNotIn('viewed_notes',request)

    def test_sigterm_scan_resumes_from_actual_observed_prefix(self):
        import signal
        import time
        image=self.base/'long.png'; score_frame().save(image)
        video=self.base/'long.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(image),'-t','20','-r','20',
            '-pix_fmt','yuv420p',str(video)],check=True)
        prepare=subprocess.run([sys.executable,str(CLI),str(video),'--output',str(self.task)],capture_output=True,text=True)
        self.assertEqual(prepare.returncode,0,prepare.stderr)
        process=subprocess.Popen([sys.executable,str(CLI),'--operation','overview','--task',str(self.task)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        deadline=time.monotonic()+15
        prefix=None
        while process.poll() is None and time.monotonic()<deadline:
            try:
                value=json.loads((self.task/'record.json').read_text())
                if value.get('overview',{}).get('scan',{}).get('frames_observed',0)>1:
                    prefix=value['overview']['scan']['cursor']
                    process.send_signal(signal.SIGTERM)
                    break
            except (OSError,ValueError):
                pass
            time.sleep(.01)
        out,err=process.communicate(timeout=15)
        self.assertIsNotNone(prefix,(out,err))
        interrupted=self.call('resume')
        spans=interrupted['overview']['scan']['completed_intervals']
        self.assertTrue(any(a==0 and b>=prefix for a,b in spans),spans)
        self.assertGreater(interrupted['metrics']['decode_elapsed'],0)
        resumed=self.call('overview')
        self.assertTrue(resumed['scan']['complete'],resumed['scan'])
        self.assertEqual(len({c['pts'] for c in resumed['candidates']}),len(resumed['candidates']))
        frozen=self.call('auto-freeze')
        self.assertEqual(frozen['status'],'frozen')
        self.assertEqual(len([r for r in frozen['regions'] if r['kind']=='system']),3)

    def test_fixed_upper_system_and_scrolling_lower_overlap_keep_positions(self):
        from PIL import ImageDraw
        a=score_frame(); b=a.copy()
        # The upper system remains fixed while the lower suffix moves upwards.
        b.paste(a.crop((70,610,1211,890)),(70,390))
        b.paste(a.crop((70,390,1211,610)),(70,610))
        ImageDraw.Draw(b).ellipse((1010,688,1025,702),fill='black')
        self.sequence([a,b])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        systems=[r for r in result['regions'] if r['kind']=='system']
        self.assertEqual(len(systems),4)
        self.assertEqual(result['checks']['events'][-1]['fixed_prefix_rows'],1)
        self.assertEqual(result['checks']['events'][-1]['overlap_rows'],1)

    def test_nonzero_scan_segments_observe_late_short_page_and_reach_actual_tail(self):
        from PIL import ImageDraw
        a=score_frame(); b=a.copy()
        ImageDraw.Draw(b).ellipse((1000,230,1020,250),fill='black')
        self.sequence([b if index==72 else a for index in range(80)])
        result=self.call('overview')
        self.assertTrue(result['scan']['complete'])
        self.assertEqual(result['scan']['frames_observed'],80)
        self.assertEqual([c['timestamp'] for c in result['candidates']], [0,18,18.25])
        self.assertEqual(result['scan']['segments'][-1]['last']['timestamp'],19.75)
        self.assertTrue(all(segment['frames']>0 for segment in result['scan']['segments']))

    def test_moving_thin_playback_line_does_not_repeat_stationary_systems(self):
        from PIL import ImageDraw
        frames=[]
        for x in (300,400,500,600):
            image=score_frame()
            ImageDraw.Draw(image).line((x,190,x,280),fill='#0080ff',width=3)
            frames.append(image)
        self.sequence(frames)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        self.assertEqual(len([r for r in result['regions'] if r['kind']=='system']),3)

    def test_moving_cursor_retains_bounded_candidates_and_reports_progress(self):
        from PIL import ImageDraw
        frames = []
        for x in range(300, 480, 9):
            image = score_frame()
            ImageDraw.Draw(image).line((x, 180, x, 350), fill='#488cc2', width=5)
            frames.append(image)
        self.sequence(frames, fps=25, crf=0)
        result = self.call('overview')
        self.assertTrue(result['scan']['complete'])
        self.assertLessEqual(len(result['candidates']), 4)
        progress = result['scan']['progress']
        self.assertEqual(progress['frames_observed'], 20)
        self.assertEqual(progress['candidates_retained'], len(result['candidates']))
        self.assertGreater(progress['candidate_bytes'], 0)
        self.assertGreaterEqual(progress['wall_seconds'], 0)
        self.assertGreater(progress['timings']['change_detection_seconds'], 0)
        self.assertGreater(progress['timings']['image_save_seconds'], 0)
        status = self.call('scan-status')
        self.assertTrue(status['metadata_only'])
        self.assertEqual(status['progress']['candidates_retained'], len(result['candidates']))
        self.assertLess(progress['checkpoint_writes'], 20)

    def test_lossy_moving_cursor_retains_bounded_candidates(self):
        from PIL import ImageDraw
        frames = []
        for x in range(300, 480, 9):
            image = score_frame()
            ImageDraw.Draw(image).line((x, 180, x, 350), fill='#488cc2', width=7)
            frames.append(image)
        self.sequence(frames, fps=25, crf=24)
        result = self.call('overview')
        self.assertTrue(result['scan']['complete'])
        self.assertLessEqual(len(result['candidates']), 4)

    def test_overlapping_cursor_does_not_hide_an_added_small_mark(self):
        from PIL import ImageDraw
        frames = []
        for index, x in enumerate(range(300, 320, 2)):
            image = score_frame()
            draw = ImageDraw.Draw(image)
            draw.line((x, 180, x, 350), fill='#488cc2', width=7)
            if index >= 5:
                draw.ellipse((400, 251, 403, 254), fill='black')
            frames.append(image)
        self.sequence(frames, fps=25)
        result = self.call('overview')
        self.assertTrue(result['scan']['complete'])
        self.assertLessEqual(len(result['candidates']), 4)
        self.assertTrue(any(c['timestamp'] == .2 for c in result['candidates']))

    def test_lossy_ambiguous_changes_stop_at_candidate_budget_without_freezing(self):
        from PIL import ImageDraw
        frames = []
        for x in range(300, 480, 9):
            image = score_frame()
            draw = ImageDraw.Draw(image)
            draw.line((x, 180, x, 350), fill='#488cc2', width=7)
            draw.ellipse((x + 300, 251, x + 303, 254), fill='black')
            frames.append(image)
        self.sequence(frames, fps=25, crf=24)
        result = self.call('overview', {'max_new_candidates': 4})
        self.assertFalse(result['scan']['complete'])
        self.assertEqual(len(result['candidates']), 4)
        self.assertEqual(result['resamples'][-1]['unresolved'][0]['code'], 'candidate_budget')
        self.assertGreater(result['scan']['progress']['candidate_ratio'], .5)
        frozen = self.call('auto-freeze')
        self.assertEqual(frozen['status'], 'blocked')
        self.call('redraw-inputs', success=False)
        self.call('overview', {'max_new_candidates': 0}, success=False)

    def test_unrelated_pure_staff_fragment_cannot_reuse_earlier_full_system(self):
        from PIL import Image, ImageDraw
        a=Image.new('RGB',(1280,960),'#303030');draw=ImageDraw.Draw(a)
        draw.rectangle((70,40,1210,910),fill='white')
        for yy in (220,232,244,256,268):
            draw.line((110,yy,1170,yy),fill='black',width=2)
        draw.ellipse((600,263,614,275),fill='black')
        b=a.copy(); draw=ImageDraw.Draw(b)
        for yy in (890,902):
            draw.line((110,yy,1170,yy),fill='black',width=2)
        self.sequence([a,b])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'blocked')
        self.assertIn('incomplete_system',[r['code'] for r in result['checks']['unresolved']])

    def test_solid_occlusion_connected_to_staff_blocks_hidden_music(self):
        from PIL import ImageDraw
        bad=score_frame()
        ImageDraw.Draw(bad).rectangle((390,205,480,280),fill='black')
        changed=score_frame()
        ImageDraw.Draw(changed).ellipse((1000,230,1020,250),fill='black')
        self.sequence([bad,changed])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'blocked')
        self.assertIn('unreadable_music',[r['code'] for r in result['checks']['unresolved']])

    def test_small_isolated_notation_changes_and_later_return_are_retained(self):
        from PIL import ImageDraw
        a=score_frame(); b=a.copy()
        ImageDraw.Draw(b).ellipse((238,251,240,253),fill='black')
        self.sequence([a,b,a])
        overview=self.call('overview')
        self.assertEqual(len(overview['candidates']),3)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        self.assertEqual(len([r for r in result['regions'] if r['kind']=='system']),9)

    def test_lossy_small_notation_and_later_return_remain_candidates(self):
        from PIL import ImageDraw
        a = score_frame()
        b = a.copy()
        ImageDraw.Draw(b).ellipse((238, 251, 241, 254), fill='black')
        self.sequence([a, b, a], crf=24)
        result = self.call('overview')
        self.assertTrue(result['scan']['complete'])
        self.assertEqual(len(result['candidates']), 3)
        self.assertEqual([c['timestamp'] for c in result['candidates']], [0, .25, .5])

    def test_unclassified_single_pixel_change_blocks_without_reprinting_the_viewport(self):
        from PIL import ImageDraw
        a=score_frame();b=a.copy()
        ImageDraw.Draw(b).point((238,251),fill='black')
        self.sequence([a,b])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'blocked')
        self.assertIn('ambiguous_visible_ink_change',[r['code'] for r in result['checks']['unresolved']])
        record=self.call('resume')
        self.assertEqual(len([r for r in record['regions'] if r['kind']=='system']),3)
        self.assertEqual(len(record['overview']['candidates']),2)
        self.call('redraw-inputs',success=False)

    def test_ordered_short_pages_keep_first_last_and_observed_blank_boundaries(self):
        from PIL import Image, ImageDraw
        blank=Image.new('RGB',(1280,960),'#303030')
        a=score_frame();b=a.copy();c=a.copy()
        ImageDraw.Draw(b).ellipse((1000,230,1020,250),fill='black')
        ImageDraw.Draw(c).ellipse((1000,670,1020,690),fill='black')
        self.sequence([blank,a,b,c,blank])
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'frozen')
        self.assertEqual([e['kind'] for e in result['checks']['events']],
            ['no_complete_staff','systems','systems','systems','no_complete_staff'])
        self.assertEqual(len([r for r in result['regions'] if r['kind']=='system']),9)
        self.assertEqual(result['checks']['first']['pts'],4096)
        self.assertEqual(result['checks']['last']['pts'],12288)

    def test_two_pixel_white_border_does_not_hide_cut_stems(self):
        from PIL import ImageDraw
        image=score_frame().crop((0,210,1280,960))
        ImageDraw.Draw(image).rectangle((70,0,1210,1),fill='white')
        self.prepare(image)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'blocked')
        self.assertIn('crop_edge',[risk['code'] for risk in result['checks']['unresolved']])

    def test_associated_header_touching_paper_edge_is_blocked(self):
        from PIL import ImageDraw
        image=score_frame();draw=ImageDraw.Draw(image)
        draw.rectangle((70,0,1210,40),fill='white')
        draw.line((300,2,300,60),fill='black',width=3)
        self.prepare(image)
        result=self.call('auto-freeze')
        self.assertEqual(result['status'],'blocked')
        self.assertIn('crop_edge',[risk['code'] for risk in result['checks']['unresolved']])
