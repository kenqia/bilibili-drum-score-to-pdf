"""Shared final Python, CLI and HTTP contracts; sources are synthetic."""
from pathlib import Path
import json
import subprocess
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
SCRIPT_CONVERSION_ENTRIES = ('script_core', 'script_cli')
REMOTE_SCRIPT_ENTRIES = (*SCRIPT_CONVERSION_ENTRIES, 'script_http')
ACQUISITION_ENTRIES = ('acquire',)
MAINTENANCE_ENTRIES = ('backup', 'verify', 'restore')


class ScriptPublicContracts(unittest.TestCase):
    def test_automatic_region_selects_staff_panel_and_preserves_its_edges(self):
        import tempfile
        from PIL import Image, ImageDraw, ImageChops
        import drum_score
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (1000, 600), 'black')
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 50, 500, 550), fill='white')
            draw.rectangle((650, 50, 950, 550), fill='white')
            draw.text((652, 53), 'TITLE / AUTHOR', fill='blue')
            draw.rectangle((652, 535, 948, 540), fill='red')
            for top in (100, 200, 300, 400):
                for line in range(5):
                    draw.line((665, top + line * 8, 935, top + line * 8), fill='black', width=2)
                draw.ellipse((700, top + 10, 710, top + 18), fill='black')
            image.save(root / 'source.png')
            source = root / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'source.png'),
                '-t', '2', '-r', '5', '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['status'], 'complete')
            self.assertFalse(result['reliable'])
            self.assertEqual(result['staff_count'], 4)
            left, top, right, bottom = result['region']
            self.assertLessEqual(left, 650)
            self.assertLessEqual(top, 50)
            self.assertGreaterEqual(right, 951)
            self.assertGreaterEqual(bottom, 551)
            self.assertGreater(left, 500)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertIsNone(ImageChops.difference(actual.crop(
                    (650 - left, 50 - top, 951 - left, 551 - top)),
                    image.crop((650, 50, 951, 551))).getbbox())

    def test_automatic_region_requires_temporal_support_and_rejects_two_score_panels(self):
        import tempfile
        from PIL import Image, ImageDraw
        import drum_score
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for ambiguous in (False, True):
                with self.subTest(ambiguous=ambiguous):
                    for index in range(8):
                        image = Image.new('RGB', (1000, 600), 'black')
                        draw = ImageDraw.Draw(image)
                        draw.rectangle((20, 50, 500, 550), fill='white')
                        draw.rectangle((650, 50, 950, 550), fill='white')
                        panels = [(665, 935)]
                        if ambiguous or index == 0:
                            panels.append((35, 485))
                        for left, right in panels:
                            for top in (100, 200, 300, 400):
                                for line in range(5):
                                    draw.line((left, top + line * 8, right, top + line * 8),
                                              fill='black', width=2)
                                draw.ellipse((left + 35, top + 10, left + 45, top + 18), fill='black')
                        image.save(root / f'frame-{index:02d}.png')
                    source = root / f'{ambiguous}.mkv'
                    subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '4', '-i',
                        str(root / 'frame-%02d.png'), '-c:v', 'ffv1', str(source)], check=True)
                    output = root / f'result-{ambiguous}'
                    if ambiguous:
                        with self.assertRaises(drum_score.ConversionError) as caught:
                            drum_score.convert(source, output)
                        self.assertEqual(caught.exception.code, 'unsupported_layout')
                        self.assertFalse(output.exists())
                    else:
                        result = drum_score.convert(source, output)
                        self.assertEqual(result['status'], 'complete')
                        self.assertEqual(result['staff_count'], 4)
                        self.assertGreater(result['region'][0], 500)

    def test_automatic_region_keeps_uncertain_single_late_staff_observation(self):
        import tempfile
        from PIL import Image, ImageDraw
        import drum_score
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(40):
                image = Image.new('RGB', (1000, 600), 'black')
                draw = ImageDraw.Draw(image)
                draw.rectangle((20, 50, 500, 550), fill='white')
                draw.rectangle((650, 50, 950, 550), fill='white')
                if index == 35:
                    for top in (100, 200, 300, 400):
                        for line in range(5):
                            draw.line((665, top + line * 8, 935, top + line * 8), fill='black', width=2)
                        draw.ellipse((700, top + 10, 710, top + 18), fill='black')
                image.save(root / f'frame-{index:02d}.png')
            source = root / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '10', '-i',
                str(root / 'frame-%02d.png'), '-c:v', 'ffv1', str(source)], check=True)
            # The existing registration stage cannot join this abrupt blank/
            # score/blank sequence. Automatic selection must reach the same
            # conservative discontinuity as manual selection, rather than
            # wrongly rejecting a short score absent at the seven probes.
            for name, options in (('auto', None), ('manual',
                    {'region_percent': [64.7, 7.833333333333333, 95.3, 92.16666666666667]})):
                with self.subTest(entry=name):
                    with self.assertRaises(drum_score.ConversionError) as caught:
                        drum_score.convert(source, root / name, options=options)
                    self.assertEqual(caught.exception.code, 'discontinuity')
                    self.assertFalse((root / name).exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Real cached worker and disposable print process')
    def test_cached_selected_result_keeps_presence_print_and_retry_contracts(self):
        import base64
        import hashlib
        import test_web_worker as web_fixture
        from test_video_cache import NETWORK
        fixture = web_fixture.WebsiteWorker(methodName='runTest')
        fixture.setUp()
        try:
            (fixture.network / 'sitecustomize.py').write_text(NETWORK)
            options = {'start_seconds': .5, 'end_seconds': 1.5,
                       'region_percent': [5, 4, 95, 95], 'ignore_fixed_overlays': False}
            url = 'https://www.bilibili.com/video/BV1rH4y1R7Rk'
            for visitor in ('a' * 32, 'b' * 32):
                reply = fixture.client.post('/api/presence', json={'visitor': visitor})
                self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.json()['online'], 2)
            first = fixture.client.post('/api/tasks', json={'url': url}).json()
            self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
            first_auth = {'Authorization': 'Bearer ' + first['capability']}
            cached = fixture.state(first['id'], first_auth)
            self.assertEqual(cached['state'], 'complete', cached)
            second = fixture.client.post('/api/tasks', json={'url': url, 'options': options}).json()
            auth = {'Authorization': 'Bearer ' + second['capability']}
            fixture.client.post('/api/tasks/' + second['id'] + '/cancel', headers=auth)
            retry = fixture.client.post('/api/tasks/' + second['id'] + '/retry', headers=auth)
            self.assertEqual(retry.json()['options'], options)
            self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
            before = fixture.state(second['id'], auth)
            self.assertEqual(before['state'], 'complete', before)
            self.assertEqual(before['result']['source']['cache']['status'], 'hit')
            self.assertEqual(before['result']['source']['cache']['expires_at'], cached['result']['source']['cache']['expires_at'])
            self.assertEqual(before['result']['conversion']['options'], options)
            from drum_score.jobs import Jobs
            records = Jobs(fixture.data).records.query(task=second['id'])
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record['settings']['options'] == options for record in records))
            complete_record = next(record for record in records if record['status'] == 'complete')
            self.assertEqual(complete_record['output']['conversion']['options'], options)
            self.assertTrue(before['result']['conversion']['is_excerpt'])
            self.assertFalse(before['result']['reliable'])
            self.assertEqual((fixture.network / 'fetches').read_text().splitlines(), ['fetch'])
            pdf = fixture.client.get('/api/tasks/' + second['id'] + '/pdf', headers=auth).content
            self.assertEqual(hashlib.sha256(pdf).hexdigest(), before['result']['pdf']['sha256'])
            relayout = fixture.client.post('/api/tasks/' + second['id'] + '/layout', headers=auth,
                                          json={'paper': 'A3', 'rows': 3})
            self.assertEqual(relayout.status_code, 200, relayout.text[:200])
            self.assertTrue(base64.b64decode(relayout.json()['pdf']).startswith(b'%PDF'))
            self.assertTrue(all(base64.b64decode(page).startswith(b'\x89PNG') for page in relayout.json()['pages']))
            self.assertEqual(fixture.state(second['id'], auth), before)
            self.assertEqual(fixture.client.get('/api/tasks/' + second['id'] + '/pdf', headers=auth).content, pdf)
            self.assertEqual(fixture.client.post('/api/presence', json={'visitor': 'a' * 32}).json()['online'], 2)
        finally:
            fixture.tearDown()

    def test_worker_rejects_cache_budget_above_one_gib(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-m', 'drum_score.worker',
                '--data-root', str(Path(temporary) / 'service'), '--once', '--cache-mib', '1025'],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(temporary) / 'service').exists())

    def test_advanced_options_reject_invalid_types_and_ranges_at_public_entries(self):
        import tempfile
        from fastapi.testclient import TestClient
        from drum_score import convert, ConversionError
        from drum_score.web import create_app
        invalid = ({'start_seconds': True}, {'start_seconds': -1},
                   {'end_seconds': 0}, {'start_seconds': 2, 'end_seconds': 1},
                   {'start_seconds': float('nan')}, {'start_seconds': 10**1000}, {'region_percent': [0, 20, 100, 20]},
                   {'region_percent': [0, 0, 101, 100]}, {'ignore_fixed_overlays': 1},
                   {'unknown': 1})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with TestClient(create_app(root / 'service')) as client:
                for options in invalid:
                    with self.subTest(options=options):
                        with self.assertRaises(ConversionError) as raised:
                            convert(root / 'missing.mp4', root / 'result', options=options)
                        self.assertEqual(raised.exception.code, 'invalid_request')
                        if options.get('start_seconds') != options.get('start_seconds'):
                            continue  # JSON has no non-finite number representation.
                        reply = client.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk', 'options': options})
                        self.assertEqual(reply.status_code, 422)
                process = subprocess.run([sys.executable, '-m', 'drum_score', str(root / 'missing.mp4'),
                    '--output', str(root / 'result'), '--start-seconds', '-1'],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(json.loads(process.stdout)['error']['code'], 'invalid_request')
                self.assertFalse((root / 'result').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Real decoder and worker')
    def test_selected_range_and_manual_region_reach_all_entries_and_retry(self):
        import hashlib
        import test_web_worker as web_fixture
        fixture = web_fixture.WebsiteWorker(methodName='runTest')
        fixture.setUp()
        options = {'start_seconds': 0.5, 'end_seconds': 1.5,
                   'region_percent': [5, 4, 95, 95], 'ignore_fixed_overlays': False}
        try:
            video = fixture.network / 'input.mp4'
            runner = fixture.network / 'options-core.py'
            runner.write_text("import sys,json\nfrom drum_score import convert\n"
                              "if __name__=='__main__': print(json.dumps(convert(sys.argv[1],sys.argv[2],options=json.loads(sys.argv[3]))))\n")
            for entry in REMOTE_SCRIPT_ENTRIES:
                with self.subTest(entry=entry):
                    if entry == 'script_http':
                        task = fixture.client.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk', 'options': options}).json()
                        auth = {'Authorization': 'Bearer ' + task['capability']}
                        fixture.client.post('/api/tasks/' + task['id'] + '/cancel', headers=auth)
                        retried = fixture.client.post('/api/tasks/' + task['id'] + '/retry', headers=auth).json()
                        self.assertEqual(retried['options'], options)
                        self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
                        state = fixture.state(task['id'], auth)
                        self.assertEqual(state['state'], 'complete', state)
                        result = state['result']
                    else:
                        output = fixture.root / entry
                        args = ([sys.executable, str(runner), str(video), str(output), json.dumps(options)]
                                if entry == 'script_core' else [sys.executable, '-m', 'drum_score', str(video), '--output', str(output),
                                    '--start-seconds', '.5', '--end-seconds', '1.5', '--region-percent', '5', '4', '95', '95', '--no-ignore-fixed-overlays'])
                        process = subprocess.run(args, env=fixture.env, capture_output=True, text=True, timeout=30)
                        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                        result = json.loads(process.stdout)
                        self.assertEqual(result['region'], [64, 38, 1216, 912])
                        times = [sample['timestamp'] for sample in result['samples']]
                        self.assertEqual(times[0], .5)
                        self.assertEqual(times[-1], 1.25)
                        self.assertTrue(all(.5 <= timestamp < 1.5 for timestamp in times))
                        self.assertTrue(all(sample['timestamp'] == sample['pts'] * sample['time_base'][0] / sample['time_base'][1] for sample in result['samples']))
                        self.assertEqual(result['staff_count'], 3)
                        self.assertEqual(result['registration']['invalid_pixels'], 0)
                        self.assertEqual(result['registration']['overlay_comparisons'], 0)
                        self.assertEqual(result['metrics']['sampling_interval_seconds'], .5)
                        self.assertEqual(result['metrics']['retained_rgb_frames'], len(result['samples']))
                        self.assertGreater(result['metrics']['retained_rgb_bytes'], 0)
                        self.assertTrue(all(.5 <= frame['timestamp'] < 1.5
                            for frame in result['preflight']['observations']))
                    self.assertEqual(result['conversion']['options'], options)
                    self.assertEqual(result['conversion']['effective_range_seconds'], [.5, 1.5])
                    self.assertTrue(result['conversion']['is_excerpt'])
                    self.assertFalse(result['reliable'])
                    self.assertEqual(result['source']['sha256'], hashlib.sha256(video.read_bytes()).hexdigest())
                    self.assertEqual(result['source']['metadata']['duration'], 2)
        finally:
            fixture.tearDown()

    @unittest.skipUnless(sys.platform == 'linux', 'Forked anonymous acquisition')
    def test_full_source_duration_limit_precedes_media_even_with_short_selection(self):
        import test_web_worker as web_fixture
        fixture = web_fixture.WebsiteWorker(methodName='runTest')
        fixture.setUp()
        # This test rewrites equal-length startup code within one timestamp tick.
        # Every child must load the new pinned synthetic backend digest.
        fixture.env['PYTHONDONTWRITEBYTECODE'] = '1'
        try:
            marker = fixture.network / 'media-opened'
            from bbdown_fixture import fixture_config, install_fake_bbdown
            config = fixture_config()
            config['view']['pages'][1]['duration'] = 601
            config['play']['timelength'] = 601000
            binary, digest = install_fake_bbdown(fixture.network, config)
            boundary = ("import io,os,socket,urllib.request\nfrom pathlib import Path\n"
                "from drum_score import bbdown_cli\n"
                "bbdown_cli.METADATA_SHA256=" + repr(digest) + "\n"
                "os.environ['PATH']=" + repr(str(binary.parent)) + "+os.pathsep+os.environ['PATH']\n"
                "socket.getaddrinfo=lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]\n"
                "urllib.request.OpenerDirector.open=lambda *a,**k:io.BytesIO(Path("
                + repr(str(fixture.network / 'input.mp4')) + ").read_bytes())\n")
            boundary += f"\noriginal_open=urllib.request.OpenerDirector.open\ndef checked_open(*a,**k):\n Path({str(marker)!r}).write_text('media')\n return original_open(*a,**k)\nurllib.request.OpenerDirector.open=checked_open\n"
            (fixture.network / 'sitecustomize.py').write_text(boundary)
            runner = fixture.network / 'duration-core.py'
            runner.write_text("import sys,json\nfrom drum_score import convert,ConversionError\n"
                "if __name__=='__main__':\n try: convert(sys.argv[1],sys.argv[2],options={'end_seconds':1})\n except ConversionError as e: print(json.dumps({'error':{'code':e.code}})); sys.exit(2)\n")
            url = 'https://www.bilibili.com/video/BV1b5411x7Ku?p=2'
            for entry in REMOTE_SCRIPT_ENTRIES:
                with self.subTest(entry=entry):
                    if entry == 'script_http':
                        task = fixture.client.post('/api/tasks', json={'url': url, 'options': {'end_seconds': 1}}).json()
                        auth = {'Authorization': 'Bearer ' + task['capability']}
                        self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
                        result = fixture.state(task['id'], auth)
                        self.assertEqual(result['state'], 'failed')
                    else:
                        output = fixture.root / entry
                        args = ([sys.executable, str(runner), url, str(output)] if entry == 'script_core'
                                else [sys.executable, '-m', 'drum_score', url, '--output', str(output), '--end-seconds', '1'])
                        process = subprocess.run(args, env=fixture.env, capture_output=True, text=True, timeout=30)
                        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                        result = json.loads(process.stdout)
                        self.assertFalse(output.exists())
                    self.assertEqual(result['error']['code'], 'resource_limit', result)
                    self.assertFalse(marker.exists(), 'duration rejection must happen before media transfer')
            # Exactly 600 reaches media verification. The 2-second fixture is
            # then rejected for integrity, proving 600 itself was permitted.
            config['view']['pages'][1]['duration'] = 600
            config['play']['timelength'] = 600000
            _, boundary_digest = install_fake_bbdown(fixture.network, config)
            (fixture.network / 'sitecustomize.py').write_text(boundary.replace(digest, boundary_digest))
            process = subprocess.run([sys.executable, str(runner), url, str(fixture.root / 'boundary')],
                                     env=fixture.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(json.loads(process.stdout)['error']['code'], 'incomplete_video')
            self.assertTrue(marker.exists())
        finally:
            fixture.tearDown()

    def test_advanced_form_defaults_are_folded_and_editable_without_source_player(self):
        import tempfile
        from html.parser import HTMLParser
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        class Form(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attributes):
                self.tags.append((tag, dict(attributes)))
        with tempfile.TemporaryDirectory() as temporary, TestClient(create_app(Path(temporary))) as client:
            form = Form()
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            form.feed(response.text)
            fields = {attrs.get('id'): attrs for tag, attrs in form.tags if tag in ('input', 'select', 'details')}
            self.assertNotIn('open', fields['advanced-options'])
            self.assertEqual(fields['start-seconds']['value'], '0')
            self.assertNotIn('value', fields['end-seconds'])
            self.assertIn('checked', fields['ignore-fixed-overlays'])
            for name in ('start-seconds', 'end-seconds', 'region-left', 'region-top', 'region-right', 'region-bottom'):
                self.assertEqual(fields[name]['type'], 'number')
                self.assertNotIn('readonly', fields[name])
            self.assertFalse(any(tag in ('video', 'iframe') for tag, _ in form.tags))
            self.assertIn('完整画面', response.text)
            self.assertIn('百分比', response.text)

    def test_withdrawn_youtube_urls_are_rejected_before_acquisition(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from drum_score import convert, ConversionError
        from drum_score.web import create_app
        urls = ('https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'https://youtu.be/dQw4w9WgXcQ',
                'https://www.youtube.com/shorts/dQw4w9WgXcQ')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with TestClient(create_app(root / 'service'), client=('192.0.2.10', 12345)) as client:
                for index, url in enumerate(urls):
                    with self.subTest(url=url):
                        output = root / ('result-' + str(index))
                        with patch('drum_score.public_video.acquire') as acquire:
                            with self.assertRaises(ConversionError) as error:
                                convert(url, output)
                            self.assertEqual(error.exception.code, 'invalid_bilibili_url')
                            acquire.assert_not_called()
                        self.assertFalse(output.exists())
                        process = subprocess.run([sys.executable, '-m', 'drum_score', url,
                            '--output', str(output)], capture_output=True, text=True, timeout=15)
                        self.assertNotEqual(process.returncode, 0)
                        self.assertEqual(json.loads(process.stdout)['error']['code'], 'invalid_bilibili_url')
                        self.assertFalse(output.exists())
                        response = client.post('/api/tasks', json={'url': url})
                        self.assertEqual(response.status_code, 422)
                        self.assertEqual(response.json()['error']['code'], 'invalid_bilibili_url')

    def test_http_temporary_layout_is_independent_complete_and_does_not_extend_expiry(self):
        import base64
        import hashlib
        from unittest.mock import patch
        import test_web_worker as web_fixture
        fixture = web_fixture.WebsiteWorker(methodName='runTest')
        fixture.setUp()
        try:
            # Full white lossless source has safe gaps; the general fixture's
            # dark paper border intentionally binds its three rows into one group.
            from PIL import Image, ImageDraw
            image = Image.new('RGB', (640, 900), 'white')
            draw = ImageDraw.Draw(image)
            for top in (70, 330, 590):
                for line in range(5):
                    draw.line((20, top + line * 8, 620, top + line * 8), fill='black')
            image.save(fixture.network / 'layout.png')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', str(fixture.network / 'layout.png'),
                '-t', '1', '-r', '2', '-c:v', 'ffv1', '-f', 'matroska', str(fixture.network / 'input.mp4')], check=True)
            created = fixture.client.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk'}).json()
            task = created['id']
            headers = {'Authorization': 'Bearer ' + created['capability']}
            self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
            before = fixture.state(task, headers)
            self.assertEqual(before['state'], 'complete', before)
            original = fixture.client.get('/api/tasks/' + task + '/pdf', headers=headers).content
            for paper, rows, count in [('A4', 1, 3), ('A3', 3, 1), ('A5', 2, 2)]:
                response = fixture.client.post('/api/tasks/' + task + '/layout', headers=headers,
                                               json={'paper': paper, 'rows': rows})
                self.assertEqual(response.status_code, 200, response.text[:300])
                result = response.json()
                self.assertEqual(result['page_count'], count)
                self.assertEqual(len(result['pages']), count)
                self.assertTrue(base64.b64decode(result['pdf']).startswith(b'%PDF'))
                self.assertTrue(all(base64.b64decode(page).startswith(b'\x89PNG') for page in result['pages']))
                from drum_score.jobs import Jobs
                record = next(record for record in Jobs(fixture.data).records.query(task=task)
                              if record['operation'] == 'layout')
                self.assertEqual(record['status'], 'complete')
                self.assertEqual(record['settings'], {'paper': paper, 'rows': rows})
                self.assertEqual(record['output']['pdf']['sha256'], hashlib.sha256(base64.b64decode(result['pdf'])).hexdigest())
                self.assertEqual(record['output']['page_count'], count)
            self.assertEqual(fixture.state(task, headers), before)
            self.assertEqual(hashlib.sha256(original).hexdigest(), before['result']['pdf']['sha256'])
            self.assertEqual(fixture.client.get('/api/tasks/' + task + '/pdf', headers=headers).content, original)
            self.assertEqual(fixture.client.post('/api/tasks/' + task + '/layout', json={}).status_code, 404)
            for settings in ({'paper': 'A0'}, {'rows': 0}, {'rows': True}, {'rows': 17}, {'direction': 'landscape'}):
                self.assertEqual(fixture.client.post('/api/tasks/' + task + '/layout', headers=headers, json=settings).status_code, 422)
            with patch('drum_score.jobs.time.time', return_value=before['expires_at'] + 1):
                self.assertEqual(fixture.client.post('/api/tasks/' + task + '/layout', headers=headers, json={}).status_code, 410)
        finally:
            fixture.tearDown()

    @unittest.skipUnless(sys.platform == 'linux', 'Real website worker and isolated metadata process')
    def test_description_rule_is_website_only_and_keeps_private_failure_record(self):
        import test_web_worker as web_fixture
        from bbdown_fixture import fixture_config
        from drum_score.jobs import Jobs
        fixture = web_fixture.WebsiteWorker(methodName='runTest')
        fixture.setUp()
        try:
            config = fixture_config()
            config['view'].update(bvid='BV1rH4y1R7Rk', desc='SYNTHETIC_DESCRIPTION ♥')
            (fixture.network / 'sitecustomize.py').write_text(
                'from pathlib import Path\nimport os,io\n'
                'from bbdown_fixture import configured_fake\n'
                'base=Path(os.environ["SYNTHETIC_NETWORK_ROOT"])\n'
                'def media(*args,**kwargs):\n'
                ' if args[0].full_url.startswith("https://b23.tv/"):\n'
                '  from urllib.error import HTTPError\n'
                '  raise HTTPError(args[0].full_url,302,"synthetic redirect",{"Location":"https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2"},None)\n'
                ' (base/"media-requested").touch()\n'
                ' return io.BytesIO((base/"input.mp4").read_bytes())\n'
                f'config={config!r}\n'
                'if (base/"allow-description").exists(): config["view"]["desc"]="synthetic ordinary description"\n'
                'fixture=configured_fake(base,config,response=media)\n'
                'fixture.__enter__()\n')
            fixture.env['PYTHONPATH'] += __import__('os').pathsep + str(Path(__file__).parent)
            task, auth = fixture.submit()
            self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
            state = fixture.state(task, auth)
            self.assertEqual(state['state'], 'failed', state)
            self.assertEqual(state['error']['message'], '该视频暂不支持整理。')
            self.assertFalse((fixture.network / 'media-requested').exists())
            record = Jobs(fixture.data).records.query(task=task)[0]
            self.assertEqual(record['error']['code'], 'description_policy_rejected')
            self.assertEqual(record['description_policy']['codepoints'], ['U+2665'])
            self.assertNotIn('SYNTHETIC_DESCRIPTION', json.dumps(record))
            # The same actual downloader in CLI has no website policy enabled.
            output = fixture.root / 'cli-result'
            cli = subprocess.run([sys.executable, '-m', 'drum_score',
                'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2', '--output', str(output)],
                env=fixture.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertTrue((fixture.network / 'media-requested').exists())
            # A later conversion failure must retain facts acquired through a
            # real synthetic short-link redirect and successful media download.
            (fixture.network / 'allow-description').touch()
            tools = fixture.network / 'failed-preview'
            tools.mkdir()
            (tools / 'pdftoppm').write_text('#!/bin/sh\nexit 2\n')
            (tools / 'pdftoppm').chmod(0o755)
            fixture.env['PATH'] = str(tools) + __import__('os').pathsep + fixture.env['PATH']
            created = fixture.client.post('/api/tasks', json={'url': 'https://b23.tv/Synthetic'}).json()
            self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
            record = Jobs(fixture.data).records.query(task=created['id'])[0]
            self.assertEqual(record['status'], 'failed')
            self.assertEqual(record['input']['resolved_url'], 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2')
            self.assertTrue(record['description_policy']['valid_description'])
            self.assertFalse(record['description_policy']['matched'])
        finally:
            fixture.tearDown()

    @unittest.skipUnless(sys.platform == 'linux', 'Ubuntu operator and HTTP contract')
    def test_operator_pause_blocks_only_admission_and_persists_across_http_restart(self):
        import os
        import tempfile
        from fastapi.testclient import TestClient
        from drum_score.web import create_app
        from drum_score.jobs import Jobs
        link = 'https://www.bilibili.com/video/BV1rH4y1R7Rk'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'service'
            app = create_app(root)
            with TestClient(app, client=('192.0.2.1', 2000)) as client:
                task = client.post('/api/tasks', json={'url': link}).json()
                auth = {'Authorization': 'Bearer ' + task['capability']}
                with TestClient(app, client=('192.0.2.3', 2000)) as other:
                    retryable = other.post('/api/tasks', json={'url': link}).json()
                    retry_auth = {'Authorization': 'Bearer ' + retryable['capability']}
                    other.post('/api/tasks/' + retryable['id'] + '/cancel', headers=retry_auth)
                args = [sys.executable, '-m', 'drum_score.maintenance', 'pause-submissions', '--data-root', str(root)]
                env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
                paused = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(paused.returncode, 0, paused.stdout + paused.stderr)
                self.assertTrue(json.loads(paused.stdout)['paused'])
                # Pausing admission does not stop the existing queue being claimed.
                self.assertEqual(Jobs(root).claim()['id'], task['id'])
                self.assertEqual(client.get('/api/tasks/' + task['id'], headers=auth).status_code, 200)
                self.assertEqual(client.post('/api/tasks/' + task['id'] + '/cancel', headers=auth).status_code, 200)
            with TestClient(create_app(root), client=('192.0.2.2', 2000)) as client:
                blocked = client.post('/api/tasks', json={'url': link})
                self.assertEqual(blocked.status_code, 503)
                self.assertEqual(blocked.json()['error']['code'], 'submissions_paused')
                retry = client.post('/api/tasks/' + retryable['id'] + '/retry', headers=retry_auth)
                self.assertEqual(retry.status_code, 503)
                self.assertEqual(retry.json()['error']['code'], 'submissions_paused')
                denied = client.post('/api/tasks/' + retryable['id'] + '/retry',
                    headers={'Authorization': 'Bearer synthetic-wrong'})
                self.assertEqual(denied.status_code, 404)
                args[3] = 'resume-submissions'
                resumed = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                self.assertFalse(json.loads(resumed.stdout)['paused'])
                self.assertEqual(client.post('/api/tasks', json={'url': link}).status_code, 201)

    @unittest.skipUnless(sys.platform == 'linux', 'Executable decoder and HTTP worker fixture')
    def test_total_deadline_still_stops_continuous_decoder_in_each_entry(self):
        import os
        import tempfile
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from drum_score import convert, ConversionError
        from drum_score.web import create_app
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'SYNTHETIC_MEDIA_FOR_STALLED_DECODER')
            tools, startup = root / 'tools', root / 'startup'
            tools.mkdir()
            startup.mkdir()
            (startup / 'sitecustomize.py').write_text(
                'from pathlib import Path\nimport os,shutil\nfrom drum_score import anonymous_backend\n'
                'def download(origin,target):\n'
                ' shutil.copyfile(os.environ["SYNTHETIC_DECODER_SOURCE"],target/"video.mp4")\n'
                ' return {"title":"Synthetic deadline fixture","authenticated":False}\n'
                'anonymous_backend.download=download\n'
                'def inspect_source(origin,target):\n return {"origin":origin,"info":{"formats":[],"duration":1.0},"backend_details":{"cid":1}}\n'
                'anonymous_backend.inspect_source=inspect_source\n')
            for name, body in {
                'ffprobe': 'import json\nprint(json.dumps({"streams":[{"width":640,"height":520,"avg_frame_rate":"1/1"}],"format":{"duration":"1"}}))\n',
                'ffmpeg': 'import os,sys,time\nfrom pathlib import Path\n'
                    'if "-h" in sys.argv:\n print("-fps_mode mode");sys.exit(0)\n'
                    'Path(os.environ["SYNTHETIC_DECODER_MARKER"]).write_text(str(os.getpid()))\n'
                    'time.sleep(30)\n',
            }.items():
                executable = tools / name
                executable.write_text('#!' + sys.executable + '\n' + body)
                executable.chmod(0o755)
            for entry in REMOTE_SCRIPT_ENTRIES:
                with self.subTest(entry=entry):
                    marker, output = root / (entry + '-decoder'), root / (entry + '-result')
                    env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                        'PYTHONPATH': os.pathsep.join(map(str, (startup, repository / 'src'))),
                        'SYNTHETIC_DECODER_MARKER': str(marker), 'SYNTHETIC_DECODER_SOURCE': str(source)}
                    if entry == 'script_core':
                        with patch.dict(os.environ, env):
                            with self.assertRaises(ConversionError) as caught:
                                convert(source, output, limits={'wall_seconds': 2})
                        code = caught.exception.code
                    elif entry == 'script_cli':
                        process = subprocess.run([sys.executable, '-m', 'drum_score', str(source),
                            '--output', str(output), '--timeout', '2'], env=env,
                            capture_output=True, text=True, timeout=15)
                        self.assertEqual(process.returncode, 2, process.stderr)
                        code = json.loads(process.stdout)['error']['code']
                    else:
                        service = root / 'service'
                        with TestClient(create_app(service), client=('192.0.2.10', 2000)) as client:
                            task = client.post('/api/tasks', json={'url': 'https://www.bilibili.com/video/BV1rH4y1R7Rk'}).json()
                            headers = {'Authorization': 'Bearer ' + task['capability']}
                            process = subprocess.run([sys.executable, '-m', 'drum_score.worker',
                                '--data-root', str(service), '--once', '--timeout', '2'],
                                env=env, capture_output=True, text=True, timeout=15)
                            self.assertEqual(process.returncode, 0, process.stderr)
                            state = client.get('/api/tasks/' + task['id'], headers=headers).json()
                            self.assertEqual(state['state'], 'failed', state)
                            code = state['error']['code']
                            self.assertNotEqual(client.get('/api/tasks/' + task['id'] + '/pdf', headers=headers).status_code, 200)
                    self.assertEqual(code, 'resource_limit')
                    self.assertTrue(marker.exists(), 'Must actually enter continuous decoding')
                    pid = int(marker.read_text())
                    state = Path('/proc') / str(pid) / 'stat'
                    self.assertTrue(not state.exists() or state.read_text().split(') ')[1].startswith('Z'))
                    self.assertFalse(output.exists())
                    self.assertEqual(list(root.rglob('.drum-score-job-*')), [])
            self.assertEqual(source.read_bytes(), b'SYNTHETIC_MEDIA_FOR_STALLED_DECODER')

    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux remote worker contract')
    def test_remote_entries_require_pinned_bbdown_without_changing_existing_files(self):
        import os
        import tempfile
        import shutil
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from drum_score import convert, ConversionError
        from drum_score.web import create_app
        repository = Path(__file__).resolve().parents[1]
        url = 'https://www.bilibili.com/video/BV1np421S78S?p=1'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / 'existing-user-video'
            sentinel.write_bytes(b'SYNTHETIC_EXISTING_CONTENT')
            startup = root / 'startup'
            startup.mkdir()
            (startup / 'sitecustomize.py').write_text(
                "import shutil\noriginal=shutil.which\n"
                "def which(name,*a,**k):\n"
                " return None if name=='BBDown' else original(name,*a,**k)\n"
                "shutil.which=which\n")
            env = {**os.environ, 'PYTHONPATH': os.pathsep.join(map(str, (startup, repository / 'src')))}
            original = shutil.which
            for entry in REMOTE_SCRIPT_ENTRIES:
                output = root / entry
                with self.subTest(entry=entry):
                    if entry == 'script_core':
                        with patch('shutil.which', side_effect=lambda name, *a, **k:
                                   None if name == 'BBDown' else original(name, *a, **k)):
                            with self.assertRaises(ConversionError) as caught:
                                convert(url, output)
                        code = caught.exception.code
                    elif entry == 'script_cli':
                        process = subprocess.run([sys.executable, '-m', 'drum_score', url,
                            '--output', str(output)], env=env, capture_output=True, text=True, timeout=15)
                        self.assertEqual(process.returncode, 2, process.stderr)
                        code = json.loads(process.stdout)['error']['code']
                    else:
                        service = root / 'service'
                        with TestClient(create_app(service), client=('192.0.2.10', 2000)) as client:
                            task = client.post('/api/tasks', json={'url': url}).json()
                            headers = {'Authorization': 'Bearer ' + task['capability']}
                            process = subprocess.run([sys.executable, '-m', 'drum_score.worker',
                                '--data-root', str(service), '--once'], env=env,
                                capture_output=True, text=True, timeout=15)
                            self.assertEqual(process.returncode, 0, process.stderr)
                            state = client.get('/api/tasks/' + task['id'], headers=headers).json()
                            self.assertEqual(state['state'], 'failed', state)
                            code = state['error']['code']
                            self.assertNotEqual(client.get('/api/tasks/' + task['id'] + '/pdf',
                                                           headers=headers).status_code, 200)
                    self.assertEqual(code, 'dependency_missing')
                    self.assertFalse(output.exists())
                    self.assertEqual(sentinel.read_bytes(), b'SYNTHETIC_EXISTING_CONTENT')
            self.assertEqual(list(root.rglob('.drum-score-*')), [])

    def test_public_cli_parsers_do_not_echo_invalid_arguments_or_private_payload(self):
        import os
        import importlib.util
        modules = ['drum_score']
        if sys.platform == 'linux':
            modules.extend(f'drum_score.maintenance:{operation}' for operation in MAINTENANCE_ENTRIES)
        if sys.platform == 'linux' and importlib.util.find_spec('fastapi'):
            modules.extend(('drum_score.web', 'drum_score.worker'))
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'operator-note').write_bytes(b'existing user file')
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            for module in modules:
                with self.subTest(module=module):
                    arguments = [str(root / 'operator-note'), '--output', str(root / 'output')] if module == 'drum_score' else ['--data-root', str(root)]
                    if ':' in module:
                        module, operation = module.split(':')
                        arguments = [operation, *arguments]
                    process = subprocess.run([sys.executable, '-m', module, *arguments, '--operation',
                        'stage', '--unknown', 'SYNTHETIC_PRIVATE_PAYLOAD'],
                        env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)},
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(process.returncode, 2)
                    self.assertEqual(json.loads(process.stdout)['error']['code'], 'invalid_request')
                    for marker in ('SYNTHETIC_PRIVATE_PAYLOAD', str(root), 'Traceback'):
                        self.assertNotIn(marker, process.stdout + process.stderr)
                    self.assertEqual({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}, before)
            if 'drum_score.web' in modules:
                from fastapi.testclient import TestClient
                from drum_score.web import create_app
                with TestClient(create_app(root / 'service'), client=('192.0.2.10', 12345)) as client:
                    def snapshot():
                        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in root.rglob('*') if p.is_file()}
                    before = snapshot()
                    self.assertEqual(client.post('/api/tasks/unknown/stage', json={'payload': 'SYNTHETIC_PRIVATE_PAYLOAD'}).status_code, 404)
                    self.assertEqual(client.patch('/api/tasks', json={'payload': 'SYNTHETIC_PRIVATE_PAYLOAD'}).status_code, 405)
                    self.assertEqual(snapshot(), before)

    @unittest.skipUnless(sys.platform == 'linux', 'Executable fixture for native preview failure')
    def test_entries_do_not_publish_pdf_when_page_preview_tool_fails(self):
        import os
        import tempfile
        from unittest.mock import patch
        from score_fixtures import score_frame, video_from_image
        from drum_score import convert, ConversionError
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root)
            before = source.read_bytes()
            tools = root / 'tools'
            tools.mkdir()
            tool = tools / 'pdftoppm'
            tool.write_text(f'#!{sys.executable}\nimport sys\nsys.stderr.write("SYNTHETIC_PRIVATE_PREVIEW /private/synthetic")\nsys.exit(1)\n')
            tool.chmod(0o755)
            with patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}):
                for entry in SCRIPT_CONVERSION_ENTRIES:
                    with self.subTest(entry=entry):
                        output = root / entry
                        if entry == 'script_core':
                            with self.assertRaises(ConversionError) as caught:
                                convert(source, output)
                            code, diagnostic = caught.exception.code, str(caught.exception)
                        else:
                            process = subprocess.run([sys.executable, '-m', 'drum_score', str(source), '--output', str(output)],
                                capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}, timeout=20)
                            self.assertEqual(process.returncode, 2)
                            code, diagnostic = json.loads(process.stdout)['error']['code'], process.stdout + process.stderr
                        self.assertEqual(code, 'preview_failed')
                        self.assertNotIn('SYNTHETIC_PRIVATE_PREVIEW', diagnostic)
                        self.assertFalse(output.exists())
                        self.assertEqual(source.read_bytes(), before)
                        self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_remote_script_matrix_refuses_nonpublic_targets_without_publication(self):
        from pathlib import Path
        import tempfile
        import os
        if not Path('/proc').is_dir():
            self.skipTest('Linux website contract')
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest('Install tests/requirements-web.txt for website matrix')
        from drum_score.web import create_app
        from drum_score import ConversionError, convert
        source = 'https://127.0.0.1/video/BV1rH4y1R7Rk'
        repository = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join(map(str, (repository / 'src',)))}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for entry in REMOTE_SCRIPT_ENTRIES:
                with self.subTest(entry=entry):
                    output = root / entry
                    if entry == 'script_core':
                        with self.assertRaises(ConversionError) as caught:
                            convert(source, output)
                        code = caught.exception.code
                    elif entry == 'script_cli':
                        process = subprocess.run([sys.executable, '-m', 'drum_score', source, '--output', str(output)],
                            env=env, capture_output=True, text=True, timeout=10)
                        self.assertEqual(process.returncode, 2)
                        code = json.loads(process.stdout)['error']['code']
                    else:
                        with TestClient(create_app(root / 'service'), client=('192.0.2.1', 2000)) as client:
                            response = client.post('/api/tasks', json={'url': source})
                            self.assertEqual(response.status_code, 422)
                            code = response.json()['error']['code']
                    self.assertEqual(code, 'invalid_bilibili_url')
                    self.assertFalse(output.exists())
            self.assertEqual(list(root.rglob('.drum-score-*')), [])

    def test_remote_script_matrix_preserves_source_pages_and_honest_completion(self):
        self.check_remote_completion(short=False)

    def test_remote_entries_expand_short_links_without_losing_page_or_source(self):
        self.check_remote_completion(short=True)

    def check_remote_completion(self, *, short):
        from pathlib import Path
        import hashlib
        if not (Path('/proc').is_dir()):
            self.skipTest('Linux website process lifecycle contract')
        # Optional web dependencies are mandatory in the Linux offline CI job.
        import test_web_worker as web_fixture
        fixture = web_fixture.WebsiteWorker(methodName='runTest')
        fixture.setUp()
        try:
            runner = fixture.network / 'invoke-core.py'
            runner.write_text("import json,sys\nfrom drum_score import convert\nif __name__ == '__main__':\n    print(json.dumps(convert(sys.argv[1],sys.argv[2])))\n")
            # Keep the actual BBDown adapter and parser in all public entries.
            # Replace only the external executable identity and media transport.
            from bbdown_fixture import fixture_config, install_fake_bbdown
            config = fixture_config(invocations=str(fixture.network / 'bbdown-invocations'))
            config['view']['bvid'] = 'BV1rH4y1R7Rk'
            binary, digest = install_fake_bbdown(fixture.network, config)
            (fixture.network / 'sitecustomize.py').write_text(
                "import io,os,socket\nfrom pathlib import Path\nfrom urllib.error import HTTPError\n"
                "from drum_score import bbdown_cli\n"
                "bbdown_cli.METADATA_SHA256=" + repr(digest) + "\n"
                "os.environ['PATH']=" + repr(str(binary.parent)) + "+os.pathsep+os.environ['PATH']\n"
                "socket.getaddrinfo=lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]\n"
                "import urllib.request\n"
                "def open_response(self,request,*a,**k):\n"
                " if request.full_url.startswith('https://b23.tv/'):\n"
                "  raise HTTPError(request.full_url,302,'Found',{'Location':'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2'},io.BytesIO())\n"
                " return io.BytesIO(Path(" + repr(str(fixture.network / 'input.mp4')) + ").read_bytes())\n"
                "urllib.request.OpenerDirector.open=open_response\n")
            source_hash = hashlib.sha256((fixture.network / 'input.mp4').read_bytes()).hexdigest()
            link = 'https://b23.tv/Synthetic7' if short else 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2'
            for entry in REMOTE_SCRIPT_ENTRIES:
                with self.subTest(entry=entry):
                    if entry == 'script_http':
                        created = fixture.client.post('/api/tasks', json={'url': link}).json()
                        task, auth = created['id'], {'Authorization': 'Bearer ' + created['capability']}
                        self.assertEqual(fixture.worker(once=True).wait(timeout=30), 0)
                        view = fixture.state(task, auth)
                        self.assertEqual(view['state'], 'complete', view)
                        result = view['result']
                        pdf = fixture.client.get(f'/api/tasks/{task}/pdf', headers=auth).content
                        for page in range(1, len(result['pages']) + 1):
                            response = fixture.client.get(f'/api/tasks/{task}/pages/{page}', headers=auth)
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(hashlib.sha256(response.content).hexdigest(), result['pages'][page-1]['sha256'])
                    else:
                        output = fixture.root / entry
                        args = [sys.executable, str(runner)] if entry == 'script_core' else [sys.executable, '-m', 'drum_score']
                        args += [link, str(output)] if entry == 'script_core' else [link, '--output', str(output)]
                        process = subprocess.run(args, env=fixture.env, capture_output=True, text=True, timeout=30)
                        self.assertEqual(process.returncode, 0, process.stderr)
                        result = json.loads(process.stdout)
                        pdf = (output / result['pdf']['path']).read_bytes()
                        self.assertEqual(json.loads((output / 'manifest.json').read_text()), result)
                    self.assertEqual(result['status'], 'complete')
                    self.assertFalse(result['reliable'])
                    self.assertEqual(result['source']['bvid'], 'BV1rH4y1R7Rk')
                    self.assertEqual(result['source']['page'], 2)
                    self.assertEqual(result['source']['sha256'], source_hash)
                    self.assertFalse(result['source']['authenticated'])
                    self.assertEqual(result['source']['backend'], 'BBDownNext')
                    self.assertEqual(result['source']['backend_version'], '2.3.0')
                    self.assertEqual(result['source']['backend_build'], 'metadata-bounded.1')
                    self.assertEqual(result['source']['backend_sha256'], digest)
                    self.assertEqual(result['source']['acquisition_route'], 'bbdown_direct')
                    self.assertEqual(result['source']['cid'], 22)
                    self.assertEqual(result['source']['full_duration'], 2)
                    self.assertEqual(hashlib.sha256(pdf).hexdigest(), result['pdf']['sha256'])
                    self.assertTrue(result['pages'])
                    self.assertIn('not_musically_proofread', {warning['code'] for warning in result['warnings']})
                    self.assertEqual(list(fixture.root.rglob('.drum-score-*')), [])
            self.assertEqual((fixture.network / 'bbdown-invocations').read_text().splitlines(), ['inspect'] * (len(REMOTE_SCRIPT_ENTRIES) + 1))
            self.assertEqual(hashlib.sha256((fixture.network / 'input.mp4').read_bytes()).hexdigest(), source_hash)
        finally:
            fixture.tearDown()

    def test_script_entries_keep_complete_result_when_temporary_cleanup_fails(self):
        from pathlib import Path
        import tempfile
        import shutil
        import contextlib
        import io
        from unittest.mock import patch
        from score_fixtures import score_frame, video_from_image
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root)
            remove_tree = shutil.rmtree
            def fail_after_removal(*args, **kwargs):
                remove_tree(*args, **kwargs)
                raise OSError('SYNTHETIC_PRIVATE_CLEANUP /private/synthetic')
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry), patch('shutil.rmtree', side_effect=fail_after_removal):
                    output = root / entry
                    if entry == 'script_core':
                        result = drum_score.convert(source, output)
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            self.assertEqual(main([str(source), '--output', str(output)]), 0)
                        result = json.loads(stream.getvalue())
                    self.assertEqual(result['status'], 'complete')
                    self.assertEqual(json.loads((output / 'manifest.json').read_text()), result)
                    self.assertTrue((output / result['pdf']['path']).is_file())
                    self.assertNotIn('SYNTHETIC_PRIVATE_CLEANUP', json.dumps(result))
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_normalize_temporary_allocation_errors(self):
        from pathlib import Path
        import tempfile
        import contextlib
        import io
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'synthetic source unchanged by allocation failure')
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry), patch('tempfile.mkdtemp',
                        side_effect=OSError('SYNTHETIC_PRIVATE_ALLOCATION /private/synthetic')):
                    output = root / entry
                    if entry == 'script_core':
                        with self.assertRaises(drum_score.ConversionError) as caught:
                            drum_score.convert(source, output)
                        code = caught.exception.code
                        diagnostic = str(caught.exception)
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            self.assertEqual(main([str(source), '--output', str(output)]), 2)
                        code = json.loads(stream.getvalue())['error']['code']
                        diagnostic = stream.getvalue()
                    self.assertEqual(code, 'conversion_failed')
                    self.assertNotIn('SYNTHETIC_PRIVATE_ALLOCATION', diagnostic)
                    self.assertNotIn('/private/synthetic', diagnostic)
                    self.assertFalse(output.exists())
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_preserve_specific_error_when_temporary_cleanup_fails(self):
        from pathlib import Path
        import tempfile
        import shutil
        import contextlib
        import io
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'invalid-video.mp4'
            source.write_bytes(b'synthetic invalid video')
            remove_tree = shutil.rmtree
            def fail_after_removal(*args, **kwargs):
                remove_tree(*args, **kwargs)
                raise OSError('SYNTHETIC_PRIVATE_CLEANUP /private/synthetic')
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry), patch('shutil.rmtree', side_effect=fail_after_removal):
                    output = root / entry
                    if entry == 'script_core':
                        with self.assertRaises(drum_score.ConversionError) as caught:
                            drum_score.convert(source, output)
                        code = caught.exception.code
                        diagnostic = str(caught.exception)
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            self.assertEqual(main([str(source), '--output', str(output)]), 2)
                        result = json.loads(stream.getvalue())
                        code = result['error']['code']
                        diagnostic = stream.getvalue()
                    self.assertEqual(code, 'invalid_input')
                    self.assertNotIn('SYNTHETIC_PRIVATE_CLEANUP', diagnostic)
                    self.assertNotIn(str(root), diagnostic)
                    self.assertFalse(output.exists())
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_normalize_output_parent_filesystem_errors(self):
        from pathlib import Path
        import tempfile
        import os
        from score_fixtures import score_frame, video_from_image
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root, name='private-source')
            before = source.read_bytes()
            output = source / 'result'
            for entry in SCRIPT_CONVERSION_ENTRIES:
                with self.subTest(entry=entry):
                    if entry == 'script_core':
                        with self.assertRaises(drum_score.ConversionError) as caught:
                            drum_score.convert(source, output)
                        code = caught.exception.code
                        diagnostic = str(caught.exception)
                    else:
                        process = subprocess.run([sys.executable, '-m', 'drum_score',
                            str(source), '--output', str(output)], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)})
                        self.assertEqual(process.returncode, 2, process.stderr)
                        result = json.loads(process.stdout)
                        self.assertEqual(result['status'], 'failed')
                        code = result['error']['code']
                        diagnostic = process.stdout + process.stderr
                    self.assertEqual(code, 'conversion_failed')
                    self.assertNotIn(str(root), diagnostic)
                    self.assertNotIn('private-source', diagnostic)
                    self.assertNotIn('Traceback', diagnostic)
                    self.assertEqual(source.read_bytes(), before)
                    self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_apply_input_resource_limit_before_decoding(self):
        from pathlib import Path
        import tempfile
        import contextlib
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        for entry in SCRIPT_CONVERSION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'source.mp4'
                source.write_bytes(b'x' * 2048)
                output = root / 'result'
                if entry == 'script_core':
                    with self.assertRaises(drum_score.ConversionError) as caught:
                        drum_score.convert(source, output, limits={'input_bytes': 1024})
                    code = caught.exception.code
                else:
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        self.assertEqual(main([str(source), '--output', str(output),
                                               '--max-input-mib', str(1/1024)]), 2)
                    code = json.loads(stream.getvalue())['error']['code']
                self.assertEqual(code, 'resource_limit')
                self.assertFalse(output.exists())
                self.assertEqual(source.read_bytes(), b'x' * 2048)
                self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_script_entries_reject_existing_paths_and_invalid_source(self):
        from pathlib import Path
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        import contextlib
        import io
        for entry in SCRIPT_CONVERSION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'source.mp4'
                source.write_bytes(b'invalid video')
                output = root / 'result'
                def invoke():
                    if entry == 'script_core':
                        try:
                            return drum_score.convert(source, output)
                        except drum_score.ConversionError as error:
                            return {'error': {'code': error.code}}
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        self.assertEqual(main([str(source), '--output', str(output)]), 2)
                    return json.loads(stream.getvalue())
                self.assertEqual(invoke()['error']['code'], 'invalid_input')
                self.assertFalse(output.exists())
                output.mkdir()
                (output / 'mine').write_bytes(b'keep')
                self.assertEqual(invoke()['error']['code'], 'output_exists')
                self.assertEqual((output / 'mine').read_bytes(), b'keep')
                self.assertEqual(source.read_bytes(), b'invalid video')


    def test_script_entries_publish_all_pages_or_no_result_for_black_input(self):
        from pathlib import Path
        import tempfile
        import contextlib
        import io
        from PIL import Image
        from score_fixtures import score_frame, video_from_image
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        import drum_score
        from drum_score.cli import main
        for entry in SCRIPT_CONVERSION_ENTRIES:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for black in (False, True):
                    source = video_from_image(Image.new('RGB', (640, 520), 'black') if black
                                              else score_frame(), root, name=f'input-{black}')
                    before = source.read_bytes()
                    output = root / f'result-{black}'
                    if entry == 'script_core':
                        try:
                            result = drum_score.convert(source, output)
                        except drum_score.ConversionError as error:
                            result = {'status': 'failed', 'error': {'code': error.code}}
                    else:
                        stream = io.StringIO()
                        with contextlib.redirect_stdout(stream):
                            status = main([str(source), '--output', str(output)])
                        self.assertEqual(status, 2 if black else 0)
                        result = json.loads(stream.getvalue())
                    self.assertEqual(source.read_bytes(), before)
                    if black:
                        self.assertEqual(result['status'], 'failed')
                        self.assertEqual(result['error']['code'], 'unsupported_layout')
                        self.assertFalse(output.exists())
                    else:
                        self.assertEqual(result['status'], 'complete')
                        self.assertFalse(result['reliable'])
                        self.assertTrue(result['warnings'])
                        self.assertGreater(len(result['pages']), 0)
                        self.assertTrue((output / result['pdf']['path']).is_file())
                        for page in result['pages']:
                            self.assertTrue((output / page['path']).is_file())


@unittest.skipUnless(sys.platform == 'linux', 'Linux maintenance contract')
class MaintenancePublicContracts(unittest.TestCase):
    def test_offline_entries_share_readonly_refusal_and_resource_contracts(self):
        import os
        import tempfile
        import hashlib
        import sqlite3
        from drum_score.jobs import Jobs
        from drum_score.maintenance import backup
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'service'
            Jobs(data)
            saved = root / 'backup'
            backup(data, saved, services_stopped=True, min_free_bytes=1)
            env = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}
            for boundary in ('symlink', 'limit', 'schema'):
                for operation in MAINTENANCE_ENTRIES:
                    with self.subTest(boundary=boundary, operation=operation):
                        source = data if operation == 'backup' else saved
                        args = ['--data-root', str(source), '--services-stopped'] if operation == 'backup' else ['--backup-root', str(source)]
                        output = root / (boundary + '-' + operation)
                        if operation != 'verify':
                            args += ['--output', str(output)]
                        if boundary == 'symlink':
                            link = root / (operation + '-link')
                            link.symlink_to(source, target_is_directory=True)
                            args[1] = str(link)
                        elif boundary == 'limit':
                            args += ['--max-mib', '.001']
                        else:
                            with sqlite3.connect(source / 'tasks.sqlite3') as db:
                                db.execute('PRAGMA user_version=999')
                        before = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
                        result = subprocess.run([sys.executable, '-m', 'drum_score.maintenance', operation, *args, '--min-free-mib', '1'], env=env, capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, 2, result.stdout)
                        self.assertEqual(json.loads(result.stdout)['status'], 'failed')
                        self.assertNotIn(str(root), result.stdout + result.stderr)
                        self.assertFalse(output.exists())
                        self.assertEqual({p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}, before)
                        if boundary == 'schema':
                            with sqlite3.connect(source / 'tasks.sqlite3') as db:
                                from drum_score.schema import SCHEMA_VERSION
                                db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')


    def test_explicit_legacy_upgrade_copies_verified_snapshot_and_keeps_source_unchanged(self):
        import hashlib
        import os
        import sqlite3
        import tempfile
        from drum_score.jobs import Jobs
        from drum_score.maintenance import backup
        from drum_score.schema import V1_STATEMENTS, SCHEMA_VERSION
        for source_version in (1, 2, 3, 4):
            with self.subTest(source_version=source_version):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    jobs = Jobs(root / 'service', min_free_bytes=1)
                    task = jobs.enqueue('https://www.bilibili.com/video/BV1rH4y1R7Rk', '192.0.2.1')
                    from drum_score.core import artifact
                    from drum_score.worker import validate_result
                    row = jobs.claim()
                    result = jobs.register_attempt(row) / 'result'
                    result.mkdir()
                    (result / 'score.pdf').write_bytes(b'%PDF-synthetic-upgrade')
                    for index in range(1, 3):
                        (result / f'page-{index}.png').write_bytes(b'synthetic-page-' + bytes([index]))
                    delivery = dict(status='complete', reliable=False, warnings=[],
                                    pdf=artifact(result, result / 'score.pdf'),
                                    pages=[artifact(result, result / f'page-{index}.png') for index in range(1, 3)],
                                    source={}, program={}, resources={},
                                    retention={'can_reconstruct_from_retained_sources': False})
                    (result / 'manifest.json').write_text(json.dumps(delivery))
                    jobs.remember_result(row, delivery)
                    jobs.finishing(row, validate_result(jobs, row))
                    jobs.settle(row, 'complete')
                    queued = jobs.enqueue('https://www.bilibili.com/video/BV1rH4y1R7Rk', '192.0.2.2')
                    queued_before = jobs.view(queued['id'], queued['capability'])
                    expected = jobs.view(task['id'], task['capability'])
                    saved = root / 'snapshot'
                    backup(jobs.root, saved, services_stopped=True, min_free_bytes=1)
                    with sqlite3.connect(saved / 'tasks.sqlite3') as db:
                        db.execute('DROP TABLE processing_records')
                        if source_version < 4:
                            db.execute('ALTER TABLE tasks DROP COLUMN options')
                            db.execute('DROP TABLE video_cache')
                        if source_version < 3:
                            db.execute('DROP TABLE submission_events')
                            db.execute('DROP TABLE submission_control')
                            db.execute('DROP INDEX task_expiry')
                        if source_version == 1:
                            db.execute(V1_STATEMENTS[-1])
                        db.execute(f'PRAGMA user_version={source_version}')
                    manifest = json.loads((saved / 'snapshot.json').read_text())
                    manifest['schema'] = source_version
                    entry = next(item for item in manifest['files'] if item['path'] == 'tasks.sqlite3')
                    entry.update(bytes=(saved / 'tasks.sqlite3').stat().st_size,
                                 sha256=hashlib.sha256((saved / 'tasks.sqlite3').read_bytes()).hexdigest())
                    (saved / 'snapshot.json').write_text(json.dumps(manifest))
                    before = {p.relative_to(saved).as_posix(): p.read_bytes() for p in saved.rglob('*') if p.is_file()}
                    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}
                    output = root / 'upgraded'
                    args = [sys.executable, '-m', 'drum_score.maintenance', f'upgrade-v{source_version}',
                            '--backup-root', str(saved), '--output', str(output), '--min-free-mib', '1']
                    response = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
                    self.assertEqual(json.loads(response.stdout)['schema'], SCHEMA_VERSION)
                    self.assertEqual(Jobs(output).view(task['id'], task['capability']), expected)
                    self.assertEqual({p.relative_to(saved).as_posix(): p.read_bytes() for p in saved.rglob('*') if p.is_file()}, before)
                    second = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(second.returncode, 2)
                    self.assertNotIn(str(root), second.stdout + second.stderr)
                    self.assertEqual(Jobs(output).view(task['id'], task['capability']), expected)
                    recovered = Jobs(output)
                    self.assertEqual(recovered.view(queued['id'], queued['capability']), queued_before)
                    for index, reference in enumerate(delivery['pages'], 1):
                        fd, _ = recovered.open_artifact(task['id'], task['capability'], index)
                        with os.fdopen(fd, 'rb') as stream:
                            self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), reference['sha256'])
                    restored_result = output / result.relative_to(jobs.root)
                    self.assertNotEqual((restored_result / 'score.pdf').stat().st_ino, (result / 'score.pdf').stat().st_ino)
                    from unittest.mock import patch
                    with patch('drum_score.jobs.time.time', return_value=expected['expires_at'] + 1):
                        recovered.cleanup()
                    self.assertFalse(restored_result.exists())
                    self.assertTrue((result / 'score.pdf').exists())
                    # A hash-matching but unknown old schema cannot be upgraded.
                    with sqlite3.connect(saved / 'tasks.sqlite3') as db:
                        db.execute('CREATE TABLE unknown(value TEXT)')
                    entry.update(bytes=(saved / 'tasks.sqlite3').stat().st_size,
                                 sha256=hashlib.sha256((saved / 'tasks.sqlite3').read_bytes()).hexdigest())
                    (saved / 'snapshot.json').write_text(json.dumps(manifest))
                    args[args.index('--output') + 1] = str(root / 'refused')
                    response = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(response.returncode, 2)
                    self.assertFalse((root / 'refused').exists())

    def test_maintenance_entries_preserve_ten_page_names_and_refuse_invalid_sequences(self):
        import hashlib
        import os
        import shutil
        import sqlite3
        import tempfile
        from reportlab.pdfgen import canvas
        from drum_score.core import artifact
        from drum_score.jobs import Jobs
        from drum_score.worker import validate_result
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = Jobs(root / 'service', min_free_bytes=1)
            task = jobs.enqueue('https://www.bilibili.com/video/BV1rH4y1R7Rk', '192.0.2.1')
            row = jobs.claim()
            result = jobs.register_attempt(row) / 'result'
            result.mkdir()
            document = canvas.Canvas(str(result / 'score.pdf'), invariant=1)
            for page in range(10):
                document.drawString(10, 10, str(page + 1))
                document.showPage()
            document.save()
            subprocess.run(['pdftoppm', '-png', '-scale-to', '16', str(result / 'score.pdf'), str(result / 'page')], check=True, capture_output=True, timeout=10)
            pages = sorted(result.glob('page-*.png'))
            self.assertEqual([p.name for p in pages], [f'page-{i:02d}.png' for i in range(1, 11)])
            manifest = dict(status='complete', reliable=False, warnings=[], pdf=artifact(result, result / 'score.pdf'), pages=[artifact(result, p) for p in pages], source={}, program={}, resources={}, retention={'can_reconstruct_from_retained_sources': False})
            (result / 'manifest.json').write_text(json.dumps(manifest))
            jobs.remember_result(row, manifest)
            jobs.finishing(row, validate_result(jobs, row))
            jobs.settle(row, 'complete')
            expected = jobs.view(task['id'], task['capability'])
            env = {**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}
            def invoke(operation, source, output=None):
                args = ['--data-root', str(source), '--services-stopped'] if operation == 'backup' else ['--backup-root', str(source)]
                if output is not None:
                    args += ['--output', str(output)]
                return subprocess.run([sys.executable, '-m', 'drum_score.maintenance', operation, *args, '--min-free-mib', '1'], env=env, capture_output=True, text=True, timeout=10)
            saved, restored = root / 'backup', root / 'restored'
            for operation, source, output in [('backup', jobs.root, saved), ('verify', saved, None), ('restore', saved, restored)]:
                response = invoke(operation, source, output)
                self.assertEqual(response.returncode, 0, response.stdout)
            recovered = Jobs(restored)
            self.assertEqual(recovered.view(task['id'], task['capability']), expected)
            self.assertEqual([ref['path'] for ref in expected['result']['pages']], [p.name for p in pages])
            for index, ref in enumerate(manifest['pages'], 1):
                fd, _ = recovered.open_artifact(task['id'], task['capability'], index)
                with os.fdopen(fd, 'rb') as stream:
                    self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), ref['sha256'])
            relative = result.relative_to(jobs.root)
            for variant in ('duplicate', 'wrong-index', 'traversal', 'extra'):
                with self.subTest(variant=variant):
                    changed = root / variant
                    shutil.copytree(saved, changed)
                    changed_manifest = changed / relative / 'manifest.json'
                    value = json.loads(changed_manifest.read_text())
                    if variant == 'duplicate':
                        value['pages'][1] = dict(value['pages'][0])
                    elif variant == 'wrong-index':
                        value['pages'][0], value['pages'][1] = value['pages'][1], value['pages'][0]
                    elif variant == 'traversal':
                        value['pages'][0]['path'] = '../page-01.png'
                    else:
                        (changed / relative / 'page-11.png').write_bytes(pages[0].read_bytes())
                    changed_manifest.write_text(json.dumps(value))
                    summary = {**expected['result'], 'pages': value['pages']}
                    with sqlite3.connect(changed / 'tasks.sqlite3') as db:
                        db.execute('UPDATE tasks SET summary=? WHERE id=?', (json.dumps(summary), task['id']))
                    snapshot = json.loads((changed / 'snapshot.json').read_text())
                    for entry in snapshot['files']:
                        data = (changed / entry['path']).read_bytes()
                        entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                    (changed / 'snapshot.json').write_text(json.dumps(snapshot))
                    for operation in ('verify', 'restore'):
                        output = root / (variant + '-restored') if operation == 'restore' else None
                        response = invoke(operation, changed, output)
                        self.assertEqual(response.returncode, 2, response.stdout)
                        if output:
                            self.assertFalse(output.exists())
