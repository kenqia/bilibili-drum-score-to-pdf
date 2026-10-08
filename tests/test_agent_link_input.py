"""Controlled anonymous backend, real CLI preparation, decisions and export."""
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from yt_dlp import YoutubeDL
from score_fixtures import CLI, score_frame, video_from_image
from test_link_input import cli, URL, MEDIA
import test_agent_workflow


class AgentLinkInputTests(unittest.TestCase):
    cli = test_agent_workflow.AgentWorkflowTests.cli

    def prepare(self, output, video, url=URL, failure=None, timeout=5, media=MEDIA, dns=None, response=None):
        info = {'id': 'BV1b5411x7Ku_p2', 'formats': [
            {'url': media, 'width': 1280, 'height': 960, 'vcodec': 'avc1', 'acodec': 'none'}]}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', [str(CLI), url, '--operation', 'prepare', '--output', str(output), '--acquisition-timeout', str(timeout)]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch.object(YoutubeDL, 'extract_info', return_value=info, side_effect=failure), patch('urllib.request.OpenerDirector.open', side_effect=response or (lambda *a, **k: io.BytesIO(video.read_bytes()))), patch('socket.getaddrinfo', return_value=dns or [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]):
            cli.main()
        return json.loads(stdout.getvalue()), stdout.getvalue() + stderr.getvalue()

    def export_decision(self, task, base, name):
        state = json.loads((task / 'task.json').read_text())
        observation = json.loads((task / 'observation.json').read_text())
        decision = {'schema_version': 1, 'task_id': state['task_id'], 'observation_sha256': state['observation_sha256'],
                    'decision_id': 'controlled-review', 'model': {'id': 'unknown', 'version': 'unknown'},
                    'prompt': {'version': 'test-1', 'text': 'Select complete native rows.'},
                    'presented_images': [i['id'] for i in observation['images']], 'visual_review': True,
                    'complete': True, 'evidence': 'Controlled saved decision, not a live model evaluation.',
                    'selected_candidates': [c['id'] for c in observation['candidates'] if c['frame_id'] == observation['frames'][0]['id']],
                    'unresolved': []}
        path = base / f'{name}-decision.json'
        path.write_text(json.dumps(decision))
        _, accepted = self.cli('--operation', 'submit', '--task', task, '--decision', path)
        self.assertEqual(accepted['phase'], 'accepted', accepted)
        code, result = self.cli('--operation', 'export', '--task', task, '--output', base / name)
        self.assertEqual(code, 0, result)
        return result

    def test_bv_and_local_original_produce_equal_native_rows_and_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            bv_task = base / 'bv-task'
            result, logs = self.prepare(bv_task, video)
            self.assertEqual(result['status'], 'waiting', result)
            observation = json.loads((bv_task / 'observation.json').read_text())
            self.assertEqual(observation['source']['origin']['page'], 2)
            self.assertFalse(observation['source']['origin']['authenticated'])
            self.assertEqual(observation['source']['width'], 1280)
            self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', logs + (bv_task / 'observation.json').read_text())
            acquired = Path(observation['source']['path'])
            self.assertEqual(acquired.parent, bv_task)
            local_task = base / 'local-task'
            self.cli(video, '--operation', 'prepare', '--output', local_task)
            bv = self.export_decision(bv_task, base, 'bv')
            local = self.export_decision(local_task, base, 'local')
            self.assertEqual(bv['source']['sha256'], local['source']['sha256'])
            self.assertEqual(bv['source']['origin']['bvid'], 'BV1b5411x7Ku')
            self.assertEqual([r['original_sha256'] for r in bv['rows']], [r['original_sha256'] for r in local['rows']])
            self.assertEqual((base / 'bv/score.pdf').read_bytes(), (base / 'local/score.pdf').read_bytes())
            before = (bv_task / 'observation.json').read_bytes()
            rejected, _ = self.prepare(bv_task, video)
            self.assertEqual(rejected['error']['code'], 'existing_output')
            self.assertEqual(before, (bv_task / 'observation.json').read_bytes())

    def test_acquisition_failure_can_retry_or_use_local_without_overwriting_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            video = video_from_image(score_frame(), base)
            for replacement in ('bv', 'local'):
                task = base / replacement
                result, logs = self.prepare(task, video, failure=RuntimeError(MEDIA))
                self.assertEqual(result['phase'], 'acquisition')
                self.assertEqual(result['error']['code'], 'public_api_unavailable')
                self.assertEqual({p.name for p in task.iterdir()}, {'manifest.json'})
                self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', logs + (task / 'manifest.json').read_text())
                if replacement == 'bv':
                    result, _ = self.prepare(task, video)
                else:
                    _, result = self.cli(video, '--operation', 'prepare', '--output', task)
                self.assertEqual(result['status'], 'waiting', result)
                self.assertTrue((task / 'observation.json').exists())
            task = base / 'protected'
            self.prepare(task, video, failure=RuntimeError(MEDIA))
            before = (task / 'manifest.json').read_bytes()
            (task / 'notes.txt').write_text('keep')
            result, _ = self.prepare(task, video)
            self.assertEqual(result['error']['code'], 'existing_output')
            self.assertEqual(before, (task / 'manifest.json').read_bytes())

    def test_agent_prepare_keeps_input_safety_decode_deadline_and_staging_gates(self):
        from anonymous_network import PublicRedirect
        from email.message import Message
        def redirect(request, **kwargs):
            headers = Message()
            headers['Location'] = 'https://127.0.0.1/?sign=DO_NOT_SAVE_TEST_SENTINEL'
            with patch('socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]):
                return PublicRedirect().redirect_request(request, io.BytesIO(), 302, 'Moved', headers, headers['Location'])
        def stall(*args, **kwargs):
            time.sleep(1)
        cases = [
            ('http', {'url': URL.replace('https:', 'http:')}, 'invalid_bilibili_url'),
            ('page', {'url': URL + '&p=3'}, 'invalid_bilibili_url'),
            ('media', {'media': 'http://cdn.bilivideo.com/video'}, 'unsafe_media_target'),
            ('private', {'dns': [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 443))]}, 'unsafe_media_target'),
            ('redirect', {'response': redirect}, 'unsafe_media_target'),
            ('decode', {'response': lambda *a, **k: io.BytesIO(b'not-video')}, 'undecodable_video'),
            ('deadline', {'failure': stall, 'timeout': .05}, 'network_timeout')]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, options, code in cases:
                with self.subTest(name=name):
                    task = base / name
                    result, logs = self.prepare(task, base / 'unused', **options)
                    self.assertEqual(result['phase'], 'acquisition', result)
                    self.assertEqual(result['error']['code'], code, result)
                    self.assertEqual({p.name for p in task.iterdir()}, {'manifest.json'})
                    self.assertNotIn('DO_NOT_SAVE_TEST_SENTINEL', logs + (task / 'manifest.json').read_text())
                    self.assertFalse(list(base.glob('.anonymous-publish-*')))

    def test_agent_prepare_stops_oversized_media_without_publishing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / 'task'
            with patch('anonymous_backend.MAX_BYTES', 10):
                result, _ = self.prepare(task, Path(directory) / 'unused', response=lambda *a, **k: io.BytesIO(b'x' * 11))
            self.assertEqual(result['error']['code'], 'download_too_large')
            self.assertEqual({p.name for p in task.iterdir()}, {'manifest.json'})
