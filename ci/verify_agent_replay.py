"""Offline CI fixture replay. Never accept a private video or upload raw records."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from score_fixtures import CLI, score_frame, video_from_image

LIMIT = 5 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise AssertionError(code)


def cli(*arguments):
    process = subprocess.run([sys.executable, str(CLI), *map(str, arguments)],
                             capture_output=True, text=True, timeout=90)
    result = json.loads(process.stdout)
    return process.returncode, result


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')


def verify(base, evidence, summary):
    video = video_from_image(score_frame(), base)
    task = base / 'task'
    _, prepared = cli(video, '--operation', 'prepare', '--output', task)
    require(prepared['status'] == 'waiting', 'prepare_failed')
    observation = json.loads((task / 'observation.json').read_text())
    decision = dict(schema_version=1, task_id=prepared['task_id'],
                    observation_sha256=prepared['observation_sha256'], decision_id='ci-fixed-1',
                    model={'id': 'synthetic-fixture', 'version': '1'},
                    prompt={'version': 'ci-fixed-1', 'text': 'Replay controlled three-row fixture.'},
                    presented_images=[image['id'] for image in observation['images']],
                    visual_review=True, complete=True, evidence='Controlled fixed fixture with three complete rows.',
                    selected_candidates=[c['id'] for c in observation['candidates']
                                         if c['frame_id'] == observation['frames'][0]['id']], unresolved=[])
    decision_path = base / 'fixed-decision.json'
    write(decision_path, {**decision, 'schema_version': 999})
    code, rejected = cli('--operation', 'submit', '--task', task, '--decision', decision_path)
    require(code != 0 and rejected['error']['code'] == 'invalid_decision', 'unknown_version_accepted')
    summary['negative_cases']['unknown_version'] = rejected['error']['code']
    require(not (task / 'decision.json').exists(), 'invalid_decision_persisted')

    # An out-of-bounds saved observation must be rejected even when its envelope hash matches.
    original_packet = (task / 'observation.json').read_bytes()
    original_state = (task / 'task.json').read_bytes()
    observation['candidates'][0]['bbox'][0] = -1
    write(task / 'observation.json', observation)
    bad_hash = hashlib.sha256((task / 'observation.json').read_bytes()).hexdigest()
    state = json.loads(original_state)
    state['observation_sha256'] = bad_hash
    write(task / 'task.json', state)
    write(decision_path, {**decision, 'observation_sha256': bad_hash})
    code, rejected = cli('--operation', 'submit', '--task', task, '--decision', decision_path)
    require(code != 0 and rejected['error']['code'] == 'invalid_decision', 'invalid_coordinates_accepted')
    summary['negative_cases']['out_of_bounds'] = rejected['error']['code']
    require(not (task / 'decision.json').exists(), 'invalid_decision_persisted')
    (task / 'observation.json').write_bytes(original_packet)
    (task / 'task.json').write_bytes(original_state)
    write(decision_path, decision)
    code, accepted = cli('--operation', 'submit', '--task', task, '--decision', decision_path)
    require(accepted['phase'] == 'accepted' and 'error' not in accepted, 'submit_failed')
    exported, replayed = base / 'export', base / 'replay'
    code, result = cli('--operation', 'export', '--task', task, '--output', exported)
    require(code == 0 and result['status'] == 'success', 'export_failed')
    require(len(result['rows']) == 3, 'missing_rows')
    independent_frame = base / 'independent-frame.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-frames:v', '1',
                    '-pix_fmt', 'rgb24', str(independent_frame)], capture_output=True, check=True, timeout=30)
    for row in [result['header']] + result['rows']:
        with Image.open(independent_frame) as frame, Image.open(exported / row['original_image']) as crop:
            require(row['timestamp'] == 0, 'unexpected_fixture_timestamp')
            require(frame.crop(row['bbox']).tobytes() == crop.tobytes(), 'crop_pixels_changed')
            with Image.open(exported / row['image']) as printable:
                require(crop.convert('L').tobytes() == printable.tobytes(), 'print_pixels_changed')
        if 'quality' in row:
            require(row['quality']['effective_dpi'] >= 150, 'low_dpi')
    summary.update(row_count=3, native_crops_equal=True,
                   minimum_effective_dpi=min(r['quality']['effective_dpi'] for r in result['rows']))
    code, replay = cli('--operation', 'replay', '--task', task, '--output', replayed)
    require(code == 0 and replay['status'] == 'success', 'replay_failed')
    pdf = (exported / 'score.pdf').read_bytes()
    require(pdf == (replayed / 'score.pdf').read_bytes(), 'replay_pdf_changed')
    info = subprocess.run(['pdfinfo', str(exported / 'score.pdf')], capture_output=True,
                          text=True, check=True, timeout=20).stdout
    require(re.search(r'^Pages:\s+1\s*$', info, re.MULTILINE), 'incorrect_pdf_pages')
    require(re.search(r'^Page size:\s+595\.\d+ x 841\.\d+ pts \(A4\)', info, re.MULTILINE), 'incorrect_page_size')
    summary.update(replay_pdf_equal=True, pdf_pages=1, pdf_sha256=hashlib.sha256(pdf).hexdigest())

    observation = json.loads(original_packet)
    damaged = task / observation['images'][0]['path']
    damaged.write_bytes(b'controlled corrupt image')
    rejected_output = base / 'corrupt'
    code, rejected = cli('--operation', 'replay', '--task', task, '--output', rejected_output)
    require(code != 0 and rejected['error']['code'] == 'source_mismatch', 'corrupt_image_accepted')
    require(not (rejected_output / 'score.pdf').exists(), 'corrupt_image_exported')
    summary['negative_cases']['corrupt_image'] = rejected['error']['code']
    require(len(pdf) < LIMIT - 16384, 'artifact_limit')
    (evidence / 'fixture-score.pdf').write_bytes(pdf)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Never overwrite or upload caller-provided content in an existing directory.
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {'status': 'failed', 'evaluation': 'fixed_decision_replay_only',
               'fixture_version': '1', 'negative_cases': {}}
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
