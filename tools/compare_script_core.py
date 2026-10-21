"""Run immutable local inputs against frozen programs, one process tree at a time.

The main adapter extracts its existing stitch/render algorithms without creating
Agent review receipts. Its output remains unreviewed comparison material.
Linux RSS polling is a sampled process-tree measurement, not a cgroup maximum.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main_adapter(checkout, source, output, name):
    sys.path.insert(0, str(Path(checkout) / 'skills/bilibili-drum-score-to-pdf/scripts'))
    import score_workflow
    import score_task
    import longshot
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas
    score_workflow.prepare(source, output)
    score_workflow.stitch(output)
    record = score_task.load(output)
    blocks, placements = longshot._continuous_pages(output, record)
    pdf = Path(output) / 'comparison.pdf'
    canvas = Canvas(str(pdf), pagesize=A4, invariant=1)
    canvas.setTitle(name)
    for block, placement in zip(blocks, placements):
        box, scale = block['crop_bbox'], placement['scale']
        image = block['image']
        canvas.saveState()
        canvas.translate(placement['bbox'][0], placement['bbox'][3])
        clip = canvas.beginPath()
        clip.rect(0, -block['height'] * scale, block['width'] * scale, block['height'] * scale)
        canvas.clipPath(clip, stroke=0)
        canvas.drawImage(str(score_task.artifact(output, image)), -box[0] * scale,
                         -(image['height'] - box[1]) * scale,
                         width=image['width'] * scale, height=image['height'] * scale)
        canvas.restoreState()
        canvas.showPage()
    canvas.save()
    result = {'pdf': 'comparison.pdf', 'page_count': len(blocks), 'placements': placements}
    (Path(output) / 'comparison-output.json').write_text(json.dumps({
        'kind': 'unreviewed_algorithm_extraction', 'output': result}, ensure_ascii=False))


def rss_tree(group):
    total = 0
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == group:
                total += int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
        except (OSError, ValueError, IndexError):
            continue
    return total


def run_bounded(command, directory, seconds, memory, checkout=None):
    environment = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                   'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1'}
    if checkout:
        root = Path(checkout).resolve()
        environment['PYTHONPATH'] = os.pathsep.join([str(root / 'src'),
            str(root / 'skills/bilibili-drum-score-to-pdf/scripts')])
    started, peak, stopped = time.monotonic(), 0, None
    with (directory / 'program.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=checkout, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                   start_new_session=True, env=environment)
        try:
            while process.poll() is None:
                peak = max(peak, rss_tree(process.pid))
                if peak > memory or time.monotonic() - started > seconds:
                    stopped = 'memory_limit' if peak > memory else 'deadline'
                    break
                time.sleep(.05)
        finally:
            # Also reap decoders which outlive their direct parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    return {'exit_code': process.returncode, 'failure': stopped,
            'elapsed_seconds': time.monotonic() - started,
            'sampled_peak_process_tree_rss_bytes': peak,
            'rss_sampling_interval_seconds': .05,
            'timing_boundary': 'local program execution only; excludes extra PDF previews, download and human review'}


def run(args):
    manifest = json.loads(Path(args.manifest).read_text())
    # Verify every input even when selecting one. The fixed set cannot drift.
    for item in manifest['inputs']:
        if digest(item['path']) != item['sha256']:
            print(json.dumps({'error': 'input_changed', 'sample': item['name']}))
            return 2
    if args.program == 'attachment' and (not args.attachment_sha256 or
            digest(args.attachment) != args.attachment_sha256):
        print(json.dumps({'error': 'attachment_changed'}))
        return 2
    if args.program in ('main', 'optimized'):
        version = subprocess.check_output(['git', '-C', args.checkout, 'rev-parse', 'HEAD'], text=True).strip()
        expected = (json.loads(Path(args.versions).read_text())['main']['commit']
                    if args.program == 'main' else args.version)
        source_paths = ['skills/bilibili-drum-score-to-pdf/scripts', 'src', 'pyproject.toml']
        changed = subprocess.check_output(['git', '-C', args.checkout, 'status',
            '--porcelain', '--untracked-files=all', '--', *source_paths], text=True)
        if version != expected or changed:
            print(json.dumps({'error': args.program + '_version_changed'}))
            return 2
    else:
        version = args.attachment_sha256 if args.program == 'attachment' else args.version
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'inputs.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    reports = []
    for item in manifest['inputs']:
        if args.sample and args.sample != item['name']:
            continue
        directory = output / item['name']
        directory.mkdir()
        if args.program == 'main':
            command = [sys.executable, str(Path(__file__).resolve()), '--main-child',
                       args.checkout, item['path'], str(directory / 'task'), item['name']]
        elif args.program == 'attachment':
            command = [sys.executable, args.attachment, item['path'], '-o', str(directory / 'score.pdf'),
                       '--debug', str(directory / 'debug')]
        else:
            command = [sys.executable, '-m', 'drum_score', item['path'],
                       '--output', str(directory / 'result')]
        report = run_bounded(command, directory, args.seconds, args.memory_mib * 1024**2,
                             args.checkout if args.program == 'optimized' else None)
        report.update(sample=item['name'], source_sha256=item['sha256'], program=args.program,
                      version=version, musical_review=False, download_seconds=None)
        pdfs = list(directory.rglob('*.pdf'))
        report['pdfs'] = [{'path': str(p.relative_to(output)), 'bytes': p.stat().st_size,
                           'sha256': digest(p)} for p in pdfs]
        # Attachment debug pages are not necessarily the actual PDF rendering.
        preview_started = time.monotonic()
        for pdf in pdfs:
            preview = pdf.parent / 'comparison-previews'
            preview.mkdir(exist_ok=False)
            try:
                subprocess.run(['pdftoppm', '-scale-to', '1400', '-png', str(pdf), str(preview / 'page')],
                               check=True, capture_output=True, timeout=120)
                pages = sorted(preview.glob('page-*.png'))
                report['pdfs'][pdfs.index(pdf)]['page_count'] = len(pages)
            except (subprocess.SubprocessError, OSError):
                report['preview_failure'] = True
        report['extra_pdf_preview_seconds'] = time.monotonic() - preview_started
        if report['failure'] is None and report['exit_code'] != 0:
            report['failure'] = 'program_failed'
        if digest(item['path']) != item['sha256']:
            report['failure'] = 'source_changed_during_execution'
        reports.append(report)
        (directory / 'measurement.json').write_text(json.dumps(report, indent=2))
        (output / 'comparison.json').write_text(json.dumps(reports, indent=2))
        print(json.dumps(report), flush=True)
    return 0 if reports and all(r['failure'] is None for r in reports) else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--main-child':
        main_adapter(*sys.argv[2:])
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--versions')
    parser.add_argument('--output', required=True)
    parser.add_argument('--program', choices=('main', 'attachment', 'optimized'), required=True)
    parser.add_argument('--checkout')
    parser.add_argument('--attachment')
    parser.add_argument('--attachment-sha256')
    parser.add_argument('--version')
    parser.add_argument('--sample')
    parser.add_argument('--seconds', type=float, default=600)
    parser.add_argument('--memory-mib', type=int, default=2048)
    args = parser.parse_args()
    if args.seconds <= 0 or args.memory_mib <= 0:
        parser.error('limits must be positive')
    if args.program == 'main' and (not args.checkout or not args.versions):
        parser.error('main requires --checkout and --versions')
    if args.program == 'attachment' and (not args.attachment or not args.attachment_sha256):
        parser.error('attachment requires its path and SHA-256')
    if args.program == 'optimized' and (not args.checkout or not args.version):
        parser.error('optimized requires --checkout and its full commit --version')
    try:
        return run(args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print(json.dumps({'error': 'comparison_setup_failed'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
