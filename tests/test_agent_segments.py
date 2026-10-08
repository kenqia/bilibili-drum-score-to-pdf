"""Ordered score pages through the public conversion CLI."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_agent_continuity as fixture


class SegmentTests(unittest.TestCase):
    cli = fixture.ContinuityTests.cli
    prepare = fixture.ContinuityTests.prepare
    def decision(self, base):
        task, old = self.prepare(base)
        packet = json.loads((task / 'observation.json').read_text())
        d = {k:v for k,v in old.items() if k not in ('rows','observations','transitions')}
        d.update(schema_version=4, decision_id='pages', segments=[], boundaries=[])
        for index, frame_ids in enumerate((['frame-000'], ['frame-001','frame-002'])):
            sightings = [copy.deepcopy(s) for s in old['observations'] if s['frame_id'] in frame_ids]
            # Page-local spatial labels intentionally repeat, including equal music.
            for s in sightings:
                s['instance_id'] = chr(65 + (s['staff_y']-220)//220)
            rows=[]
            for s in sightings[:3]:
                rows.append(dict(instance_id=s['instance_id'], observation_id=s['id'], frame_id=s['frame_id'],
                    coordinate_space='native_pixels', roi=[0,0,1280,960], bbox=s['bbox'],
                    evidence_images=[i['id'] for i in packet['images'] if i.get('frame_id')==s['frame_id'] and i['kind']=='native_detail'],
                    complete=True,cursor='clear',occlusion='clear',boundary_verified=True,evidence='Native full row.'))
            transitions=[] if index==0 else [copy.deepcopy(old['transitions'][1])]
            # An Agent-confirmed title exists even where detector header is empty.
            header = {k:v for k,v in rows[0].items() if k not in ('instance_id','observation_id')}
            header.update(bbox=[70,20,1210,160], evidence='Full title and tempo region.')
            d['segments'].append(dict(id=f'page-{index}',frames=frame_ids,rows=rows,observations=sightings,
                transitions=transitions,extras=[dict(kind='title',placement='before_rows',region=header)],
                outside_rows_verified=True,evidence='All title and dynamics included; start and end visible.'))
        d['boundaries']=[dict(from_segment='page-0',to_segment='page-1',from_frame='frame-000',to_frame='frame-001',
            change='page_turn',relation='next',before_complete=True,after_complete=True,continuity_verified=True,
            evidence_images=['frame-000','frame-001','comparison'],unresolved=[],
            evidence='Visible last bar ends before page turn and next page begins at its succeeding bar; no hidden page inferred from a count.')]
        return task,d

    def test_two_pages_keep_equal_instances_titles_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); task,d=self.decision(base)
            path=base/'decision.json'; path.write_text(json.dumps(d))
            accepted=self.cli('--operation','submit','--task',task,'--decision',path)
            self.assertEqual(accepted['phase'],'accepted',accepted)
            out=base/'out'; result=self.cli('--operation','export','--task',task,'--output',out)
            self.assertEqual(result['status'],'success',result)
            self.assertEqual([r['segment_id'] for r in result['rows']], ['page-0']*3+['page-1']*3)
            self.assertEqual([r['global_y'] for r in result['rows']], [220,440,660]*2)
            self.assertEqual(len(result['extras']),2)
            self.assertEqual(result['coverage']['scope'],'observed_ordered_segments')
            again=self.cli('--operation','replay','--task',task,'--output',base/'again')
            self.assertEqual(again['status'],'success',again)
            self.assertEqual((out/'score.pdf').read_bytes(),(base/'again/score.pdf').read_bytes())

    def test_ambiguous_boundaries_and_unprotected_symbols_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); task,d=self.decision(base); path=base/'bad.json'
            cases=[
                ('skip',lambda x:x['boundaries'][0].update(relation='skip')),
                ('backward',lambda x:x['boundaries'][0].update(relation='backward')),
                ('similar page unknown',lambda x:x['boundaries'][0].update(relation='uncertain')),
                ('not continuity proof',lambda x:x['boundaries'][0].update(continuity_verified=False)),
                ('edge fragment',lambda x:x['segments'][0]['observations'][-1].update(complete=False)),
                ('jump layout',lambda x:x['boundaries'][0].update(change='layout_jump')),
                ('zoom',lambda x:x['boundaries'][0].update(change='scale')),
                ('missing page frame',lambda x:x['segments'][1].update(frames=['frame-002'])),
                ('missing boundary',lambda x:x.update(boundaries=[])),
                ('unprotected title',lambda x:x['segments'][0].update(outside_rows_verified=False)),
                ('wrong region order',lambda x:x['segments'][0]['extras'][0].update(placement='after_rows')),
                ('duplicate title',lambda x:x['segments'][0]['extras'].append(copy.deepcopy(x['segments'][0]['extras'][0])))]
            for name,change in cases:
                with self.subTest(name=name):
                    bad=copy.deepcopy(d);change(bad);path.write_text(json.dumps(bad))
                    result=self.cli('--operation','submit','--task',task,'--decision',path)
                    self.assertEqual(result['status'],'waiting',result)
                    self.assertTrue(result['issues'])
                    self.assertFalse((task/'decision.json').exists())
