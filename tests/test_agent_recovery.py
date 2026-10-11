"""Recovery keeps raw provenance and hard content vetoes through the CLI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
import test_agent_content as fixtures


class RecoveryTests(unittest.TestCase):
    minimum_chain = True
    request = fixtures.ContentChecksTests.request
    build = fixtures.ContentChecksTests.build
    prepare_score = fixtures.ContentChecksTests.prepare_score

    def cli(self, *args):
        if '--evidence-mode' in args and 'lazy' in args:
            args = (*args, '--evidence-recovery')
            if getattr(self, 'mixed', False):
                args = (*args, '--script-acceptance')
        return fixtures.ContentChecksTests.cli(self, *args)

    def reviewed_request(self, task, decision):
        request, packet = fixtures.ContentChecksTests.reviewed_request(self, task, decision)
        records = []
        for sighting in decision['segments'][0]['observations']:
            frame = next(f for f in packet['frames'] if f['id'] == sighting['frame_id'])
            bbox = [0, sighting['bbox'][1], frame['width'], sighting['bbox'][3]]
            with Image.open(task / frame['path']) as image:
                pixels = np.asarray(image.crop(bbox)).astype(int)
            # Known fixture truth, not a real-video clean classifier.
            cursor = bool(((pixels.max(axis=2)-pixels.min(axis=2)) > 70).any())
            records.append(dict(frame_id=frame['id'], frame_sha256=frame['sha256'],
                pts=frame['pts'], time_base=frame['time_base'], bbox=bbox,
                evidence_images=[i['id'] for i in packet['images']
                    if i.get('frame_id') == frame['id'] and i['kind'] == 'native_detail'],
                cursor='present' if cursor else 'clear', occlusion='clear',
                evidence='Known controlled fixture complete source and deliberate colored cursor.'))
        request['review']['native_clean_regions'] = records
        return request, packet

    def test_cursor_results_retained_and_reused_frames_preserve_pts_without_reviews(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base, variant='stationary_bridge_cursor')
            request, packet = self.reviewed_request(task, decision)
            draft = self.build(base, task, request)
            self.assertTrue(draft['ready_to_submit'], draft.get('unresolved'))
            dirty = [c for c in draft['sources']['content_checks'] if c['reason'] == 'cursor_or_obstruction']
            self.assertTrue(dirty)
            self.assertTrue(all(not c['blocking'] and c['replacement_evidence']['original_result_retained'] for c in dirty))
            accepted = self.cli('--operation', 'submit', '--task', task, '--decision', base/'draft/decision.json')
            self.assertEqual(accepted['phase'], 'accepted', accepted.get('error'))
            reused = base/'reused'
            state = self.cli('--reuse-task', task, '--output', reused, '--evidence-mode', 'lazy', '--minimum-evidence-chain')
            self.assertEqual(state['phase'], 'review', state.get('error'))
            fresh = json.loads((reused/'observation.json').read_text())
            self.assertEqual([(f['sha256'],f['pts'],f['time_base']) for f in packet['frames']],
                             [(f['sha256'],f['pts'],f['time_base']) for f in fresh['frames']])
            self.assertFalse(fresh['recovery_seed']['reviews_reused'])
            self.assertEqual(state['decision_history'], [])
            self.assertEqual(state['metrics']['seek_count'], 0)
            proposal = json.loads((reused/'seed-proposal.json').read_text())
            self.assertTrue(all(not r['complete'] and not r['evidence_images'] for r in proposal['segments'][0]['rows']))
            plan = self.cli('--operation', 'candidate-plan', '--task', reused, '--output', base/'candidates')
            self.assertEqual(plan['row_count'], 3, plan.get('error'))
            resumed = self.cli('--operation', 'resume', '--task', reused)
            self.assertEqual(resumed['phase'], 'review', resumed.get('error'))

    def test_unknown_and_explicit_content_conflicts_remain_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base, variant='stationary_bridge_conflict')
            request, _ = self.reviewed_request(task, decision)
            result = self.build(base, task, request)
            self.assertFalse(result['ready_to_submit'])
            self.assertTrue(any(c['status'] == 'conflict' and c['blocking'] for c in result['sources']['content_checks']))
            request = copy.deepcopy(request)
            request['review']['native_clean_regions'][0]['occlusion'] = 'uncertain'
            result = self.build(base, task, request, 'unknown')
            self.assertFalse(result['ready_to_submit'])
            self.assertTrue(any(b['reason'] == 'native_occlusion_uncertain'
                for c in result['sources']['content_checks'] for b in c.get('native_blockers', [])))

    def test_independent_edges_cover_gaps_through_geometry_only_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base, variant='stationary_edge_support')
            state = json.loads((task/'task.json').read_text())
            packet = json.loads((task/'observation.json').read_text())
            request = dict(schema_version=1, task_id=state['task_id'],
                observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                request_id='four-endpoints', issue=dict(reason='Controlled independent edge fixture.',start=0,end=2),
                timestamps=[.5])
            path = base/'supplement.json'; path.write_text(json.dumps(request))
            state = self.cli('--operation','supplement','--task',task,'--decision',path)
            self.assertEqual(state['phase'], 'review', state.get('error'))
            packet = json.loads((task/'observation.json').read_text())
            request = dict(schema_version=1, task_id=state['task_id'],
                observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                source_sha256=packet['source']['sha256'], request_id='four-native',
                reason='Controlled native endpoint fixture.', regions=[dict(frame_id=f['id'],
                    frame_sha256=f['sha256'],pts=f['pts'],time_base=f['time_base'],bbox=[0,0,1280,960])
                    for f in packet['frames']])
            path = base/'materialize-four.json'; path.write_text(json.dumps(request))
            state = self.cli('--operation','materialize','--task',task,'--decision',path)
            packet = json.loads((task/'observation.json').read_text())
            part = decision['segments'][0]; templates = copy.deepcopy(part['observations'][:3])
            part['frames'] = [f['id'] for f in packet['frames']]
            part['observations'] = [dict(copy.deepcopy(s),id=f'{fi}-{s["instance_id"]}',frame_id=f['id'],
                complete=not (s['instance_id']=='C' and fi in (1,2)))
                for fi,f in enumerate(packet['frames']) for s in templates]
            part['transitions'] = [dict(from_frame=a['id'],to_frame=b['id'],
                matches=[[f'{fi}-{k}',f'{fi+1}-{k}'] for k in 'ABC'],evidence='Controlled ordered geometry.')
                for fi,(a,b) in enumerate(zip(packet['frames'],packet['frames'][1:]))]
            decision.update(observation_sha256=state['observation_sha256'],
                presented_images=[i['id'] for i in packet['images']],
                coverage=dict(first_frame=part['frames'][0],last_frame=part['frames'][-1],unresolved=[]))
            request, _ = self.reviewed_request(task, decision)
            allowed = {(0,'A'),(2,'A'),(1,'B'),(3,'B'),(0,'C'),(3,'C')}
            request['review']['native_clean_regions'] = [r for r in request['review']['native_clean_regions']
                if (part['frames'].index(r['frame_id']), 'ABC'[(r['bbox'][1]-172)//220]) in allowed]
            draft = self.build(base, task, request)
            self.assertTrue(draft['ready_to_submit'], draft.get('unresolved'))
            intervals = [c['evidence_chain'] for c in draft['sources']['content_checks']
                if c['scope']=='proposed_geometric_pair_only']
            self.assertTrue(all(c['sufficient'] and len(c['witnesses'])==2 for c in intervals))
            self.assertTrue(all(len({(w['from_frame'],w['to_frame']) for w in c['witnesses']})==2 for c in intervals))
            self.assertTrue(any(c['reason']=='partial_or_missing_margin' and not c['blocking']
                for c in draft['sources']['content_checks']))

    def test_mixed_gap_recomputes_and_exports_identical_replay(self):
        self.mixed = True
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base, variant='stationary_bridge_cursor')
            request, _ = self.reviewed_request(task, decision)
            request['review']['visual_review'] = False
            request['review']['transitions'] = dict(evidence='Script suggestion; trusted clean ordered bridge required.')
            for confirmation in request['review']['confirmations']:
                if 'transitions' in confirmation['path'] and confirmation['path'][-1] == 'evidence':
                    confirmation['value'] = 'Script suggestion; trusted clean ordered bridge required.'
            for interval in request['review']['score_audit']['intervals']:
                interval.update(status='pending', regions=[])
            draft = self.build(base, task, request)
            self.assertTrue(draft['ready_to_submit'], draft.get('unresolved'))
            saved = json.loads((base/'draft/decision.json').read_text())
            self.assertFalse(saved['visual_review'])
            accepted = self.cli('--operation','submit','--task',task,'--decision',base/'draft/decision.json')
            self.assertEqual(accepted['phase'], 'accepted', accepted.get('error'))
            for op in ('export','replay'):
                out = self.cli('--operation',op,'--task',task,'--output',base/op)
                self.assertEqual(out['status'], 'success', out.get('error'))
            self.assertEqual((base/'export/score.pdf').read_bytes(), (base/'replay/score.pdf').read_bytes())
