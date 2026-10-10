"""Lifecycle reports observed at the unified CLI boundary."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from score_fixtures import CLI, score_frame, video_from_image


class PerformanceTests(unittest.TestCase):
    def cli(self, *args):
        process = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)
        self.assertTrue(process.stdout, process.stderr)
        return json.loads(process.stdout)

    def controlled_cli(self, *args, clock=None):
        import contextlib
        import io
        from unittest.mock import patch
        from test_link_input import cli
        if not hasattr(self, 'clock_anchor'):
            self.clock_anchor = time.time(), time.monotonic()
        stable = clock is None
        if stable:
            clock = lambda: self.clock_anchor[0] + (time.monotonic() - self.clock_anchor[1])
        capture = io.StringIO()
        with patch.object(sys, 'argv', [str(CLI), *map(str,args)]), contextlib.redirect_stdout(capture), patch('agent_performance.time.time', side_effect=clock):
            cli.main()
        result = json.loads(capture.getvalue())
        if stable:
            self.assertTrue(result['performance']['wall_clock_valid'],result)
            self.assertIsNotNone(result['performance']['wall_elapsed_seconds'],result)
            self.assertEqual(result['performance']['clock_anomalies'],[])
        return result

    def test_prepare_resume_and_report_include_wait_without_recounting(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            prepared = self.controlled_cli(video, '--output', task)
            report = prepared['performance']
            self.assertEqual(report['task_status'], 'waiting')
            self.assertIsNone(report['first_deliverable_at'])
            self.assertIsNone(report['model_tokens'])
            self.assertEqual(report['operations'][0]['operation'], 'prepare')
            self.assertGreater(report['operations'][0]['elapsed_seconds'], 0)
            time.sleep(0.05)
            resumed = self.controlled_cli('--operation', 'resume', '--task', task)['performance']
            self.assertEqual(report['submitted_at'], resumed['submitted_at'])
            self.assertGreater(resumed['wall_elapsed_seconds'], report['wall_elapsed_seconds'] + 0.05)
            self.assertEqual(len(resumed['operations']), 2)
            rebuilt = self.controlled_cli('--operation', 'report', '--task', task)['performance']
            again = self.controlled_cli('--operation', 'report', '--task', task)['performance']
            self.assertEqual(rebuilt['operations'], again['operations'])
            self.assertEqual(rebuilt['stages'], again['stages'])
            self.assertEqual(rebuilt['source']['sha256'], json.loads((task / 'observation.json').read_text())['source']['sha256'])
            self.assertEqual(rebuilt['metrics']['analyzed_frames'], 3)

    def test_controlled_overlapping_stages_are_idempotent_and_cannot_mark_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            video = video_from_image(score_frame(), base)
            report = self.controlled_cli(video, '--output', task)['performance']
            operation = report['operations'][0]
            event = dict(event_id='host-review-1', name='agent_review', started_at=operation['started_at'],
                         ended_at=operation['ended_at'], elapsed_seconds=operation['elapsed_seconds'], status='complete')
            packet = dict(schema_version=1, lifecycle_id=report['lifecycle_id'], source=dict(kind='controlled_fixture', id='test'),
                          events=[event, dict(event, event_id='host-review-2')])
            path = base / 'events.json'
            path.write_text(json.dumps(packet))
            first = self.controlled_cli('--operation', 'resume', '--task', task, '--performance-events', path)['performance']
            second = self.controlled_cli('--operation', 'resume', '--task', task, '--performance-events', path)['performance']
            external = [e for e in second['stages'] if e['source'] == 'controlled_fixture']
            self.assertEqual(len(external), 2)
            self.assertEqual(first['stages'], second['stages'])
            self.assertEqual(second['task_status'], 'waiting')
            self.assertIsNone(second['first_deliverable_at'])
            self.assertGreater(sum(e['elapsed_seconds'] for e in second['stages']), second['wall_elapsed_seconds'])
            packet['events'][0]['elapsed_seconds'] += 1
            path.write_text(json.dumps(packet))
            failed = self.controlled_cli('--operation', 'resume', '--task', task, '--performance-events', path)
            self.assertEqual(failed['error']['code'], 'invalid_performance')
            rebuilt = self.controlled_cli('--operation', 'report', '--task', task)['performance']
            self.assertEqual(first['stages'], rebuilt['stages'])

    def test_forward_clock_jump_nulls_wall_elapsed_and_survives_resume_and_report(self):
        import itertools
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base/'task'
            video = video_from_image(score_frame(),base)
            now = time.time()
            ticks = itertools.chain([now,now],itertools.repeat(now+3600))
            clock = lambda: next(ticks)
            prepared = self.controlled_cli(video,'--output',task,clock=clock)['performance']
            self.assertFalse(prepared['wall_clock_valid'])
            self.assertIsNone(prepared['wall_elapsed_seconds'])
            self.assertEqual(len(prepared['clock_anomalies']),1)
            anomaly = prepared['clock_anomalies'][0]
            self.assertEqual(anomaly['kind'],'wall_clock_discontinuity')
            self.assertEqual(anomaly['operation_id'],prepared['operations'][0]['event_id'])
            self.assertEqual(anomaly['wall_seconds'],3600)
            self.assertGreater(anomaly['monotonic_seconds'],0)
            self.assertGreater(anomaly['wall_seconds']-anomaly['monotonic_seconds'],1)
            resumed = self.controlled_cli('--operation','resume','--task',task,clock=clock)['performance']
            self.assertEqual(len(resumed['operations']),2)
            ledger = (task/'performance.json').read_bytes()
            rebuilt = self.controlled_cli('--operation','report','--task',task,clock=clock)['performance']
            for report in (resumed,rebuilt):
                self.assertFalse(report['wall_clock_valid'])
                self.assertIsNone(report['wall_elapsed_seconds'])
                self.assertEqual(report['clock_anomalies'],prepared['clock_anomalies'])
                self.assertEqual(report['operations'][0],prepared['operations'][0])
            self.assertEqual(rebuilt['operations'],resumed['operations'])
            self.assertEqual((task/'performance.json').read_bytes(),ledger)

    def decision(self, task, base):
        state = json.loads((task / 'task.json').read_text())
        packet = json.loads((task / 'observation.json').read_text())
        value = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                     decision_id='test-review', model=dict(id='test', version='unknown'),
                     prompt=dict(version='test', text='Controlled fixture decision.'),
                     presented_images=[i['id'] for i in packet['images']], visual_review=True, complete=True,
                     evidence='Fixed complete fixture rows.', unresolved=[],
                     selected_candidates=[c['id'] for c in packet['candidates'] if c['frame_id'] == packet['frames'][0]['id']])
        path = base / 'decision.json'
        path.write_text(json.dumps(value))
        return path

    def test_failed_attempts_repeated_submission_and_delivery_survive_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            self.controlled_cli(video_from_image(score_frame(), base), '--output', task)
            first = self.controlled_cli('--operation', 'export', '--task', task, '--output', base / 'missing')
            self.assertEqual(first['performance']['operations'][-1]['status'], 'failed')
            decision = self.decision(task, base)
            self.controlled_cli('--operation', 'submit', '--task', task, '--decision', decision)
            second = self.controlled_cli('--operation', 'submit', '--task', task, '--decision', decision)
            self.assertEqual(len(json.loads((task / 'task.json').read_text())['decision_history']), 1)
            self.assertEqual(second['performance']['script_operation_count'], 4)
            self.assertIsNone(second['performance']['first_deliverable_at'])
            output = base / 'out'
            result = self.controlled_cli('--operation', 'export', '--task', task, '--output', output)
            self.assertEqual(result['performance']['task_status'], 'waiting')
            confirmation = self.controlled_cli('--operation', 'confirm-delivery', '--task', task, '--output', output,
                                    '--decision', self.delivery_review(task, output, base))
            result['performance'] = confirmation['performance']
            self.assertTrue((output / 'manifest.json').is_file())
            self.assertTrue((output / 'score.pdf').is_file())
            end = result['performance']['first_deliverable_at']
            self.assertEqual(result['performance']['metrics']['analyzed_frames'], 3)
            resumed = self.controlled_cli('--operation', 'resume', '--task', task)
            self.assertEqual(resumed['performance']['task_status'], 'success')
            self.assertEqual(resumed['performance']['first_deliverable_at'], end)
            self.assertEqual(resumed['performance']['wall_elapsed_seconds'], result['performance']['wall_elapsed_seconds'])
            duplicate = self.controlled_cli('--operation', 'submit', '--task', task, '--decision', decision)['performance']
            self.assertEqual(duplicate['task_status'], 'success')
            replayed = self.controlled_cli('--operation', 'replay', '--task', task, '--output', base / 'replay')
            self.assertEqual(replayed['performance']['first_deliverable_at'], end)
            self.assertEqual((output / 'score.pdf').read_bytes(), (base / 'replay/score.pdf').read_bytes())

    def test_process_interruption_is_recovered_without_inventing_monotonic_duration(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            self.cli(video_from_image(score_frame(), base), '--output', task)
            self.cli('--operation', 'submit', '--task', task, '--decision', self.decision(task, base))
            binaries = base / 'bin'
            binaries.mkdir()
            wrapper = binaries / 'ffmpeg'
            wrapper.write_text('#!/bin/sh\nsleep 2\nexit 1\n')
            wrapper.chmod(0o755)
            environment = dict(os.environ, PATH=str(binaries)+os.pathsep+os.environ['PATH'])
            process = subprocess.Popen([sys.executable, str(CLI), '--operation','export','--task',str(task),'--output',str(base/'interrupted')],
                                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic()+10
                while time.monotonic() < deadline:
                    ledger = json.loads((task / 'performance.json').read_text())
                    if any(e['name'] == 'source_redecode' and e['status'] == 'running' for e in ledger['stages']):
                        break
                    time.sleep(0.01)
                else:
                    self.fail('export did not persist its stage start')
                process.kill()
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            resumed = self.cli('--operation', 'resume', '--task', task)['performance']
            interrupted = [e for e in resumed['operations'] if e['status'] == 'interrupted']
            self.assertEqual(len(interrupted), 1)
            self.assertIsNone(interrupted[0]['elapsed_seconds'])
            self.assertIsNone(resumed['first_deliverable_at'])
            self.cli('--operation','export','--task',task,'--output',base/'retry')
            delivered = self.cli('--operation', 'confirm-delivery', '--task', task, '--output', base/'retry',
                                 '--decision', self.delivery_review(task, base/'retry', base))['performance']
            self.assertEqual(delivered['task_status'], 'success')

    def test_acquisition_failure_retry_preserves_submission_and_failed_cost(self):
        from test_agent_link_input import AgentLinkInputTests
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            task = base / 'task'
            failed, _ = AgentLinkInputTests().prepare(task, video, failure=RuntimeError('controlled backend failure'))
            self.assertEqual({p.name for p in task.iterdir()}, {'manifest.json'})
            initial = failed['performance']
            self.assertEqual(initial['operations'][0]['status'], 'failed')
            self.assertEqual(initial['stages'][0]['name'], 'anonymous_acquisition')
            retried = self.cli(video, '--output', task)['performance']
            self.assertEqual(retried['submitted_at'], initial['submitted_at'])
            self.assertEqual(len(retried['operations']), 2)
            self.assertEqual(retried['operations'][0], initial['operations'][0])
            self.assertTrue((task / 'performance.json').exists())

    def test_old_task_report_has_unknown_start_and_wall_clock_regression_is_reported(self):
        import contextlib
        import io
        from unittest.mock import patch
        from test_link_input import cli
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            report = self.cli(video_from_image(score_frame(), base), '--output', task)['performance']
            capture = io.StringIO()
            with patch.object(sys, 'argv', [str(CLI),'--operation','resume','--task',str(task)]), contextlib.redirect_stdout(capture), patch('agent_performance.time.time', return_value=report['submitted_at']-10):
                cli.main()
            regressed = json.loads(capture.getvalue())['performance']
            self.assertFalse(regressed['wall_clock_valid'])
            self.assertIsNone(regressed['wall_elapsed_seconds'])
            self.assertTrue(regressed['clock_anomalies'])
            import itertools
            capture = io.StringIO()
            now = time.time()
            with patch.object(sys, 'argv', [str(CLI),'--operation','resume','--task',str(task)]), contextlib.redirect_stdout(capture), patch('agent_performance.time.time', side_effect=itertools.chain([now,now], itertools.repeat(now+3600))):
                cli.main()
            forward = json.loads(capture.getvalue())['performance']
            self.assertTrue(any(a['kind'] == 'wall_clock_discontinuity' for a in forward['clock_anomalies']))
            (task / 'performance.json').unlink()
            old = self.cli('--operation','report','--task',task)['performance']
            self.assertIsNone(old['submitted_at'])
            self.assertIsNone(old['wall_elapsed_seconds'])
            self.assertFalse((task / 'performance.json').exists())
            pending = task / 'publication.json'
            import hashlib
            journal = json.dumps({key: hashlib.sha256((task / f'{stem}.json').read_bytes()).hexdigest() for stem,key in [('observation','observation_sha256'),('task','state_sha256'),('sampling','sampling_sha256')]})
            pending.write_text(journal)
            rejected = self.cli('--operation','report','--task',task)
            self.assertEqual(rejected['error']['code'], 'invalid_task')
            self.assertEqual(pending.read_text(), journal)

    def test_report_rebuilds_failed_prepare_before_observation_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            failed = self.cli(base / 'missing.mp4', '--output', task)
            self.assertEqual(failed['status'], 'failed')
            self.assertGreater(failed['performance']['operations'][0]['elapsed_seconds'], 0)
            original = (task / 'performance.json').read_bytes()
            rebuilt = self.cli('--operation', 'report', '--task', task)
            self.assertEqual(rebuilt['status'], 'failed')
            self.assertEqual(rebuilt['performance']['operations'], failed['performance']['operations'])
            self.assertEqual((task / 'performance.json').read_bytes(), original)

    def test_malformed_ledger_is_rejected_without_mutating_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            self.cli(video_from_image(score_frame(), base), '--output', task)
            path = task / 'performance.json'
            original = json.loads(path.read_text())
            for mutation in ({'schema_version': True}, {'submitted_at': 10**1000}, {'task_status': 'invented'}, {'unrecognized': 'controlled-fixture'}):
                path.write_text(json.dumps(original | mutation))
                before = path.read_bytes()
                rejected = self.cli('--operation', 'report', '--task', task)
                self.assertEqual(rejected['status'], 'failed')
                self.assertEqual(path.read_bytes(), before)

    def test_incomplete_internal_events_fail_before_resuming_or_mutating_ledger(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            self.cli(video_from_image(score_frame(), base), '--output', task)
            path = task / 'performance.json'
            original = json.loads(path.read_text())
            for kind, field in [('stages','name'), ('stages','source'), ('stages','operation_id'),
                                ('stages','offset_seconds'), ('operations','operation'), ('operations','ended_at')]:
                for operation in ('resume','report'):
                    with self.subTest(kind=kind, field=field, operation=operation):
                        damaged = copy.deepcopy(original)
                        damaged[kind][0].pop(field)
                        path.write_text(json.dumps(damaged))
                        before = path.read_bytes()
                        rejected = self.cli('--operation', operation, '--task', task)
                        self.assertEqual(rejected['status'], 'failed')
                        self.assertEqual(path.read_bytes(), before)

    def delivery_review(self, task, output, base, review_id='delivery-1'):
        import hashlib
        state = json.loads((task / 'task.json').read_text())
        ledger = json.loads((task / 'performance.json').read_text())
        manifest = json.loads((output / 'manifest.json').read_text())
        receipt = dict(schema_version=1, review_id=review_id, task_id=state['task_id'], lifecycle_id=ledger['lifecycle_id'],
                       observation_sha256=state['observation_sha256'], decision_sha256=state['decision_history'][-1]['sha256'],
                       pdf_sha256=hashlib.sha256((output / 'score.pdf').read_bytes()).hexdigest(),
                       manifest_sha256=hashlib.sha256((output / 'manifest.json').read_bytes()).hexdigest(),
                       reviewer=dict(kind='controlled_fixture', id='fixture'),
                       source_manifest_verified=True, complete_score_verified=True,
                       pages=[dict(page=index, evidence='Viewed the rendered fixture page; all full rows and margins visible.')
                              for index in range(1, manifest['page_count']+1)])
        path = base / f'{review_id}.json'
        path.write_text(json.dumps(receipt))
        return path

    def test_export_requires_actual_delivery_review_and_revision_keeps_timer_running(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            self.controlled_cli(video_from_image(score_frame(), base), '--output', task)
            decision = self.decision(task, base)
            self.controlled_cli('--operation', 'submit', '--task', task, '--decision', decision)
            output = base / 'output'
            exported = self.controlled_cli('--operation', 'export', '--task', task, '--output', output)['performance']
            self.assertEqual(exported['task_status'], 'waiting')
            self.assertIsNone(exported['first_deliverable_at'])
            self.assertIsNone(exported['delivered_at'])
            self.assertIsNotNone(exported['exported_at'])
            time.sleep(0.05)
            waiting = self.controlled_cli('--operation', 'report', '--task', task)['performance']
            self.assertGreater(waiting['wall_elapsed_seconds'], exported['wall_elapsed_seconds']+0.05)
            receipt = self.delivery_review(task, output, base)
            confirmed = self.controlled_cli('--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', receipt)
            self.assertEqual(confirmed['status'], 'success')
            delivered = confirmed['performance']
            self.assertTrue(delivered['delivery_confirmed'])
            self.assertGreater(delivered['delivered_at'], exported['exported_at'])
            again = self.controlled_cli('--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', receipt)['performance']
            self.assertEqual(again['delivered_at'], delivered['delivered_at'])
            self.assertEqual(len(again['delivery_history']), 1)
            value = json.loads(decision.read_text())
            value.update(decision_id='revised', evidence='Rechecked full score and retained the same complete rows.')
            revision = dict(schema_version=5, decision_id='revision-1', reviewed_frames=[f['id'] for f in json.loads((task/'observation.json').read_text())['frames']],
                            revision_of='test-review', decision=value)
            decision.write_text(json.dumps(revision))
            revised = self.controlled_cli('--operation', 'submit', '--task', task, '--decision', decision)['performance']
            self.assertEqual(revised['task_status'], 'waiting')
            self.assertIsNone(revised['delivered_at'])
            self.assertEqual(revised['first_deliverable_at'], delivered['first_deliverable_at'])
            self.assertGreater(revised['wall_elapsed_seconds'], delivered['wall_elapsed_seconds'])
            self.assertEqual(len(revised['delivery_history']), 1)
            stale = self.controlled_cli('--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', receipt)
            self.assertEqual(stale['error']['code'], 'invalid_delivery')
            replay = base / 'replay'
            replayed = self.controlled_cli('--operation', 'replay', '--task', task, '--output', replay)['performance']
            self.assertFalse(replayed['delivery_confirmed'])
            receipt = self.delivery_review(task, replay, base, 'replay-review')
            rejected = self.controlled_cli('--operation', 'confirm-delivery', '--task', task, '--output', replay, '--decision', receipt)
            self.assertEqual(rejected['error']['code'], 'invalid_delivery')
            output2 = base / 'output2'
            self.controlled_cli('--operation', 'export', '--task', task, '--output', output2)
            review2 = self.delivery_review(task, output2, base, 'delivery-2')
            final = self.controlled_cli('--operation', 'confirm-delivery', '--task', task, '--output', output2, '--decision', review2)['performance']
            self.assertTrue(final['delivery_confirmed'])
            self.assertEqual(len(final['delivery_history']), 2)
            self.assertGreater(final['delivered_at'], delivered['delivered_at'])

    def test_delivery_review_rejects_missing_checks_stale_hashes_and_tampered_exports(self):
        import copy
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / 'task'
            self.cli(video_from_image(score_frame(), base), '--output', task)
            self.cli('--operation', 'submit', '--task', task, '--decision', self.decision(task, base))
            output = base / 'output'
            self.cli('--operation', 'export', '--task', task, '--output', output)
            path = self.delivery_review(task, output, base)
            original = json.loads(path.read_text())
            for change in ({'source_manifest_verified': False}, {'complete_score_verified': False}, {'pages': []},
                           {'pages': [dict(page=1, evidence='')]}, {'pdf_sha256': '0'*64}, {'manifest_sha256': '0'*64},
                           {'observation_sha256': '0'*64}, {'decision_sha256': '0'*64}, {'lifecycle_id': 'other'}, {'unexpected': True}):
                path.write_text(json.dumps(original | change))
                rejected = self.cli('--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', path)
                self.assertEqual(rejected['error']['code'], 'invalid_delivery')
                self.assertFalse(rejected['performance']['delivery_confirmed'])
                self.assertEqual(rejected['performance']['delivery_history'], [])
            with (output/'score.pdf').open('ab') as stream:
                stream.write(b'controlled-tamper')
            changed = copy.deepcopy(original)
            changed['pdf_sha256'] = hashlib.sha256((output/'score.pdf').read_bytes()).hexdigest()
            path.write_text(json.dumps(changed))
            rejected = self.cli('--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', path)
            self.assertEqual(rejected['error']['code'], 'invalid_delivery')
            self.assertFalse(rejected['performance']['delivery_confirmed'])
