"""Spatial Agent decisions exercised through the unified CLI."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw
from score_fixtures import CLI


class ContinuityTests(unittest.TestCase):
    def cli(self, *args):
        p = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)
        return json.loads(p.stdout)

    def prepare(self, base):
        # Equal visual content at distinct long-score positions is intentional.
        for frame_index, ys in enumerate(([220, 440, 660], [220, 440, 660], [220, 440, 660], [220, 440, 660],
                                         [220, 440, 660], [220, 440, 660], [220, 440, 660], [220, 440, 660])):
            image = Image.new('RGB', (1280, 960), 'white')
            draw = ImageDraw.Draw(image)
            for y in ys:
                for line in range(5):
                    draw.line((80, y + 12 * line, 1200, y + 12 * line), fill='black', width=2)
                draw.ellipse((220, y + 25, 235, y + 40), fill='black')
                draw.text((300, y + 65), chr(ord('A') + ys.index(y) + (frame_index >= 4)), fill='black')
            image.save(base / f'{frame_index:03d}.png')
        video = base / 'input.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '4', '-i', str(base / '%03d.png'), '-pix_fmt', 'yuv420p', str(video)], check=True)
        task = base / 'task'
        state = self.cli(video, '--operation', 'prepare', '--output', task)
        packet = json.loads((task / 'observation.json').read_text())
        decision = dict(schema_version=3, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                        decision_id='scroll', model=dict(id='fixture', version='unknown'), prompt=dict(version='spatial-1', text='Compare spatial rows and native details.'),
                        presented_images=[i['id'] for i in packet['images']], visual_review=True, complete=True,
                        evidence='Two rows visibly correspond; later equal content is a different spatial row.', unresolved=[],
                        rows=[], observations=[], transitions=[], coverage=dict(first_frame='frame-000', last_frame='frame-002', unresolved=[]))
        # First stable view has A/B/C. Later view B/C/D after +220 scroll.
        for fi, (instances, ys) in enumerate([(list('ABC'), [220, 440, 660]), (list('BCD'), [220, 440, 660]), (list('BCD'), [220, 440, 660])]):
            for instance, y in zip(instances, ys):
                obs = dict(id=f'{fi}-{instance}', frame_id=f'frame-{fi:03d}', instance_id=instance,
                           staff_y=y, spacing=12, bbox=[70, y-40, 1210, y+100], complete=True, evidence='Visible staff and complete row.')
                decision['observations'].append(obs)
                if instance not in [r['instance_id'] for r in decision['rows']]:
                    decision['rows'].append(dict(instance_id=instance, observation_id=obs['id'], frame_id=obs['frame_id'],
                        coordinate_space='native_pixels', roi=[0,0,1280,960], bbox=obs['bbox'],
                        evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id') == obs['frame_id'] and i['kind']=='native_detail'],
                        complete=True, cursor='clear', occlusion='clear', boundary_verified=True, evidence='Full clean native row.'))
        decision['transitions'] = [dict(from_frame='frame-000', to_frame='frame-001', matches=[['0-B','1-B'],['0-C','1-C']], evidence='B and C keep their order; scroll is 220 pixels.'),
                                   dict(from_frame='frame-001', to_frame='frame-002', matches=[['1-B','2-B'],['1-C','2-C'],['1-D','2-D']], evidence='Same positions during the pause.')]
        return task, decision

    def test_scroll_and_pause_preserve_distinct_repeated_spatial_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare(base)
            path = base / 'decision.json'; path.write_text(json.dumps(decision))
            accepted = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(accepted['phase'], 'accepted', accepted)
            out = base / 'out'
            result = self.cli('--operation', 'export', '--task', task, '--output', out)
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual([r['global_y'] for r in result['rows']], [220,440,660,880])
            self.assertEqual([r['instance_id'] for r in result['rows']], list('ABCD'))
            self.assertEqual(result['coverage']['hidden_content_proven_absent'], False)
            replay = self.cli('--operation', 'replay', '--task', task, '--output', base / 'replay')
            self.assertEqual(replay['status'], 'success', replay)
            self.assertEqual((out/'score.pdf').read_bytes(), (base/'replay/score.pdf').read_bytes())

    def test_missing_identity_and_geometry_conflicts_remain_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare(base)
            path = base / 'bad.json'
            cases = [
                ('same spatial position', lambda d: d['observations'][1].update(staff_y=220, bbox=[80,180,1200,320])),
                ('overlapping rows', lambda d: d['observations'][1].update(bbox=[80,250,1200,550])),
                ('single overlap', lambda d: d['transitions'][0].update(matches=[['0-B','1-B']])),
                ('conflicting shift', lambda d: d['observations'][4].update(staff_y=460)),
                ('scale change', lambda d: d['observations'][4].update(spacing=16)),
                ('tail missing', lambda d: d['coverage'].update(last_frame='frame-001')),
                ('missing relation', lambda d: d['transitions'][1].update(matches=[['1-B','2-B'],['1-C','2-C']])),
                ('cyclic order', lambda d: d['transitions'][1].update(to_frame='frame-000')),
                ('partial only', lambda d: d['observations'][5].update(complete=False)),
                ('missing row', lambda d: d.update(rows=d['rows'][:-1])),
                ('repeated instance', lambda d: d['rows'][3].update(instance_id='A')),
                ('unresolved gap', lambda d: d['coverage'].update(unresolved=['rapid jump may hide a row']))]
            for name, change in cases:
                with self.subTest(name=name):
                    bad=copy.deepcopy(decision); change(bad); path.write_text(json.dumps(bad))
                    result=self.cli('--operation','submit','--task',task,'--decision',path)
                    self.assertEqual(result['status'],'waiting',result)
                    self.assertFalse((task/'decision.json').exists())
                    self.assertTrue(result['issues'])

    def test_partial_observation_can_only_select_its_later_complete_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); task,decision=self.prepare(base)
            decision['observations'][1]['complete']=False
            later=decision['observations'][3]
            packet=json.loads((task/'observation.json').read_text())
            row=decision['rows'][1]
            row.update(observation_id=later['id'],frame_id=later['frame_id'],bbox=later['bbox'],
                       evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id')==later['frame_id'] and i['kind']=='native_detail'])
            path=base/'decision.json'; path.write_text(json.dumps(decision))
            result=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(result['phase'],'accepted',result)
            result=self.cli('--operation','export','--task',task,'--output',base/'out')
            self.assertEqual(result['status'],'success',result)
            self.assertEqual(result['rows'][1]['source_frame'],'frame-001.png')
