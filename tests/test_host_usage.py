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

    def test_images_missing_usage_and_unknown_fields_preserve_cost_completeness(self):
        from test_agent_performance import PerformanceTests
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task, report = self.prepare(base)
            decision = PerformanceTests().decision(task, base)
            self.run_cli(CLI, '--operation', 'submit', '--task', task, '--decision', decision)
            _, exported = self.run_cli(CLI, '--operation', 'export', '--task', task, '--output', base/'output')
            report = exported['performance']
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

    def test_aggregate_keeps_status_denominator_and_replay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            runs=[]
            for index, seconds in enumerate((10,20,30,40,50)):
                runs.append(dict(run_id=f'run-{index}',sample_id='standard',code_version='baseline',entry='url',mode='review',
                    input_sha256='a'*64,environment_id='frozen-env',model_id='fixture-model',model_version='unknown',
                    measurement_source='controlled_fixture',timeout_seconds=1200,
                    performance=dict(lifecycle_id=f'life-{index}',task_status='success',wall_elapsed_seconds=seconds,
                        first_deliverable_at=seconds,wall_clock_valid=True,model_tokens=dict(input_tokens=90,output_tokens=10,total_tokens=100))))
            for status in ('waiting','failed','cancelled','timeout'):
                runs.append(dict(runs[0],run_id=status,performance=dict(lifecycle_id=status,task_status=status,
                    wall_elapsed_seconds=8,first_deliverable_at=None,wall_clock_valid=True,model_tokens=None)))
            runs.append(dict(runs[0],run_id='replay',mode='replay',performance=dict(runs[0]['performance'],lifecycle_id='replay',wall_elapsed_seconds=1)))
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
            self.assertEqual(next(g for g in result['groups'] if g['mode']=='replay')['delivery_seconds']['sample_count'],1)
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
            packet=self.packet(exported['performance'])
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
