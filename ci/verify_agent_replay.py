"""Offline CI fixture replay. Never accept a private video or upload raw records."""
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
sys.path.insert(0, str(ROOT / 'skills/bilibili-drum-score-to-pdf/scripts'))
import score_workflow as workflow

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


def controlled_review(regions, review):
    return {**review, 'unresolved': review.get('unresolved', [])}


def refused(action, code, summary):
    try:
        action()
    except workflow.ReconstructionError:
        summary['negative_cases'][code] = 'reconstruction_rejected'
    else:
        raise AssertionError(code + '_accepted')


def verify(base, evidence, summary):
    video = fixture_video(base)
    task = base / 'task'
    workflow.prepare(video, task)
    shot = workflow.capture(task, 0)
    regions = [{'capture': shot['id'], 'bbox': [0, 0, 640, 65],
                'kind': 'header', 'position': 'title'}]
    regions += [{'capture': shot['id'], 'bbox': [0, top - 35, 640, top + 80],
                 'kind': 'system', 'position': 'system-' + str(index),
                 'staff_top': 35, 'staff_spacing': 10}
                for index, top in enumerate((100, 260, 420), 1)]
    review = {'viewed_captures': [shot['id']], 'complete': True,
              'notes': 'Fixed controlled geometry, automated replay only; no Agent visual acceptance.',
              'continuity': 'Three fixture systems in their drawn order.',
              'first_last': 'Fixture header and all three complete systems.'}
    review = controlled_review(regions, review)
    workflow.present(task, [shot['id']], 'Controlled CI presentation, not a live Agent view.')
    record_path = task / 'record.json'
    original = record_path.read_bytes()
    state = json.loads(original)
    state['schema'] = 'unsupported/999'
    write(record_path, state)
    refused(lambda: workflow.load(task), 'unknown_version', summary)
    record_path.write_bytes(original)
    bad = [dict(r) for r in regions]
    bad[1]['bbox'] = [-1, 65, 640, 180]
    refused(lambda: workflow.assemble(task, 'Fixture song', bad, review),
            'out_of_bounds', summary)
    require(workflow.load(task)['regions'] == [], 'invalid_selection_persisted')
    workflow.assemble(task, 'Fixture song', regions, review)
    selected = record_path.read_bytes()
    workflow.assemble(task, 'Fixture song', regions,
                      {**review, 'unresolved': ['Controlled hidden note']})
    refused(lambda: workflow.redraw_inputs(task), 'unresolved', summary)
    require('output' not in workflow.load(task), 'unresolved_exported')
    record_path.write_bytes(selected)
    for page in workflow.redraw_inputs(task):
        workflow.fail_redraw(task, page['id'], 'Offline CI explicitly forces vector; no host tool call.')
    result = workflow.export(task)
    pdf_path = task / result['pdf']
    pdf = pdf_path.read_bytes()
    require(pdf_path.name == 'Fixture song.pdf', 'incorrect_pdf_name')
    require(result['page_count'] == 1 and result['routes'] == ['vector'], 'incorrect_export')
    require(result['status'] == 'needs_pdf_review', 'false_visual_acceptance')
    require(workflow.export(task) == result, 'resume_output_changed')
    require(pdf_path.read_bytes() == pdf, 'replay_pdf_changed')
    # Rebuild from an independent task, rather than merely returning a cached PDF.
    replay_task = base / 'replay'
    workflow.prepare(video, replay_task)
    replay_shot = workflow.capture(replay_task, 0)
    replay_regions = [{**r, 'capture': replay_shot['id']} for r in regions]
    workflow.present(replay_task, [replay_shot['id']], 'Controlled CI presentation.')
    workflow.assemble(replay_task, 'Fixture song', replay_regions,
                      controlled_review(replay_regions, {**review, 'viewed_captures': [replay_shot['id']]}))
    for page in workflow.redraw_inputs(replay_task):
        workflow.fail_redraw(replay_task, page['id'], 'Offline CI explicitly forces vector; no host tool call.')
    replay = workflow.export(replay_task)
    require((replay_task / replay['pdf']).read_bytes() == pdf, 'independent_replay_pdf_changed')
    # Native tools may encode localized dates with the Windows code page.
    # These checks need only ASCII fields, so retain bytes throughout.
    info = subprocess.run(['pdfinfo', str(pdf_path)], capture_output=True,
                          check=True, timeout=20).stdout
    require(re.search(rb'^Pages:\s+1\s*$', info, re.MULTILINE), 'incorrect_pdf_pages')
    require(re.search(rb'^Page size:\s+595\.\d+ x 841\.\d+ pts \(A4\)', info, re.MULTILINE), 'incorrect_page_size')
    listing = subprocess.run(['pdfimages', '-list', str(pdf_path)], capture_output=True,
                             check=True, timeout=20).stdout.splitlines()
    require(len(listing) == 2, 'bitmap_in_vector_pdf')
    summary.update(system_count=3, replay_pdf_equal=True, pdf_pages=1,
                   pdf_name=pdf_path.name, embedded_images=0, model_cost=None,
                   pdf_sha256=hashlib.sha256(pdf).hexdigest())
    (task / shot['path']).write_bytes(b'controlled corrupt image')
    refused(lambda: workflow.export(task), 'corrupt_image', summary)
    require(pdf_path.read_bytes() == pdf, 'corruption_overwrote_pdf')
    require(len(pdf) < LIMIT - 16384, 'artifact_limit')
    (evidence / 'fixture-score.pdf').write_bytes(pdf)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Never overwrite or upload caller-provided content in an existing directory.
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {'status': 'failed', 'evaluation': 'synthetic_vector_replay_only',
               'fixture_version': '2', 'negative_cases': {}}
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
