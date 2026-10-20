"""Public longshot workflow; synthetic images are not musical acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw
from score_fixtures import CLI, video_from_image


def scrolling_video(root, offsets=None):
    """Seven visibly distinct systems, six overlapping stationary viewports."""
    sheet = Image.new('RGB', (640, 1420), 'white')
    draw = ImageDraw.Draw(sheet)
    draw.text((35, 35), 'LONGSHOT FIXTURE', fill='black')
    for row in range(7):
        top = 140 + row * 180
        for line in range(5):
            draw.line((25, top + line * 8, 615, top + line * 8), fill='black', width=1)
        for note in range(row + 2):
            x = 65 + note * 45
            draw.ellipse((x, top + 12, x + 10, top + 20), fill='black')
            draw.line((x + 10, top - 25 - row * 2, x + 10, top + 17), fill='black', width=2)
        draw.rectangle((40, top + 55, 80 + row * 25, top + 60 + row), fill='black')
    offsets = [index // 4 * 180 for index in range(24)] if offsets is None else offsets
    for index, shift in enumerate(offsets):
        frame = sheet.crop((0, shift, 640, shift + 520)) if shift is not None else Image.new('RGB', (640, 520), 'white')
        # Keep a fixed watermark in the upper right; the stitcher must not erase it.
        if shift is not None:
            ImageDraw.Draw(frame).rectangle((590, 15, 610, 25), fill='black')
        frame.save(root / f'frame-{index:03d}.png')
    video = root / 'scroll.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '1', '-i',
                    str(root / 'frame-%03d.png'), '-c:v', 'ffv1', str(video)], check=True)
    return video, sheet


class LongshotCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.task = self.root / 'task'
        self.video, self.sheet = scrolling_video(self.root)

    def tearDown(self):
        self.sheet.close()
        self.temporary.cleanup()

    def call(self, operation, **payload):
        args = [sys.executable, str(CLI), '--operation', operation]
        if operation == 'prepare':
            args += [str(self.video), '--output', str(self.task)]
        else:
            request = self.root / 'request.json'
            request.write_text(json.dumps(payload))
            args += ['--task', str(self.task), '--request', str(request)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_stage_stitches_all_systems_without_manual_selection_or_pixel_cleanup(self):
        self.call('prepare')
        stage = self.call('stage')
        self.assertEqual(stage['phase'], 'longshot_review')
        longshot = stage['artifacts']['longshot']
        with Image.open(self.task / longshot['image']['path']) as image:
            self.assertEqual(image.size, (640, 1420))
            for row in range(7):
                self.assertLess(image.getpixel((50, 197 + row * 180)), 80, row)
            self.assertLess(image.getpixel((600, 20)), 80)
        self.assertEqual(longshot['system_count'], 7)
        records = json.loads((self.task / longshot['samples']['path']).read_text())
        self.assertEqual(records[0]['timestamp'], 0)
        self.assertEqual(records[-1]['timestamp'], 23)
        self.assertTrue(all(isinstance(s['pts'], int) and len(s['time_base']) == 2 for s in records))
        before = (self.task / longshot['image']['path']).read_bytes()
        again = self.call('stage')
        self.assertEqual(again['artifacts']['longshot'], longshot)
        self.assertEqual((self.task / longshot['image']['path']).read_bytes(), before)
        self.assertEqual(self.call('resume')['captures'], [])

    def test_one_overall_review_produces_vector_pdf_without_per_row_receipts(self):
        self.call('prepare')
        first = self.call('stage')['artifacts']['longshot']
        self.call('review-longshot', title='Synthetic longshot', notes='Controlled overall view; local ambiguity accepted.')
        stage = self.call('stage')
        self.assertEqual(stage['phase'], 'generation')
        for handoff in stage['handoffs']:
            self.assertEqual(handoff['status'], 'ready_to_dispatch')
            self.assertIn('局部', handoff['request']['prompt'])
            self.call('fail-redraw', identifier=handoff['group'], outcome='unavailable',
                      notes='Synthetic host has no image generation.')
        result = self.call('stage')
        self.assertEqual(result['phase'], 'pdf_review')
        output = result['artifacts']['output']
        self.assertEqual(output['checks']['status'], 'passed')
        self.assertEqual(output['checks']['ordered_source_regions'], list(range(7)))
        self.assertEqual(len(output['previews']), output['page_count'])
        self.assertIn('推测', output['notice'])
        self.assertFalse(output['reliable'])
        self.call('review-pdf', pages=result['next']['pages'], output_revision=output['output_revision'],
                  notes='Controlled page review, not musical accuracy.')
        self.assertEqual(self.call('stage')['phase'], 'complete')
        self.assertEqual(self.call('resume')['longshot']['image'], first['image'])

    def test_generation_resumes_one_call_and_auto_cuts_accepted_image_after_one_correction(self):
        self.call('prepare')
        self.call('stage')
        self.call('review-longshot', title='Synthetic generated score', notes='Controlled overall review.')
        initial = self.call('stage')['handoffs'][0]
        request = initial['request']['request']
        self.call('dispatch-redraw', identifier=initial['group'], request=request)
        resumed = self.call('stage')['handoffs'][0]
        self.assertEqual(resumed['status'], 'recover_existing_call')
        self.assertEqual(resumed['request']['request'], request)
        output = self.task / 'controlled-host-output.png'
        output.write_bytes(Path(initial['input']).read_bytes())
        self.call('finish-redraw', identifier=initial['group'], request=request, output=str(output),
                  tool='host-imagegen', receipt='controlled-fixture-not-a-real-generation')
        self.call('review-redraw', identifier=initial['group'], accepted=False, notes='Controlled correction request.')
        correction = self.call('begin-redraw', identifier=initial['group'], correction=True,
                               viewed_notes='Controlled one correction.')
        self.call('finish-redraw', identifier=initial['group'], request=correction['request'], output=str(output),
                  tool='host-imagegen', receipt='controlled-fixture-correction')
        accepted = self.call('review-redraw', identifier=initial['group'], accepted=True,
                             notes='Controlled acceptance; local symbol ambiguity allowed.')
        self.assertEqual(len(accepted['boundaries']), 7)
        self.assertEqual(accepted['corrections_used'], 1)
        rendered = self.call('stage')['artifacts']['output']
        self.assertEqual(rendered['routes'], ['imagegen'])
        self.call('layout', margin=30, minimum_gap=10)
        revised = self.call('stage')['artifacts']['output']
        self.assertNotEqual(rendered['output_revision'], revised['output_revision'])
        self.assertTrue((self.task / rendered['pdf']).is_file())
        page = self.call('resume')['redraw_pages'][0]
        self.assertEqual([a['request'] for a in page['attempts']], [request, correction['request']])

    def test_continuous_scrolling_keeps_intermediate_systems(self):
        directory = self.root / 'continuous'
        directory.mkdir()
        self.sheet.close()
        self.video, self.sheet = scrolling_video(directory, list(range(0, 901, 30)))
        self.call('prepare')
        longshot = self.call('stage')['artifacts']['longshot']
        self.assertEqual(longshot['system_count'], 7)
        with Image.open(self.task / longshot['image']['path']) as image:
            self.assertEqual(image.size, (640, 1420))
            for row in range(7):
                self.assertLess(image.getpixel((50, 197 + row * 180)), 80, row)

    def test_blank_outro_does_not_erase_the_final_music_system(self):
        directory = self.root / 'outro'
        directory.mkdir()
        self.sheet.close()
        self.video, self.sheet = scrolling_video(directory,
            [index // 4 * 180 for index in range(24)] + [None] * 8)
        self.call('prepare')
        longshot = self.call('stage')['artifacts']['longshot']
        self.assertEqual(longshot['system_count'], 7)
        with Image.open(self.task / longshot['image']['path']) as image:
            self.assertLess(image.getpixel((50, 1277)), 80)

    def test_vector_fallback_preserves_pale_short_ending_staff(self):
        image = Image.new('RGB', (640, 600), 'white')
        draw = ImageDraw.Draw(image)
        for top, right in ((140, 615), (400, 220)):
            for line in range(5):
                draw.line((25, top + line * 8, right, top + line * 8), fill=(195, 195, 195))
            draw.ellipse((80, top + 12, 90, top + 20), fill='black')
        self.video = video_from_image(image, self.root, 'pale-ending')
        image.close()
        self.call('prepare')
        self.call('stage')
        self.call('review-longshot', title='Pale short ending', notes='Controlled full and short pale staffs.')
        for handoff in self.call('stage')['handoffs']:
            self.call('fail-redraw', identifier=handoff['group'], outcome='unavailable', notes='Controlled no tool.')
        output = self.call('stage')['artifacts']['output']
        material = json.loads((self.task / output['vector']['path']).read_text())
        lines = [line for vector in material['vectors'] for line in vector['lines']]
        short = [line for line in lines if 390 < line[1] < 440 and line[2] < 230]
        self.assertEqual(len(short), 5, short)

    def test_cleaned_image_can_separate_staffs_joined_by_playback_marker(self):
        clean = Image.new('RGB', (640, 600), 'white')
        draw = ImageDraw.Draw(clean)
        for top in (140, 400):
            for line in range(5):
                draw.line((25, top + line * 8, 615, top + line * 8), fill='black')
        marked = clean.copy()
        ImageDraw.Draw(marked).line((320, 170, 320, 405), fill='blue', width=4)
        self.video = video_from_image(marked, self.root, 'joined-systems')
        marked.close()
        self.call('prepare')
        self.assertEqual(self.call('stage')['artifacts']['longshot']['system_count'], 1)
        self.call('review-longshot', title='Joined systems', notes='Controlled two staffs joined by a marker.')
        handoff = self.call('stage')['handoffs'][0]
        request = handoff['request']['request']
        self.call('dispatch-redraw', identifier=handoff['group'], request=request)
        output = self.root / 'cleaned.png'
        clean.save(output)
        clean.close()
        self.call('finish-redraw', identifier=handoff['group'], request=request, output=str(output),
                  tool='host-imagegen', receipt='controlled-cleaned-marker-not-real-generation')
        accepted = self.call('review-redraw', identifier=handoff['group'], accepted=True,
                             notes='Controlled same two staffs with playback marker removed.')
        self.assertEqual(accepted['boundaries'], [[0, 0, 640, 600]])


if __name__ == '__main__':
    unittest.main()
