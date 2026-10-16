#!/usr/bin/env python3
"""Agent reconstruction entry. JSON stdout; no embedded model calls."""
import argparse
import json
import math
from pathlib import Path
import signal

from public_video import InputError, ACQUISITION_SECONDS, retryable_acquisition
from video_seek import ConversionError

OPERATIONS = ('redraw-requests','dispatch-redraw','cancel-redraw','scan-status','crop-checks','stage','layout','overview','resample','auto-freeze','revise-crop','prepare','resume','navigate','promote','cache-report','cache-limits','capture','present','assemble','redraw-inputs','generation-materials',
              'begin-redraw','finish-redraw','fail-redraw','review-redraw',
              'reject-accepted-redraw','export','review-pdf',
              'midi-request','midi-submit','midi-playable','midi-export','midi-resume')


def request_file(path):
    file = Path(path)
    if file.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('request too large')
    value = json.loads(file.read_text())
    if not isinstance(value, dict):
        raise ValueError('request must be object')
    return value


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?')
    parser.add_argument('--output', help='New task directory')
    parser.add_argument('--task', help='Current reconstruction task directory')
    parser.add_argument('--operation', choices=OPERATIONS, default='prepare')
    parser.add_argument('--request', help='Agent-authored JSON object of operation arguments')
    parser.add_argument('--acquisition-timeout', type=float, default=ACQUISITION_SECONDS)
    args = parser.parse_args()
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        if not math.isfinite(args.acquisition_timeout) or args.acquisition_timeout <= 0:
            raise ValueError('invalid deadline')
        payload = request_file(args.request) if args.request else {}
        if args.operation.startswith('midi-'):
            import midi_workflow
            names = {'midi-request':'request_conversion','midi-submit':'submit_transcription',
                     'midi-playable':'submit_playable_transcription','midi-export':'export_complete','midi-resume':'resume'}
            if not args.task:
                raise ValueError('task required')
            result = getattr(midi_workflow,names[args.operation])(args.task,**payload)
        else:
            import score_workflow
            if args.operation == 'prepare':
                if not args.input or not args.output:
                    raise ValueError('input and output required')
                target=Path(args.output)
                if target.exists() and not (target/'record.json').exists() and (target.is_symlink() or not target.is_dir() or any(target.iterdir())) and not retryable_acquisition(target):
                    raise ConversionError('existing_output','目标目录已有文件。')
                result = score_workflow.prepare(args.input,args.output,args.acquisition_timeout)
            else:
                if not args.task:
                    raise ValueError('task required')
                name = 'load' if args.operation == 'resume' else args.operation.replace('-','_')
                result = getattr(score_workflow,name)(args.task,**payload)
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
                (target/'manifest.json').write_text(json.dumps(result,ensure_ascii=False))
        print(json.dumps(result,ensure_ascii=False))
        return 2
    except (Exception,KeyboardInterrupt) as error:
        result = {'status':'failed','complete':False,'error':{
            'code':error.code if isinstance(error,ConversionError) else 'invalid_request','message':'输入、当前任务或操作参数无效；旧任务请另建新版任务。'}}
        print(json.dumps(result,ensure_ascii=False))
        return 2
    finally:
        signal.signal(signal.SIGTERM,previous)


if __name__ == '__main__':
    raise SystemExit(main())
