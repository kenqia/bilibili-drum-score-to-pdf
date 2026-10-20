#!/usr/bin/env python3
"""Agent reconstruction entry. JSON stdout; no embedded model calls."""
import argparse
import json
import inspect
import uuid
import math
from pathlib import Path
import signal
import sys

from public_video import InputError, ACQUISITION_SECONDS, retryable_acquisition
from video_seek import ConversionError

OPERATIONS = ('prepare', 'resume', 'stage', 'navigate', 'capture', 'promote', 'present',
              'assemble', 'revise-selection', 'revise-crop', 'crop-checks', 'layout',
              'cache-report', 'cache-limits', 'redraw-inputs', 'redraw-requests',
              'dispatch-redraw', 'cancel-redraw', 'begin-redraw', 'finish-redraw',
              'fail-redraw', 'review-redraw', 'reject-accepted-redraw',
              'generation-materials', 'export', 'review-pdf')


def request_file(path):
    file = Path(path)
    if file.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('request too large')
    value = json.loads(file.read_text(encoding='utf-8-sig'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('non-finite JSON')))
    if not isinstance(value, dict):
        raise ValueError('request must be object')
    return value


class RequestError(ValueError):
    def __init__(self, field=None):
        self.field = field


def error_receipt(error, operation):
    from score_task import ReconstructionError
    if isinstance(error, ConversionError):
        code = error.code
    elif isinstance(error, ReconstructionError):
        code = error.code
    elif isinstance(error, RequestError):
        code = 'invalid_request'
    elif isinstance(error, KeyboardInterrupt):
        code = 'interrupted'
    else:
        code = 'internal_error'
    messages = {'invalid_request': '请求字段或参数无效，请核对操作参数。',
                'source_review_required': '来源审阅尚未完成，请读取 stage。',
                'invalid_state': '当前任务状态不允许该操作，请读取 stage 或 resume。',
                'decode_failed': '视频解码失败，请检查来源和解码工具。',
                'internal_error': '操作发生内部错误；保留当前任务，报告操作名与错误码。',
                'interrupted': '操作已中断；恢复当前任务，不要重复未知调用。'}
    detail = {'code': code, 'operation': operation, 'message': messages.get(code, '操作失败，请检查来源与当前任务。')}
    # Only program-defined fields/actions may be exposed, never raw exceptions.
    if isinstance(error, (RequestError, ReconstructionError)) and getattr(error, 'field', None):
        detail['field'] = error.field
    if isinstance(error, ReconstructionError) and error.action:
        detail['action'] = error.action
    return {'status': 'failed', 'complete': False, 'error': detail}


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({'status': 'failed', 'complete': False, 'error': {
            'code': 'invalid_request', 'message': '命令参数无效，请查看 --help。'}}, ensure_ascii=False))
        self.exit(2)


def summary(result, task=None):
    """Save the complete receipt; summary never implies an image was viewed."""
    if isinstance(result, dict):
        phase = result.get('phase', 'task')
        status = result.get('status', 'pending')
        issues = result.get('unresolved', result.get('issues', result.get('checks', {}).get('issues', [])))
        next_step = result.get('next')
        compact_next = {key: next_step[key] for key in ('operation', 'operations', 'request',
                       'pages', 'output_revision') if key in next_step} if isinstance(next_step, dict) else None
        compact = {'phase': phase, 'status': status, 'complete': result.get('complete', phase == 'complete' and status == 'complete'),
                   'issue_count': len(issues), 'next': compact_next}
        if 'error' in result:
            compact['error'] = result['error']
    else:
        compact = {'phase': 'task', 'status': 'pending', 'complete': False,
                   'issue_count': 0, 'next': None, 'item_count': len(result)}
    if task is not None:
        from score_task import write_path
        relative = Path('responses') / (uuid.uuid4().hex + '.json')
        path = write_path(task, relative)
        path.parent.mkdir(exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, allow_nan=False)
        compact['details'] = {'path': relative.as_posix(), 'read_operation': 'resume',
                              'instruction': '读取此完整回执文件；resume 读取当前任务状态。'}
    return compact


def invoke(function, *args, **payload):
    try:
        inspect.signature(function).bind(*args, **payload)
    except TypeError:
        raise RequestError('request') from None
    return function(*args, **payload)


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = JSONArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?')
    parser.add_argument('--output', help='New task directory')
    parser.add_argument('--task', help='Current reconstruction task directory')
    parser.add_argument('--operation', choices=OPERATIONS, default='prepare')
    parser.add_argument('--request', help='Agent-authored JSON object of operation arguments')
    parser.add_argument('--acquisition-timeout', type=float, default=ACQUISITION_SECONDS)
    parser.add_argument('--output-format', choices=('json', 'summary'), default='json')
    parser.add_argument('--summary', action='store_true', help='Alias for --output-format summary')
    args = parser.parse_args()
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        if not math.isfinite(args.acquisition_timeout) or args.acquisition_timeout <= 0:
            raise RequestError('acquisition-timeout')
        try:
            payload = request_file(args.request) if args.request else {}
        except (OSError, ValueError, UnicodeError):
            raise RequestError('request') from None
        import score_workflow
        if args.operation == 'prepare':
            if not args.input or not args.output:
                raise RequestError('input/output')
            target=Path(args.output)
            if target.exists() and not (target/'record.json').exists() and (target.is_symlink() or not target.is_dir() or any(target.iterdir())) and not retryable_acquisition(target):
                raise ConversionError('existing_output','目标目录已有文件。')
            result = score_workflow.prepare(args.input,args.output,args.acquisition_timeout)
        else:
            if not args.task:
                raise RequestError('task')
            name = 'load' if args.operation == 'resume' else args.operation.replace('-','_')
            result = invoke(getattr(score_workflow,name),args.task,**payload)
        if args.summary or args.output_format == 'summary':
            result = summary(result, args.output if args.operation == 'prepare' else args.task)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0
    except InputError as error:
        result = {'schema_version':1,'rows':[],'issues':[],'origin':error.origin,'phase':'acquisition','status':'failed','complete':False,
                  'error':{'code':error.code,'message':str(error)}}
        if hasattr(error,'diagnostics'):
            result['error'].update(error.diagnostics)
        if hasattr(error,'http_status'):
            result['error']['http_status'] = error.http_status
        if args.output:
            target = Path(args.output)
            if not target.exists() or retryable_acquisition(target):
                target.mkdir(parents=True,exist_ok=True)
                (target/'manifest.json').write_text(json.dumps(result,ensure_ascii=False), encoding='utf-8')
        if args.summary or args.output_format == 'summary':
            result = summary(result)
        print(json.dumps(result,ensure_ascii=False))
        return 2
    except (Exception,KeyboardInterrupt) as error:
        result = error_receipt(error, args.operation)
        if args.summary or args.output_format == 'summary':
            result = summary(result)
        print(json.dumps(result,ensure_ascii=False))
        return 2
    finally:
        signal.signal(signal.SIGTERM,previous)


if __name__ == '__main__':
    raise SystemExit(main())
