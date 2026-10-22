"""Offline synthetic product verification with bounded public evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from drum_score import convert, ConversionError

LIMIT = 5 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise AssertionError(code)


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')


def fixture_video(base):
    """Controlled geometry; no network, model or musical interpretation."""
    image = Image.new('RGB', (640, 640), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((20, 15), 'Fixture song   quarter=120   4/4', fill='black')
    for top in (100, 260, 420):
        for line in range(5):
            draw.line((20, top + line * 10, 620, top + line * 10), fill='black')
        draw.ellipse((110, top + 21, 125, top + 30), fill='black')
        draw.line((125, top + 25, 125, top - 15), fill='black', width=2)
    png, video = base / 'fixture.png', base / 'fixture.mp4'
    image.save(png)
    subprocess.run(['ffmpeg', '-v', 'error', '-loop', '1', '-i', str(png),
                    '-t', '1', '-r', '5', '-pix_fmt', 'yuv420p', str(video)],
                   check=True, capture_output=True, timeout=30)
    return video


def verify(base, evidence, summary):
    video = fixture_video(base)
    before = hashlib.sha256(video.read_bytes()).hexdigest()
    output = base / 'result'
    result = convert(video, output)
    replay = convert(video, base / 'replay')
    require(result['status'] == 'complete' and result['reliable'] is False, 'false_proofreading')
    require(result['staff_count'] == 3, 'lost_systems')
    require(result['source']['sha256'] == before, 'source_changed')
    pdf = (output / result['pdf']['path']).read_bytes()
    require(pdf == (base / 'replay' / replay['pdf']['path']).read_bytes(), 'replay_pdf_changed')
    require(all((output / ref['path']).is_file() for ref in result['pages']), 'missing_preview')
    for code, action in [('output_exists', lambda: convert(video, output)),
                         ('resource_limit', lambda: convert(video, base / 'limited', limits={'input_bytes': 1}))]:
        try:
            action()
        except ConversionError as error:
            require(error.code == code, 'wrong_error')
            summary['negative_cases'][code] = 'rejected'
        else:
            raise AssertionError('invalid_accepted')
    info = subprocess.run(['pdfinfo', str(output / result['pdf']['path'])], capture_output=True,
                          check=True, timeout=20).stdout
    require(re.search(rb'^Page size:\s+595\.\d+ x 841\.\d+ pts \(A4\)', info, re.MULTILINE), 'incorrect_page_size')
    listing = subprocess.run(['pdfimages', '-list', str(output / result['pdf']['path'])],
                             capture_output=True, check=True, timeout=20).stdout.splitlines()
    require(len(pdf) < LIMIT - 16384, 'artifact_limit')
    summary.update(system_count=result['staff_count'], replay_pdf_equal=True,
        pdf_pages=len(result['pages']), pdf_name=result['pdf']['path'], embedded_images=len(listing) - 2,
        pdf_sha256=hashlib.sha256(pdf).hexdigest())
    (evidence / 'fixture-score.pdf').write_bytes(pdf)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Never overwrite or upload caller-provided content in an existing directory.
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {'status': 'failed', 'evaluation': 'synthetic_image_product_only',
               'fixture_version': '3', 'negative_cases': {}}
    try:
        with tempfile.TemporaryDirectory(prefix='score-ci-') as directory:
            verify(Path(directory), args.output, summary)
        summary['status'] = 'passed'
    except Exception as error:
        # Only a bounded class/code is public; raw subprocess logs/paths stay out of artifacts.
        summary['failure_type'] = type(error).__name__
        if isinstance(error, AssertionError) and re.fullmatch('[a-z_]{1,80}', str(error)):
            summary['failure_code'] = str(error)
    write(args.output / 'summary.json', summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
