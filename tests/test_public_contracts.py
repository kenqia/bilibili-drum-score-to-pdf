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
                with TestClient(create_app(root / 'service')) as client:
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
            self.assertEqual((fixture.network / 'bbdown-invocations').read_text().splitlines(), ['inspect'] * len(REMOTE_SCRIPT_ENTRIES))
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
                                db.execute('PRAGMA user_version=2')
                        before = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
                        result = subprocess.run([sys.executable, '-m', 'drum_score.maintenance', operation, *args, '--min-free-mib', '1'], env=env, capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, 2, result.stdout)
                        self.assertEqual(json.loads(result.stdout)['status'], 'failed')
                        self.assertNotIn(str(root), result.stdout + result.stderr)
                        self.assertFalse(output.exists())
                        self.assertEqual({p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}, before)
                        if boundary == 'schema':
                            with sqlite3.connect(source / 'tasks.sqlite3') as db:
                                db.execute('PRAGMA user_version=1')


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
