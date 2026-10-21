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


class ScriptPublicContracts(unittest.TestCase):
    def test_public_cli_parsers_do_not_echo_invalid_arguments_or_private_payload(self):
        import os
        import importlib.util
        modules = ['drum_score']
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
            source_hash = hashlib.sha256((fixture.network / 'input.mp4').read_bytes()).hexdigest()
            link = 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=2'
            for entry in REMOTE_SCRIPT_ENTRIES:
                with self.subTest(entry=entry):
                    if entry == 'script_http':
                        task, auth = fixture.submit()
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
                    self.assertEqual(hashlib.sha256(pdf).hexdigest(), result['pdf']['sha256'])
                    self.assertTrue(result['pages'])
                    self.assertIn('not_musically_proofread', {warning['code'] for warning in result['warnings']})
                    self.assertEqual(list(fixture.root.rglob('.drum-score-*')), [])
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
