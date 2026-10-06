#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.3.0", "numpy==2.5.3", "opencv-python-headless==5.0.0.93", "reportlab==5.0.1"]
# ///
"""Unified conversion entry point. JSON on stdout; progress only on stderr."""
import argparse
import json
import sys
from drum_score import convert


def main():
    parser = argparse.ArgumentParser(description='Restore a local white multi-staff drum score as A4 PDF.')
    parser.add_argument('input', help='Local video path')
    parser.add_argument('--output', required=True, help='Output directory')
    args = parser.parse_args()
    print('正在检查视频并提取完整谱行。', file=sys.stderr, flush=True)
    result = convert(args.input, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'success' else 2


if __name__ == '__main__':
    raise SystemExit(main())
