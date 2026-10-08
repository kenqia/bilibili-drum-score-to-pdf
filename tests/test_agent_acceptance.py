"""Independent source audit is exercised through its command-line boundary."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import test_agent_continuity as fixture
import test_agent_segments as segment_fixture


class AcceptanceTests(unittest.TestCase):
    cli = fixture.ContinuityTests.cli
    prepare = fixture.ContinuityTests.prepare

    def test_saved_agent_execution_passes_independent_pts_and_replay_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            task, decision = self.prepare(base)
            record = base / 'decision.json'
            record.write_text(json.dumps(decision))
            accepted = self.cli('--operation', 'submit', '--task', task, '--decision', record)
            self.assertEqual(accepted['phase'], 'accepted', accepted)
            first, second = base / 'first', base / 'second'
            self.assertEqual(self.cli('--operation', 'export', '--task', task, '--output', first)['status'], 'success')
            self.assertEqual(self.cli('--operation', 'replay', '--task', task, '--output', second)['status'], 'success')
            verifier = Path(__file__).with_name('verify_agent_acceptance.py')
            command = [sys.executable, str(verifier), '--first', str(first), '--second', str(second), '--report', str(base / 'report.json')]
            process = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads((base / 'report.json').read_text())
            self.assertFalse(result['visual_content_verified_by_this_script'])
            row = json.loads((first / 'manifest.json').read_text())['rows'][0]
            from PIL import Image
            path = first / row['original_image']
            with Image.open(path) as original:
                changed = original.convert('RGB')
            changed.putpixel((0, 0), (12, 34, 56))
            changed.save(path)
            process = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(process.returncode, 0)

    def test_same_a4_pages_with_wrong_embedded_pixels_are_rejected(self):
        from PIL import Image
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            task, decision = self.prepare(base)
            record = base / 'decision.json'
            record.write_text(json.dumps(decision))
            self.assertEqual(self.cli('--operation', 'submit', '--task', task, '--decision', record)['phase'], 'accepted')
            first, second = base / 'first', base / 'second'
            self.assertEqual(self.cli('--operation', 'export', '--task', task, '--output', first)['status'], 'success')
            self.assertEqual(self.cli('--operation', 'replay', '--task', task, '--output', second)['status'], 'success')
            manifest = json.loads((first / 'manifest.json').read_text())
            # Same image dimensions, placements and page count; one embedded pixel differs.
            for output in (first, second):
                pdf = canvas.Canvas(str(output / manifest['pdf']), pagesize=A4, invariant=1)
                blocks = manifest.get('extras', []) + ([manifest['header']] if manifest.get('header') else []) + manifest['rows']
                for page in range(1, manifest['page_count'] + 1):
                    for index, block in enumerate(blocks):
                        if block['page'] != page:
                            continue
                        with Image.open(output / block['image']) as image:
                            pixels = image.convert('L')
                        if index == 0:
                            pixels.putpixel((0, 0), (pixels.getpixel((0, 0)) + 1) % 256)
                        left, top, right, bottom = block['pdf_bbox']
                        pdf.drawImage(ImageReader(pixels), left, top, right-left, bottom-top)
                    pdf.showPage()
                pdf.save()
            process = subprocess.run([sys.executable, str(Path(__file__).with_name('verify_agent_acceptance.py')),
                '--first', str(first), '--second', str(second), '--report', str(base / 'report.json')],
                capture_output=True, text=True)
            self.assertNotEqual(process.returncode, 0, 'Wrong PDF content passed independent audit')
            self.assertIn('PDF embedded pixels differ', process.stderr)

    def test_ordered_segments_audit_all_embedded_title_and_extra_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            helper = segment_fixture.SegmentTests()
            task, decision = helper.decision(base)
            record = base / 'decision.json'
            record.write_text(json.dumps(decision))
            self.assertEqual(self.cli('--operation', 'submit', '--task', task, '--decision', record)['phase'], 'accepted')
            first, second = base / 'first', base / 'second'
            self.assertEqual(self.cli('--operation', 'export', '--task', task, '--output', first)['status'], 'success')
            self.assertEqual(self.cli('--operation', 'replay', '--task', task, '--output', second)['status'], 'success')
            process = subprocess.run([sys.executable, str(Path(__file__).with_name('verify_agent_acceptance.py')),
                '--first', str(first), '--second', str(second), '--report', str(base / 'report.json')],
                capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads((base / 'report.json').read_text())['pdf_embedded_blocks'], 8)
