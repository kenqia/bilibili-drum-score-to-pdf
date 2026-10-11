"""Reuse verified observations and search real candidates before decision building.

Historical identities and selected PTS are suggestions, never new visual reviews.
"""
import copy
import shutil
from pathlib import Path
from PIL import Image
from agent_performance import stage
from video_seek import ConversionError

POLICY = 'clean_sources_v1'


def enabled(state, packet):
    value = packet.get('evidence_recovery_policy')
    if value is None and state.get('evidence_recovery_policy') is None:
        return False
    if value != POLICY or state.get('evidence_recovery_policy') != POLICY or packet.get('evidence_mode') != 'lazy' or not packet.get('minimum_evidence_chain_policy'):
        raise ConversionError('invalid_task', '原生证据恢复策略必须在新 lazy 最小链任务固定。')
    return True


def seed(reference, output, script_acceptance, minimum_evidence_chain, evidence_recovery, mode=None):
    from agent_workflow import checked_task, digest, load_json, write_json, prepare
    reference = Path(reference)
    with stage('source_verification'):
        state, packet = checked_task(reference, recover=False)
    source = Path(packet['source']['path'])
    destination = output / ('source' + source.suffix)
    shutil.copyfile(source, destination)
    if digest(destination) != packet['source']['sha256']:
        raise ConversionError('source_mismatch', '独立视频副本与可信来源不一致。')
    prior = copy.deepcopy(packet)
    prior.pop('workflow_mode', None)
    if mode:
        prior['workflow_mode'] = mode
    prior['images'] = [i for i in prior['images'] if i['kind'] == 'native']
    for frame in prior['frames']:
        source = reference / frame['path']
        if source.parent != reference or source.is_symlink() or digest(source) != frame['sha256']:
            raise ConversionError('source_mismatch', '复用原帧来源已改变。')
        shutil.copyfile(source, output / frame['path'])
    # Do not migrate accepted reviews, evidence updates or policy from the old task.
    prior.pop('evidence_updates', None)
    prior['script_acceptance_policy'] = 'continuous_clean_v1' if script_acceptance else None
    prior['minimum_evidence_chain_policy'] = 'ordered_anchors_v1' if minimum_evidence_chain else None
    prior['evidence_recovery_policy'] = POLICY if evidence_recovery else None
    if state.get('decision_history'):
        entry = state['decision_history'][-1]
        value = load_json(reference / entry['path'])
        decision = value.get('decision', value)
        proposal = {k: copy.deepcopy(decision[k]) for k in ('schema_version', 'segments', 'boundaries', 'coverage') if k in decision}
        if decision['schema_version'] not in (3, 4):
            raise ConversionError('invalid_input', '接受结构复用仅支持 v3/v4 连续谱面任务。')
        if decision['schema_version'] == 3:
            proposal = {k: copy.deepcopy(decision[k]) for k in ('schema_version', 'rows', 'observations', 'transitions', 'coverage')}
        from agent_decision_builder import clear_review
        clear_review(proposal)
        for part in proposal.get('segments', [proposal]):
            for row in part['rows'] + [e['region'] for e in part.get('extras', [])]:
                row['evidence_images'] = []
        write_json(output / 'seed-proposal.json', proposal)
    prior['recovery_seed'] = dict(task_id=state['task_id'], observation_sha256=state['observation_sha256'],
        decision_sha256=state.get('decision_history', [{}])[-1].get('sha256') if state.get('decision_history') else None,
        reused_frames=len(prior['frames']), historical_sampling=copy.deepcopy(packet['sampling']),
        reviews_reused=False, independent_source=True)
    sampling = copy.deepcopy(packet['sampling'])
    sampling['thumbnail_checks'] = 0
    sampling['thumbnail_elapsed'] = 0
    # Limits count retained evidence as well as new work. Historical decode costs
    # remain in provenance; current prepare performs no seeks or navigation.
    result = prepare(destination, output, origin=packet['source'].get('origin'),
        timestamps=[], sampling=sampling, prior=prior, version=packet.get('observation_version', 1), evidence_mode='lazy')
    return result


def candidate_plan(task, output, request_path=None):
    from agent_workflow import checked_task, load_json, write_json
    from agent_content import local_ink
    state, packet = checked_task(task)
    request = load_json(request_path) if request_path else None
    if request is not None:
        fields = {'schema_version', 'task_id', 'observation_sha256', 'observation_version', 'proposal'}
        if not isinstance(request, dict) or set(request) != fields or type(request['schema_version']) is not int or request['schema_version'] != 1 or any(request[k] != state[k] for k in ('task_id', 'observation_sha256', 'observation_version')):
            raise ConversionError('invalid_request', '候选搜索须绑定当前观察包。')
        proposal = request['proposal']
    else:
        if (task / 'seed-proposal.json').exists():
            proposal = load_json(task / 'seed-proposal.json')
        else:
            from agent_proposals import suggest
            proposal = suggest(packet)['structure']
    if not isinstance(proposal, dict) or proposal.get('schema_version') not in (3, 4):
        raise ConversionError('invalid_request', '候选搜索需要 v3/v4 连续谱面的观察身份建议。')
    from agent_decision_builder import check_structure
    check_structure(proposal, packet)
    frames = {f['id']: f for f in packet['frames']}
    parts = proposal['segments'] if proposal['schema_version'] == 4 else [proposal]
    results = []
    native_reads = 0
    with stage('candidate_search'):
        for part in parts:
            candidates = {}
            for fid in part.get('frames', list(frames)):
                with Image.open(task / frames[fid]['path']) as image:
                    native_reads += 1
                    for s in part['observations']:
                        if s['frame_id'] != fid:
                            continue
                        # Proposal completeness is unconfirmed. This is a pixel
                        # preflight only; actual full edges remain Agent authority.
                        mask, reason, pixels = local_ink(image, {**s, 'complete': True})
                        f = frames[fid]
                        candidate = dict(observation_id=s['id'], frame_id=fid, bbox=s['bbox'],
                            frame_sha256=f['sha256'], pts=f['pts'], time_base=f['time_base'], timestamp=f['timestamp'],
                            pixel_status='candidate' if mask is not None else 'uncertain', reason=reason,
                            analyzed_pixels=pixels, actual_native_review=False)
                        candidates.setdefault(s['instance_id'], []).append(candidate)
            for row in part['rows']:
                options = candidates.get(row['instance_id'], [])
                options.sort(key=lambda c: (c['pixel_status'] != 'candidate', c['observation_id'] != row['observation_id'], c['timestamp']))
                good = [c for c in options if c['pixel_status'] == 'candidate']
                results.append(dict(instance_id=row['instance_id'], preferred_observation=row['observation_id'],
                    selected=good[0] if good else None, alternatives=options,
                    next_action='Review the selected full native band.' if good else
                        'Review existing boundary proposals before requesting a bounded local supplement.'))
    result = dict(status='waiting', complete=False, phase='candidate_search', task_id=state['task_id'],
        observation_sha256=state['observation_sha256'], observation_version=state['observation_version'],
        source_sha256=packet['source']['sha256'], native_reads=native_reads,
        row_count=len(results), rows_with_candidates=sum(r['selected'] is not None for r in results),
        rows=results, identities_confirmed=False, review_reused=False,
        next_action='Review actual candidates and missing intervals before build-decision.')
    write_json(output / 'candidate-plan.json', result)
    write_json(output / 'proposal.json', proposal)
    return {k: result[k] for k in ('status', 'complete', 'phase', 'row_count', 'rows_with_candidates', 'native_reads', 'next_action')} | {'plan': str((output / 'candidate-plan.json').resolve())}
