"""Controlled accounting at the public host CLI and task report boundary."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from score_fixtures import CLI, score_frame, video_from_image

HOST = CLI.with_name('host_usage.py')


class HostUsageTests(unittest.TestCase):
    def run_cli(self, script, *args, env=None):
        result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, env=env)
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def prepare(self, base):
        task = base / 'task'
        _, value = self.run_cli(CLI, video_from_image(score_frame(), base), '--output', task)
        return task, value['performance']

    def packet(self, report):
        return dict(schema_version=1, lifecycle_id=report['lifecycle_id'], task_id=report['task_id'],
                    source=dict(kind='controlled_fixture', id='fixture'),
                    scope=dict(invocation_id='run-1', root_thread_id='root', root_turn_id='turn',
                               started_at=report['submitted_at'], ended_at=time.time(), mode='review', thread_ids=['root']),
                    coverage=dict(lifecycle_complete=report['task_status'] != 'waiting', model_calls_complete=True, tools_complete=True, images_complete=False,
                                  expected_response_ids=['response-1', 'response-retry'], missing_reasons=['images not instrumented']),
                    events=[dict(kind='model_call', event_id='usage-1', thread_id='root', response_id='response-1',
                                 timestamp=report['submitted_at'], status='complete', usage=dict(input_tokens=100, output_tokens=10, total_tokens=110,
                                 cached_input_tokens=64, reasoning_output_tokens=4)),
                            dict(kind='model_call', event_id='usage-2', thread_id='root', response_id='response-retry',
                                 timestamp=report['submitted_at'], status='failed', usage=dict(input_tokens=100, output_tokens=3, total_tokens=103)),
                            dict(kind='host_tool_call', event_id='tool-1', thread_id='root', call_id='call-1',
                                 timestamp=report['submitted_at'], tool_name='view_image', status='failed')])

    def test_import_deduplicates_response_events_and_accounts_failed_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, report = self.prepare(base)
            packet = self.packet(report)
            path = base / 'usage.json'
            path.write_text(json.dumps(packet))
            code, first = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(code, 0, first)
            code, second = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(second['usage'], first['usage'])
            summary = second['usage']
            self.assertEqual(summary['observed_actual_tokens']['total_tokens'], 213)
            self.assertEqual(summary['observed_actual_tokens']['cached_input_tokens'], 64)
            self.assertEqual(summary['model_call_count'], 2)
            self.assertEqual(summary['failed_model_calls'], 1)
            self.assertEqual(summary['observed_host_tool_calls'], 1)
            self.assertIsNone(summary['host_tool_calls'])
            self.assertIsNone(summary['model_tokens'])  # task still waiting, scope not closed
            _, rebuilt = self.run_cli(CLI, '--operation', 'report', '--task', task)
            self.assertEqual(rebuilt['performance']['host_usage'], summary)
            packet['events'][0]['usage']['input_tokens'] = 101
            packet['events'][0]['usage']['total_tokens'] = 111
            path.write_text(json.dumps(packet))
            code, failed = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(code, 2)
            self.assertEqual(failed['error']['code'], 'invalid_host_usage')
            _, after = self.run_cli(CLI, '--operation', 'report', '--task', task)
            self.assertEqual(after['performance']['host_usage'], summary)

    def test_collect_filters_lineage_turn_window_and_exports_only_allowed_metadata(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, report = self.prepare(base)
            home = base / 'host'
            sessions = home / 'sessions' / '2026' / '10' / '09'
            sessions.mkdir(parents=True)
            start = report['submitted_at']
            end = time.time()
            usage = dict(input_tokens=20, output_tokens=2, total_tokens=22, cached_input_tokens=8, reasoning_output_tokens=1)
            def row(kind, payload, timestamp=start):
                return dict(type=kind, timestamp=timestamp, payload=payload)
            meta = dict(id='root', session_id='root', cwd=str(Path.cwd()), originator='Codex Desktop', source='vscode')
            records = [row('session_meta', meta), row('turn_context', dict(root_turn_id='turn', model='fixture-model')),
                       row('response_item', dict(type='message', content='PRIVATE_BODY_SENTINEL')),
                       row('token_usage_record', dict(thread_id='root', root_turn_id='turn', response_id='dev', usage=usage), start-1),
                       row('token_usage_record', dict(thread_id='root', root_turn_id='other-turn', response_id='other', usage=usage)),
                       row('token_usage_record', dict(thread_id='root', root_turn_id='turn', response_id='real', usage=usage,
                           thread_token_usage=dict(total_tokens=999999))),
                       row('event_msg', dict(type='token_count', info=dict(total_tokens=999999))),
                       row('response_item', dict(type='custom_tool_call', call_id='call-1', name='exec', input='PRIVATE_ARGUMENT_SENTINEL', status='completed'))]
            (sessions / 'root.jsonl').write_text('\n'.join(json.dumps(x) for x in records)+'\n')
            child = dict(id='child', session_id='root', cwd=str(Path.cwd()), originator='Codex Desktop',
                         source=dict(subagent=dict(thread_spawn=dict(parent_thread_id='root'))))
            (sessions / 'child.jsonl').write_text('\n'.join(json.dumps(x) for x in [row('session_meta',child),
                row('token_usage_record',dict(thread_id='child', root_turn_id='turn', response_id='child-response', usage=usage))])+'\n')
            (sessions / 'unrelated.jsonl').write_text(json.dumps(row('session_meta',dict(meta,id='unrelated',session_id='unrelated')))+'\nNOT_PRIVATE_JSON\n')
            # Windows/WSL aliases must not double the input files.
            (home / 'archived_sessions').symlink_to(home / 'sessions', target_is_directory=True)
            output = base / 'collected.json'
            env = os.environ.copy()
            env.update(CODEX_THREAD_ID='root', CODEX_HOME=str(home))
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--root-turn', 'turn', '--invocation', 'video-1',
                '--start', start, '--end', end, '--output', output, '--thread-id', 'root', '--thread-id', 'child', env=env)
            self.assertEqual(code, 0, result)
            collected = json.loads(output.read_text())
            self.assertEqual([e['response_id'] for e in collected['events'] if e['kind']=='model_call'], ['child-response','real'])
            self.assertEqual(sum(e['usage']['total_tokens'] for e in collected['events'] if e['kind']=='model_call'),44)
            self.assertFalse(collected['coverage']['model_calls_complete'])
            self.assertNotIn('PRIVATE_', output.read_text())
            self.assertNotIn('999999', output.read_text())
            self.assertFalse((task / 'host-usage.json').exists())  # collect is read-only for task
            child_output = base / 'child-only.json'
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'child-only',
                '--thread-id', 'child', '--start', start, '--end', end, '--output', child_output, env=env)
            self.assertEqual(code, 0, result)
            child_packet = json.loads(child_output.read_text())
            self.assertEqual(child_packet['scope']['root_turn_id'], 'turn')
            self.assertEqual(len(child_packet['events']), 1)
            self.assertEqual(child_packet['events'][0]['thread_id'], 'child')

    def continuation_fixture(self, base):
        import os
        task, report = self.prepare(base)
        home = base / 'host'
        sessions = home / 'sessions'
        sessions.mkdir(parents=True)
        start = report['submitted_at']
        # A later filename has an older turn. A copied root metadata record inside
        # the child file does not transfer that file's ownership to the root.
        meta = dict(id='root', session_id='root', cwd=str(Path.cwd()), originator='Codex Desktop', source='vscode')
        child = dict(meta, id='child', source=dict(subagent=dict(thread_spawn=dict(parent_thread_id='root'))))
        usage = dict(input_tokens=20, output_tokens=2, total_tokens=22)
        def row(kind, payload, offset=0):
            return dict(type=kind, timestamp=start + offset, payload=payload)
        def model(thread, response, turn='latest', offset=2):
            return row('token_usage_record', dict(thread_id=thread, root_turn_id=turn, response_id=response, usage=usage), offset)
        def write(name, records):
            path = sessions / name
            path.write_text('\n'.join(json.dumps(record) for record in records) + '\n')
            return path
        latest = [row('session_meta', meta), row('turn_context', dict(root_turn_id='latest'), 1),
                  model('root', 'real'), model('root', 'retry'),
                  row('response_item', dict(type='custom_tool_call', call_id='call', name='exec', status='completed', input='PRIVATE_ARGS'), 2)]
        write('a-latest.jsonl', latest)
        write('z-old.jsonl', [row('session_meta', meta), row('turn_context', dict(root_turn_id='old')),
                             model('root', 'old-response', turn='old'),
                             row('turn_context', dict(root_turn_id='future'), 5)])
        write('child.jsonl', [row('session_meta', child), row('session_meta', meta),
                             model('child', 'child-response'), model('root', 'wrong-owner'),
                             row('response_item', dict(type='message', content='PRIVATE_BODY'))])
        env = os.environ.copy()
        env.update(CODEX_THREAD_ID='root', CODEX_HOME=str(home))
        return task, home, start, env, latest, write

    def test_collect_continuations_choose_latest_turn_and_keep_child_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, home, start, env, _, _ = self.continuation_fixture(base)
            for threads, expected in ((['root'], {'real', 'retry'}), (['child'], {'child-response'})):
                output = base / (threads[0] + '.json')
                args = [arg for thread in threads for arg in ('--thread-id', thread)]
                code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'continuation',
                    '--start', start, '--end', start+3, '--output', output, *args, env=env)
                self.assertEqual(code, 0, result)
                packet = json.loads(output.read_text())
                self.assertEqual(packet['scope']['root_turn_id'], 'latest')
                self.assertEqual({event['response_id'] for event in packet['events'] if event['kind']=='model_call'}, expected)
                self.assertTrue(all(packet['coverage'][name] is False for name in
                    ('lifecycle_complete', 'model_calls_complete', 'tools_complete', 'images_complete')))
                self.assertNotIn('PRIVATE_', output.read_text())
            self.assertFalse((task/'host-usage.json').exists())

    def test_collect_duplicate_continuations_are_idempotent_and_reject_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, _, start, env, latest, write = self.continuation_fixture(base)
            duplicate = write('copied.jsonl', latest)
            output = base / 'duplicates.json'
            args = ('collect', '--task', task, '--invocation', 'duplicate', '--root-turn', 'latest',
                    '--start', start, '--end', start+3, '--thread-id', 'root')
            code, result = self.run_cli(HOST, *args, '--output', output, env=env)
            self.assertEqual(code, 0, result)
            packet = json.loads(output.read_text())
            self.assertEqual(len(packet['events']), 3)
            self.assertEqual(sum(e['usage']['total_tokens'] for e in packet['events'] if e['kind']=='model_call'), 44)
            # Changed usage and changed tool metadata for an existing stable ID fail
            # before writing any partial output or changing the video task.
            for index, changes in ((2, dict(usage=dict(input_tokens=21, output_tokens=2, total_tokens=23))),
                                   (4, dict(name='other_tool'))):
                records = json.loads(json.dumps(latest))
                records[index]['payload'].update(changes)
                write(duplicate.name, records)
                failed_output = base / f'conflict-{index}.json'
                code, result = self.run_cli(HOST, *args, '--output', failed_output, env=env)
                self.assertEqual(code, 2, result)
                self.assertFalse(failed_output.exists())
            self.assertFalse((task/'host-usage.json').exists())

    def test_collect_rejects_conflicting_first_metadata_for_scoped_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, _, start, env, latest, write = self.continuation_fixture(base)
            records = json.loads(json.dumps(latest))
            records[0]['payload']['cwd'] = str(base/'another-project')
            write('conflicting-owner.jsonl', records)
            output = base/'conflict.json'
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'conflict',
                '--start', start, '--end', start+3, '--thread-id', 'root', '--output', output, env=env)
            self.assertEqual(code, 2, result)
            self.assertFalse(output.exists())

    def test_collect_prefers_current_home_and_keeps_explicit_historical_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, home, start, env, latest, _ = self.continuation_fixture(base)
            fallback = base/'fallback-home'/'.codex'/'sessions'
            fallback.mkdir(parents=True)
            mirror = json.loads(json.dumps(latest))
            mirror[2]['payload']['response_id'] = 'mirror-only'
            (fallback/'root.jsonl').write_text('\n'.join(json.dumps(record) for record in mirror)+'\n')
            env['HOME'] = str(base/'fallback-home')
            output = base/'historical.json'
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'historical',
                '--root-turn', 'old', '--start', start+1, '--end', start+3,
                '--thread-id', 'root', '--output', output, env=env)
            self.assertEqual(code, 0, result)
            packet = json.loads(output.read_text())
            self.assertEqual([event['response_id'] for event in packet['events']], ['old-response'])
            current = base/'current.json'
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'current',
                '--start', start+1, '--end', start+3, '--thread-id', 'root', '--output', current, env=env)
            self.assertEqual(code, 0, result)
            self.assertEqual({event['response_id'] for event in json.loads(current.read_text())['events']
                if event['kind']=='model_call'}, {'real', 'retry'})
            after = base/'after.json'
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'after',
                '--root-turn', 'latest', '--start', start+2.5, '--end', start+3,
                '--thread-id', 'root', '--output', after, env=env)
            self.assertEqual(code, 0, result)
            self.assertEqual(json.loads(after.read_text())['events'], [])

    def test_collect_requires_explicit_turn_for_simultaneous_conflicting_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, _, start, env, latest, write = self.continuation_fixture(base)
            records = json.loads(json.dumps(latest[:2]))
            records[1]['payload']['root_turn_id'] = 'same-time-other-turn'
            write('same-time.jsonl', records)
            output = base/'ambiguous.json'
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'ambiguous',
                '--start', start, '--end', start+3, '--thread-id', 'root', '--output', output, env=env)
            self.assertEqual(code, 2, result)
            self.assertFalse(output.exists())
            code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'explicit',
                '--root-turn', 'latest', '--start', start, '--end', start+3,
                '--thread-id', 'root', '--output', output, env=env)
            self.assertEqual(code, 0, result)

    def test_collect_requires_root_session_and_no_parent(self):
        for changes in (dict(session_id='another-session'),
                        dict(source=dict(subagent=dict(thread_spawn=dict(parent_thread_id='another-root'))))):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                task, home, start, env, _, _ = self.continuation_fixture(base)
                for name in ('a-latest.jsonl', 'z-old.jsonl'):
                    path = home/'sessions'/name
                    records = [json.loads(line) for line in path.read_text().splitlines()]
                    records[0]['payload'].update(changes)
                    path.write_text('\n'.join(json.dumps(record) for record in records)+'\n')
                output = base/'wrong-root.json'
                code, result = self.run_cli(HOST, 'collect', '--task', task, '--invocation', 'wrong-root',
                    '--root-turn', 'latest', '--start', start, '--end', start+3,
                    '--thread-id', 'root', '--output', output, env=env)
                self.assertEqual(code, 2, result)
                self.assertFalse(output.exists())

    def test_images_missing_usage_and_unknown_fields_preserve_cost_completeness(self):
        from test_agent_performance import PerformanceTests
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, report = self.prepare(base)
            decision = PerformanceTests().decision(task, base)
            self.run_cli(CLI, '--operation', 'submit', '--task', task, '--decision', decision)
            _, exported = self.run_cli(CLI, '--operation', 'export', '--task', task, '--output', base/'output')
            _, delivered = self.run_cli(CLI, '--operation', 'confirm-delivery', '--task', task, '--output', base/'output',
                                      '--decision', PerformanceTests().delivery_review(task, base/'output', base))
            report = delivered['performance']
            packet = self.packet(report)
            image = json.loads((task/'observation.json').read_text())['images'][0]
            packet['coverage']['images_complete'] = True
            packet['coverage']['missing_reasons'] = []
            packet['events'].extend([dict(kind='image_presented', event_id='image-1', thread_id='root', call_id='present-1',
                timestamp=report['submitted_at'], image_id=image['id'], image_source='observation', width=640,height=480,
                panel_count=1,source_pixels=1280*960),dict(kind='image_presented', event_id='image-2', thread_id='root', call_id='present-2',
                timestamp=report['submitted_at'], image_id=image['id'], image_source='observation', width=640,height=480,
                panel_count=1,source_pixels=1280*960),dict(kind='image_presented', event_id='pdf-1',thread_id='root',call_id='pdf',
                timestamp=report['submitted_at'],image_id='page-1',image_source='delivery',width=794,height=1123,panel_count=1,source_pixels=None)])
            path = base/'usage.json'
            path.write_text(json.dumps(packet))
            code, result = self.run_cli(HOST,'import','--task',task,'--events',path)
            self.assertEqual(code,0,result)
            summary = result['usage']
            self.assertEqual(summary['model_tokens']['total_tokens'],213)
            self.assertIsNone(summary['model_tokens']['cached_input_tokens'])
            self.assertEqual(summary['actual_presented_images'],3)
            self.assertEqual(summary['unique_presented_images'],2)
            self.assertEqual(summary['repeated_presentations'],1)
            self.assertEqual(summary['presented_pixels'],1506062)
            self.assertEqual(summary['additional_image_presentations'],1)
            self.assertFalse(summary['declared_presented_images_match'])
            # Missing failed-call usage cannot certify actual total.
            packet['events'].append(dict(kind='model_call',event_id='missing',thread_id='root',response_id='missing',
                timestamp=report['submitted_at'],status='failed',usage=None))
            packet['coverage']['expected_response_ids'].append('missing')
            packet['scope']['ended_at']=time.time()
            path.write_text(json.dumps(packet))
            code,result=self.run_cli(HOST,'import','--task',task,'--events',path)
            self.assertEqual(code,0,result)
            self.assertIsNone(result['usage']['model_tokens'])
            self.assertEqual(result['usage']['observed_actual_tokens']['total_tokens'],213)
            original=(task/'host-usage.json').read_bytes()
            for mutate in ('unknown_usage','unknown_image','bad_dimensions','unbound_thread','huge_count'):
                bad=json.loads(json.dumps(packet))
                if mutate=='unknown_usage':bad['events'][0]['usage']['provider_magic_tokens']=7
                elif mutate=='unknown_image':bad['events'][3]['image_id']='invented'
                elif mutate=='bad_dimensions':bad['events'][3]['width']=True
                elif mutate=='unbound_thread':bad['events'][0]['thread_id']='unrelated'
                else:bad['events'][0]['usage']['input_tokens']=10**1000
                path.write_text(json.dumps(bad))
                code,value=self.run_cli(HOST,'import','--task',task,'--events',path)
                self.assertEqual(code,2,mutate)
                self.assertEqual((task/'host-usage.json').read_bytes(),original)

    def test_real_baseline_requires_valid_wall_clock_and_elapsed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'runs.json'
            performance = dict(
                task_id='task', lifecycle_id='life', task_status='success',
                delivered_at=25, delivery_confirmed=True, delivery_review_id='review',
                wall_clock_valid=True, wall_elapsed_seconds=20,
                state_revision=dict(phase='accepted', complete=True,
                                    observation_sha256='a'*64, decision_sha256='b'*64),
                delivery_history=[dict(confirmed_at=25, review=dict(
                    review_id='review', task_id='task', lifecycle_id='life',
                    observation_sha256='a'*64, decision_sha256='b'*64,
                    reviewer=dict(kind='agent', id='reviewer')))],
                model_tokens=dict(input_tokens=100, output_tokens=10, total_tokens=110),
                host_usage=dict(token_complete=True, declared_presented_images_match=True,
                    source=dict(kind='host'), observed_actual_tokens=dict(total_tokens=110),
                    coverage=dict(lifecycle_complete=True, model_calls_complete=True,
                                  tools_complete=True, images_complete=True)))
            run = dict(run_id='run', sample_id='standard', code_version='candidate',
                entry='url', mode='review', input_sha256='c'*64, environment_id='frozen-env',
                model_id='model', model_version='unknown', measurement_source='host',
                timeout_seconds=1200)
            for case in ('valid', 'invalid_clock', 'missing_clock_flag', 'missing_elapsed', 'null_elapsed'):
                with self.subTest(case=case):
                    report = json.loads(json.dumps(performance))
                    if case == 'invalid_clock':
                        report.update(wall_clock_valid=False, wall_elapsed_seconds=None)
                    elif case == 'missing_clock_flag':
                        del report['wall_clock_valid']
                    elif case == 'missing_elapsed':
                        del report['wall_elapsed_seconds']
                    elif case == 'null_elapsed':
                        report['wall_elapsed_seconds'] = None
                    path.write_text(json.dumps(dict(schema_version=1, runs=[run|dict(performance=report)])))
                    code, result = self.run_cli(HOST, 'aggregate', '--runs', path)
                    self.assertEqual(code, 0, result)
                    group = result['groups'][0]
                    self.assertEqual(group['submitted_count'], 1)
                    self.assertEqual(group['status_counts']['success'], 1)
                    self.assertEqual(group['actual_total_tokens'], 110)
                    self.assertEqual(group['known_observed_total_tokens'], 110)
                    self.assertEqual(group['known_elapsed_seconds_by_status']['success'],
                                     [report.get('wall_elapsed_seconds')])
                    self.assertEqual(group['delivery_seconds']['p50'], 20 if case == 'valid' else None)
                    self.assertEqual(group['real_baseline_eligible'], case == 'valid')

    def test_aggregate_keeps_status_denominator_and_replay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            runs=[]
            for index, seconds in enumerate((10,20,30,40,50)):
                runs.append(dict(run_id=f'run-{index}',sample_id='standard',code_version='baseline',entry='url',mode='review',
                    input_sha256='a'*64,environment_id='frozen-env',model_id='fixture-model',model_version='unknown',
                    measurement_source='controlled_fixture',timeout_seconds=1200,
                    performance=dict(lifecycle_id=f'life-{index}',task_status='success',wall_elapsed_seconds=seconds,
                        first_deliverable_at=seconds,delivered_at=seconds,delivery_confirmed=True,wall_clock_valid=True,model_tokens=dict(input_tokens=90,output_tokens=10,total_tokens=100))))
            for status in ('waiting','failed','cancelled','timeout'):
                runs.append(dict(runs[0],run_id=status,performance=dict(lifecycle_id=status,task_status=status,
                    wall_elapsed_seconds=8,first_deliverable_at=None,wall_clock_valid=True,model_tokens=None)))
            runs.append(dict(runs[0],run_id='replay',mode='replay',performance=dict(runs[0]['performance'],lifecycle_id='replay',task_status='waiting',delivered_at=None,delivery_confirmed=False,wall_elapsed_seconds=1)))
            runs.append(runs[0])  # duplicated report import is idempotent
            path=base/'runs.json';path.write_text(json.dumps(dict(schema_version=1,runs=runs)))
            code,result=self.run_cli(HOST,'aggregate','--runs',path)
            self.assertEqual(code,0,result)
            group=next(g for g in result['groups'] if g['mode']=='review')
            self.assertEqual(group['submitted_count'],9)
            self.assertEqual(group['delivery_seconds'],dict(sample_count=5,p50=30,p90=50,algorithm='nearest-rank'))
            self.assertAlmostEqual(group['status_rates']['success'],5/9)
            self.assertAlmostEqual(group['status_rates']['cancelled'],1/9)
            self.assertIsNone(group['actual_total_tokens'])
            self.assertEqual(group['complete_token_run_count'],5)
            self.assertEqual(group['known_observed_total_tokens'],500)
            self.assertEqual(next(g for g in result['groups'] if g['mode']=='replay')['delivery_seconds']['sample_count'],0)
            self.assertTrue(group['small_sample_limit'])
            self.assertFalse(group['real_baseline_eligible'])
            runs[-1]=dict(runs[0],input_sha256='b'*64)
            path.write_text(json.dumps(dict(schema_version=1,runs=runs)))
            self.assertEqual(self.run_cli(HOST,'aggregate','--runs',path)[0],2)

    def test_only_explicit_complete_caller_scope_can_report_zero_model_tokens(self):
        from test_agent_performance import PerformanceTests
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            task,_=self.prepare(base)
            self.run_cli(CLI,'--operation','submit','--task',task,'--decision',PerformanceTests().decision(task,base))
            _,exported=self.run_cli(CLI,'--operation','export','--task',task,'--output',base/'output')
            _, delivered = self.run_cli(CLI, '--operation', 'confirm-delivery', '--task', task, '--output', base/'output',
                                      '--decision', PerformanceTests().delivery_review(task, base/'output', base))
            packet=self.packet(delivered['performance'])
            packet['events']=[]
            packet['coverage']['expected_response_ids']=[]
            path=base/'usage.json';path.write_text(json.dumps(packet))
            code,result=self.run_cli(HOST,'import','--task',task,'--events',path)
            self.assertEqual(code,0,result)
            self.assertEqual(result['usage']['model_tokens']['total_tokens'],0)
            self.assertTrue(result['usage']['token_complete'])
            packet['coverage']['model_calls_complete']=False
            packet['scope']['ended_at']=time.time()
            path.write_text(json.dumps(packet))
            _,partial=self.run_cli(HOST,'import','--task',task,'--events',path)
            self.assertIsNone(partial['usage']['model_tokens'])

    def test_complete_usage_waits_for_current_delivery_confirmation(self):
        from test_agent_performance import PerformanceTests
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, _ = self.prepare(base)
            helper = PerformanceTests()
            decision = helper.decision(task, base)
            self.run_cli(CLI, '--operation', 'submit', '--task', task, '--decision', decision)
            output = base / 'output'
            _, exported = self.run_cli(CLI, '--operation', 'export', '--task', task, '--output', output)
            packet = self.packet(exported['performance'])
            packet['coverage']['lifecycle_complete'] = True
            path = base / 'usage.json'
            path.write_text(json.dumps(packet))
            _, waiting = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertIsNone(waiting['usage']['model_tokens'])
            receipt = helper.delivery_review(task, output, base)
            _, confirmed = self.run_cli(CLI, '--operation', 'confirm-delivery', '--task', task, '--output', output, '--decision', receipt)
            self.assertTrue(confirmed['performance']['delivery_confirmed'])
            _, old_window = self.run_cli(CLI, '--operation', 'report', '--task', task)
            self.assertIsNone(old_window['performance']['model_tokens'])
            packet['scope']['ended_at'] = time.time()
            path.write_text(json.dumps(packet))
            _, complete = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(complete['usage']['model_tokens']['total_tokens'], 213)
            value = json.loads(decision.read_text())
            value.update(decision_id='revised', evidence='Actual recheck requires a new delivery review.')
            revision = dict(schema_version=5, decision_id='revision-1', reviewed_frames=[f['id'] for f in json.loads((task/'observation.json').read_text())['frames']],
                            revision_of='test-review', decision=value)
            decision.write_text(json.dumps(revision))
            _, revised = self.run_cli(CLI, '--operation', 'submit', '--task', task, '--decision', decision)
            self.assertIsNone(revised['performance']['model_tokens'])
            self.assertFalse(revised['performance']['delivery_confirmed'])

    def test_supplement_preserves_presentations_from_archived_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, report = self.prepare(base)
            state = json.loads((task/'task.json').read_text())
            observation = json.loads((task/'observation.json').read_text())
            batch = next(i for i in observation['images'] if i['kind'] == 'batch_comparison')
            packet = self.packet(report)
            packet['events'].append(dict(kind='image_presented', event_id='batch-view-1', thread_id='root', call_id='batch-view',
                timestamp=report['submitted_at'], image_id=batch['id'], image_source='observation', width=640, height=170,
                panel_count=3, source_pixels=1920*510))
            packet_path = base/'usage.json'
            packet_path.write_text(json.dumps(packet))
            code, imported = self.run_cli(HOST, 'import', '--task', task, '--events', packet_path)
            self.assertEqual(code, 0, imported)
            request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                observation_version=1, request_id='review-gap', issue=dict(reason='Inspect a missing native interval.', start=0, end=1), timestamps=[0.25])
            path = base/'request.json'
            path.write_text(json.dumps(request))
            _, supplemented = self.run_cli(CLI, '--operation', 'supplement', '--task', task, '--decision', path)
            self.assertEqual(supplemented['phase'], 'review')
            self.assertEqual(supplemented['observation_version'], 2)
            self.assertEqual(supplemented['performance']['host_usage']['observed_image_presentations'], 1)
            _, rebuilt = self.run_cli(CLI, '--operation', 'report', '--task', task)
            self.assertEqual(rebuilt['performance']['host_usage']['verified_observation_source_pixels'], 1920*510)
            code, again = self.run_cli(HOST, 'import', '--task', task, '--events', packet_path)
            self.assertEqual(code, 0, again)
            self.assertEqual(again['usage']['observed_image_presentations'], 1)
            packet['scope']['ended_at'] = time.time()
            packet['events'][-1]['observation_sha256'] = state['observation_sha256']
            packet_path.write_text(json.dumps(packet))
            code, bound = self.run_cli(HOST, 'import', '--task', task, '--events', packet_path)
            # The same normalized archived binding remains idempotent.
            self.assertEqual(code, 0, bound)
            packet['events'][-1].update(event_id='batch-view-2', call_id='batch-view-again')
            packet_path.write_text(json.dumps(packet))
            code, bound = self.run_cli(HOST, 'import', '--task', task, '--events', packet_path)
            self.assertEqual(code, 0, bound)
            self.assertEqual(bound['usage']['observed_image_presentations'], 2)
            original = (task/'host-usage.json').read_bytes()
            packet['events'][-1]['observation_sha256'] = '0'*64
            packet['scope']['ended_at'] = time.time()
            packet_path.write_text(json.dumps(packet))
            self.assertEqual(self.run_cli(HOST, 'import', '--task', task, '--events', packet_path)[0], 2)
            self.assertEqual((task/'host-usage.json').read_bytes(), original)

    def test_real_baseline_gate_preserves_explicit_fixture_delivery_provenance(self):
        from test_agent_performance import PerformanceTests
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, _ = self.prepare(base)
            helper = PerformanceTests()
            self.run_cli(CLI, '--operation', 'submit', '--task', task, '--decision', helper.decision(task, base))
            output = base/'output'
            self.run_cli(CLI, '--operation', 'export', '--task', task, '--output', output)
            _, delivered = self.run_cli(CLI, '--operation', 'confirm-delivery', '--task', task, '--output', output,
                                        '--decision', helper.delivery_review(task, output, base))
            packet = self.packet(delivered['performance'])
            packet['source']['kind'] = 'host'
            packet['coverage'].update(lifecycle_complete=True, images_complete=True, missing_reasons=[])
            for index, image in enumerate(json.loads((task/'observation.json').read_text())['images']):
                with Image.open(task/image['path']) as raster:
                    width, height = raster.size
                packet['events'].append(dict(kind='image_presented', event_id=f'image-{index}', call_id=f'image-{index}',
                    thread_id='root', timestamp=packet['scope']['started_at'], image_id=image['id'], image_source='observation',
                    width=width, height=height, panel_count=1, source_pixels=width*height))
            path = base/'usage.json'
            path.write_text(json.dumps(packet))
            self.assertEqual(self.run_cli(HOST, 'import', '--task', task, '--events', path)[0], 0)
            _, value = self.run_cli(CLI, '--operation', 'report', '--task', task)
            report = value['performance']
            self.assertTrue(report['host_usage']['declared_presented_images_match'])
            run = dict(run_id='fixture-delivery',sample_id='fixture',code_version='candidate',entry='local',mode='review',
                       input_sha256=report['source']['sha256'],environment_id='fixture-env',model_id='test',model_version='unknown',
                       measurement_source='host',timeout_seconds=1200,performance=report)
            aggregate = base/'runs.json'
            aggregate.write_text(json.dumps(dict(schema_version=1,runs=[run])))
            _, result = self.run_cli(HOST, 'aggregate', '--runs', aggregate)
            self.assertFalse(result['groups'][0]['real_baseline_eligible'])
            # An otherwise identical caller-supplied real-review provenance clears this specific gate.
            report['delivery_history'][-1]['review']['reviewer']['kind'] = 'agent'
            report['delivery_reviewer']['kind'] = 'agent'
            aggregate.write_text(json.dumps(dict(schema_version=1,runs=[run])))
            _, result = self.run_cli(HOST, 'aggregate', '--runs', aggregate)
            self.assertTrue(result['groups'][0]['real_baseline_eligible'])
            report['delivery_confirmed'] = False
            aggregate.write_text(json.dumps(dict(schema_version=1,runs=[run])))
            self.assertEqual(self.run_cli(HOST, 'aggregate', '--runs', aggregate)[0], 2)

    def test_legacy_comparison_binding_survives_equal_size_new_montage(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            # Lossless fixture retains equal PNG bytes at distinct real source PTS.
            score_frame().save(base/'source.png')
            video = base/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(base/'source.png'),
                            '-t','2','-r','4','-c:v','libx264','-crf','0','-pix_fmt','yuv420p',str(video)], check=True)
            task = base/'task'
            _, prepared = self.run_cli(CLI, video, '--output', task)
            report = prepared['performance']
            def supplement(timestamp, request_id):
                state = json.loads((task/'task.json').read_text())
                request = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
                    observation_version=state['observation_version'], request_id=request_id,
                    issue=dict(reason='Inspect another native interval.', start=0, end=1), timestamps=[timestamp])
                path = base/f'{request_id}.json'
                path.write_text(json.dumps(request))
                return self.run_cli(CLI, '--operation', 'supplement', '--task', task, '--decision', path)[1]
            report = supplement(0.25, 'first-gap')['performance']
            observation = json.loads((task/'observation.json').read_text())
            montage = next(i for i in observation['images'] if i['id'] == 'comparison')
            from PIL import Image
            with Image.open(task/montage['path']) as raster:
                width, height = raster.size
            packet = self.packet(report)
            packet['events'].append(dict(kind='image_presented', event_id='montage-view', thread_id='root', call_id='montage-call',
                timestamp=time.time(), image_id='comparison', image_source='observation', width=width, height=height,
                panel_count=4, source_pixels=width*height))
            packet['scope']['ended_at'] = time.time()
            path = base/'usage.json'
            path.write_text(json.dumps(packet))
            self.assertEqual(self.run_cli(HOST, 'import', '--task', task, '--events', path)[0], 0)
            supplemented = supplement(0.5, 'second-gap')
            self.assertEqual(supplemented['phase'], 'review')
            self.assertEqual(supplemented['performance']['host_usage']['observed_image_presentations'], 1)
            current = json.loads((task/'observation.json').read_text())
            new = next(i for i in current['images'] if i['id'] == 'comparison')
            with Image.open(task/new['path']) as raster:
                self.assertEqual(raster.size, (width,height))
            self.assertNotEqual(new['sha256'], montage['sha256'])
            code, again = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(code, 0, again)
            self.assertEqual(again['usage']['observed_image_presentations'], 1)
            stored = json.loads((task/'host-usage.json').read_text())
            self.assertEqual(stored['events'][-1]['observation_sha256'], report['state_revision']['observation_sha256'])

            current_hash = json.loads((task/'task.json').read_text())['observation_sha256']
            packet['events'].append(dict(kind='image_presented', event_id='new-montage-view', thread_id='root', call_id='new-montage-call',
                timestamp=time.time(), image_id='comparison', image_source='observation', width=width, height=height,
                panel_count=5, source_pixels=width*height, observation_sha256=current_hash))
            packet['scope']['ended_at'] = time.time()
            path.write_text(json.dumps(packet))
            _, distinct = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(distinct['usage']['observed_image_presentations'], 2)
            self.assertEqual(distinct['usage']['unique_presented_images'], 2)
            self.assertEqual(distinct['usage']['repeated_presentations'], 0)
            # The same source PNG in two observation versions is a repeated presentation.
            for index, binding in enumerate((report['state_revision']['observation_sha256'], current_hash)):
                packet['events'].append(dict(kind='image_presented', event_id=f'native-repeat-{index}', call_id=f'native-call-{index}',
                    thread_id='root', timestamp=time.time(), image_id='frame-000', image_source='observation',
                    width=1280, height=960, panel_count=1, source_pixels=1280*960, observation_sha256=binding))
            # Caller-owned external IDs are scoped by their source, not by their string alone.
            for index, source in enumerate(('delivery','diagnostic','delivery')):
                packet['events'].append(dict(kind='image_presented', event_id=f'external-{index}', call_id=f'external-call-{index}',
                    thread_id='root', timestamp=time.time(), image_id='external-page', image_source=source,
                    width=640, height=480, panel_count=1, source_pixels=None))
            packet['scope']['ended_at'] = time.time()
            path.write_text(json.dumps(packet))
            _, totals = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(totals['usage']['observed_image_presentations'], 7)
            self.assertEqual(totals['usage']['unique_presented_images'], 5)
            self.assertEqual(totals['usage']['repeated_presentations'], 2)

            native = {i['id']: i for i in current['images'] if i['kind'] == 'native'}
            self.assertEqual(native['frame-000']['sha256'], native['frame-001']['sha256'])
            packet['events'].append(dict(kind='image_presented', event_id='different-source', call_id='different-source-call',
                thread_id='root', timestamp=time.time(), image_id='frame-001', image_source='observation',
                width=1280, height=960, panel_count=1, source_pixels=1280*960, observation_sha256=current_hash))
            packet['scope']['ended_at'] = time.time()
            path.write_text(json.dumps(packet))
            _, sources = self.run_cli(HOST, 'import', '--task', task, '--events', path)
            self.assertEqual(sources['usage']['observed_image_presentations'], 8)
            self.assertEqual(sources['usage']['unique_presented_images'], 6)
            self.assertEqual(sources['usage']['repeated_presentations'], 2)
