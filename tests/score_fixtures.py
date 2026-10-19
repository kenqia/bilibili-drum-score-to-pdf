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


def video_from_image(image, directory, name='input'):
    png = directory / f'{name}.png'
    video = directory / f'{name}.mp4'
    image.save(png)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-i', str(png), '-t', '2', '-r', '4', '-pix_fmt', 'yuv420p', str(video)], check=True)
    return video


def controlled_source_review(regions, review):
    """Explicitly synthetic assertions, never evidence of an actual Agent view."""
    def ref(region):
        return {key: region[key] for key in ('position', 'capture', 'bbox')}
    rows = [r for r in regions if r.get('kind', 'system') == 'system']
    def endpoint(region):
        return {**ref(region), 'notes': 'Controlled synthetic source assertion.'}
    return {**review, 'evidence': {
        'title': endpoint(regions[0]), 'first': endpoint(rows[0]), 'last': endpoint(rows[-1]),
        'joins': [{'previous': ref(a), 'current': ref(b),
                   'method': 'same_capture' if a['capture'] == b['capture'] else 'ordered_page',
                   'notes': 'Controlled synthetic position order.'} for a, b in zip(rows, rows[1:])]}}


def controlled_reselection(task, title, regions, review):
    """Supply explicit fixture receipts when a legacy test changes its sources."""
    import score_workflow
    import reconstruction
    regions = [{**r, 'position': r.get('position') or str(i)} for i, r in enumerate(regions)]
    captures = list(dict.fromkeys(r['capture'] for r in regions))
    score_workflow.present(task, captures, 'Controlled fixture view, not real visual acceptance.')
    review = controlled_source_review(regions, {**review, 'viewed_captures': captures,
        'continuity': 'Controlled source order.', 'first_last': 'Controlled endpoints.'})
    return reconstruction.assemble(task, title, regions, review)
