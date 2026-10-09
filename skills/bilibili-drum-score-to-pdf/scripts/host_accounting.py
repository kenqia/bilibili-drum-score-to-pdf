"""Strict, credential-free caller accounting, separate from observation identity."""
import math
from pathlib import Path
import re
from video_seek import ConversionError
from PIL import Image

TOKEN_FIELDS = {'input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens',
                'cache_write_input_tokens', 'reasoning_output_tokens', 'text_input_tokens', 'image_input_tokens'}


def require(condition):
    if not condition:
        raise ValueError('invalid host accounting')


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', value))


def number(value):
    require(type(value) in (int, float))
    require(math.isfinite(value) and value >= 0)


def count(value):
    require(type(value) is int and 0 <= value <= 2**63-1)


def task_context(directory, load):
    ledger = load(directory / 'performance.json')
    require(isinstance(ledger, dict) and ledger.get('lifecycle_id') and ledger.get('task_id'))
    return ledger


def validate(packet, ledger, known_images):
    require(isinstance(packet, dict) and set(packet) == {'schema_version', 'lifecycle_id', 'task_id', 'source', 'scope', 'coverage', 'events'})
    require(type(packet['schema_version']) is int and packet['schema_version'] == 1)
    require(packet['lifecycle_id'] == ledger['lifecycle_id'] and packet['task_id'] == ledger['task_id'])
    source = packet['source']
    require(isinstance(source, dict) and set(source) == {'kind', 'id'} and source['kind'] in ('host', 'controlled_fixture', 'codex_desktop_jsonl'))
    identifier(source['id'])
    scope = packet['scope']
    require(isinstance(scope, dict) and set(scope) == {'invocation_id', 'root_thread_id', 'root_turn_id', 'started_at', 'ended_at', 'mode'})
    for name in ('invocation_id', 'root_thread_id', 'root_turn_id'):
        identifier(scope[name])
    require(scope['mode'] in ('review', 'replay'))
    for name in ('started_at', 'ended_at'):
        number(scope[name])
    require(scope['started_at'] <= scope['ended_at'])
    coverage = packet['coverage']
    require(isinstance(coverage, dict) and set(coverage) == {'model_calls_complete', 'tools_complete', 'images_complete', 'expected_response_ids', 'missing_reasons'})
    for name in ('model_calls_complete', 'tools_complete', 'images_complete'):
        require(type(coverage[name]) is bool)
    require(isinstance(coverage['expected_response_ids'], list) and len(coverage['expected_response_ids']) <= 100000)
    for value in coverage['expected_response_ids']:
        identifier(value)
    require(len(set(coverage['expected_response_ids'])) == len(coverage['expected_response_ids']))
    require(isinstance(coverage['missing_reasons'], list) and all(isinstance(x, str) and len(x) <= 256 for x in coverage['missing_reasons']))
    require(isinstance(packet['events'], list) and len(packet['events']) <= 100000)
    events = {}
    semantic = {}
    for event in packet['events']:
        require(isinstance(event, dict))
        common = {'kind', 'event_id', 'thread_id', 'timestamp'}
        kind = event.get('kind')
        fields = {'model_call': {'response_id', 'status', 'usage'},
                  'host_tool_call': {'call_id', 'tool_name', 'status'},
                  'image_presented': {'call_id', 'image_id', 'width', 'height', 'panel_count', 'source_pixels'}}
        require(kind in fields and set(event) == common | fields[kind])
        for name in ('event_id', 'thread_id'):
            identifier(event[name])
        number(event['timestamp'])
        require(scope['started_at'] <= event['timestamp'] <= scope['ended_at'])
        if kind == 'model_call':
            identifier(event['response_id'])
            require(event['status'] in ('complete', 'failed', 'cancelled', 'unknown'))
            usage = event['usage']
            if usage is not None:
                require(isinstance(usage, dict) and not set(usage)-TOKEN_FIELDS and {'input_tokens', 'output_tokens', 'total_tokens'} <= set(usage))
                for value in usage.values():
                    count(value)
                require(usage['input_tokens'] + usage['output_tokens'] == usage['total_tokens'])
                for name in ('cached_input_tokens', 'cache_write_input_tokens', 'text_input_tokens', 'image_input_tokens'):
                    require(usage.get(name, 0) <= usage['input_tokens'])
                require(usage.get('reasoning_output_tokens', 0) <= usage['output_tokens'])
                require(usage.get('cached_input_tokens', 0) + usage.get('cache_write_input_tokens', 0) <= usage['input_tokens'])
                require(usage.get('text_input_tokens', 0) + usage.get('image_input_tokens', 0) <= usage['input_tokens'])
            key = (kind, event['thread_id'], event['response_id'])
        elif kind == 'host_tool_call':
            for name in ('call_id', 'tool_name'):
                identifier(event[name])
            require(event['status'] in ('complete', 'failed', 'cancelled', 'unknown'))
            key = (kind, event['thread_id'], event['call_id'])
        else:
            identifier(event['call_id'])
            require(event['image_id'] in known_images)
            for name in ('width', 'height', 'panel_count', 'source_pixels'):
                count(event[name])
                require(event[name] > 0)
            require(event['source_pixels'] == known_images[event['image_id']])
            key = (kind, event['event_id'])  # repeat presentations each retain a delivery event
        require(event['event_id'] not in events or events[event['event_id']] == event)
        require(key not in semantic or semantic[key] == event)
        events[event['event_id']] = event
        semantic[key] = event
    return packet | {'events': list(events.values())}


def image_catalog(directory, load):
    observation = load(directory / 'observation.json')
    # Native source dimensions remain distinct from actual presented dimensions.
    catalog = {}
    for image in observation['images']:
        path = directory / image['path']
        require(not path.is_symlink() and path.resolve().is_relative_to(directory.resolve()))
        with Image.open(path) as raster:
            catalog[image['id']] = raster.width * raster.height
    return catalog


def import_packet(directory, packet, load, write):
    try:
        ledger = task_context(directory, load)
        known = image_catalog(directory, load)
        packet = validate(packet, ledger, known)
        path = directory / 'host-usage.json'
        if path.exists():
            previous = validate(load(path), ledger, known)
            require(previous['source'] == packet['source'])
            fixed = set(packet['scope']) - {'ended_at'}
            require(all(previous['scope'][k] == packet['scope'][k] for k in fixed))
            # Re-importing an older snapshot cannot erase later coverage or events.
            if packet['scope']['ended_at'] < previous['scope']['ended_at']:
                merged = previous | {'events': previous['events'] + packet['events']}
            else:
                merged = packet | {'events': previous['events'] + packet['events']}
            packet = validate(merged, ledger, known)
        write(path, packet)
        return summarize(packet, ledger, directory, load)
    except (ConversionError, OSError, ValueError, TypeError, KeyError, OverflowError):
        raise ConversionError('invalid_host_usage', '宿主计量字段、任务绑定或已有事件内容非法。') from None


def summarize(packet, ledger, directory, load):
    models = [e for e in packet['events'] if e['kind'] == 'model_call']
    tools = [e for e in packet['events'] if e['kind'] == 'host_tool_call']
    images = [e for e in packet['events'] if e['kind'] == 'image_presented']
    usages = [e['usage'] for e in models if e['usage'] is not None]
    observed = {k: sum(u[k] for u in usages if k in u) if usages and any(k in u for u in usages) else None for k in TOKEN_FIELDS}
    # Optional split totals are complete only when every response supplies the field.
    actual = {k: sum(u[k] for u in usages) if usages and all(k in u for u in usages) else None for k in TOKEN_FIELDS}
    ids = {e['response_id'] for e in models}
    missing = sorted(set(packet['coverage']['expected_response_ids']) - ids)
    missing_usage = [e['response_id'] for e in models if e['usage'] is None]
    end = ledger.get('first_deliverable_at')
    scope_closed = (end is not None and packet['scope']['started_at'] <= ledger['submitted_at'] and packet['scope']['ended_at'] >= end)
    complete = packet['coverage']['model_calls_complete'] and not missing and not missing_usage and scope_closed
    reasons = list(packet['coverage']['missing_reasons'])
    if not packet['coverage']['model_calls_complete']:
        reasons.append('model call coverage unavailable')
    if not scope_closed:
        reasons.append('invocation does not cover a delivered lifecycle')
    if missing or missing_usage:
        reasons.append('expected responses or usage missing')
    declared = None
    decision = directory / 'decision.json'
    if decision.exists():
        value = load(decision)
        declared = value.get('decision', value).get('presented_images')
    presented = {e['image_id'] for e in images}
    return dict(source=packet['source'], scope=packet['scope'], coverage=packet['coverage'],
                observed_actual_tokens=observed, model_tokens=actual if complete else None, token_complete=complete,
                model_call_count=len(models), failed_model_calls=sum(e['status'] == 'failed' for e in models),
                missing_response_ids=missing, missing_usage_response_ids=missing_usage,
                observed_host_tool_calls=len(tools), host_tool_calls=len(tools) if packet['coverage']['tools_complete'] and scope_closed else None,
                host_tool_types={name: sum(e['tool_name'] == name for e in tools) for name in sorted({e['tool_name'] for e in tools})},
                observed_image_presentations=len(images), actual_presented_images=len(images) if packet['coverage']['images_complete'] and scope_closed else None,
                unique_presented_images=len(presented), repeated_presentations=len(images)-len(presented),
                presented_pixels=sum(e['width']*e['height'] for e in images), source_pixels=sum(e['source_pixels'] for e in images),
                presented_panels=sum(e['panel_count'] for e in images),
                declared_presented_images_match=None if declared is None or not packet['coverage']['images_complete'] else set(declared) == presented,
                missing_measurements=sorted(set(reasons)))


def task_summary(directory, ledger, load):
    path = Path(directory) / 'host-usage.json'
    if not path.exists():
        return None
    try:
        packet = validate(load(path), ledger, image_catalog(directory, load))
        return summarize(packet, ledger, Path(directory), load)
    except (ConversionError, OSError, ValueError, TypeError, KeyError, OverflowError):
        raise ConversionError('invalid_host_usage', '已保存的宿主计量非法。') from None
