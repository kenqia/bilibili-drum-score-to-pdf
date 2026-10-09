"""Experimental content veto through the approved unified CLI seam."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw, ImageFont
from score_fixtures import CLI
import test_decision_builder


class ContentChecksTests(unittest.TestCase):
    request = test_decision_builder.DecisionBuilderTests.request
    build = test_decision_builder.DecisionBuilderTests.build

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)
        self.assertTrue(result.stdout, result.stderr)
        return json.loads(result.stdout)

    def reviewed_request(self, task, decision):
        request,packet=test_decision_builder.DecisionBuilderTests.reviewed_request(self,task,decision)
        if packet.get('evidence_mode')!='lazy':
            return request,packet
        segment=decision['segments'][0]
        frames=packet['frames']
        details={f['id']:next(i['id'] for i in packet['images'] if i['kind']=='native_detail'
                 and i.get('frame_id')==f['id'] and i['bbox']==[0,0,f['width'],f['height']]) for f in frames}
        def region(fid,bbox):
            return dict(frame_id=fid,bbox=copy.deepcopy(bbox),evidence_images=[details[fid]])
        title=segment['extras'][0]['region']
        checks={kind:dict(status='checked',regions=[region(title['frame_id'],title['bbox'])],
                    print_regions=[dict(kind='extra',index=0)],evidence='Drawn native fixture title, tempo 96 and 4/4 are inside the title extra.')
                for kind in ('title','tempo','time_signature')}
        row=segment['rows'][0]
        checks['outside_rows']=dict(status='checked',regions=[region(row['frame_id'],row['bbox'])],
                    print_regions=[dict(kind='row',index=0)],evidence='Drawn native stems and beams lie inside the complete printed row.')
        first,last=frames[0],frames[-1]
        request['review']['score_audit']=dict(segments=[dict(id=segment['id'],checks=checks,
            first_edge=dict(complete=True,regions=[region(first['id'],[0,0,first['width'],first['height']])],
                            evidence='Opening title and complete first native staff are visible.'),
            last_edge=dict(complete=True,regions=[region(last['id'],[0,0,last['width'],last['height']])],
                           evidence='Final native D staff and blank ending margin are visible.'))],
            intervals=[dict(from_frame=a['id'],to_frame=b['id'],status='checked',
                            regions=[region(f['id'],[0,0,f['width'],f['height']]) for f in (a,b)],
                            evidence='Controlled true translation and pause endpoints reviewed; no claim about hidden unsampled content.')
                       for a,b in zip(frames,frames[1:])],unresolved=[])
        return request,packet

    def prepare_score(self, base, wrong=False, mode='lazy', variant='notes'):
        # A genuinely translated long score. D repeats A's music at a new position.
        long_score = Image.new('RGB', (1280, 1400), 'white')
        draw = ImageDraw.Draw(long_score)
        font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',28)
        draw.text((100,75),'Fixture score    tempo 96    4/4',fill='black',font=font)
        for row, y in enumerate((220, 440, 660, 880)):
            for line in range(5):
                draw.line((80, y + 12*line, 1200, y + 12*line), fill='black', width=2)
            if variant != 'empty':
                for n in range(5):
                    x = 180 + (row % 3)*55 + n*155
                    draw.ellipse((x-10, y+23, x+10, y+39), fill='black')
                    draw.line((x+10, y+31, x+10, y-32), fill='black', width=3)
                    draw.line((x+10, y-32, x+55, y-32), fill='black', width=4)
        for index in range(8):
            shift = 220 if index >= 4 else 0
            frame = long_score.crop((0, shift, 1280, shift+960))
            if variant == 'overlay':
                ImageDraw.Draw(frame).rectangle((150,196,350,256),fill='black')
            if variant == 'cursor' and index >= 4:
                ImageDraw.Draw(frame).rectangle((490, 180, 506, 760), fill='#e05050')
            frame.save(base / f'{index:03d}.png')
        video = base / 'input.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '4', '-i', str(base/'%03d.png'), '-pix_fmt', 'yuv420p', str(video)], check=True)
        task = base / 'task'
        state = self.cli(video, '--output', task, '--evidence-mode', mode)
        self.assertEqual(state['status'], 'waiting', state)
        packet = json.loads((task/'observation.json').read_text())
        if mode == 'lazy':
            request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                observation_version=state['observation_version'], source_sha256=packet['source']['sha256'],
                request_id='content-evidence', reason='Controlled fixture reviews native complete rows.',
                regions=[dict(frame_id=f['id'], frame_sha256=f['sha256'], pts=f['pts'], time_base=f['time_base'], bbox=[0,0,1280,960]) for f in packet['frames']])
            path = base / 'materialize.json'; path.write_text(json.dumps(request))
            state = self.cli('--operation','materialize','--task',task,'--decision',path)
            self.assertEqual(state['phase'], 'review', state)
            packet = json.loads((task/'observation.json').read_text())
        frames = packet['frames']
        decision = dict(schema_version=3, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
            decision_id='content-test', model=dict(id='controlled-fixture',version='unknown'),
            prompt=dict(version='content-test',text='Review five-line geometry and native score.'),
            presented_images=[i['id'] for i in packet['images']],visual_review=True,complete=True,
            evidence='Controlled fixture reviews full native margins and geometric correspondences.', unresolved=[],
            rows=[],observations=[],transitions=[],coverage=dict(first_frame=frames[0]['id'],last_frame=frames[-1]['id'],unresolved=[]))
        instances = [list('ABC'), list('ABC' if wrong else 'BCD'), list('ABC' if wrong else 'BCD')]
        for fi, (frame, labels) in enumerate(zip(frames, instances)):
            for instance, y in zip(labels, (220,440,660)):
                sighting = dict(id=f'{fi}-{instance}',frame_id=frame['id'],instance_id=instance,staff_y=y,spacing=12,
                    bbox=[70,y-48,1210,y+100],complete=True,evidence='Complete five-line native observation.')
                decision['observations'].append(sighting)
                if instance not in [r['instance_id'] for r in decision['rows']]:
                    decision['rows'].append(dict(instance_id=instance,observation_id=sighting['id'],frame_id=frame['id'],
                        coordinate_space='native_pixels',roi=[0,0,1280,960],bbox=sighting['bbox'],
                        evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id')==frame['id'] and i['kind']=='native_detail'],
                        complete=True,cursor='clear',occlusion='clear',boundary_verified=True,evidence='Full clean native crop.'))
        for fi in range(2):
            common = [i for i in instances[fi] if i in instances[fi+1]]
            decision['transitions'].append(dict(from_frame=frames[fi]['id'],to_frame=frames[fi+1]['id'],
                matches=[[f'{fi}-{i}',f'{fi+1}-{i}'] for i in common],evidence='Controlled fixture explicitly proposes these ordered correspondences.'))
        header=dict(frame_id=frames[0]['id'],coordinate_space='native_pixels',roi=[0,0,1280,960],bbox=[70,40,1210,140],
            evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id')==frames[0]['id'] and i['kind']=='native_detail'],
            complete=True,cursor='clear',occlusion='clear',boundary_verified=True,evidence='Native title, tempo and time signature.')
        segment=dict(id='score',frames=[f['id'] for f in frames],rows=decision.pop('rows'),observations=decision.pop('observations'),
            transitions=decision.pop('transitions'),extras=[dict(kind='title',placement='before_rows',region=header)],
            outside_rows_verified=True,evidence='Controlled native title and row margins reviewed.')
        decision.update(schema_version=4,segments=[segment],boundaries=[])
        return task, decision

    def test_geometrically_self_consistent_wrong_correspondence_cannot_export(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,wrong=True)
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertFalse(draft['ready_to_submit'],draft)
            checks=draft['sources']['content_checks']
            self.assertIn('conflict',[c['status'] for c in checks])
            path=base/'direct.json';path.write_text(json.dumps(decision))
            rejected=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(rejected['status'],'waiting',rejected)
            out=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertNotEqual(out['status'],'success',out)
            self.assertFalse((base/'out/score.pdf').exists())

    def test_corrected_correspondence_keeps_repeated_music_and_replays_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base)
            wrong=copy.deepcopy(decision)
            part=wrong['segments'][0]
            part['rows']=part['rows'][:3]
            for fi in (1,2):
                for offset,label in enumerate('ABC'):
                    part['observations'][fi*3+offset].update(id=f'{fi}-{label}',instance_id=label)
            for fi,t in enumerate(part['transitions']):
                t['matches']=[[f'{fi}-{label}',f'{fi+1}-{label}'] for label in 'ABC']
            bad,_=self.reviewed_request(task,wrong)
            rejected=self.build(base,task,bad,'wrong-draft')
            self.assertFalse(rejected['ready_to_submit'],rejected)
            request,_=self.reviewed_request(task,decision)
            request['proposal']=bad['proposal']
            request['corrections']=[dict(path=['segments',0,k],value=decision['segments'][0][k]) for k in ('rows','observations','transitions')]
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            self.assertTrue(all(c['status']=='not_contradicted' for c in draft['sources']['content_checks']))
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            out=self.cli('--operation','export','--task',task,'--output',base/'out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(out['status'],'success',out)
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual([r['instance_id'] for r in out['rows']],list('ABCD'))
            self.assertEqual([r['global_y'] for r in out['rows']],[220,440,660,880])
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())
            for row in out['rows']:
                with Image.open(base/'out'/row['source_frame']) as frame, Image.open(base/'out'/row['original_image']) as crop:
                    self.assertEqual(frame.crop(row['bbox']).tobytes(),crop.tobytes())
            report=self.cli('--operation','report','--task',task)['performance']
            self.assertGreater(report['content_validation']['pair_checks'],0)
            self.assertGreater(report['content_validation']['analyzed_pixels'],0)
            self.assertIn('content_validation',[e['name'] for e in report['stages']])

    def test_identical_obstructed_regions_are_uncertain_instead_of_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,variant='overlay')
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertFalse(draft['ready_to_submit'],draft)
            checks=draft['sources']['content_checks']
            obstructed=[c for c in checks if c['matches']==['1-B','2-B']]
            self.assertEqual([c['status'] for c in obstructed],['uncertain'])
            self.assertIn('overlay',obstructed[0]['reason'])

    def test_cursor_and_low_information_cannot_be_confirmed_by_review_flags(self):
        for variant, reason in (('cursor','cursor_or_obstruction'),('empty','insufficient_notation_ink')):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as directory:
                base=Path(directory);task,decision=self.prepare_score(base,variant=variant)
                request,_=self.reviewed_request(task,decision)
                draft=self.build(base,task,request)
                self.assertFalse(draft['ready_to_submit'],draft)
                self.assertIn(reason,[c['reason'] for c in draft['sources']['content_checks']])
                path=base/'review.json';path.write_text(json.dumps(decision))
                rejected=self.cli('--operation','submit','--task',task,'--decision',path)
                self.assertEqual(rejected['status'],'waiting',rejected)
                out=self.cli('--operation','export','--task',task,'--output',base/'out')
                self.assertNotEqual(out['status'],'success',out)
                self.assertFalse((base/'out/score.pdf').exists())
                report=self.cli('--operation','report','--task',task)['performance']
                self.assertGreater(report['content_validation']['uncertain_checks'],0)
                self.assertGreater(report['content_validation']['pair_checks'],0)

    def test_partial_observation_and_crop_hiding_native_staff_stay_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base)
            partial=copy.deepcopy(decision)
            partial['segments'][0]['observations'][3]['complete']=False
            request,_=self.reviewed_request(task,partial)
            draft=self.build(base,task,request,'partial')
            self.assertFalse(draft['ready_to_submit'],draft)
            self.assertIn('partial_or_missing_margin',[c['reason'] for c in draft['sources']['content_checks']])
            narrow=copy.deepcopy(decision)
            for sighting in narrow['segments'][0]['observations']:
                sighting['bbox'][0]=180
            for row in narrow['segments'][0]['rows']:
                row['bbox'][0]=180
            request,_=self.reviewed_request(task,narrow)
            draft=self.build(base,task,request,'narrow')
            self.assertFalse(draft['ready_to_submit'],draft)
            self.assertIn('crop_excludes_native_staff',[c['reason'] for c in draft['sources']['content_checks']])

    def test_legacy_full_keeps_existing_geometry_only_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base,wrong=True,mode='full')
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertTrue(draft['ready_to_submit'],draft)
            self.assertEqual(draft['sources']['content_checks'],[])
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            report=self.cli('--operation','report','--task',task)['performance']
            self.assertEqual(report['content_validation']['pair_checks'],0)

    def test_uncertain_crop_restores_complete_native_boundary_and_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base)
            narrow=copy.deepcopy(decision)
            for key in ('observations','rows'):
                for record in narrow['segments'][0][key]:
                    record['bbox'][0]=180
            request,_=self.reviewed_request(task,narrow)
            waiting=self.build(base,task,request,'narrow')
            self.assertFalse(waiting['ready_to_submit'],waiting)
            restored,_=self.reviewed_request(task,decision)
            restored['proposal']=request['proposal']
            restored['corrections']=[dict(path=['segments',0,key,index,'bbox'],value=record['bbox'])
                for key in ('observations','rows') for index,record in enumerate(decision['segments'][0][key])]
            ready=self.build(base,task,restored,'restored')
            self.assertTrue(ready['ready_to_submit'],ready)
            self.assertTrue(all(c['status']=='not_contradicted' for c in ready['sources']['content_checks']))
            accepted=self.cli('--operation','submit','--task',task,'--decision',base/'restored/decision.json')
            self.assertEqual(accepted['phase'],'accepted',accepted)
            out=self.cli('--operation','export','--task',task,'--output',base/'out')
            replay=self.cli('--operation','replay','--task',task,'--output',base/'replay')
            self.assertEqual(out['status'],'success',out)
            self.assertEqual(replay['status'],'success',replay)
            self.assertEqual([r['instance_id'] for r in out['rows']],list('ABCD'))
            self.assertEqual((base/'out/score.pdf').read_bytes(),(base/'replay/score.pdf').read_bytes())
            for row in out['rows']:
                with Image.open(base/'out'/row['source_frame']) as frame, Image.open(base/'out'/row['original_image']) as crop:
                    self.assertEqual(frame.crop(row['bbox']).tobytes(),crop.tobytes())

    def test_subpixel_staff_geometry_waits_without_fabricating_content_support(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);task,decision=self.prepare_score(base)
            for sighting in decision['segments'][0]['observations']:
                sighting['spacing']=.001
            request,_=self.reviewed_request(task,decision)
            draft=self.build(base,task,request)
            self.assertEqual(draft['status'],'waiting',draft)
            self.assertFalse(draft['ready_to_submit'],draft)
            self.assertIn('unreliable_five_line_spacing',[c['reason'] for c in draft['sources']['content_checks']])
