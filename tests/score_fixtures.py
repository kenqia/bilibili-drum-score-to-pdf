"""CLI acceptance tests using drawn score features and real video/PDF tools."""
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def score_frame(size=(1280, 960), row_count=3):
    frame = Image.new('RGB', size, '#303030')
    draw = ImageDraw.Draw(frame)
    draw.rectangle((70, 40, 1210, size[1] - 50), fill='white')
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 28)
    except OSError:
        font = ImageFont.load_default(size=28)
    draw.text((130, 75), 'Fixture song    tempo 96    4/4', fill='black', font=font)
    for row, top in enumerate(220 + row * 220 for row in range(row_count)):
        for line in range(5):
            draw.line((110, top + line * 12, 1170, top + line * 12), fill='black', width=2)
        for note in range(4 + row % 3):
            x = 220 + note * 125
            draw.ellipse((x - 8, top + 27, x + 8, top + 39), fill='black')
            draw.line((x + 8, top + 33, x + 8, top - 32), fill='black', width=3)
        draw.text((120, top + 80), f'ROW {row + 1}', fill='black', font=font)
    return frame


def video_from_image(image, directory, name='input', *, duration=2):
    png = directory / f'{name}.png'
    video = directory / f'{name}.mp4'
    image.save(png)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', str(png), '-t', str(duration), '-r', '4', '-pix_fmt', 'yuv420p', str(video)], check=True)
    return video


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
