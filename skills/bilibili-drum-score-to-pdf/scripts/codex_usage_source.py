"""Whitelist metric metadata from explicitly scoped Desktop session files."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from host_accounting import TOKEN_FIELDS, identifier, number, require, task_context, validate, image_catalog


def timestamp(value):
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            value = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    number(value)
    return value


def homes(explicit=None):
    if explicit:
        return [Path(explicit)]
    candidates = [Path(os.environ['CODEX_HOME'])] if os.environ.get('CODEX_HOME') else []
    candidates.append(Path.home() / '.codex')
    users = Path('/mnt/c/Users')
    if users.is_dir():
        candidates.extend(user / '.codex' for user in sorted(users.iterdir()) if user.is_dir())
    result, seen = [], set()
    for path in candidates:
        if path.is_dir():
            stat = path.stat()
            key = (stat.st_dev, stat.st_ino)
            if key not in seen:
                result.append(path)
                seen.add(key)
    return result


def session_metadata(home):
    """Read only the first record before deciding whether a file belongs to scope."""
    result, seen = [], set()
    for category in ('sessions', 'archived_sessions'):
        directory = home / category
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob('*.jsonl')):
            stat = path.stat()
            key = (stat.st_dev, stat.st_ino)
            if key in seen:
                continue
            seen.add(key)
            with path.open() as stream:
                try:
                    first = json.loads(stream.readline())
                    if first.get('type') != 'session_meta':
                        continue
                    payload = first.get('payload', {})
                    source = payload.get('source')
                    spawn = source.get('subagent', {}).get('thread_spawn', {}) if isinstance(source, dict) else {}
                    meta = {k: payload.get(k) for k in ('id', 'session_id', 'cwd', 'originator')}
                    meta['parent'] = spawn.get('parent_thread_id')
                    result.append((path, meta))
                except (ValueError, TypeError, AttributeError):
                    continue
    return result


def collect(directory, root, root_turn, invocation, start, end, home, load, cwd, mode, threads):
    for value in (root, invocation):
        identifier(value)
    start, end = timestamp(start), timestamp(end)
    require(start <= end)
    ledger = task_context(directory, load)
    matches = []
    for candidate in homes(home):
        metas = session_metadata(candidate)
        roots = [(path, meta) for path, meta in metas if meta['id'] == root and meta['cwd'] == str(Path(cwd).resolve()) and meta['originator'] == 'Codex Desktop']
        if roots:
            matches.append((metas, roots))
            break  # Prefer the authoritative current home; never merge fallback homes.
    require(len(matches) == 1)
    metas, roots = matches[0]
    require(all(meta['session_id'] == root and meta['parent'] is None for _, meta in roots))
    if root_turn is None:
        latest, turns = None, set()
        for path, _ in roots:
            with path.open() as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                        payload = record.get('payload', {})
                        if record.get('type') in ('turn_context', 'event_msg') and payload.get('root_turn_id'):
                            when = timestamp(record.get('timestamp'))
                            if when <= end and (latest is None or when > latest):
                                latest, turns = when, {payload['root_turn_id']}
                            elif when == latest:
                                turns.add(payload['root_turn_id'])
                    except json.JSONDecodeError:
                        continue
        require(len(turns) == 1)
        root_turn = turns.pop()
    identifier(root_turn)
    lineage = {root}
    changed = True
    while changed:
        before = len(lineage)
        lineage.update(meta['id'] for _, meta in metas if meta['parent'] in lineage and meta['session_id'] == root and meta['cwd'] == str(Path(cwd).resolve()) and meta['originator'] == 'Codex Desktop')
        changed = len(lineage) != before
    # Continuations share first-record ownership; a conflicting owner cannot
    # contribute events merely because another file granted the same thread ID.
    owners = {}
    for _, meta in metas:
        if meta['id'] in lineage:
            require(meta['id'] not in owners or owners[meta['id']] == meta)
            owners[meta['id']] = meta
    require(bool(threads) and set(threads) <= lineage)
    for thread in threads:
        identifier(thread)
    selected = sorted((path, meta) for path, meta in metas if meta['id'] in threads)
    events = []
    for path, meta in selected:
        turn = None
        with path.open() as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                    kind, payload = record.get('type'), record.get('payload', {})
                    if kind in ('turn_context', 'event_msg') and payload.get('root_turn_id'):
                        turn = payload['root_turn_id']
                    if kind not in ('token_usage_record', 'response_item'):
                        continue
                    when = timestamp(record.get('timestamp'))
                    if not start <= when <= end:
                        continue
                    thread = meta['id']
                    if kind == 'token_usage_record':
                        if payload.get('root_turn_id') != root_turn or payload.get('thread_id') != thread:
                            continue
                        response = payload.get('response_id')
                        identifier(response)
                        usage = payload.get('usage')
                        if isinstance(usage, dict):
                            # Unknown provider semantics must not silently appear complete.
                            require(not set(usage)-TOKEN_FIELDS)
                            usage = {k: usage[k] for k in TOKEN_FIELDS if k in usage}
                        event = dict(kind='model_call', response_id=response, status='unknown', usage=usage)
                        identity = 'usage.' + thread + '.' + response
                    elif turn == root_turn and payload.get('type') in ('custom_tool_call', 'function_call'):
                        call, name = payload.get('call_id'), payload.get('name')
                        identifier(call)
                        identifier(name)
                        status = {'completed': 'complete', 'failed': 'failed', 'cancelled': 'cancelled'}.get(payload.get('status'), 'unknown')
                        event = dict(kind='host_tool_call', call_id=call, tool_name=name, status=status)
                        identity = 'tool.' + thread + '.' + call
                    else:
                        continue
                    events.append(event | dict(event_id=hashlib.sha256(identity.encode()).hexdigest(), thread_id=thread, timestamp=when))
                except json.JSONDecodeError:
                    # An active session may end in an incomplete JSON line; coverage stays partial.
                    continue
    packet = dict(schema_version=1, lifecycle_id=ledger['lifecycle_id'], task_id=ledger['task_id'],
                  source=dict(kind='codex_desktop_jsonl', id='desktop-' + root),
                  scope=dict(invocation_id=invocation, root_thread_id=root, root_turn_id=root_turn, started_at=start, ended_at=end, mode=mode, thread_ids=sorted(set(threads))),
                  coverage=dict(lifecycle_complete=False, model_calls_complete=False, tools_complete=False, images_complete=False,
                                expected_response_ids=[], missing_reasons=['Desktop source lacks response-start and failed-call coverage',
                                'Nested tool calls and actual image presentations are not fully observable']), events=events)
    return validate(packet, ledger, image_catalog(directory, load))
