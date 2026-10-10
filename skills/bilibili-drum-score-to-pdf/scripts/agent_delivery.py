"""Explicit caller review of exported pages; never infers visual understanding."""
import re
from pathlib import Path
from video_seek import ConversionError

REVIEW_FIELDS = {'schema_version','review_id','task_id','lifecycle_id','observation_sha256','decision_sha256',
                 'pdf_sha256','manifest_sha256','reviewer','source_manifest_verified','complete_score_verified','pages'}


def review_shape(value):
    def require(condition):
        if not condition:
            raise ValueError('invalid delivery review')
    require(isinstance(value, dict) and set(value) == REVIEW_FIELDS)
    require(type(value['schema_version']) is int and value['schema_version'] == 1)
    for field in ('review_id','task_id','lifecycle_id'):
        require(isinstance(value[field], str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value[field])))
    for field in ('observation_sha256','decision_sha256','pdf_sha256','manifest_sha256'):
        require(isinstance(value[field], str) and bool(re.fullmatch(r'[a-f0-9]{64}', value[field])))
    reviewer = value['reviewer']
    require(isinstance(reviewer, dict) and set(reviewer) == {'kind','id'} and reviewer['kind'] in ('agent','human','controlled_fixture'))
    require(isinstance(reviewer['id'], str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', reviewer['id'])))
    require(value['source_manifest_verified'] is True and value['complete_score_verified'] is True)
    require(isinstance(value['pages'], list) and 0 < len(value['pages']) <= 1000)
    for index, page in enumerate(value['pages'], 1):
        require(isinstance(page, dict) and set(page) == {'page','evidence'} and type(page['page']) is int and page['page'] == index)
        require(isinstance(page['evidence'], str) and bool(page['evidence'].strip()) and len(page['evidence']) <= 2000)


def confirm(output, path, recorder, state, observation, load, digest):
    try:
        output = Path(output)
        if output.is_symlink() or not output.is_dir() or state.get('phase') != 'accepted' or not state.get('complete') or not state.get('decision_history'):
            raise ValueError
        value = load(path)
        review_shape(value)
        latest = state['decision_history'][-1]
        if any(value[k] != v for k,v in dict(task_id=state['task_id'], lifecycle_id=recorder.data['lifecycle_id'],
                  observation_sha256=state['observation_sha256'], decision_sha256=latest['sha256']).items()):
            raise ValueError
        pdf, manifest_path = output / 'score.pdf', output / 'manifest.json'
        if pdf.is_symlink() or manifest_path.is_symlink() or digest(pdf) != value['pdf_sha256'] or digest(manifest_path) != value['manifest_sha256']:
            raise ValueError
        expected = dict(directory=str(output.resolve()), pdf_sha256=value['pdf_sha256'], manifest_sha256=value['manifest_sha256'],
                        observation_sha256=value['observation_sha256'], decision_sha256=value['decision_sha256'])
        if not any(e['operation'] == 'export' and e['status'] == 'success' and e.get('artifact') == expected for e in recorder.data['operations']):
            raise ValueError
        manifest = load(manifest_path)
        saved = load(recorder.directory / latest['path'])
        decision = saved.get('decision', saved)
        if manifest.get('status') != 'success' or manifest.get('complete') is not True or manifest.get('task_id') != state['task_id'] or manifest.get('observation_sha256') != state['observation_sha256'] or manifest.get('decision') != decision or manifest.get('source') != observation['source'] or manifest.get('page_count') != len(value['pages']):
            raise ValueError
        for existing in recorder.data.get('delivery_history', []):
            if existing['review']['review_id'] == value['review_id'] and (existing['review'] != value or existing['directory'] != str(output.resolve())):
                raise ValueError
        recorder.confirmation = dict(review=value, directory=str(output.resolve()))
        return dict(status='success', complete=True, phase='delivery_confirmed', task_id=state['task_id'], review_id=value['review_id'])
    except (ConversionError, OSError, ValueError, TypeError, KeyError, OverflowError):
        raise ConversionError('invalid_delivery', '交付审核字段、当前版本或导出来源绑定非法。') from None


def current_delivery(ledger):
    revision = ledger.get('state_revision', {})
    if ledger.get('delivered_at') is None or revision.get('phase') != 'accepted' or revision.get('complete') is not True:
        return None
    return next((record for record in ledger.get('delivery_history', [])
        if record['review']['review_id'] == ledger.get('delivery_review_id') and record['confirmed_at'] == ledger['delivered_at']
        and record['review']['task_id'] == ledger.get('task_id') and record['review']['lifecycle_id'] == ledger.get('lifecycle_id')
        and record['review']['observation_sha256'] == revision.get('observation_sha256')
        and record['review']['decision_sha256'] == revision.get('decision_sha256')), None)
