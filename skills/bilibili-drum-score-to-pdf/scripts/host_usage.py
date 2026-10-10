#!/usr/bin/env python3
"""Explicit CLI for controlled host accounting. Never exports session bodies."""
import argparse
import json
import os
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
    collector = commands.add_parser('collect')
    collector.add_argument('--task', type=Path, required=True)
    collector.add_argument('--root-thread', default=os.environ.get('CODEX_THREAD_ID'))
    collector.add_argument('--root-turn', help='Defaults to the latest root turn metadata at the invocation end')
    collector.add_argument('--thread-id', action='append', required=True, help='Explicit invocation thread allowlist; root development is excluded unless named')
    collector.add_argument('--invocation', required=True)
    collector.add_argument('--start', required=True)
    collector.add_argument('--end', required=True)
    collector.add_argument('--codex-home', type=Path)
    collector.add_argument('--cwd', default=os.getcwd())
    collector.add_argument('--mode', choices=['review','review_only','replay'], default='review')
    collector.add_argument('--output', type=Path, required=True)
    aggregation = commands.add_parser('aggregate')
    aggregation.add_argument('--runs', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == 'aggregate':
            from benchmark_aggregate import aggregate
            result = aggregate(load_json(args.runs))
        else:
            if args.task.is_symlink():
                raise ValueError
            checked_task(args.task, recover=False)
        if args.operation == 'import':
            result = dict(status='success', usage=import_packet(args.task, load_json(args.events), load_json, write_json))
        elif args.operation == 'collect':
            from codex_usage_source import collect
            packet = collect(args.task, args.root_thread, args.root_turn, args.invocation, args.start, args.end, args.codex_home, load_json, args.cwd, args.mode, args.thread_id)
            if args.output.exists() or args.output.is_symlink():
                raise ValueError
            write_json(args.output, packet)
            result = dict(status='success', event_count=len(packet['events']), coverage=packet['coverage'])
    except (ConversionError, OSError, ValueError, TypeError, KeyError, OverflowError):
        result = dict(status='failed', error=dict(code='invalid_host_usage', message='宿主计量输入或任务绑定非法。'))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'success' else 2


if __name__ == '__main__':
    raise SystemExit(main())
