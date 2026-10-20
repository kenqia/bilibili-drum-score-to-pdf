"""Public longshot workflow; synthetic images are not musical acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw
from score_fixtures import CLI


def scrolling_video(root):
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
    for index in range(24):
        frame = sheet.crop((0, (index // 4) * 180, 640, (index // 4) * 180 + 520))
        # Keep a fixed watermark in the upper right; the stitcher must not erase it.
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


if __name__ == '__main__':
    unittest.main()
