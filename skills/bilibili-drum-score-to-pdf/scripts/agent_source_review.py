"""Source-bound Agent evidence. Records assertions, never simulates vision."""
import copy
import hashlib
import json

from score_task import ReconstructionError

CONTRACT = 'agent-source-review/1'


def reference(region):
    return {key: region[key] for key in ('position', 'capture', 'bbox')}


def issue_inventory(record):
    """Keep original automatic doubts even after a manual selection replaces them."""
    items = {item['id']: copy.deepcopy(item) for item in record.get('source_issue_history', [])}
    groups = [('program', record.get('program_checks', {}).get('unresolved', [])),
              ('navigation', record.get('navigation', {}).get('unresolved', [])),
              ('rows', record.get('row_manifest', {}).get('unresolved', [])),
              ('review', record.get('source_review', {}).get('unresolved', []))]
    for origin, issues in groups:
        for issue in issues:
            identity = {'source_sha256': record['source']['sha256'], 'origin': origin, 'issue': issue}
            identifier = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            items.setdefault(identifier, {'id': identifier, **identity})
    return list(items.values())


def _fail(message, field='review'):
    raise ReconstructionError(message, code='source_review_required', field=field,
                              action='present, source-issues, then assemble with actual evidence')


def _check_shapes(review):
    evidence = review.get('evidence', {})
    if not isinstance(evidence, dict):
        _fail('审阅依据必须为对象。', 'review.evidence')
    joins = evidence.get('joins', [])
    if not isinstance(joins, list) or any(not isinstance(j, dict) or any(
            not isinstance(j.get(side), dict) or not isinstance(j[side].get('position'), str)
            for side in ('previous', 'current')) for j in joins):
        _fail('接续依据必须引用原谱位置。', 'review.evidence.joins')
    decisions = review.get('issue_dispositions', [])
    if not isinstance(decisions, list) or any(not isinstance(d, dict) or not isinstance(d.get('id'), str)
                                           for d in decisions):
        _fail('疑点处理记录必须为列表。', 'review.issue_dispositions')
    viewed = review.get('viewed_captures', [])
    if not isinstance(viewed, list) or any(not isinstance(v, str) for v in viewed):
        _fail('已查看来源必须为截图标识列表。', 'review.viewed_captures')


def _legacy_approval(record, regions):
    """Carry only verified, unchanged old manual sources into the new contract."""
    if record.get('agent_review_contract'):
        return record.get('legacy_source_approval', {})
    from automatic_score import _fingerprint
    frozen = record.get('freeze', {})
    if (frozen.get('producer') != 'agent' or frozen.get('fingerprint') != _fingerprint(record)
            or record.get('source_review', {}).get('complete') is not True
            or record['source_review'].get('unresolved')):
        return {}
    mapped = []
    fields = ('capture', 'bbox', 'kind', 'staff_top', 'staff_spacing')
    for old in record['regions']:
        matches = [r for r in regions if all(r.get(k) == old.get(k) for k in fields)
                   and (not old.get('position') or old['position'] == r['position'])]
        mapped.append(copy.deepcopy(matches[0]) if len(matches) == 1 else None)
    systems = [r for r, old in zip(mapped, record['regions']) if old.get('kind', 'system') == 'system']
    title_index = next((i for i, r in enumerate(record['regions']) if r.get('kind') == 'header'), 0)
    endpoints = {'title': mapped[title_index], 'first': systems[0] if systems else None,
                 'last': systems[-1] if systems else None}
    return {'regions': [r for r in mapped if r],
            'joins': [[reference(a), reference(b)] for a, b in zip(systems, systems[1:]) if a and b],
            'endpoints': {name: reference(r) for name, r in endpoints.items() if r},
            'title': record.get('title')}


def validate(record, regions, review, *, same=False, upgrade=False, title=None):
    """Validate new contracts and upgrade changed manual selections, not old freezes."""
    active = record.get('agent_review_contract') == CONTRACT or bool(review.get('evidence'))
    upgrade = upgrade and bool(record.get('regions')) and not same
    if not active and not upgrade:
        return copy.deepcopy(review), issue_inventory(record), False
    _check_shapes(review)
    regions = copy.deepcopy(regions)
    if any(not isinstance(r.get('position'), str) or not r['position'].strip() for r in regions):
        _fail('每个来源位置需要明确标签。', 'regions')
    if len({r['position'] for r in regions}) != len(regions):
        _fail('同位置只能选择一个来源。', 'regions.position')
    legacy = _legacy_approval(record, regions)
    inherited = [r for r in regions if any(all(r.get(k) == old.get(k) for k in
                 ('position', 'capture', 'bbox', 'kind', 'staff_top', 'staff_spacing'))
                 for old in legacy.get('regions', []))]
    if legacy:
        record['legacy_source_approval'] = copy.deepcopy(legacy)
    presented = {identifier for item in record.get('presentations', []) for identifier in item['images']}
    selected = {r['capture'] for r in regions if r not in inherited}
    result = copy.deepcopy(review)
    issues = issue_inventory(record)
    if review.get('complete') is not True or review.get('unresolved'):
        return result, issues, True
    if not selected.issubset(presented):
        _fail('先实际查看所选原生截图并通过 present 留下记录。', 'review.viewed_captures')
    evidence = review.get('evidence')
    if not isinstance(evidence, dict):
        _fail('需要标题、音乐起点、末行和相邻来源的结构化审阅依据。', 'review.evidence')
    systems = [r for r in regions if r.get('kind', 'system') == 'system']
    if not systems:
        _fail('整曲来源至少需要一条完整谱行。', 'regions')
    by_position = {r['position']: r for r in regions}
    viewed_items = review.get('viewed_captures', [])
    if not isinstance(viewed_items, list) or any(not isinstance(v, str) for v in viewed_items):
        _fail('已查看来源必须为截图标识列表。', 'review.viewed_captures')
    viewed = set(viewed_items)

    def verify_ref(item, expected=None):
        if not isinstance(item, dict) or not isinstance(item.get('position'), str):
            _fail('审阅依据必须引用具体原谱位置、截图与裁剪。', 'review.evidence')
        region = by_position.get(item.get('position'))
        if region is None or reference(region) != {k: item.get(k) for k in ('position', 'capture', 'bbox')}:
            _fail('审阅依据已过期或来源不匹配。', 'review.evidence')
        if item['capture'] not in viewed or expected is not None and item['position'] != expected['position']:
            _fail('审阅依据未覆盖对应原生来源。', 'review.evidence')

    for name, expected in (('title', next((r for r in regions if r.get('kind') == 'header'), regions[0])),
                           ('first', systems[0]), ('last', systems[-1])):
        if (expected in inherited and reference(expected) == legacy.get('endpoints', {}).get(name)
                and name not in evidence and
                (name != 'title' or (title if title is not None else record.get('title')) == legacy.get('title'))):
            continue
        item = evidence.get(name)
        verify_ref(item, expected)
        if not isinstance(item.get('notes'), str) or not item['notes'].strip():
            _fail('标题与首尾必须分别留下实际审阅依据。', 'review.evidence.' + name)
    joins = evidence.get('joins')
    required = [(a, b) for a, b in zip(systems, systems[1:]) if not
                (a in inherited and b in inherited and [reference(a), reference(b)] in legacy.get('joins', []))]
    if not isinstance(joins, list) or len(joins) not in (len(required), len(systems) - 1):
        _fail('需要逐个相邻原谱位置的接续依据。', 'review.evidence.joins')
    pairs = list(zip(systems, systems[1:])) if len(joins) == len(systems) - 1 else required
    for join, (previous, current) in zip(joins, pairs):
        if not isinstance(join, dict):
            _fail('接续依据必须为对象。', 'review.evidence.joins')
        verify_ref(join.get('previous'), previous)
        verify_ref(join.get('current'), current)
        if join.get('method') not in ('same_capture', 'overlap', 'ordered_page', 'numbered') or not isinstance(
                join.get('notes'), str) or not join['notes'].strip():
            _fail('接续必须说明实际采用的依据。', 'review.evidence.joins')
        if join['method'] == 'same_capture' and previous['capture'] != current['capture']:
            _fail('同图接续不能用于不同截图。', 'review.evidence.joins')
    dispositions = result.get('issue_dispositions', [])
    if not isinstance(dispositions, list) or any(not isinstance(d, dict) for d in dispositions):
        _fail('疑点处理记录必须为列表。', 'review.issue_dispositions')
    known = {item['id']: item for item in issues}
    decisions = {}
    for decision in dispositions:
        identifier = decision.get('id')
        if not isinstance(identifier, str) or identifier not in known or identifier in decisions or decision.get('outcome') not in ('resolved', 'unresolved'):
            _fail('疑点处理引用无效、重复或结果未知。', 'review.issue_dispositions')
        if not isinstance(decision.get('notes'), str) or not decision['notes'].strip() or not isinstance(
                decision.get('captures'), list) or not decision['captures'] or any(not isinstance(c, str) for c in decision['captures']) or not set(decision['captures']).issubset(viewed & presented):
            _fail('每项疑点处理都需要实际查看的来源和具体依据。', 'review.issue_dispositions')
        issue = known[identifier]['issue']
        from row_manifest import affects
        scoped = [r for r in regions if isinstance(issue, dict) and affects(issue, r)]
        bindings = [reference(r) for r in (scoped or regions) if r['capture'] in decision['captures']]
        if not bindings or decision.get('selection_refs', bindings) != bindings:
            _fail('疑点处理依据已因选源修改而失效。', 'review.issue_dispositions')
        decision['selection_refs'] = bindings
        decisions[identifier] = decision
    if any(decisions.get(identifier, {}).get('outcome') != 'resolved' for identifier in known):
        _fail('已有来源疑点需要逐项处理；整体 complete 不能替代处理依据。', 'review.issue_dispositions')
    result.update(evidence_version=CONTRACT, source_sha256=record['source']['sha256'])
    return result, issues, True


def source_handoff(record):
    issues = issue_inventory(record)
    refs = [reference(r) for r in record.get('regions', []) if r.get('position')]
    resolved = {d['id'] for d in record.get('source_review', {}).get('issue_dispositions', [])
                if d.get('outcome') == 'resolved' and d.get('selection_refs')
                and all(ref in refs for ref in d['selection_refs'])}
    issues = [item for item in issues if item['id'] not in resolved]
    captures = [{key: shot[key] for key in ('id', 'path', 'sha256', 'pts', 'time_base', 'timestamp')}
                for shot in record['captures']]
    scan = record.get('overview', {}).get('scan', {})
    from automatic_score import SCAN_POLICY_VERSION
    strict_coverage = scan.get('complete') is True and scan.get('policy_version') == SCAN_POLICY_VERSION
    duration = record['source']['duration']
    last = max(0, duration - record['source'].get('frame_duration', .04))
    return {'phase': 'source', 'status': 'blocked' if issues else 'pending', 'complete': False,
            'artifacts': {'captures': captures}, 'unresolved': issues,
            'provenance': {'producer': 'agent', 'reviewed': False, 'strict_time_coverage': strict_coverage, 'scan_performed': False},
            'sampling_suggestions': [{'seconds': 0, 'purpose': 'title and music start'},
                                     {'seconds': last, 'purpose': 'last complete system and ending'}],
            'next': {'operation': 'capture', 'request': {'seconds': 0},
                     'operations': ['navigate', 'capture', 'promote', 'present', 'source-issues', 'assemble'],
                     'required_fields': {'present': ['identifiers', 'notes'],
                                         'assemble': ['title', 'regions', 'review']},
                     'instruction': '实际查看原生截图后 present；按原谱位置选行，确认标题、首尾、接续与已有疑点。',
                     'review_template': {'viewed_captures': [], 'complete': False, 'unresolved': [],
                         'notes': '', 'continuity': '', 'first_last': '',
                         'evidence': {'title': {'position': '', 'capture': '', 'bbox': [], 'notes': ''},
                                      'first': {'position': '', 'capture': '', 'bbox': [], 'notes': ''},
                                      'last': {'position': '', 'capture': '', 'bbox': [], 'notes': ''},
                                      'joins': []}, 'issue_dispositions': []}}}


def merge_review(record, regions, patch):
    """Reuse evidence for unchanged positions; callers replace only affected items."""
    previous = copy.deepcopy(record.get('source_review', {}))
    old_evidence = previous.get('evidence', {})
    new_evidence = patch.get('evidence', {})
    _check_shapes(patch)
    merged = {**previous, **patch}
    if old_evidence or new_evidence:
        merged['evidence'] = {**old_evidence, **new_evidence}
        if 'joins' in new_evidence:
            joins = {item['current']['position']: item for item in old_evidence.get('joins', [])}
            joins.update({item['current']['position']: item for item in new_evidence['joins']})
            systems = [r for r in regions if r.get('kind', 'system') == 'system']
            merged['evidence']['joins'] = [joins[r['position']] for r in systems[1:] if r['position'] in joins]
    current_refs = [reference(r) for r in regions]
    decisions = {d['id']: d for d in previous.get('issue_dispositions', [])
                 if d.get('selection_refs') and all(ref in current_refs for ref in d['selection_refs'])}
    decisions.update({d['id']: d for d in patch.get('issue_dispositions', [])})
    merged['issue_dispositions'] = list(decisions.values())
    return merged
