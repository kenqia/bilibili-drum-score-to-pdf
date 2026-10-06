#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.3.0", "numpy==2.5.3", "opencv-python-headless==5.0.0.93", "reportlab==5.0.1"]
# ///
"""Unified conversion entry point. JSON on stdout; progress only on stderr."""
import argparse
import json
import sys
from pathlib import Path
from public_video import acquire, InputError
from drum_score import convert


def main():
    parser = argparse.ArgumentParser(description='Restore a local white multi-staff drum score as A4 PDF.')
    parser.add_argument('input', help='Local video path or HTTPS Bilibili BV video URL')
    parser.add_argument('--output', required=True, help='Output directory')
    args = parser.parse_args()
    print('正在检查视频并提取完整谱行。', file=sys.stderr, flush=True)
    origin = None
    try:
        source = args.input
        if '://' in source:
            print('正在通过匿名公开接口获取视频，失败时请使用本地高清视频。', file=sys.stderr, flush=True)
            source, origin = acquire(source, args.output)
        result = convert(source, args.output)
    except InputError as error:
        origin = error.origin
        result = {'schema_version': 1, 'status': 'failed', 'complete': False, 'issues': [], 'rows': [], 'error': {'code': error.code, 'message': str(error)}}
        if hasattr(error, 'http_status'):
            result['error']['http_status'] = error.http_status
    if origin is not None:
        result['origin'] = origin
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'success' else 2


if __name__ == '__main__':
    raise SystemExit(main())
