"""CLI acceptance tests using drawn score features and real video/PDF tools."""
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'skills/bilibili-drum-score-to-pdf/scripts/convert.py'


def score_frame(size=(1280, 960), row_count=3):
    frame = Image.new('RGB', size, '#303030')
    draw = ImageDraw.Draw(frame)
    draw.rectangle((70, 40, 1210, size[1] - 50), fill='white')
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28)
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


def video_from_image(image, directory, name='input'):
    png = directory / f'{name}.png'
    video = directory / f'{name}.mp4'
    image.save(png)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', str(png), '-t', '2', '-r', '4', '-pix_fmt', 'yuv420p', str(video)], check=True)
    return video


