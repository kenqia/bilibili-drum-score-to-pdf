"""Bound expansion of review evidence without switching validation policies."""
from agent_regions import covered
from video_seek import ConversionError

SOFT_REASONS = {'candidate_shortage', 'native_review_pending', 'layout_unconfirmed'}


def hard_checks(checks):
    return [c for c in checks if c.get('status') == 'conflict' or c.get('reason') in
            ('unreliable_alignment', 'unreliable_five_line_spacing', 'uncertain_horizontal_extent')]


def remember_findings(task, result):
    from agent_workflow import load_json
    state = load_json(task / 'task.json')
    if state.get('workflow_mode') not in ('auto', 'fast'):
        return
    if result.get('sources', {}).get('agent_confirmations', {}).get('identity_verified') is not True:
        return
    hard = hard_checks(result.get('sources', {}).get('content_checks', []))
    hard.extend(dict(reason='geometry_conflict', message=i['message']) for i in result.get('unresolved', []) if i.get('hard_geometry'))
    if hard:
        remember_hard(task, state, hard)


def remember_hard(task, state, hard):
    from agent_workflow import write_json
    if state.get('workflow_mode') not in ('auto', 'fast') or state.get('workflow_findings'):
        return
    # The first hard finding survives later evidence versions. Full comparisons
    # remain in the originating build artifacts; do not duplicate a large ledger.
    counts = {}
    for finding in hard:
        counts[finding['reason']] = counts.get(finding['reason'], 0) + 1
    state['workflow_findings'] = dict(observation_sha256=state['observation_sha256'], reasons=counts)
    write_json(task / 'task.json', state)



def routing(state, packet):
    expanded = bool(state.get('full_review_attempts')) or any(e['request_id'].startswith('stronger-review-') for e in packet.get('evidence_updates', []))
    hard = bool(state.get('workflow_findings') or hard_checks(state.get('content_checks', [])))
    missing = any(not covered([0,0,f['width'],f['height']], [i['bbox'] for i in packet['images']
        if i.get('frame_id') == f['id'] and i['kind'] in ('detail','native_detail')]) for f in packet['frames'])
    available = state.get('workflow_mode') == 'auto' and not expanded and not hard and missing
    return dict(mode=state['workflow_mode'], automatic_full_review_available=available,
                hard_findings=hard, full_review_rounds=int(expanded), max_full_review_rounds=1,
                next_action='Search and review existing candidates first; strengthen missing native review only if necessary.'
                    if available else 'Review remaining evidence locally or keep waiting; no automatic full expansion.')

def strengthen(task, request_path):
    from agent_workflow import checked_task, load_json, write_json
    from agent_evidence import materialize
    state, packet = checked_task(task)
    request = load_json(request_path)
    fields = {'schema_version', 'task_id', 'observation_sha256', 'observation_version', 'reason'}
    if (not isinstance(request, dict) or set(request) != fields or type(request['schema_version']) is not int
            or request['schema_version'] != 1 or type(request['observation_version']) is not int
            or any(request[k] != state[k] for k in ('task_id', 'observation_sha256', 'observation_version'))
            or request['reason'] not in SOFT_REASONS):
        raise ConversionError('invalid_request', '加强审阅须绑定当前任务并说明可恢复的软缺口。')
    if state.get('workflow_mode') not in ('auto', 'fast') or packet['evidence_mode'] != 'lazy':
        raise ConversionError('invalid_input', '加强审阅只扩充 auto/fast 任务证据，不切换验证器。')
    if state.get('workflow_findings') or hard_checks(state.get('content_checks', [])):
        raise ConversionError('hard_evidence_conflict', '已有明确内容或对齐冲突，禁止以全量回退绕过。')
    history = [e for e in packet.get('evidence_updates', []) if e['request_id'].startswith('stronger-review-')]
    if history or state.get('full_review_attempts'):
        raise ConversionError('sampling_budget', '整包加强审阅已执行一轮，继续局部核查或保留 waiting。')
    regions = []
    for f in packet['frames']:
        bbox = [0, 0, f['width'], f['height']]
        details = [i['bbox'] for i in packet['images'] if i.get('frame_id') == f['id']
                   and i['kind'] in ('detail', 'native_detail')]
        if not covered(bbox, details):
            regions.append(dict(frame_id=f['id'], frame_sha256=f['sha256'], pts=f['pts'], time_base=f['time_base'], bbox=bbox))
    if len(packet['frames']) > 96:
        raise ConversionError('sampling_budget', '加强审阅超出96张原帧上限。')
    # One materialize publication retains accepted history, budgets and source PTS.
    # If everything is already covered, record a cache-only publication so this
    # round remains durable and repeated fallback cannot restart its budget.
    if not regions:
        f = packet['frames'][0]
        detail = next(i for i in packet['images'] if i.get('frame_id') == f['id'] and i['kind'] in ('detail', 'native_detail'))
        regions = [dict(frame_id=f['id'], frame_sha256=f['sha256'], pts=f['pts'], time_base=f['time_base'], bbox=detail['bbox'])]
    roi = dict(schema_version=1, task_id=state['task_id'], observation_sha256=state['observation_sha256'],
               observation_version=state['observation_version'], source_sha256=packet['source']['sha256'],
               request_id='stronger-review-1', reason=request['reason'], regions=regions)
    path = task / 'stronger-review-request.json'
    state['full_review_attempts'] = 1
    write_json(task / 'task.json', state)
    write_json(path, roi)
    result = materialize(task, path)
    result['metrics'].update(seek_count=0, thumbnail_checks=0)
    result['next_action'] = 'Actually review all native evidence and rebind the decision; original lazy gates remain active.'
    return result
