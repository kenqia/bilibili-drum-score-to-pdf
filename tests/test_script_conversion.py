"""Shared conversion entry contracts; synthetic sources are not music acceptance."""
from pathlib import Path
import sys
import tempfile
import subprocess
import json
import os
import time
from PIL import Image, ImageDraw, ImageChops
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import drum_score


class ScriptConversion(unittest.TestCase):
    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process identity contract')
    def test_guardian_does_not_rebind_a_reused_root_pid(self):
        # Replace only external /proc observations; signal targets remain real.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
            guard = None
            read_fd, write_fd = os.pipe()
            try:
                (root / 'sitecustomize.py').write_text("""from pathlib import Path
import os
original = Path.read_text
observed = Path(os.environ['IDENTITY_FIXTURE'])
target = '/proc/' + os.environ['SENTINEL_PID'] + '/stat'
def read(self, *args, **kwargs):
    value = original(self, *args, **kwargs)
    if str(self) == target and not (observed / 'reused').exists():
        head, tail = value.rsplit(') ', 1)
        fields = tail.split()
        fields[19] = 'original-identity'
        (observed / 'observed').write_text('ready')
        return head + ') ' + ' '.join(fields)
    return value
Path.read_text = read
""")
                identity = root.stat()
                guard = subprocess.Popen([sys.executable, '-m', 'drum_score.guardian',
                    str(read_fd), str(sentinel.pid), str(root / 'owned'),
                    str(identity.st_dev), str(identity.st_ino), 'original-identity'],
                    pass_fds=(read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env={**os.environ, 'IDENTITY_FIXTURE': str(root), 'SENTINEL_PID': str(sentinel.pid),
                         'PYTHONPATH': os.pathsep.join([str(root), *sys.path])})
                os.close(read_fd)
                read_fd = None
                self.assertEqual(guard.stdout.read(1), b'R')
                deadline = time.monotonic() + 5
                while not (root / 'observed').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((root / 'observed').exists())
                (root / 'reused').touch()
                time.sleep(.05)
                os.close(write_fd)
                write_fd = None
                guard.communicate(timeout=5)
                self.assertEqual(guard.returncode, 0)
                self.assertIsNone(sentinel.poll(), 'unrelated reused PID was killed')
            finally:
                for fd in (read_fd, write_fd):
                    if fd is not None:
                        os.close(fd)
                if guard is not None and guard.poll() is None:
                    guard.kill()
                    guard.communicate(timeout=5)
                sentinel.terminate()
                sentinel.wait(timeout=5)


    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process identity contract')
    def test_supervisor_does_not_rebind_reused_descendant_pid(self):
        # Only /proc observations are synthetic. Both supervised work and the
        # unrelated sentinel are actual processes receiving actual OS signals.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'tools'
            tools.mkdir()
            probe = tools / 'ffprobe'
            probe.write_text(f'#!{sys.executable}\nimport os,time\nfrom pathlib import Path\nPath({str(root / "worker-pid")!r}).write_text(str(os.getppid()))\ntime.sleep(60)\n')
            probe.chmod(0o755)
            (root / 'source.mp4').write_bytes(b'supervised synthetic input')
            sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
            process = None
            try:
                (root / 'sitecustomize.py').write_text("""from pathlib import Path
import os
original = Path.read_text
fixture = Path(os.environ['IDENTITY_FIXTURE'])
if 'drum_score.guardian' in __import__('sys').orig_argv:
    marker = fixture / ('guardian-pid-' + str(os.getpid()))
    marker.write_text(str(os.getpid()))
    os.replace(marker, fixture / 'guardian-pid')
target = '/proc/' + os.environ['SENTINEL_PID'] + '/stat'
def read(self, *args, **kwargs):
    value = original(self, *args, **kwargs)
    if str(self) == target and (fixture / 'worker-pid').exists():
        head, tail = value.rsplit(') ', 1)
        fields = tail.split()
        fields[1] = original(fixture / 'worker-pid').strip()
        phase = 'replacement' if (fixture / 'reused').exists() else 'original'
        if phase == 'original':
            fields[19] = 'original-descendant-identity'
        observed = fixture / (phase + '-' + str(os.getpid()))
        count = int(original(observed)) if observed.exists() else 0
        update = observed.with_name(observed.name + '.next')
        update.write_text(str(count + 1))
        os.replace(update, observed)
        return head + ') ' + ' '.join(fields)
    return value
Path.read_text = read
""")
                process = subprocess.Popen([sys.executable, '-m', 'drum_score', str(root / 'source.mp4'),
                    '--output', str(root / 'result'), '--timeout', '30'],
                    env={**os.environ, 'IDENTITY_FIXTURE': str(root), 'SENTINEL_PID': str(sentinel.pid),
                         'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                         'PYTHONPATH': os.pathsep.join([str(root), *sys.path])},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                def wait_observers(phase):
                    deadline = time.monotonic() + 10
                    while process.poll() is None and time.monotonic() < deadline:
                        guardian_pid = root / 'guardian-pid'
                        if guardian_pid.exists():
                            observers = [process.pid, int(guardian_pid.read_text())]
                            # The second read proves the previous scan returned
                            # and its identity was recorded by each observer.
                            if all((path := root / f'{phase}-{pid}').exists()
                                   and path.read_text().isdigit()
                                   and int(path.read_text()) >= 2 for pid in observers):
                                return
                        time.sleep(.01)
                    self.fail(f'Both supervisor and guardian must observe {phase} identity')
                wait_observers('original')
                (root / 'reused').touch()
                wait_observers('replacement')
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(json.loads(stdout)['error']['code'], 'cancelled', stderr)
                self.assertIsNone(sentinel.poll(), 'unrelated reused descendant PID was killed')
                self.assertFalse((root / 'result').exists())
                self.assertEqual(list(root.glob('.drum-score-*')), [])
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
                sentinel.terminate()
                sentinel.wait(timeout=5)


    def test_page_balancing_moves_whole_groups_to_sparse_final_page(self):
        from drum_score.imaging import _page_strips
        groups = [(0, 600), (600, 1200), (1200, 1800), (1800, 2400), (2400, 2700)]
        strips = _page_strips(groups, 2000)
        self.assertEqual(strips, [(0, 1200), (1200, 2700)])
        self.assertEqual(_page_strips([(0, 2200)], 2200), [(0, 2200)])
        self.assertEqual(_page_strips(groups, 3000), [(0, 2700)])


    def test_source_size_limit_is_checked_before_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'large.mp4'
            source.write_bytes(b'12345')
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result', limits={'input_bytes': 4})
            self.assertEqual(caught.exception.code, 'resource_limit')
            self.assertFalse((root / 'result').exists())


    def test_memory_and_temporary_disk_budgets_fail_without_partial_publication(self):
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root)
            before = source.read_bytes()
            for limit in ('rss_bytes', 'temp_bytes'):
                with self.subTest(limit=limit):
                    with self.assertRaises(drum_score.ConversionError) as caught:
                        drum_score.convert(source, root / limit, limits={limit: 1})
                    self.assertEqual(caught.exception.code, 'resource_limit')
                    self.assertFalse((root / limit).exists())
                    self.assertEqual(source.read_bytes(), before)
                    self.assertEqual(list(root.glob('.drum-score-*')), [])


    def test_total_deadline_stops_child_decoder_and_cleans_owned_temporary_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'not decoded by the waiting fixture')
            tools = root / 'bin'
            tools.mkdir()
            decoder = tools / 'ffprobe'
            decoder.write_text(f'#!{sys.executable}\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(root / 'decoder-pid')) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
            decoder.chmod(0o755)
            from unittest.mock import patch
            with patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}):
                with self.assertRaises(drum_score.ConversionError) as caught:
                    drum_score.convert(source, root / 'result', limits={'wall_seconds': .5})
            self.assertEqual(caught.exception.code, 'resource_limit')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(list(root.glob('.drum-score-*')), [])
            self.assertTrue((root / 'decoder-pid').exists())
            pid = int((root / 'decoder-pid').read_text())
            if Path('/proc').is_dir():
                state = Path('/proc') / str(pid) / 'stat'
                self.assertTrue(not state.exists() or state.read_text().split(') ')[1].startswith('Z'))


    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process recovery contract')
    def test_abnormal_conversion_worker_stops_its_independent_session_descendant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'worker exit fixture')
            binaries = root / 'bin'
            binaries.mkdir()
            decoder = binaries / 'ffprobe'
            decoder.write_text(f'#!{sys.executable}\nimport os,time,signal\nfrom pathlib import Path\nos.setsid()\nPath(' + repr(str(root / 'decoder-pid')) + ').write_text(str(os.getpid()))\ntime.sleep(.2)\nos.kill(os.getppid(),signal.SIGKILL)\ntime.sleep(30)\n')
            decoder.chmod(0o755)
            from unittest.mock import patch
            with patch.dict(os.environ, {'PATH': str(binaries) + os.pathsep + os.environ['PATH']}):
                with self.assertRaises(drum_score.ConversionError) as caught:
                    drum_score.convert(source, root / 'result')
            self.assertEqual(caught.exception.code, 'conversion_failed')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(list(root.glob('.drum-score-*')), [])
            pid = int((root / 'decoder-pid').read_text())
            state = Path('/proc') / str(pid) / 'stat'
            self.assertTrue(not state.exists() or state.read_text().split(') ')[1].startswith('Z'))


    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process recovery contract')
    def test_killed_caller_leaves_no_active_decoder_or_task_temporary_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'waiting decoder fixture')
            binaries = root / 'bin'
            binaries.mkdir()
            decoder = binaries / 'ffprobe'
            decoder.write_text(f'#!{sys.executable}\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(root / 'decoder-pid')) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
            decoder.chmod(0o755)
            process = subprocess.Popen([sys.executable, '-m', 'drum_score', str(source),
                '--output', str(root / 'result')], env={**os.environ,
                'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
                'PYTHONPATH': os.pathsep.join(sys.path)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not (root / 'decoder-pid').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / 'decoder-pid').exists())
                process.kill()
                process.wait(timeout=5)
                deadline = time.monotonic() + 5
                while list(root.glob('.drum-score-*')) and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(list(root.glob('.drum-score-*')), [])
                pid = int((root / 'decoder-pid').read_text())
                state = Path('/proc') / str(pid) / 'stat'
                self.assertTrue(not state.exists() or state.read_text().split(') ')[1].startswith('Z'))
                self.assertFalse((root / 'result').exists())
                self.assertEqual(source.read_bytes(), b'waiting decoder fixture')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()


    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process recovery contract')
    def test_guardian_startup_failure_never_starts_decoder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'guardian handshake fixture')
            (root / 'sitecustomize.py').write_text(
                "import os,sys\nif 'drum_score.guardian' in sys.orig_argv: os._exit(23)\n")
            binaries = root / 'bin'
            binaries.mkdir()
            decoder = binaries / 'ffprobe'
            decoder.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath(' +
                repr(str(root / 'decoder-started')) + ").touch()\n")
            decoder.chmod(0o755)
            process = subprocess.run([sys.executable, '-m', 'drum_score', str(source),
                '--output', str(root / 'result')], env={**os.environ,
                'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
                'PYTHONPATH': os.pathsep.join([str(root), *sys.path])},
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(json.loads(process.stdout)['error']['code'], 'conversion_failed')
            self.assertFalse((root / 'decoder-started').exists())
            self.assertFalse((root / 'result').exists())
            self.assertEqual(list(root.glob('.drum-score-*')), [])
            self.assertEqual(source.read_bytes(), b'guardian handshake fixture')

    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux process recovery contract')
    def test_paused_guardian_retains_caller_death_cleanup_identity(self):
        import json
        import signal
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            source.write_bytes(b'paused guardian fixture')
            binaries = root / 'bin'
            binaries.mkdir()
            decoder = binaries / 'ffprobe'
            decoder.write_text(f'#!{sys.executable}\n' + '''import os,time,json,signal
from pathlib import Path
def state(pid):
    fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()
    return {'pid':pid,'parent':int(fields[1]),'group':int(fields[2]),'session':int(fields[3]),'start':fields[19],'state':fields[0]}
worker=state(os.getppid())
children=(Path('/proc')/str(worker['parent'])/'task'/str(worker['parent'])/'children').read_text().split()
guardian=next(state(int(pid)) for pid in children if int(pid)!=worker['pid'] and state(int(pid))['session']==int(pid))
registered=Path(''' + repr(str(root / 'registered.json')) + ''')
temporary=registered.with_suffix('.tmp')
temporary.write_text(json.dumps({'probe':state(os.getpid()),'worker':worker,'guardian':guardian}))
temporary.replace(registered)
while not registered.with_name('allow-pause').exists():
    time.sleep(.005)
os.kill(guardian['pid'],signal.SIGSTOP)
while state(guardian['pid'])['state']!='T':
    time.sleep(.005)
child=os.fork()
if child==0:
    time.sleep(30)
    os._exit(0)
marker=Path(''' + repr(str(root / 'decoder.json')) + ''')
temporary=marker.with_suffix('.tmp')
temporary.write_text(json.dumps({'decoder':state(child),'probe':state(os.getpid()),'worker':worker,'guardian':guardian}))
temporary.replace(marker)
os._exit(0)
''')
            decoder.chmod(0o755)
            process = subprocess.Popen([sys.executable, '-m', 'drum_score', str(source),
                '--output', str(root / 'result')], env={**os.environ,
                'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
                'PYTHONPATH': os.pathsep.join(sys.path)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            identities = None
            def state(identity):
                try:
                    fields = (Path('/proc') / str(identity['pid']) / 'stat').read_text().rsplit(') ', 1)[1].split()
                    return fields[0] if fields[19] == identity['start'] else None
                except FileNotFoundError:
                    return None
            try:
                deadline = time.monotonic() + 10
                while not (root / 'registered.json').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / 'registered.json').exists())
                identities = json.loads((root / 'registered.json').read_text())
                (root / 'allow-pause').touch()
                while not (root / 'decoder.json').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / 'decoder.json').exists())
                identities.update(json.loads((root / 'decoder.json').read_text()))
                deadline = time.monotonic() + 3
                while state(identities['probe']) not in (None, 'Z') and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertIn(state(identities['probe']), (None, 'Z'))
                process.kill()
                process.wait(timeout=5)
                deadline = time.monotonic() + 3
                while state(identities['worker']) not in (None, 'T') and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertIn(state(identities['worker']), (None, 'T'))
                os.kill(identities['guardian']['pid'], signal.SIGCONT)
                deadline = time.monotonic() + 5
                while list(root.glob('.drum-score-*')) and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(list(root.glob('.drum-score-*')), [])
                self.assertIn(state(identities['decoder']), (None, 'Z'), json.dumps(identities))
                self.assertFalse((root / 'result').exists())
                self.assertEqual(source.read_bytes(), b'paused guardian fixture')
            finally:
                if identities:
                    if state(identities['guardian']) == 'T':
                        os.kill(identities['guardian']['pid'], signal.SIGCONT)
                    worker = identities['worker']
                    if state(worker) not in (None, 'Z') and worker['group'] == worker['pid']:
                        try:
                            os.killpg(worker['pid'], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    for name in ('decoder', 'probe', 'worker'):
                        if name in identities and state(identities[name]) not in (None, 'Z'):
                            try:
                                os.kill(identities[name]['pid'], signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    live = identities and any(state(item) not in (None, 'Z') for item in identities.values())
                    if not live and not list(root.glob('.drum-score-*')):
                        break
                    time.sleep(.02)
                process.stdout.close()
                process.stderr.close()
                if identities:
                    self.assertTrue(all(state(item) in (None, 'Z') for item in identities.values()), identities)
                self.assertEqual(list(root.glob('.drum-score-*')), [])

    def test_cancelled_conversion_does_not_publish_or_leave_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 520), 'white')
            draw = ImageDraw.Draw(image)
            for top in (120, 300):
                for line in range(5):
                    draw.line((25, top + 8 * line, 615, top + 8 * line), fill='black')
            image.save(root / 'frame.png')
            source = root / 'video.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'frame.png'),
                '-t', '2', '-r', '4', '-c:v', 'ffv1', str(source)], check=True)
            cancelled = False
            def progress(stage):
                nonlocal cancelled
                if stage == 'sampling':
                    cancelled = True
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result', progress=progress, cancel=lambda: cancelled)
            self.assertEqual(caught.exception.code, 'cancelled')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(list(root.glob('.drum-score-*')), [])


    def test_invalid_input_never_publishes_or_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'invalid.mp4'
            source.write_bytes(b'not a video')
            output = root / 'result'
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, output)
            self.assertEqual(caught.exception.code, 'invalid_input')
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), b'not a video')
            output.mkdir()
            marker = output / 'mine'
            marker.write_bytes(b'existing')
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, output)
            self.assertEqual(caught.exception.code, 'output_exists')
            self.assertEqual(marker.read_bytes(), b'existing')


    def test_cli_errors_are_json_without_private_path_or_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.run([sys.executable, '-m', 'drum_score',
                str(root / 'private-name.mp4'), '--output', str(root / 'result')],
                env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            error = json.loads(result.stdout)
            self.assertEqual(error['error']['code'], 'invalid_input')
            self.assertNotIn('private-name', result.stdout + result.stderr)
            self.assertFalse((root / 'result').exists())


    def test_public_link_validation_retains_partition_and_rejects_nonpublic_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for address in ['http://www.bilibili.com/video/BV1rH4y1R7Rk',
                    'https://127.0.0.1/video/BV1rH4y1R7Rk',
                    'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=0']:
                with self.subTest(address=address), self.assertRaises(drum_score.ConversionError) as caught:
                    drum_score.convert(address, root / 'result')
                self.assertEqual(caught.exception.code, 'invalid_bilibili_url')
                self.assertFalse((root / 'result').exists())


    def test_static_video_produces_complete_a4_pages_and_actual_source_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 520), 'white')
            draw = ImageDraw.Draw(image)
            draw.text((30, 20), 'TITLE / AUTHOR / 120 BPM', fill='black')
            for top in (120, 300):
                for line in range(5):
                    draw.line((25, top + 8 * line, 615, top + 8 * line), fill='black')
                draw.ellipse((90, top + 10, 105, top + 20), fill=(220, 20, 30))
                draw.rectangle((200, top - 20, 202, top + 20), fill='black')
            image.save(root / 'native.png')
            source = root / 'native.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'native.png'),
                '-t', '2', '-r', '4', '-c:v', 'ffv1', str(source)], check=True)
            stages = []
            def progress(stage):
                stages.append(stage)
                if stage == 'complete':
                    raise RuntimeError('SYNTHETIC observer error after publication')
            result = drum_score.convert(source, root / 'result', progress=progress)
            self.assertEqual(result['status'], 'complete')
            self.assertFalse(result['reliable'])
            self.assertGreaterEqual(len(result['warnings']), 1)
            self.assertEqual(stages[-1], 'complete')
            output = root / 'result'
            with Image.open(output / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, image.size)
                self.assertEqual(actual.getpixel((97, 135)), (220, 20, 30))
            self.assertTrue((output / result['pdf']['path']).is_file())
            subprocess.run(['pdfimages', '-png', str(output / result['pdf']['path']), str(root / 'embedded')],
                           check=True, capture_output=True)
            # Row packing removes blank padding, but must preserve every source
            # pixel containing notation, including detached colored marks.
            from collections import Counter
            expected = Counter(pixel for pixel in image.get_flattened_data() if min(pixel) < 255)
            actual = Counter()
            for path in root.glob('embedded-*.png'):
                with Image.open(path) as embedded:
                    self.assertEqual(embedded.width, image.width)
                    actual.update(pixel for pixel in embedded.convert('RGB').get_flattened_data() if min(pixel) < 255)
            self.assertEqual(actual, expected)
            self.assertGreater(len(result['pages']), 0)
            for page in result['pages']:
                with Image.open(output / page['path']) as preview:
                    self.assertAlmostEqual(preview.width / preview.height, 210 / 297, places=2)
            self.assertTrue(all(isinstance(frame['pts'], int) and len(frame['time_base']) == 2
                                and len(frame['sha256']) == 64 for frame in result['samples']))
            self.assertEqual(len(result['source']['sha256']), 64)
            self.assertGreaterEqual(result['metrics']['native_motion_observations'], len(result['samples']))
            self.assertEqual(result['program']['name'], 'bilibili-drum-score-to-pdf')
            self.assertEqual(len(result['program']['source_sha256']), 64)
            self.assertEqual(result['samples'][0]['timestamp'], 0)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual(manifest, result)


    def test_scrolling_preserves_every_position_and_full_endpoints(self):
        from score_fixtures import scrolling_video
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, sheet = scrolling_video(root)
            result = drum_score.convert(video, root / 'result')
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, sheet.size)
                for row in range(7):
                    self.assertLess(min(actual.getpixel((50, 197 + row * 180))), 80, row)
            self.assertEqual(result['staff_count'], 7)
            self.assertEqual(result['samples'][0]['timestamp'], 0)
            self.assertEqual(result['samples'][-1]['timestamp'], 23)
            self.assertEqual(result['page_regions'][0][0], 0)
            self.assertEqual(result['page_regions'][-1][1], 1420)
            sheet.close()


    def test_blank_outro_preserves_last_music_system_and_actual_source_tail(self):
        from score_fixtures import scrolling_video
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, sheet = scrolling_video(root, [i // 2 * 180 for i in range(12)] + [None, None])
            result = drum_score.convert(video, root / 'result')
            self.assertEqual(result['staff_count'], 7)
            self.assertEqual(result['samples'][-1]['timestamp'], 13)
            self.assertEqual(result['page_regions'][-1][1], 1420)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                for row in range(7):
                    self.assertLess(min(actual.getpixel((50, 197 + row * 180))), 80)
            sheet.close()


    def test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 2400), (249, 249, 249))
            draw = ImageDraw.Draw(image)
            for row, top in enumerate(range(100, 2350, 280)):
                color = (150, 150, 150) if row == 8 else (0, 0, 0)
                right = 300 if row == 8 else 615
                for line in range(5):
                    draw.line((25, top + 8 * line, right, top + 8 * line), fill=color)
                draw.ellipse((90, top + 12, 100, top + 20), fill=color)
                draw.line((100, top - 20, 100, top + 18), fill=color, width=2)
                draw.rectangle((600, top + 70, 605, top + 75), fill=(220, 20, 30))
            image.save(root / 'source.png')
            source = root / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'source.png'),
                '-t', '1', '-r', '2', '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            subprocess.run(['pdfimages', '-png', str(root / 'result' / result['pdf']['path']),
                str(root / 'embedded')], check=True, capture_output=True)
            listing = subprocess.run(['pdfimages', '-list', str(root / 'result' / result['pdf']['path'])],
                check=True, capture_output=True).stdout.splitlines()[2:]
            self.assertGreater(len(listing), 1)
            # Poppler reads actual PDF image placements. Identical image width
            # and x/y resolution mean identical printed width and uniform scale.
            placements = [line.split() for line in listing]
            self.assertEqual(len({(row[3], row[12], row[13]) for row in placements}), 1)
            self.assertTrue(all(row[12] == row[13] for row in placements))
            regions = result['page_regions']
            self.assertEqual(regions[0][0], 0)
            self.assertEqual(regions[-1][1], image.height)
            for index, (start, end) in enumerate(regions):
                if index:
                    self.assertEqual(regions[index - 1][1], start)
            # This pale paper has no removable blank padding: concatenating
            # actual embedded images must restore the complete source exactly.
            embedded_paths = sorted(root.glob('embedded-*.png'))
            restored = Image.new('RGB', image.size)
            y = 0
            for path in embedded_paths:
                with Image.open(path) as embedded:
                    self.assertEqual(embedded.width, image.width)
                    restored.paste(embedded, (0, y))
                    y += embedded.height
            self.assertEqual(y, image.height)
            self.assertIsNone(ImageChops.difference(restored, image).getbbox())


    def test_changed_source_is_rejected_without_publishing_or_touching_other_results(self):
        from score_fixtures import score_frame, video_from_image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = video_from_image(score_frame(), root)
            previous = root / 'previous.pdf'
            previous.write_bytes(b'existing result')
            def progress(stage):
                if stage == 'paginating':
                    with source.open('ab') as stream:
                        stream.write(b'synthetic source mutation')
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result', progress=progress)
            self.assertEqual(caught.exception.code, 'source_changed')
            self.assertFalse((root / 'result').exists())
            self.assertEqual(previous.read_bytes(), b'existing result')


    def test_proven_thin_video_borders_do_not_join_all_printable_systems(self):
        from score_fixtures import scrolling_video
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, sheet = scrolling_video(root)
            for index, path in enumerate(sorted(root.glob('frame-*.png'))):
                with Image.open(path) as frame:
                    bordered = Image.new('RGB', (644, 520), 'black')
                    bordered.paste(frame, (2, 0))
                    bordered.save(root / f'border-{index:03d}.png')
            source = root / 'border.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '1', '-i',
                str(root / 'border-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['region'], [2, 0, 642, 520])
            # Compact printing may fit all groups on one page; the borders
            # must still leave independently printable system images.
            subprocess.run(['pdfimages', '-png', str(root / 'result' / result['pdf']['path']),
                str(root / 'border-embedded')], check=True, capture_output=True)
            self.assertGreaterEqual(len(list(root.glob('border-embedded-*.png'))), 2)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, sheet.size)
                self.assertIsNone(ImageChops.difference(actual.crop((0, 100, 570, 1420)),
                    sheet.crop((0, 100, 570, 1420))).getbbox())

            with Image.open(root / 'border-000.png') as marked:
                marked.putpixel((0, 200), (0, 0, 255))
                marked.save(root / 'border-000.png')
            changed = root / 'edge-mark.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '1', '-i',
                str(root / 'border-%03d.png'), '-c:v', 'ffv1', str(changed)], check=True)
            retained = drum_score.convert(changed, root / 'retained')
            self.assertEqual(retained['region'], [0, 0, 644, 520])
            with Image.open(root / 'retained' / retained['longshot']['path']) as image:
                self.assertEqual(image.getpixel((0, 200)), (0, 0, 255))


    def test_preflight_keeps_uncertain_intro_and_checks_distributed_native_frames(self):
        from score_fixtures import scrolling_video
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, _ = scrolling_video(root, offsets=[None, None, 0, 45, 90, 135])
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['preflight']['decision'], 'continue')
            observations = result['preflight']['observations']
            self.assertGreaterEqual(len(observations), 3)
            self.assertTrue(any(observation['staff_structure'] for observation in observations))
            self.assertLess(observations[0]['timestamp'], observations[-1]['timestamp'])
            self.assertTrue(all('pts' in observation and 'time_base' in observation
                                for observation in observations))




    def test_fixed_overlay_is_unknown_for_matching_but_kept_in_source_rgb(self):
        from score_fixtures import scrolling_video
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, sheet = scrolling_video(root, offsets=list(range(0, 901, 45)))
            result = drum_score.convert(source, root / 'result')
            self.assertGreater(result['registration']['invalid_pixels'], 0)
            disabled = drum_score.convert(source, root / 'disabled',
                options={'ignore_fixed_overlays': False})
            self.assertEqual(disabled['registration']['invalid_pixels'], 0)
            self.assertEqual(disabled['registration']['overlay_comparisons'], 0)
            self.assertEqual(result['staff_count'], 7)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, sheet.size)
                self.assertEqual(actual.getpixel((600, 20)), (0, 0, 0))
                # Distinctive notation away from the fixed overlay is retained.
                self.assertIsNone(ImageChops.difference(actual.crop((0, 100, 570, 1420)),
                    sheet.crop((0, 100, 570, 1420))).getbbox())


    def test_unique_narrow_viewport_overlap_keeps_complete_source_pixels(self):
        # Real failure BV1fbFczHE1r jumps between stationary viewports with
        # only a short distinctive fragment in common. This is synthetic.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 970), 'white')
            draw = ImageDraw.Draw(sheet)
            for row, top in enumerate((100, 270, 450, 620, 800)):
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                draw.text((30, top - 18), str(17 + row * 7), fill='black')
                for note in range(7):
                    x = 75 + note * 70 + row * 3
                    y = top + (note + row) % 4 * 6
                    draw.ellipse((x, y, x + 10, y + 8), fill='black')
                    draw.line((x + 10, y - 30, x + 10, y + 5), fill='black', width=2)
            for index, shift in enumerate((0, 0, 450, 450)):
                with sheet.crop((0, shift, 640, shift + 520)) as frame:
                    frame.save(root / f'snap-{index:03d}.png')
            source = root / 'snap.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i',
                str(root / 'snap-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertFalse(result['reliable'])
            self.assertEqual(result['staff_count'], 5)
            self.assertGreater(result['registration']['refinement_requests'], 0)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, sheet.size)
                self.assertIsNone(ImageChops.difference(actual.convert('RGB'), sheet).getbbox())


    def test_detected_page_flip_does_not_silently_publish_only_first_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(4):
                image = Image.new('RGB', (640, 520), 'white')
                draw = ImageDraw.Draw(image)
                for top in (120, 300):
                    for line in range(5):
                        draw.line((25, top + 8 * line, 615, top + 8 * line), fill='black')
                    for note in range(6):
                        x = 45 + note * 30 + (0 if index < 2 else 250)
                        draw.ellipse((x, top + 10, x + 10, top + 20), fill='black')
                        draw.line((x + 10, top - 30, x + 10, top + 20), fill='black', width=2)
                image.save(root / f'flip-{index}.png')
            source = root / 'flip.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '1', '-i', str(root / 'flip-%d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            with self.assertRaises(drum_score.ConversionError) as caught:
                drum_score.convert(source, root / 'result')
            self.assertEqual(caught.exception.code, 'discontinuity')
            self.assertFalse((root / 'result').exists())


    def test_identical_music_at_later_scroll_positions_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 1420), 'white')
            draw = ImageDraw.Draw(sheet)
            for row in range(7):
                top = 140 + row * 180
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                for x in (95, 195, 295, 395):
                    draw.ellipse((x, top + 10, x + 10, top + 20), fill='black')
                    draw.line((x + 10, top - 25, x + 10, top + 17), fill='black', width=2)
            for index, shift in enumerate(range(0, 901, 45)):
                sheet.crop((0, shift, 640, shift + 520)).save(root / f'repeat-{index:03d}.png')
            source = root / 'repeat.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '2', '-i', str(root / 'repeat-%03d.png'),
                            '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 7)
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, (640, 1420))
                self.assertIsNone(ImageChops.difference(actual.convert('RGB'), sheet).getbbox())


    def test_native_motion_between_identical_samples_never_publishes_shortened_score(self):
        # Seven unnumbered identical systems move by one system per 0.5s.
        # The retained endpoint images alias, but their native intermediate
        # frames visibly move. Refusing ambiguity is safer than inventing rows.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 1420), 'white')
            draw = ImageDraw.Draw(sheet)
            for row in range(7):
                top = 140 + 180 * row
                for line in range(5):
                    draw.line((25, top + 8 * line, 615, top + 8 * line), fill='black')
                for x in (95, 195, 295, 395):
                    draw.ellipse((x, top + 10, x + 10, top + 20), fill='black')
                    draw.line((x + 10, top - 25, x + 10, top + 17), fill='black', width=2)
            for index, shift in enumerate(range(0, 901, 12)):
                sheet.crop((0, shift, 640, shift + 520)).save(root / f'alias-{index:03d}.png')
            source = root / 'alias.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '30', '-i',
                            str(root / 'alias-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            compressed = root / 'alias.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-c:v', 'libx264',
                            '-threads', '1', '-crf', '23', '-pix_fmt', 'yuv420p', str(compressed)], check=True)
            # A 270px sampling jump has a plausible nonzero 90px alias too.
            for index, shift in enumerate(range(0, 901, 18)):
                sheet.crop((0, shift, 640, shift + 520)).save(root / f'wide-{index:03d}.png')
            wide = root / 'wide.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '30', '-i',
                            str(root / 'wide-%03d.png'), '-c:v', 'ffv1', str(wide)], check=True)
            wide_compressed = root / 'wide.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(wide), '-c:v', 'libx264',
                            '-threads', '1', '-crf', '23', '-pix_fmt', 'yuv420p', str(wide_compressed)], check=True)
            for index, video in enumerate((source, compressed, wide, wide_compressed)):
                with self.subTest(source=video.name):
                    before = video.read_bytes()
                    output = root / f'result-{index}'
                    with self.assertRaises(drum_score.ConversionError) as caught:
                        drum_score.convert(video, output)
                    self.assertEqual(caught.exception.code, 'discontinuity')
                    self.assertFalse(output.exists())
                    self.assertEqual(list(root.glob('.drum-score-*')), [])
                    self.assertEqual(video.read_bytes(), before)
            sheet.close()


    def test_static_lossy_video_does_not_invent_scroll_from_compression_changes(self):
        from score_fixtures import score_frame
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = score_frame()
            image.save(root / 'still.png')
            source = root / 'still.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'still.png'),
                            '-t', '2', '-r', '30', '-c:v', 'libx264', '-threads', '1',
                            '-crf', '23', '-pix_fmt', 'yuv420p', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 3)
            self.assertEqual(result['registration']['invalid_pixels'], 0)
            self.assertTrue(all(placement['offset'] == 0 for placement in result['placements']))
            with Image.open(root / 'result' / result['longshot']['path']) as longshot:
                self.assertLessEqual(longshot.height, image.height)
            image.close()


    def test_changing_background_keeps_unambiguous_stationary_score(self):
        from score_fixtures import score_frame
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = score_frame()
            image.save(root / 'still.png')
            image.close()
            source = root / 'animated-background.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'still.png'),
                            '-t', '2', '-r', '30', '-vf',
                            "drawbox=x=0:y=0:w=64:h=ih:color=white:t=fill:enable='mod(n,2)'",
                            '-c:v', 'libx264', '-threads', '1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 3)
            self.assertTrue(all(placement['offset'] == 0 for placement in result['placements']))
            self.assertGreater(max(sample['native_motion_max_luma_difference']
                                   for sample in result['samples']), 1.0)


    def test_native_tail_pts_regression_keeps_decoder_order_and_real_timestamps(self):
        import struct
        from score_fixtures import score_frame
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = score_frame()
            image.save(root / 'still.png')
            image.close()
            source = root / 'tail-pts.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'still.png'),
                            '-t', '2', '-r', '25', '-c:v', 'libx264', '-threads', '1',
                            '-bf', '3', str(source)], check=True)
            data = bytearray(source.read_bytes())
            # Change only the synthetic MP4 presentation offset of its final
            # delayed frame. The encoded pictures and decoding order stay real.
            def composition_tables(begin, end):
                while begin + 8 <= end:
                    size, tag = struct.unpack_from('>I4s', data, begin)
                    self.assertGreaterEqual(size, 8)
                    if tag in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
                        yield from composition_tables(begin + 8, begin + size)
                    if tag == b'ctts':
                        yield begin
                    begin += size
            tables = list(composition_tables(0, len(data)))
            self.assertEqual(len(tables), 1)
            table = tables[0]
            count = struct.unpack_from('>I', data, table + 12)[0]
            last_entry = table + 16 + (count - 1) * 8
            run, offset = struct.unpack_from('>II', data, last_entry)
            self.assertEqual(run, 1)
            self.assertGreater(offset, 0)
            struct.pack_into('>I', data, last_entry + 4, 0)
            source.write_bytes(data)
            probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'frame=best_effort_timestamp', '-of', 'json', str(source)],
                capture_output=True, check=True)
            native = [frame['best_effort_timestamp'] for frame in json.loads(probe.stdout)['frames']]
            self.assertLess(native[-1], native[-2])
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 3)
            self.assertEqual(result['metrics']['native_motion_observations'], len(native))
            self.assertEqual(result['samples'][-1]['pts'], native[-1])
            self.assertEqual(source.read_bytes(), bytes(data))


    def test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new('RGB', (640, 1420), 'white')
            draw = ImageDraw.Draw(sheet)
            for row in range(7):
                top = 140 + row * 180
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
                for x in (95, 195, 295, 395):
                    draw.ellipse((x, top + 10, x + 10, top + 20), fill='black')
                    draw.line((x + 10, top - 25, x + 10, top + 17), fill='black', width=2)
                draw.text((30, top - 15), str(row + 1), fill='black')
            # Each sampled half-second moves one system, with 340px of actual
            # overlap. Tiny measure numbers distinguish otherwise repeated music.
            for index, shift in enumerate(range(0, 901, 12)):
                with sheet.crop((0, shift, 640, shift + 520)) as frame:
                    frame.save(root / f'fast-repeat-{index:03d}.png')
            source = root / 'fast-repeat.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '30',
                            '-i', str(root / 'fast-repeat-%03d.png'), '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 7)
            self.assertEqual([placement['offset'] for placement in result['placements']],
                             [0, 180, 360, 540, 720, 900])
            with Image.open(root / 'result' / result['longshot']['path']) as actual:
                self.assertEqual(actual.size, sheet.size)
                self.assertIsNone(ImageChops.difference(actual.convert('RGB'), sheet).getbbox())
            self.assertEqual(result['page_regions'][-1][1], 1420)


    def test_no_safe_gap_preserves_tall_group_without_hard_cut(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new('RGB', (640, 2200), 'white')
            draw = ImageDraw.Draw(image)
            for top in (120, 1900):
                for line in range(5):
                    draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
            # Known colored mark connects the two systems. It must not be cut
            # just because its luminance is lighter than the staff threshold.
            draw.line((10, 0, 10, 2199), fill=(255, 210, 0), width=2)
            image.save(root / 'group.png')
            source = root / 'group.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(root / 'group.png'),
                            '-t', '2', '-r', '1', '-c:v', 'ffv1', str(source)], check=True)
            result = drum_score.convert(source, root / 'result')
            self.assertEqual(result['staff_count'], 2)
            self.assertEqual(result['page_regions'], [[0, 2200]])
            self.assertIn('joined_staff_rows', {warning['code'] for warning in result['warnings']})
            self.assertEqual(result['pagination']['max_staffs_per_group'], 2)
            self.assertEqual(len(result['pages']), 1)
            subprocess.run(['pdfimages', '-png', str(root / 'result' / result['pdf']['path']),
                            str(root / 'group-embedded')], check=True, capture_output=True)
            with Image.open(root / 'group-embedded-000.png') as embedded:
                self.assertEqual(embedded.size, image.size)
                self.assertIsNone(ImageChops.difference(embedded.convert('RGB'), image).getbbox())
