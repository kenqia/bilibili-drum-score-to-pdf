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
                               started_at=report['submitted_at'], ended_at=time.time(), mode='review'),
                    coverage=dict(model_calls_complete=True, tools_complete=True, images_complete=False,
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
