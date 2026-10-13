"""Serialize explicit percussion events; Mido is an optional caller dependency.

This module performs no notation recognition. Beats and durations are exact
quarter-note fractions, and unresolved source symbols prevent export.
"""
from collections import defaultdict, deque
from fractions import Fraction
from pathlib import Path
import math
import os
import tempfile


def _tick(value, resolution=480):
    tick = Fraction(str(value)) * resolution
    if tick.denominator != 1 or tick < 0:
        raise ValueError('beat must be nonnegative and exactly representable at 480 PPQ')
    return int(tick)


def export_midi(score, output, *, experimental=False):
    """Write explicit events; this serializer does not certify source review.

    Only an explicitly experimental export may apply a declared convention
    while the original author drum mapping remains unresolved. Other musical
    uncertainties are always rejected.
    """
    import mido
    if score.get('unresolved'):
        raise ValueError('unresolved musical symbols prevent MIDI export')
    if score.get('author_mapping_unresolved') and not experimental:
        raise ValueError('unresolved author drum mapping prevents normal MIDI export')
    end = _tick(score['beats'])
    tempo = score['tempo_bpm']
    if not end or type(tempo) not in (int, float) or not math.isfinite(tempo) or not 0 < tempo <= 1000:
        raise ValueError('positive score length and tempo required')
    timeline = []
    for event in score['events']:
        start, duration = _tick(event['beat']), _tick(event['duration'])
        note, velocity = event['note'], event['velocity']
        if not duration or start + duration > end:
            raise ValueError('event duration exceeds the reviewed score')
        if type(note) is not int or not 35 <= note <= 81:
            raise ValueError('event requires an explicit GM percussion note 35..81')
        if type(velocity) is not int or not 1 <= velocity <= 127:
            raise ValueError('event requires an explicit velocity 1..127')
        timeline.extend([(start, 1, note, velocity), (start + duration, 0, note, 0)])
    # Same-note overlapping notes cannot be paired unambiguously in MIDI.
    last_end = {}
    for event in sorted(score['events'], key=lambda e: (Fraction(str(e['beat'])), e['note'])):
        start, duration = _tick(event['beat']), _tick(event['duration'])
        if start < last_end.get(event['note'], 0):
            raise ValueError('overlapping events on the same percussion note')
        last_end[event['note']] = start + duration
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    meta = mido.MidiTrack()
    meta.extend([mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(score['tempo_bpm'])),
                 mido.MetaMessage('time_signature', numerator=4, denominator=4),
                 mido.MetaMessage('end_of_track', time=end)])
    drums = mido.MidiTrack()
    drums.append(mido.MetaMessage('track_name', name='GM percussion event export'))
    previous = 0
    for tick, on, note, velocity in sorted(timeline):
        drums.append(mido.Message('note_on' if on else 'note_off', channel=9,
                                 note=note, velocity=velocity, time=tick - previous))
        previous = tick
    drums.append(mido.MetaMessage('end_of_track', time=end - previous))
    midi.tracks.extend([meta, drums])
    output = Path(output)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + output.name + '-', dir=output.parent)
    os.close(descriptor)
    try:
        midi.save(temporary)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inspect_midi(path):
    """Read actual MIDI bytes and reject unpaired percussion events."""
    import mido
    midi = mido.MidiFile(str(path))
    result = dict(ticks_per_beat=midi.ticks_per_beat, end_tick=0,
                  tempos=[], time_signatures=[], events=[])
    for track in midi.tracks:
        tick, active = 0, defaultdict(deque)
        for message in track:
            tick += message.time
            if message.type == 'set_tempo':
                result['tempos'].append([tick, message.tempo])
            elif message.type == 'time_signature':
                result['time_signatures'].append([tick, message.numerator, message.denominator])
            elif message.type in ('note_on', 'note_off'):
                key = message.channel, message.note
                if message.type == 'note_on' and message.velocity:
                    active[key].append((tick, message.velocity))
                else:
                    if not active[key]:
                        raise ValueError('unpaired note-off in actual MIDI')
                    start, velocity = active[key].popleft()
                    result['events'].append(dict(tick=start, duration_ticks=tick - start,
                                                 note=message.note, velocity=velocity,
                                                 channel=message.channel))
        if any(active.values()):
            raise ValueError('unpaired note-on in actual MIDI')
        result['end_tick'] = max(result['end_tick'], tick)
    result['events'].sort(key=lambda e: (e['tick'], e['note'], e['duration_ticks'], e['velocity']))
    return result
