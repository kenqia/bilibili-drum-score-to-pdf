"""Mode routing and cold candidate planning through the public CLI."""
import json
from pathlib import Path
import tempfile
import unittest
from score_fixtures import score_frame, video_from_image
import test_agent_content as fixtures
import test_agent_recovery as recovery
import hashlib


class WorkflowModesTests(unittest.TestCase):
    cli = fixtures.ContentChecksTests.cli

    def test_cold_fast_review_plan_supplies_current_candidate_request(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = video_from_image(score_frame(), base)
            task = base / 'task'
            prepared = self.cli(source, '--output', task, '--mode', 'fast')
            self.assertEqual(prepared.get('phase'), 'review', prepared.get('error'))
            packet = json.loads((task / 'observation.json').read_text())
            self.assertEqual(packet['evidence_mode'], 'lazy')
            self.assertEqual(packet['workflow_mode'], 'fast')
            self.assertEqual(packet['evidence_recovery_policy'], 'clean_sources_v1')
            self.assertEqual(packet['minimum_evidence_chain_policy'], 'ordered_anchors_v1')
            self.assertEqual(packet['script_acceptance_policy'], 'continuous_clean_v1')
            self.assertFalse((task / 'seed-proposal.json').exists())
            planned = self.cli('--operation', 'review-plan', '--task', task, '--output', base / 'plan')
            candidate_request = base / 'plan' / planned['candidate_request']
            searched = self.cli('--operation', 'candidate-plan', '--task', task,
                                '--decision', candidate_request, '--output', base / 'candidates')
            self.assertEqual(searched.get('phase'), 'candidate_search', searched.get('error'))
            self.assertGreater(searched['row_count'], 0)
            candidate = json.loads((base / 'candidates/candidate-plan.json').read_text())
            self.assertFalse(candidate['identities_confirmed'])
            self.assertFalse(candidate['review_reused'])
            self.assertTrue(all(not c['actual_native_review'] for r in candidate['rows'] for c in r['alternatives']))
            self.cli('--operation', 'materialize', '--task', task,
                     '--decision', planned['materialize_requests'][0]['path'])
            stale = self.cli('--operation', 'candidate-plan', '--task', task,
                             '--decision', candidate_request, '--output', base / 'stale')
            self.assertEqual(stale['status'], 'failed')
            self.assertEqual(stale['error']['code'], 'invalid_request')


class ReusedSourceLifecycleTests(unittest.TestCase):
    minimum_chain = True
    cli = recovery.RecoveryTests.cli
    request = recovery.RecoveryTests.request
    build = recovery.RecoveryTests.build
    prepare_score = recovery.RecoveryTests.prepare_score
    reviewed_request = recovery.RecoveryTests.reviewed_request

    def test_reused_task_survives_original_directory_move_and_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original = base / 'original'
            original.mkdir()
            task, decision = self.prepare_score(original, variant='stationary_bridge_cursor')
            request, _ = self.reviewed_request(task, decision)
            built = self.build(original, task, request)
            self.assertTrue(built['ready_to_submit'])
            self.cli('--operation', 'submit', '--task', task, '--decision', original / 'draft/decision.json')
            reused = base / 'reused'
            seeded = self.cli('--reuse-task', task, '--output', reused, '--mode', 'auto')
            self.assertEqual(seeded.get('phase'), 'review', seeded.get('error'))
            packet = json.loads((reused / 'observation.json').read_text())
            source = Path(packet['source']['path'])
            self.assertEqual(source.parent, reused.resolve())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), packet['source']['sha256'])
            original.rename(base / 'moved-original')
            state = self.cli('--operation', 'resume', '--task', reused)
            self.assertEqual(state.get('phase'), 'review', state.get('error'))
            materialize = dict(schema_version=1, task_id=state['task_id'],
                observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                source_sha256=packet['source']['sha256'], request_id='independent-native',
                reason='Controlled source lifecycle native review.', regions=[dict(frame_id=f['id'],
                    frame_sha256=f['sha256'], pts=f['pts'], time_base=f['time_base'], bbox=[0,0,1280,960])
                    for f in packet['frames']])
            path = base / 'materialize.json'
            path.write_text(json.dumps(materialize))
            updated = self.cli('--operation', 'materialize', '--task', reused, '--decision', path)
            packet = json.loads((reused / 'observation.json').read_text())
            decision.update(task_id=updated['task_id'], observation_sha256=updated['observation_sha256'],
                presented_images=[i['id'] for i in packet['images']])
            for part in decision['segments']:
                for row in part['rows'] + [e['region'] for e in part.get('extras', [])]:
                    row['evidence_images'] = [i['id'] for i in packet['images'] if i.get('frame_id') == row['frame_id'] and i['kind'] == 'native_detail']
            request, _ = self.reviewed_request(reused, decision)
            built = self.build(base, reused, request)
            self.assertTrue(built['ready_to_submit'], built.get('unresolved'))
            accepted = self.cli('--operation', 'submit', '--task', reused, '--decision', base / 'draft/decision.json')
            self.assertEqual(accepted.get('phase'), 'accepted', accepted.get('error'))
            for op in ('export', 'replay'):
                result = self.cli('--operation', op, '--task', reused, '--output', base / op)
                self.assertEqual(result['status'], 'success', result.get('error'))
            self.assertEqual((base / 'export/score.pdf').read_bytes(), (base / 'replay/score.pdf').read_bytes())


class StrongerReviewTests(unittest.TestCase):
    minimum_chain = True
    request = recovery.RecoveryTests.request
    build = recovery.RecoveryTests.build
    prepare_score = recovery.RecoveryTests.prepare_score
    reviewed_request = recovery.RecoveryTests.reviewed_request

    def cli(self, *args):
        if '--evidence-mode' in args and 'lazy' in args:
            args = (*args, '--mode', 'auto')
        return fixtures.ContentChecksTests.cli(self, *args)

    def test_auto_strengthens_same_task_without_decoding_or_relaxing_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base)
            packet_before = json.loads((task / 'observation.json').read_text())
            # Existing details already cover all native frames. The operation
            # still assesses the current bound review and adds no duplicate ROI.
            request, _ = self.reviewed_request(task, decision)
            path = base / 'review.json'
            state = json.loads((task / 'task.json').read_text())
            stronger_request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'], observation_version=state['observation_version'], reason='native_review_pending')
            path.write_text(json.dumps(stronger_request))
            stronger = self.cli('--operation', 'strengthen-review', '--task', task, '--decision', path)
            self.assertEqual(stronger.get('phase'), 'review', stronger.get('error'))
            self.assertFalse(stronger['complete'])
            self.assertEqual(stronger['metrics']['generated_images'], 0)
            self.assertEqual(stronger['metrics']['seek_count'], 0)
            self.assertEqual(stronger['metrics']['thumbnail_checks'], 0)
            packet_after = json.loads((task / 'observation.json').read_text())
            for key in ('frames', 'source', 'sampling', 'evidence_mode', 'evidence_recovery_policy'):
                self.assertEqual(packet_before[key], packet_after[key])
            decision['observation_sha256'] = stronger['observation_sha256']
            request, _ = self.reviewed_request(task, decision)
            built = self.build(base, task, request)
            self.assertTrue(built['ready_to_submit'], built.get('unresolved'))
            self.assertEqual(packet_after['evidence_recovery_policy'], 'clean_sources_v1')
            self.assertEqual(packet_after['evidence_mode'], 'lazy')

    def test_conflict_cannot_route_to_full_or_legacy_success(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base, variant='stationary_bridge_conflict')
            request, _ = self.reviewed_request(task, decision)
            path = base / 'review.json'
            built = self.build(base, task, request)
            self.assertFalse(built['ready_to_submit'])
            state = json.loads((task / 'task.json').read_text())
            path.write_text(json.dumps(dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'], observation_version=state['observation_version'], reason='candidate_shortage')))
            before = (task / 'observation.json').read_bytes()
            stronger = self.cli('--operation', 'strengthen-review', '--task', task, '--decision', path)
            self.assertEqual(stronger['status'], 'waiting')
            self.assertEqual(stronger['error']['code'], 'hard_evidence_conflict')
            self.assertEqual((task / 'observation.json').read_bytes(), before)
            self.assertFalse((task / 'score.pdf').exists())
            mode_switch = self.cli('--operation', 'resume', '--task', task, '--mode', 'full')
            self.assertEqual(mode_switch['status'], 'failed')
            self.assertEqual(mode_switch['error']['code'], 'invalid_input')


    def test_geometry_conflict_and_source_tampering_cannot_strengthen(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base)
            decision['segments'][0]['observations'][3]['staff_y'] += 20
            request, _ = self.reviewed_request(task, decision)
            built = self.build(base, task, request)
            self.assertFalse(built['ready_to_submit'])
            state = json.loads((task / 'task.json').read_text())
            path = base / 'stronger.json'
            path.write_text(json.dumps(dict(schema_version=1, task_id=state['task_id'],
                observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                reason='layout_unconfirmed')))
            stronger = self.cli('--operation', 'strengthen-review', '--task', task, '--decision', path)
            self.assertEqual(stronger.get('error', {}).get('code'), 'hard_evidence_conflict')
            packet = json.loads((task / 'observation.json').read_text())
            Path(packet['source']['path']).write_bytes(b'tampered controlled fixture source')
            refused = self.cli('--operation', 'strengthen-review', '--task', task, '--decision', path)
            self.assertEqual(refused.get('error', {}).get('code'), 'source_mismatch')


class ModeBudgetTests(unittest.TestCase):
    cli = fixtures.ContentChecksTests.cli

    def test_modes_legacy_defaults_and_fast_do_not_automatically_expand(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = video_from_image(score_frame(), base)
            for mode in (None, 'full', 'auto', 'fast'):
                task = base / (mode or 'legacy')
                args = (('--mode', mode) if mode else ())
                prepared = self.cli(source, '--output', task, *args)
                self.assertEqual(prepared['phase'], 'review', prepared.get('error'))
                packet = json.loads((task / 'observation.json').read_text())
                self.assertEqual(packet['evidence_mode'], 'lazy' if mode in ('auto', 'fast') else 'full')
                if mode in ('auto', 'fast'):
                    self.assertFalse(any(i['kind'] in ('detail', 'native_detail') for i in packet['images']))
            invalid = self.cli(source, '--output', base / 'invalid', '--mode', 'full', '--script-acceptance')
            self.assertEqual(invalid.get('error', {}).get('code'), 'invalid_input')
            fast = base / 'fast'
            before = (fast / 'observation.json').read_bytes()
            fast_plan = self.cli('--operation', 'review-plan', '--task', fast, '--output', base / 'fast-plan')
            self.assertFalse(fast_plan['workflow_routing']['automatic_full_review_available'])
            auto_plan = self.cli('--operation', 'review-plan', '--task', base / 'auto', '--output', base / 'auto-plan')
            self.assertTrue(auto_plan['workflow_routing']['automatic_full_review_available'])
            self.assertTrue((base / 'auto-plan' / auto_plan['workflow_routing']['request']).is_file())
            self.assertEqual((fast / 'observation.json').read_bytes(), before)

    def test_strengthening_missing_regions_is_bounded_and_reuses_source_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = video_from_image(score_frame(), base)
            task = base / 'task'
            self.cli(source, '--output', task, '--mode', 'auto')
            before = json.loads((task / 'observation.json').read_text())
            sampling = (task / 'sampling.json').read_bytes()
            state = json.loads((task / 'task.json').read_text())
            path = base / 'stronger.json'
            request = dict(schema_version=1, task_id=state['task_id'],
                observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                reason='native_review_pending')
            path.write_text(json.dumps(request))
            stronger = self.cli('--operation', 'strengthen-review', '--task', task, '--decision', path)
            self.assertEqual(stronger['phase'], 'review', stronger.get('error'))
            self.assertEqual(stronger['metrics']['generated_images'], len(before['frames']))
            after = json.loads((task / 'observation.json').read_text())
            self.assertEqual(before['frames'], after['frames'])
            self.assertEqual(before['source'], after['source'])
            self.assertEqual((task / 'sampling.json').read_bytes(), sampling)
            self.assertFalse(stronger['complete'])
            self.assertEqual(stronger['metrics']['seek_count'], 0)
            request.update(observation_sha256=stronger['observation_sha256'], observation_version=stronger['observation_version'])
            path.write_text(json.dumps(request))
            repeated = self.cli('--operation', 'strengthen-review', '--task', task, '--decision', path)
            self.assertEqual(repeated['error']['code'], 'sampling_budget')
            report = self.cli('--operation', 'report', '--task', task)
            self.assertEqual(report['performance']['materialization']['generated_images'], len(before['frames']))
            self.assertIsNone(report['performance']['model_tokens'])


class DirectSubmitRoutingTests(unittest.TestCase):
    minimum_chain = True
    cli = StrongerReviewTests.cli
    request = recovery.RecoveryTests.request
    build = recovery.RecoveryTests.build
    prepare_score = recovery.RecoveryTests.prepare_score
    reviewed_request = recovery.RecoveryTests.reviewed_request

    def test_direct_visual_submit_hard_conflict_is_preserved_for_routing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, decision = self.prepare_score(base, variant='stationary_bridge_conflict')
            request, packet = self.reviewed_request(task, decision)
            path = base / 'decision.json'
            path.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + '\n')
            state = json.loads((task / 'task.json').read_text())
            continuity = dict(schema_version=1, task_id=state['task_id'],
                observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                source_sha256=packet['source']['sha256'], decision_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                policy='ordered_anchors_v1', evidence_recovery_policy='clean_sources_v1',
                native_clean_regions=request['review']['native_clean_regions'])
            (base / 'continuity.json').write_text(json.dumps(continuity))
            rejected = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(rejected['status'], 'waiting', rejected.get('error'))
            self.assertTrue(any(i.get('status') == 'conflict' for i in rejected['issues']))
            plan = self.cli('--operation', 'review-plan', '--task', task, '--output', base / 'plan')
            self.assertTrue(plan['workflow_routing']['hard_findings'])
            self.assertFalse(plan['workflow_routing']['automatic_full_review_available'])
            stronger_path = base / 'stronger.json'
            state = json.loads((task / 'task.json').read_text())
            stronger_path.write_text(json.dumps(dict(schema_version=1, task_id=state['task_id'],
                observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
                reason='candidate_shortage')))
            stronger = self.cli('--operation', 'strengthen-review', '--task', task, '--decision', stronger_path)
            self.assertEqual(stronger.get('error', {}).get('code'), 'hard_evidence_conflict')
