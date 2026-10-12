"""Recompute decision authority, continuity, validation and audit in one order."""
from contextlib import nullcontext
from dataclasses import dataclass
from agent_performance import stage
from video_seek import ConversionError


@dataclass
class DecisionReview:
    chosen: list
    content_checks: list
    authority: dict | None
    acceptance_record: dict | None
    continuity_record: dict | None
    audit: dict | None


def review(task, value, state, observation, *, submitted_path=None, accepted_entry=None, repeat=False):
    """Read submission sidecars or accepted history; never accept a draft here."""
    from agent_workflow import load_json, validate
    if (submitted_path is None) == (accepted_entry is None):
        raise ValueError('Specify one decision record source')
    submission = submitted_path is not None
    decision = value.get('decision', value)
    acceptance_record, authority = None, None
    if decision.get('visual_review') is False:
        from agent_acceptance import load_for_submit, check
        if submission:
            acceptance_record, authority = load_for_submit(submitted_path, value, state, observation, task, load_json)
        else:
            if not repeat and 'acceptance_path' not in accepted_entry:
                raise ConversionError('review_required', '混合决定缺少已保存脚本接受旁记录。')
            acceptance_record = load_json(task / accepted_entry['acceptance_path'])
            if not repeat and acceptance_record.get('decision_sha256') != accepted_entry['sha256']:
                raise ConversionError('invalid_decision', '接受旁记录不属于精确保存决定。')
            authority = check(acceptance_record, value, state, observation, task)
    continuity_record, continuity_clean = None, None
    from agent_evidence_chain import enabled, load_for_submit as load_continuity, check as check_continuity
    chain = bool(observation.get('minimum_evidence_chain_policy')) if repeat else enabled(state, observation)
    if chain:
        if submission:
            continuity_record, continuity_clean = load_continuity(submitted_path, value, state, observation, load_json)
        else:
            if 'continuity_path' not in accepted_entry:
                message = '接受历史缺少连续证据。' if repeat else '缺少已接受的连续证据旁记录。'
                raise ConversionError('review_required', message)
            continuity_record = load_json(task / accepted_entry['continuity_path'])
            continuity_clean = check_continuity(continuity_record, value, state, observation)
    content_checks = []
    with nullcontext() if repeat else stage('decision_validation'):
        chosen = validate(decision, state, observation, task, None if repeat else content_checks, authority, continuity_clean)
    if submission and content_checks:
        state['content_checks'] = content_checks
    audit = None
    if repeat or observation.get('evidence_mode') == 'lazy':
        from agent_audit import load_for_submit as load_audit, check as check_audit
        if not submission and not repeat and 'audit_path' not in accepted_entry:
            raise ConversionError('review_required', '实验 lazy 缺少已接受的整曲审计记录。')
        with nullcontext() if repeat else stage('coverage_audit'):
            audit = (load_audit(submitted_path, value, state, observation, load_json, authority) if submission else
                     check_audit(load_json(task / accepted_entry['audit_path']), value, state, observation, authority))
    return DecisionReview(chosen, content_checks, authority, acceptance_record, continuity_record, audit)
