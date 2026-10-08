"""Independently check saved Agent execution; visual content needs a separate review."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from fractions import Fraction
from collections import Counter
from PIL import Image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory):
    result = json.loads((directory / 'manifest.json').read_text())
    assert result['status'] == 'success' and result['complete'] and not result['issues']
    assert result['decision']['schema_version'] in (3, 4)
    assert not result['coverage']['unresolved']
    source = Path(result['source']['path'])
    assert sha(source) == result['source']['sha256']
    probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,time_base:format=duration', '-of', 'json', str(source)],
        capture_output=True, check=True, timeout=30).stdout)
    stream = probe['streams'][0]
    assert (stream['width'], stream['height']) == (result['source']['width'], result['source']['height'])
    base = Fraction(stream['time_base'])
    blocks = result.get('extras', []) + ([result['header']] if result.get('header') else []) + result['rows']
    signatures = []
    expected_pdf_images = Counter()
    with tempfile.TemporaryDirectory(prefix='agent-independent-') as temporary:
        scratch = Path(temporary)
        decoded = {}
        for block in blocks:
            pts = block['pts']
            assert Fraction(*block['time_base']) == base
            assert abs(float(pts * base) - block['timestamp']) < 1e-9
            if pts not in decoded:
                path = scratch / f'{pts}.png'
                process = subprocess.run(['ffmpeg', '-nostdin', '-v', 'info', '-copyts',
                    '-ss', str(max(0, float(pts * base) - 1)), '-threads', '2', '-i', str(source),
                    '-vf', f'select=eq(pts\\,{pts}),showinfo', '-frames:v', '1', '-threads', '1',
                    '-pix_fmt', 'rgb24', str(path)], capture_output=True, check=True, timeout=60)
                diagnostic = process.stderr.decode(errors='replace')
                actual = re.findall(r'\bpts:\s*(-?\d+)', diagnostic)
                assert actual and int(actual[0]) == pts and path.exists()
                decoded[pts] = Image.open(path).convert('RGB')
            frame = decoded[pts]
            box = block['bbox']
            assert len(box) == 4 and all(type(x) is int for x in box)
            assert 0 <= box[0] < box[2] <= frame.width and 0 <= box[1] < box[3] <= frame.height
            with Image.open(directory / block['source_frame']) as saved, Image.open(directory / block['original_image']) as crop, Image.open(directory / block['image']) as gray:
                assert frame.tobytes() == saved.convert('RGB').tobytes()
                assert frame.crop(box).tobytes() == crop.convert('RGB').tobytes()
                source_gray = frame.crop(box).convert('L')
                assert source_gray.size == gray.size
                assert source_gray.tobytes() == gray.convert('L').tobytes()
                expected_pdf_images[(block['page'], source_gray.size, source_gray.tobytes())] += 1
            assert sha(directory / block['original_image']) == block['original_sha256']
            pdfbox = block['pdf_bbox']
            assert 36 <= pdfbox[0] < pdfbox[2] <= 560
            assert 36 <= pdfbox[1] < pdfbox[3] <= 806
            dpi = (box[2] - box[0]) / ((pdfbox[2] - pdfbox[0]) / 72)
            assert dpi >= 150
            if 'quality' in block:
                assert abs(dpi - block['quality']['effective_dpi']) < .01
            signatures.append({k: block[k] for k in ('pts', 'time_base', 'bbox', 'original_sha256', 'page', 'pdf_bbox')})
        rows = result['rows']
        assert [r['index'] for r in rows] == list(range(len(rows)))
        for a, b in zip(rows, rows[1:]):
            if a.get('segment_id') == b.get('segment_id'):
                assert a['global_y'] < b['global_y']
        for page in range(1, result['page_count'] + 1):
            placements = sorted((b['pdf_bbox'] for b in blocks if b['page'] == page), key=lambda b: b[1])
            assert all(a[3] <= b[1] for a, b in zip(placements, placements[1:]))
        pdf = directory / result['pdf']
        info = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert re.search(r'^Page size:\s+595\.\d+ x 841\.\d+ pts \(A4\)', info, re.M)
        listing = subprocess.run(['pdfimages', '-list', str(pdf)], capture_output=True, text=True, check=True, timeout=30).stdout
        records = [line.split() for line in listing.splitlines() if re.match(r'^\s*\d+\s+\d+\s+', line)]
        assert len(records) == len(blocks), 'PDF embedded image count differs from source blocks'
        subprocess.run(['pdfimages', '-png', str(pdf), str(scratch / 'embedded')], capture_output=True, check=True, timeout=30)
        actual_pdf_images = Counter()
        for record in records:
            page, number, kind, width, height, color, components, bits = record[:8]
            assert kind == 'image' and color == 'gray' and components == '1' and bits == '8', 'PDF must embed 8-bit grayscale source blocks'
            with Image.open(scratch / f'embedded-{int(number):03d}.png') as embedded:
                assert embedded.mode == 'L' and embedded.size == (int(width), int(height))
                actual_pdf_images[(int(page), embedded.size, embedded.tobytes())] += 1
        assert actual_pdf_images == expected_pdf_images, 'PDF embedded pixels differ from original source grayscale'
        assert re.search(rf'^Pages:\s+{result["page_count"]}\s*$', info, re.M)
    return {'rows': len(result['rows']), 'pages': result['page_count'], 'signatures': signatures,
            'pdf_sha256': sha(directory / result['pdf']), 'source_sha256': sha(source),
            'minimum_effective_dpi': min(r['quality']['effective_dpi'] for r in result['rows']),
            'pdf_embedded_blocks': len(blocks), 'independent_source_pts': len(decoded), 'visual_content_verified_by_this_script': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--second', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    first, second = verify(args.first), verify(args.second)
    assert first == second
    args.report.write_text(json.dumps({'status': 'verified_saved_decision_execution', **first}, indent=2) + '\n')
    print(json.dumps({'status': 'verified', 'rows': first['rows'], 'pages': first['pages']}))


if __name__ == '__main__':
    main()
