#!/usr/bin/env python3
"""Explicit CLI for controlled host accounting. Never exports session bodies."""
import argparse
import json
from pathlib import Path
from agent_workflow import load_json, write_json, checked_task
from host_accounting import import_packet
from video_seek import ConversionError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    importer = commands.add_parser('import')
    importer.add_argument('--task', type=Path, required=True)
    importer.add_argument('--events', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.task.is_symlink():
            raise ValueError
        checked_task(args.task, recover=False)
        result = dict(status='success', usage=import_packet(args.task, load_json(args.events), load_json, write_json))
    except (ConversionError, OSError, ValueError, TypeError, KeyError, OverflowError):
        result = dict(status='failed', error=dict(code='invalid_host_usage', message='宿主计量输入或任务绑定非法。'))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'success' else 2


if __name__ == '__main__':
    raise SystemExit(main())
