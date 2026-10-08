"""Verify two full BV1rH4y1R7Rk runs, independent source decode and PDF rendering."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'))
from video_seek import VideoReader, probe_video
from cursor_detect import cursor_occluded


def verify(directory):
    result = json.loads((directory / 'manifest.json').read_text())
    assert result['status'] == 'success' and result['complete']
    assert result['origin']['bvid'] == 'BV1rH4y1R7Rk' and not result['origin']['authenticated']
    assert result['source']['width'] == 1920 and result['source']['height'] == 1080
    assert len(result['rows']) == 12 and result['page_count'] == 2
    assert result['metrics']['analyzed_frames'] < 60
    source = Path(result['source']['path'])
    metrics = dict(seek_count=0, decode_elapsed=0, decoded_reported_frames=0, peak_temp_disk=0)
    reader = VideoReader(source, probe_video(source), metrics)
    signatures = []
    try:
        for block in [result['header']] + result['rows']:
            pts, frame = reader.read(block['timestamp'])
            assert abs(pts - block['timestamp']) < .001
            expected = frame.crop(block['bbox'])
            with Image.open(directory / block['original_image']) as original:
                np.testing.assert_array_equal(np.asarray(expected), np.asarray(original))
                with Image.open(directory / block['image']) as printable:
                    np.testing.assert_array_equal(np.asarray(original.convert('L')), np.asarray(printable))
            with Image.open(directory / block['source_frame']) as saved_frame:
                np.testing.assert_array_equal(np.asarray(frame), np.asarray(saved_frame))
            assert hashlib.sha256((directory / block['original_image']).read_bytes()).hexdigest() == block['original_sha256']
            if 'index' in block:
                assert block['quality']['complete'] and not block['quality']['obstruction_detected']
                assert not cursor_occluded(expected, block['staff_spacing'])
                assert block['quality']['effective_dpi'] >= 260
                assert block['pdf_bbox'][1] >= 36 and block['pdf_bbox'][3] <= 806
                selected = block['selected_candidate']
                assert selected['timestamp'] == block['timestamp'] and selected['bbox'] == block['bbox']
                with Image.open(directory / selected['original_crop']) as candidate:
                    np.testing.assert_array_equal(np.asarray(expected), np.asarray(candidate))
                signatures.append({k: block[k] for k in ('index', 'global_y', 'timestamp', 'bbox', 'original_sha256', 'page', 'pdf_bbox')})
    finally:
        reader.close()
    assert [r['index'] for r in result['rows']] == list(range(12))
    assert all(a['global_y'] < b['global_y'] for a, b in zip(result['rows'], result['rows'][1:]))
    pdf = directory / result['pdf']
    info = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True, check=True).stdout
    assert '595.276 x 841.89 pts (A4)' in info
    with tempfile.TemporaryDirectory(prefix='score-verification-') as temporary:
        prefix = Path(temporary) / 'page'
        subprocess.run(['pdftoppm', '-r', '150', '-png', str(pdf), str(prefix)], capture_output=True, check=True)
        pages = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(temporary).glob('page-*.png'))]
        assert len(pages) == 2
    return result, signatures, pages, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--second', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    first, first_rows, first_pages, first_check = verify(args.first)
    second, second_rows, second_pages, second_check = verify(args.second)
    assert first_rows == second_rows
    assert first_pages == second_pages
    assert first['header']['original_sha256'] == second['header']['original_sha256']
    assert (args.first / 'score.pdf').read_bytes() == (args.second / 'score.pdf').read_bytes()
    report = {'status': 'verified', 'sample': 'BV1rH4y1R7Rk', 'rows': first_rows,
              'page_sha256': first_pages, 'pdf_sha256': hashlib.sha256((args.first / 'score.pdf').read_bytes()).hexdigest(),
              'first_metrics': first['metrics'], 'second_metrics': second['metrics'],
              'independent_source_decode': [first_check, second_check]}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'rows': len(first_rows), 'pages': len(first_pages)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
