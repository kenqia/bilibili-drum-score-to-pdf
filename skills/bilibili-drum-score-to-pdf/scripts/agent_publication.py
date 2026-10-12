"""Publish bound observation records and finish interrupted publication forward."""
import os
from video_seek import ConversionError


def publish(task, observation, sampling, state):
    from agent_workflow import write_json, digest
    write_json(task / 'observation.next.json', observation)
    write_json(task / 'sampling.next.json', sampling)
    updated = state | dict(observation_sha256=digest(task / 'observation.next.json'),
                           sampling_sha256=digest(task / 'sampling.next.json'))
    write_json(task / 'task.next.json', updated)
    write_json(task / 'publication.json', dict(observation_sha256=updated['observation_sha256'],
               sampling_sha256=updated['sampling_sha256'], state_sha256=digest(task / 'task.next.json')))
    recover(task)
    return updated


def recover(task):
    from agent_workflow import load_json, digest
    journal = task / 'publication.json'
    if not journal.exists():
        return
    record = load_json(journal)
    if set(record) != {'observation_sha256', 'state_sha256', 'sampling_sha256'}:
        raise ConversionError('invalid_task', '观察发布记录非法。')
    for stem, key in [('observation', 'observation_sha256'), ('sampling', 'sampling_sha256'), ('task', 'state_sha256')]:
        pending = task / f'{stem}.next.json'
        current = task / f'{stem}.json'
        path = pending if pending.exists() else current
        if digest(path) != record[key]:
            raise ConversionError('source_mismatch', '中断发布记录已损坏。')
        if pending.exists():
            os.replace(pending, current)
    journal.unlink()
