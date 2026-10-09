"""Lazy native evidence through the approved unified CLI boundary."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image
from score_fixtures import CLI, score_frame, video_from_image


class LazyEvidenceTests(unittest.TestCase):
    def cli(self, *args):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)
        self.assertTrue(result.stdout, result.stderr)
        return json.loads(result.stdout)

    def prepare(self, base):
        video = video_from_image(score_frame(), base)
        task = base / 'task'
        state = self.cli(video, '--output', task, '--evidence-mode', 'lazy')
        self.assertEqual(state['status'], 'waiting', state)
        return task, state, json.loads((task / 'observation.json').read_text())

    def test_lazy_prepare_keeps_native_sources_and_navigation_without_bulk_details(self):
        with tempfile.TemporaryDirectory() as directory:
            task, state, observation = self.prepare(Path(directory))
            self.assertEqual(observation['evidence_mode'], 'lazy')
            self.assertEqual({i['kind'] for i in observation['images']}, {'native', 'comparison'})
            self.assertEqual(len(list(task.glob('*.png'))), len(observation['frames']) + 1)
            self.assertTrue(observation['candidates'])
            self.assertEqual(state['metrics']['detail_images'], 0)
            self.assertEqual(state['metrics']['comparison_images'], 1)
            resumed = self.cli('--operation', 'resume', '--task', task)
            self.assertEqual(resumed['observation_sha256'], state['observation_sha256'])

    def request(self, state, observation, boxes=None):
        frame = observation['frames'][0]
        return dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                    observation_version=state['observation_version'], source_sha256=observation['source']['sha256'],
                    request_id='native-rows', reason='Inspect complete staff and margins.',
                    regions=[dict(frame_id=frame['id'], frame_sha256=frame['sha256'], pts=frame['pts'],
                                  time_base=frame['time_base'], bbox=box) for box in
                             (boxes or [[80, 160, 1200, 350], [80, 390, 1200, 560], [80, 610, 1200, 780]])])

    def test_requested_native_rows_export_replay_and_cache_without_decoding(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, state, observation = self.prepare(base)
            old_packet = (task / 'observation.json').read_bytes()
            request = self.request(state, observation)
            path = base / 'request.json'
            path.write_text(json.dumps(request))
            materialized = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            self.assertEqual(materialized['phase'], 'review', materialized)
            self.assertEqual(materialized['observation_version'], 2)
            self.assertEqual((task / 'observation-v1.json').read_bytes(), old_packet)
            packet = (task / 'observation.json').read_bytes()
            current = json.loads(packet)
            details = [i for i in current['images'] if i['kind'] == 'native_detail']
            self.assertEqual(len(details), 3)
            for detail, region in zip(details, request['regions']):
                with Image.open(task / current['frames'][0]['path']) as frame, Image.open(task / detail['path']) as crop:
                    self.assertEqual(crop.size, (region['bbox'][2]-region['bbox'][0], region['bbox'][3]-region['bbox'][1]))
                    self.assertEqual(crop.tobytes(), frame.crop(region['bbox']).tobytes())
                self.assertEqual(detail['source_sha256'], request['source_sha256'])
                self.assertEqual(detail['pts'], region['pts'])
                self.assertEqual(detail['mapping']['scale'], [1, 1])
            repeat = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            self.assertEqual(repeat['materialized_images'], materialized['materialized_images'])
            self.assertEqual((task / 'observation.json').read_bytes(), packet)
            self.assertEqual(repeat['performance']['operations'][-1]['metrics']['generated_images'], 0)
            rows = [dict(frame_id=current['frames'][0]['id'], coordinate_space='native_pixels',
                         roi=[70, 40, 1210, 910], bbox=i['bbox'], evidence_images=[i['id']],
                         complete=True, cursor='clear', occlusion='clear', boundary_verified=True,
                         evidence='Complete native staff and margins.') for i in details]
            decision = dict(schema_version=2, task_id=state['task_id'],
                            observation_sha256=materialized['observation_sha256'], decision_id='review',
                            model=dict(id='controlled-fixture', version='unknown'),
                            prompt=dict(version='lazy-test', text='Review sources and requested details.'),
                            presented_images=[i['id'] for i in current['images']], visual_review=True,
                            complete=True, evidence='Three complete fixed rows.', rows=rows, unresolved=[])
            path.write_text(json.dumps(decision))
            legacy = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(legacy['status'], 'waiting', legacy)
            from test_agent_audit import AuditTests
            audited_state, audited_packet = AuditTests.native_sources(self, base, task, materialized, current)
            request = AuditTests.reviewed_request(self, audited_state, audited_packet)
            segment = request['proposal']['segments'][0]
            for row, detail in zip(segment['rows'], details):
                row['bbox'] = detail['bbox']
            for index, sighting in enumerate(segment['observations']):
                sighting['bbox'] = details[index % 3]['bbox']
            built = AuditTests.build(self, base, task, request, 'audited-build')
            self.assertTrue(built.get('ready_to_submit'), built)
            accepted = self.cli('--operation', 'submit', '--task', task, '--decision', base / 'audited-build/decision.json')
            self.assertEqual(accepted['phase'], 'accepted', accepted)
            exported = self.cli('--operation', 'export', '--task', task, '--output', base / 'out')
            self.assertEqual(exported['status'], 'success', exported)
            replayed = self.cli('--operation', 'replay', '--task', task, '--output', base / 'replay')
            self.assertEqual(replayed['status'], 'success', replayed)
            self.assertEqual((base / 'out/score.pdf').read_bytes(), (base / 'replay/score.pdf').read_bytes())

    def test_bound_requests_and_complete_native_coverage_reject_invalid_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, state, observation = self.prepare(base)
            request = self.request(state, observation, [[80, 160, 600, 350]])
            path = base / 'request.json'
            before = (task / 'observation.json').read_bytes()
            for mutate in [lambda r: r.update(task_id='other'),
                           lambda r: r.update(observation_version=True),
                           lambda r: r.update(source_sha256='0'*64),
                           lambda r: r.update(observation_sha256='0'*64),
                           lambda r: r['regions'][0].update(frame_sha256='0'*64),
                           lambda r: r['regions'][0].update(pts=1),
                           lambda r: r['regions'][0].update(time_base='1/999'),
                           lambda r: r['regions'][0].update(bbox=[80, 160, 2000, 350]),
                           lambda r: r['regions'][0].update(bbox=[80, 160, 600, True])]:
                bad = copy.deepcopy(request)
                mutate(bad)
                path.write_text(json.dumps(bad))
                rejected = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
                self.assertEqual(rejected['error']['code'], 'invalid_request', rejected)
                self.assertEqual((task / 'observation.json').read_bytes(), before)
                self.assertFalse(list(task.glob('roi-*.png')))
            path.write_text(json.dumps(request))
            updated = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            current = json.loads((task / 'observation.json').read_text())
            detail = next(i for i in current['images'] if i['kind'] == 'native_detail')
            decision = dict(schema_version=2, task_id=state['task_id'], observation_sha256=updated['observation_sha256'],
                            decision_id='narrow', model=dict(id='fixture', version='unknown'),
                            prompt=dict(version='test', text='Check boundaries.'), presented_images=[i['id'] for i in current['images']],
                            visual_review=True, complete=True, evidence='Check entire first row.', unresolved=[],
                            rows=[dict(frame_id=detail['frame_id'], coordinate_space='native_pixels', roi=[70, 40, 1210, 910],
                                       bbox=[80, 160, 1200, 350], evidence_images=[detail['id']], complete=True,
                                       cursor='clear', occlusion='clear', boundary_verified=True, evidence='Full staff.')])
            path.write_text(json.dumps(decision))
            rejected = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(rejected['error']['code'], 'review_required', rejected)
            from test_agent_audit import AuditTests
            audit_state, audit_packet = AuditTests.native_sources(self, base, task, updated, current)
            audit_request = AuditTests.reviewed_request(self, audit_state, audit_packet)
            audit_request['proposal']['segments'][0]['rows'][0]['evidence_images'] = [detail['id']]
            insufficient = AuditTests.build(self, base, task, audit_request, 'insufficient-native')
            self.assertFalse(insufficient['ready_to_submit'], insufficient)
            self.assertIn('missing_evidence', [i['reason'] for i in insufficient['unresolved']])
            decision['observation_sha256'] = state['observation_sha256']
            path.write_text(json.dumps(decision))
            rejected = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(rejected['error']['code'], 'invalid_decision', rejected)
            (task / detail['path']).write_bytes(b'tampered')
            path.write_text(json.dumps(request))
            rejected = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            self.assertEqual(rejected['error']['code'], 'source_mismatch', rejected)
            exported = self.cli('--operation', 'export', '--task', task, '--output', base / 'out')
            self.assertEqual(exported['error']['code'], 'source_mismatch', exported)
            self.assertFalse((base / 'out/score.pdf').exists())

    def test_evidence_update_keeps_accepted_prefix_and_requires_explicit_rebinding(self):
        from test_agent_continuity import ContinuityTests
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, full = ContinuityTests.prepare(self, base)
            packet = json.loads((task / 'observation.json').read_text())
            prefix = copy.deepcopy(full)
            prefix.update(decision_id='prefix', observations=prefix['observations'][:6], transitions=prefix['transitions'][:1])
            prefix['coverage']['last_frame'] = 'frame-001'
            prefix['presented_images'] = [i['id'] for i in packet['images'] if i.get('frame_id') != 'frame-002'
                                         and not any(p['frame_id'] == 'frame-002' for p in i.get('panels', []))
                                         or i['kind'] == 'comparison']
            batch = dict(schema_version=5, decision_id='prefix-batch', reviewed_frames=['frame-000', 'frame-001'],
                         revision_of=None, decision=prefix)
            path = base / 'decision.json'
            path.write_text(json.dumps(batch))
            accepted = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(accepted['phase'], 'batch_accepted', accepted)
            history = copy.deepcopy(accepted['decision_history'])
            old_record = (task / history[0]['path']).read_bytes()
            request = self.request(accepted, packet, [[10, 10, 500, 150]])
            path.write_text(json.dumps(request))
            updated = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            self.assertEqual(updated['reviewed_frames'], accepted['reviewed_frames'], updated)
            self.assertEqual(updated['decision_history'], history)
            self.assertEqual((task / history[0]['path']).read_bytes(), old_record)
            path.write_text(json.dumps(batch))
            rejected = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(rejected['error']['code'], 'invalid_decision', rejected)
            revised = copy.deepcopy(batch)
            revised.update(decision_id='prefix-evidence-update', revision_of='prefix-batch')
            revised['decision']['observation_sha256'] = updated['observation_sha256']
            path.write_text(json.dumps(revised))
            accepted_update = self.cli('--operation', 'submit', '--task', task, '--decision', path)
            self.assertEqual(accepted_update['phase'], 'batch_accepted', accepted_update)
            self.assertEqual(len(accepted_update['decision_history']), 2)
            saved = json.loads((task / accepted_update['decision_history'][-1]['path']).read_text())
            self.assertEqual(saved['decision']['rows'], prefix['rows'])
            self.assertEqual(saved['decision']['presented_images'], prefix['presented_images'])
            exported = self.cli('--operation', 'export', '--task', task, '--output', base / 'out')
            self.assertEqual(exported['status'], 'waiting', exported)

    def test_lazy_supplement_preserves_details_and_budget_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, state, packet = self.prepare(base)
            path = base / 'request.json'
            evidence_request = self.request(state, packet, [[80, 160, 1200, 350]])
            path.write_text(json.dumps(evidence_request))
            state = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            detail_paths = list(task.glob('roi-*.png'))
            original = {p.name: p.read_bytes() for p in detail_paths}
            request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                           observation_version=state['observation_version'], request_id='clean-view',
                           issue=dict(reason='inspect nearby source', start=0, end=1), timestamps=[0.25])
            path.write_text(json.dumps(request))
            updated = self.cli('--operation', 'supplement', '--task', task, '--decision', path)
            self.assertEqual(updated['observation_version'], 3, updated)
            packet = json.loads((task / 'observation.json').read_text())
            self.assertEqual(packet['evidence_mode'], 'lazy')
            self.assertEqual(len(packet['evidence_updates']), 1)
            self.assertEqual({i['kind'] for i in packet['images']}, {'native', 'comparison', 'native_detail'})
            self.assertEqual(packet['metrics']['detail_images'], 1)
            self.assertEqual(updated['sampling_usage']['requests'], 1)
            for name, data in original.items():
                self.assertEqual((task / name).read_bytes(), data)

            request.update(observation_sha256=updated['observation_sha256'], observation_version=3, request_id='same-pts', timestamps=[0.9])
            path.write_text(json.dumps(request))
            failed = self.cli('--operation', 'supplement', '--task', task, '--decision', path)
            self.assertEqual(failed['error']['code'], 'invalid_request', failed)
            resumed = self.cli('--operation', 'resume', '--task', task)
            self.assertEqual(resumed['sampling_usage']['requests'], 2)
            for name, data in original.items():
                self.assertEqual((task / name).read_bytes(), data)

    def test_update_paths_cannot_follow_symlinks_and_resume_completes_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, state, packet = self.prepare(base)
            path = base / 'request.json'
            request = self.request(state, packet, [[80, 160, 1200, 350]])
            path.write_text(json.dumps(request))
            external = base / 'external.txt'
            external.write_text('preserve this file')
            for name in ('observation-v1.json', 'evidence-request-2.json', 'observation.next.json.tmp'):
                link = task / name
                link.symlink_to(external)
                result = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
                self.assertEqual(result['error']['code'], 'source_mismatch', result)
                self.assertEqual(external.read_text(), 'preserve this file')
                link.unlink()
            updated = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            self.assertEqual(updated['observation_version'], 2, updated)
            original = (task / 'observation.json').read_bytes()
            journal = {}
            for stem, key in [('observation', 'observation_sha256'), ('sampling', 'sampling_sha256'), ('task', 'state_sha256')]:
                data = (task / f'{stem}.json').read_bytes()
                (task / f'{stem}.next.json').write_bytes(data)
                journal[key] = hashlib.sha256(data).hexdigest()
            (task / 'publication.json').write_text(json.dumps(journal))
            (task / 'observation.json').write_bytes((task / 'observation-v1.json').read_bytes())
            resumed = self.cli('--operation', 'resume', '--task', task)
            self.assertEqual(resumed['observation_version'], 2, resumed)
            self.assertEqual((task / 'observation.json').read_bytes(), original)
            self.assertFalse((task / 'publication.json').exists())

    def test_partial_generation_failure_keeps_source_evidence_and_actual_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            seed, state, packet = self.prepare(base)
            path = base / 'request.json'
            path.write_text(json.dumps(self.request(state, packet, [[80, 390, 1200, 560]])))
            seeded = self.cli('--operation', 'materialize', '--task', seed, '--decision', path)
            seed_packet = json.loads((seed / 'observation.json').read_text())
            image_id = seeded['materialized_images'][0]
            filename = next(i['path'] for i in seed_packet['images'] if i['id'] == image_id)
            task = base / 'other-task'
            state = self.cli(base / 'input.mp4', '--output', task, '--evidence-mode', 'lazy')
            packet = json.loads((task / 'observation.json').read_text())
            before = (task / 'observation.json').read_bytes()
            outside = base / 'outside.png'
            outside.write_bytes(b'preserve')
            (task / filename).symlink_to(outside)
            request = self.request(state, packet, [[80, 160, 1200, 350], [80, 390, 1200, 560]])
            path.write_text(json.dumps(request))
            failed = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            self.assertEqual(failed['error']['code'], 'source_mismatch', failed)
            self.assertEqual((task / 'observation.json').read_bytes(), before)
            self.assertEqual(outside.read_bytes(), b'preserve')
            report = self.cli('--operation', 'report', '--task', task)['performance']
            self.assertEqual(report['materialization']['generated_images'], 1)
            self.assertEqual(report['materialization']['generated_in_failed_operations'], 1)
            self.assertEqual(report['generated_images'], 4)
            generated = report['operations'][-1]['metrics']['generated_evidence']
            self.assertEqual(len(generated), 1)
            self.assertEqual(generated[0]['bbox'], [80, 160, 1200, 350])
            self.assertEqual(generated[0]['source_sha256'], packet['source']['sha256'])
            self.assertTrue((task / generated[0]['path']).is_file())
            (task / filename).unlink()
            retried = self.cli('--operation', 'materialize', '--task', task, '--decision', path)
            self.assertEqual(retried['observation_version'], 2, retried)
            report = retried['performance']
            self.assertEqual(report['materialization']['generated_images'], 2)
            self.assertEqual(report['generated_images'], 6)
            self.assertEqual(retried['metrics']['cache_hits'], 1)


if __name__ == '__main__':
    unittest.main()
