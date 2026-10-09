#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.3.0", "numpy==2.5.3", "opencv-python-headless==5.0.0.93", "reportlab==5.0.1", "yt-dlp==2026.8.19"]
# ///
"""Unified conversion entry point. JSON on stdout; progress only on stderr."""
import argparse
import json
import math
import signal
import sys
from pathlib import Path
from public_video import acquire, InputError, ACQUISITION_SECONDS, retryable_acquisition
import time
from video_seek import VideoReader, probe_video, ConversionError
from viewport_sampler import ViewportSampler
from viewport_tracker import ViewportError
from manifest import export_rows, save_crop, persist
from pdf_export import write_pdf


def convert(source, output):
    began = time.monotonic()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {'schema_version': 1, 'status': 'failed', 'complete': False,
              'issues': [], 'rows': [], 'header': None}
    metrics = {'seek_count': 0, 'analyzed_frames': 0, 'selected_keyframes': 0,
               'candidate_observations': 0, 'decode_elapsed': 0.0,
               'decoded_reported_frames': 0, 'peak_temp_disk': 0}
    reader = sampler = None
    try:
        metadata = probe_video(source)
        result['source'] = {'kind': 'local', 'path': str(Path(source).resolve()), **metadata}
        if metadata['width'] < 700:
            raise ConversionError('low_resolution', '视频分辨率不足，请提供清晰本地视频。')
        reader = VideoReader(source, metadata, metrics)
        sampler = ViewportSampler(reader, output, metrics)
        tracks = sampler.run()
        rows = export_rows(output, tracks)
        header = sampler.header
        if header['bbox'][3] > header['bbox'][1]:
            header.update(save_crop(output, header['source_frame'], header['bbox'], 'header'))
        else:
            header = None
        pages = write_pdf(output, header, rows)
        result.update(status='success', complete=True, rows=rows, header=header,
                      page_count=pages, pdf='score.pdf', transitions=sampler.transitions)
    except ViewportError as error:
        observation = getattr(error, 'observation', None)
        timestamp, screenshot = (observation.timestamp, observation.source_frame) if observation else sampler.last
        result.update(status='waiting', issues=[{'reason': error.code, 'timestamp': timestamp, 'screenshot': screenshot}],
                      error={'code': error.code, 'message': '缺少可靠的空间接续或干净完整观察，请提供更好的视频后运行新任务。'})
    except ConversionError as error:
        waiting = error.code == 'unsupported_layout'
        result.update(status='waiting' if waiting else 'failed', error={'code': error.code, 'message': str(error)})
        if waiting and sampler and sampler.last:
            timestamp, screenshot = sampler.last
            result['issues'] = [{'reason': error.code, 'timestamp': timestamp, 'screenshot': screenshot}]
    finally:
        if reader:
            reader.close()
        metrics['conversion_elapsed'] = time.monotonic() - began
        metrics['total_elapsed'] = metrics['conversion_elapsed']
        result['metrics'] = metrics
    return result


def interrupt_conversion(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description='Prepare native drum-score evidence for Agent review, then submit and export as A4 PDF.')
    parser.add_argument('input', nargs='?', help='Local video path or HTTPS Bilibili BV video URL')
    parser.add_argument('--output', help='Output directory')
    parser.add_argument('--operation', choices=['convert', 'prepare', 'submit', 'resume', 'supplement', 'export', 'replay', 'report', 'confirm-delivery'], default='prepare',
                        help='Operation (default: prepare; convert runs the legacy moving viewport path)')
    parser.add_argument('--task', help='Existing Agent observation task')
    parser.add_argument('--performance-events', help='Controlled host timing events JSON, bound to the task lifecycle')
    parser.add_argument('--decision', help='Agent-authored JSON decision')
    parser.add_argument('--acquisition-timeout', type=float, default=ACQUISITION_SECONDS,
                        help='Overall anonymous acquisition deadline in seconds (default: 1800)')
    args = parser.parse_args()
    if not math.isfinite(args.acquisition_timeout) or args.acquisition_timeout <= 0:
        parser.error('--acquisition-timeout must be a finite positive number')
    if args.operation != 'convert':
        from agent_workflow import run
        previous = signal.signal(signal.SIGTERM, interrupt_conversion)
        try:
            result = run(args.operation, args.input, args.task, args.decision, args.output, acquisition_timeout=args.acquisition_timeout, performance_events=args.performance_events)
        finally:
            signal.signal(signal.SIGTERM, previous)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result['status'] == 'success' else 2
    if not args.input or not args.output:
        parser.error('conversion needs input and --output')
    target = Path(args.output)
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir())) and not retryable_acquisition(target)):
        result = {'status': 'failed', 'complete': False, 'error': {'code': 'existing_output', 'message': '结果目录已有内容，请选择新的空目录。'}}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    began = time.monotonic()
    acquisition_elapsed = 0.0
    previous_handler = signal.signal(signal.SIGTERM, interrupt_conversion)
    print('正在检查视频并提取完整谱行。', file=sys.stderr, flush=True)
    origin = None
    try:
        source = args.input
        if '://' in source:
            print('正在通过匿名公开接口获取视频，失败时请使用本地高清视频。', file=sys.stderr, flush=True)
            source, origin = acquire(source, args.output, timeout=args.acquisition_timeout)
            acquisition_elapsed = time.monotonic() - began
        result = convert(source, args.output)
    except InputError as error:
        origin = error.origin
        result = {'schema_version': 1, 'phase': 'acquisition', 'status': 'failed', 'complete': False, 'issues': [], 'rows': [], 'error': {'code': error.code, 'message': str(error)}}
        if hasattr(error, 'diagnostics'):
            result['error'].update(error.diagnostics)
        if hasattr(error, 'http_status'):
            result['error']['http_status'] = error.http_status
    except KeyboardInterrupt:
        result = {'schema_version': 1, 'status': 'failed', 'complete': False, 'rows': [], 'issues': [],
                  'error': {'code': 'decode_failed', 'message': '转换已中断，请在新的空目录重新运行。'}}
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
    if 'metrics' in result:
        result['metrics'].update(total_elapsed=time.monotonic() - began, acquisition_elapsed=acquisition_elapsed)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result = persist(result, output, origin=origin)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'success' else 2


if __name__ == '__main__':
    raise SystemExit(main())
