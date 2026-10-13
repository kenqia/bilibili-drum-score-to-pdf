"""Optional Agent-reviewed complete-score conversion, separate from PDF creation.

Natural-language intent is decided by the host Agent, never a keyword detector.
The caller supplies that decision plus the verbatim explicit MIDI request.
"""
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import uuid


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save(task, record):
    temporary = Path(task) / 'midi-record.tmp'
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(Path(task) / 'midi-record.json')


def resume(task):
    record = json.loads((Path(task) / 'midi-record.json').read_text())
    if record.get('schema') != 'score-midi/1':
        raise ValueError('unsupported MIDI task')
    for reference in [record['pdf'], *record['sources']]:
        if not Path(reference['path']).is_file() or _hash(reference['path']) != reference['sha256']:
            raise ValueError('source or delivered PDF changed; review again')
    if record.get('transcription'):
        review = record['music_review']
        semantic_hash = hashlib.sha256(json.dumps(record['transcription'],sort_keys=True).encode()).hexdigest()
        if semantic_hash != review['transcription_sha256'] or review['pdf_sha256'] != record['pdf']['sha256'] or review['source_hashes'] != [r['sha256'] for r in record['sources']]:
            raise ValueError('transcription or musical review evidence changed')
    if record.get('output'):
        output = (Path(task) / record['output']['path']).resolve()
        if not output.is_relative_to(Path(task).resolve()) or not output.is_file() or _hash(output) != record['output']['sha256']:
            raise ValueError('MIDI delivery changed or missing')
    return record


def request_conversion(task, pdf, sources, request, *, requested_midi=False):
    """Record explicit host-understood MIDI intent; PDF-only is a strict no-op."""
    if requested_midi is not True:
        return None
    if not isinstance(request, str) or not request.strip():
        raise ValueError('explicit natural-language MIDI request required')
    pdf = Path(pdf).resolve()
    sources = [Path(path).resolve() for path in sources]
    if not sources:
        raise ValueError('original score evidence required for musical review')
    if (Path(task) / 'midi-record.json').exists():
        record = resume(task)
        if record['pdf']['path'] != str(pdf) or [r['path'] for r in record['sources']] != list(map(str,sources)):
            raise ValueError('existing task belongs to other evidence')
        return record
    references = [{'path':str(path),'sha256':_hash(path)} for path in [pdf,*sources]]
    task = Path(task)
    if task.exists() and any(task.iterdir()):
        raise ValueError('task directory contains user files')
    task.mkdir(parents=True, exist_ok=True)
    record = {'schema':'score-midi/1','request':request,'pdf':references[0],
              'sources':references[1:],'status':'needs_music_review','model_cost':None}
    _save(task,record)
    return record


def submit_transcription(task, transcription, review):
    """Persist complete Agent semantics and hash-bound full musical review."""
    record = resume(task)
    # JSON roundtrip detaches mutable caller data before persisting.
    transcription = json.loads(json.dumps(transcription))
    measures = transcription['measures']
    ids = [measure['id'] for measure in measures]
    if not ids or len(set(ids)) != len(ids) or any(not isinstance(i,str) or not i for i in ids):
        raise ValueError('distinct complete written-measure IDs required')
    order = transcription['play_order']
    if not order or set(order) != set(ids):
        raise ValueError('play order must cover every written measure; no omitted complex measures')
    if not transcription.get('title') or not transcription.get('policy'):
        raise ValueError('score title and explicit playback conventions required')
    if review.get('complete') is not True or set(review.get('reviewed_measures',[])) != set(ids) or review.get('viewed_pdf') is not True or set(review.get('viewed_sources',[])) != {r['path'] for r in record['sources']} or not review.get('notes'):
        raise ValueError('Agent must review full PDF and originals, including every measure')
    record['transcription'] = transcription
    record['music_review'] = {**review,'pdf_sha256':record['pdf']['sha256'],
                              'source_hashes':[r['sha256'] for r in record['sources']],
                              'transcription_sha256':hashlib.sha256(json.dumps(transcription,sort_keys=True).encode()).hexdigest()}
    record['status'] = 'needs_music_review' if transcription.get('unresolved') or transcription.get('mapping_unresolved') else 'ready_for_midi'
    record.pop('output',None)
    record.pop('readback',None)
    record.pop('failure',None)
    _save(task,record)
    return record


def _expand(transcription):
    measures = {m['id']:m for m in transcription['measures']}
    beat = Fraction(0)
    score = {'events':[],'tempo_changes':[],'meter_changes':[], 'unresolved':transcription.get('unresolved',[]), 'author_mapping_unresolved':transcription.get('mapping_unresolved',[])}
    previous_tempo, previous_meter = None, None
    for identifier in transcription['play_order']:
        measure = measures[identifier]
        numerator, denominator = measure['meter']
        length = Fraction(str(measure['beats']))
        if type(numerator) is not int or type(denominator) is not int or denominator <= 0 or length != Fraction(numerator*4,denominator):
            raise ValueError('measure beats disagree with reviewed meter')
        tempo = measure['tempo_bpm']
        if tempo != previous_tempo:
            score['tempo_changes'].append({'beat':str(beat),'bpm':tempo})
            previous_tempo = tempo
        if measure['meter'] != previous_meter:
            score['meter_changes'].append({'beat':str(beat),'numerator':numerator,'denominator':denominator})
            previous_meter = measure['meter']
        for event in measure['events']:
            local = Fraction(str(event['beat']))
            duration = Fraction(str(event['duration']))
            if local < 0 or duration <= 0 or local+duration > length:
                raise ValueError('event outside complete reviewed measure')
            if not event.get('voice'):
                raise ValueError('each event must preserve its reviewed voice')
            score['events'].append({**event,'beat':str(beat+local)})
        beat += length
    score['beats'] = str(beat)
    score['tempo_bpm'] = score['tempo_changes'][0]['bpm']
    return score


def export_complete(task):
    """Export complete accepted semantics and compare actual MIDI bytes."""
    record = resume(task)
    if record.get('status') == 'midi_reviewed':
        return record
    if record.get('status') not in ('ready_for_midi','midi_failed'):
        raise ValueError('musical or mapping review unresolved; PDF retained')
    try:
        score = _expand(record['transcription'])
        # Import only after explicit request and complete review.
        from midi_export import export_midi, inspect_midi
        import mido
        from delivery_layout import pdf_name
        output = Path(task) / 'exports' / uuid.uuid4().hex / (Path(pdf_name(record['transcription']['title'])).stem + '.mid')
        output.parent.mkdir(parents=True)
        export_midi(score,output)
        actual = inspect_midi(output)
        expected = Counter((int(Fraction(e['beat'])*480),int(Fraction(e['duration'])*480),e['note'],e['velocity'],9) for e in score['events'])
        observed = Counter((e['tick'],e['duration_ticks'],e['note'],e['velocity'],e['channel']) for e in actual['events'])
        tempos = [[int(Fraction(c['beat'])*480),mido.bpm2tempo(c['bpm'])] for c in score['tempo_changes']]
        meters = [[int(Fraction(c['beat'])*480),c['numerator'],c['denominator']] for c in score['meter_changes']]
        if expected != observed or actual['end_tick'] != int(Fraction(score['beats'])*480) or actual['tempos'] != tempos or actual['time_signatures'] != meters:
            raise ValueError('MIDI readback failed; PDF retained')
    except (ValueError, OSError, ImportError):
        record.update(status='midi_failed',failure='MIDI validation or export failed; PDF retained')
        _save(task,record)
        raise
    record.pop('failure',None)
    record.update(status='midi_reviewed',readback=actual,output={'path':str(output.relative_to(task)),'sha256':_hash(output),'expanded_order':record['transcription']['play_order'],'beats':score['beats']})
    _save(task,record)
    return record
