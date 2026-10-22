"""Source review assertions bound to selected captures, never simulated vision."""
import copy

from score_task import ReconstructionError

CONTRACT = 'agent-source-review/2'


def validate(record, regions, review, *, same=False, upgrade=False, title=None):
    """Keep one source review and native-view receipts, without per-row forms."""
    active = bool(record.get('agent_review_contract')) or upgrade and bool(record.get('regions')) and not same
    if not active:
        return copy.deepcopy(review), False
    for field in ('notes', 'continuity', 'first_last'):
        if not isinstance(review.get(field), str) or not review[field].strip():
            raise ReconstructionError('说明谱名、首尾和实际接续依据。',
                code='source_review_required', field='review.' + field, action='assemble')
    viewed = review.get('viewed_captures')
    if (not isinstance(viewed, list) or any(not isinstance(item, str) for item in viewed)
            or type(review.get('complete')) is not bool
            or not isinstance(review.get('unresolved', []), list)):
        raise ReconstructionError('需要已查看来源列表、完整性确认及未决项列表。',
            code='source_review_required', field='review', action='assemble')
    positions = [r.get('position') for r in regions]
    if (any(not isinstance(p, str) or not p.strip() for p in positions)
            or len(set(positions)) != len(positions)):
        raise ReconstructionError('每个原谱位置只能选择一个明确来源。',
            code='source_review_required', field='regions.position', action='assemble')
    if review.get('complete') is True and not review.get('unresolved'):
        selected = {r['capture'] for r in regions}
        presented = {identifier for item in record.get('presentations', []) for identifier in item['images']}
        if not selected.issubset(set(viewed) & presented):
            raise ReconstructionError('实际查看全部所选原生截图并通过 present 留下记录。',
                code='source_review_required', field='review.viewed_captures', action='present')
    return {**copy.deepcopy(review), 'evidence_version': CONTRACT,
            'source_sha256': record['source']['sha256']}, True


def source_handoff(record):
    captures = [{key: shot[key] for key in ('id', 'path', 'sha256', 'pts', 'time_base', 'timestamp')}
                for shot in record['captures']]
    unresolved = record.get('source_review', {}).get('unresolved', [])
    last = max(0, record['source']['duration'] - record['source'].get('frame_duration', .04))
    return {'phase': 'source', 'status': 'blocked' if unresolved else 'pending', 'complete': False,
            'artifacts': {'captures': captures}, 'unresolved': unresolved,
            'provenance': {'producer': 'agent', 'reviewed': False},
            'sampling_suggestions': [{'seconds': 0, 'purpose': 'title and music start'},
                                     {'seconds': last, 'purpose': 'last complete system and ending'}],
            'next': {'operation': 'capture', 'request': {'seconds': 0},
                     'operations': ['navigate', 'capture', 'promote', 'present', 'assemble'],
                     'instruction': '查看原生首尾图，再按可见接续补采；以明确原谱位置提交有序完整谱行。',
                     'review_template': {'viewed_captures': [], 'complete': False, 'unresolved': [],
                         'notes': '', 'continuity': '', 'first_last': ''}}}


def merge_review(record, regions, patch):
    """Retain context; only an explicit new decision can approve revised sources."""
    return {**copy.deepcopy(record.get('source_review', {})), **copy.deepcopy(patch),
            'complete': patch.get('complete', False)}
