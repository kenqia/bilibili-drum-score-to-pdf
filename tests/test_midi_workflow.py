import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/bilibili-drum-score-to-pdf/scripts'))

class MidiRequestTests(unittest.TestCase):
    def test_pdf_only_does_not_create_conversion_task_or_load_mido(self):
        from midi_workflow import request_conversion
        with tempfile.TemporaryDirectory() as d:
            task=Path(d)/'midi'
            self.assertIsNone(request_conversion(task, Path(d)/'absent.pdf', [], '请给我PDF', requested_midi=False))
            self.assertFalse(task.exists())

@unittest.skipUnless(importlib.util.find_spec('mido'),'optional Mido absent')
class MidiWorkflowTests(unittest.TestCase):
    def test_measure_local_tempo_changes_survive_actual_readback_and_repeats(self):
        from midi_workflow import request_conversion, submit_transcription, export_complete
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';source=root/'original.png'
            pdf.write_bytes(b'pdf fixture');source.write_bytes(b'source fixture');task=root/'midi'
            request_conversion(task,pdf,[source],'完整MIDI',requested_midi=True)
            score={'title':'Reviewed tempo changes','policy':{'default_velocity':96},
                'measures':[
                    {'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,
                     'tempo_changes':[{'beat':'1/3','bpm':90},{'beat':'2','bpm':150}], 'events':[]},
                    {'id':'2','beats':'3','meter':[3,4],'tempo_bpm':120,'events':[]}],
                'play_order':['1','2','1','2'],'unresolved':[],'mapping_unresolved':[]}
            review={'complete':True,'reviewed_measures':['1','2'],'viewed_sources':[str(source.resolve())],
                    'viewed_pdf':True,'notes':'Controlled fixture, not real source acceptance'}
            submit_transcription(task,score,review)
            actual=export_complete(task)['readback']
            self.assertEqual(actual['tempos'],[[0,500000],[160,666667],[960,400000],
                [1920,500000],[3520,666667],[4320,400000],[5280,500000]])
            self.assertEqual(actual['end_tick'],6720)
            self.assertEqual(pdf.read_bytes(),b'pdf fixture')

    def test_invalid_measure_tempo_changes_are_rejected_before_accepting_review(self):
        from midi_workflow import request_conversion, submit_transcription, resume
        invalid=[None, {}, [{'beat':'0','bpm':90}], [{'beat':'-1','bpm':90}],
            [{'beat':'4','bpm':90}], [{'beat':'1/7','bpm':90}],
            [{'beat':'2','bpm':90},{'beat':'1','bpm':100}],
            [{'beat':'1','bpm':90},{'beat':'1','bpm':100}],
            [{'beat':'1','bpm':True}], [{'beat':'1','bpm':0}],
            [{'beat':'1','bpm':1001}], [{'beat':'1','bpm':'90'}],
            [{'beat':'1','bpm':float('inf')}], [{'beat':'bad','bpm':90}],
            [{'beat':'1'}], [{'beat':'1','bpm':90,'curve':'rit'}]]
        for changes in invalid:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as d:
                root=Path(d);pdf=root/'score.pdf';source=root/'original.png';task=root/'midi'
                pdf.write_bytes(b'accepted PDF');source.write_bytes(b'original')
                request_conversion(task,pdf,[source],'完整MIDI',requested_midi=True)
                score={'title':'Invalid tempo','policy':{'default_velocity':96},
                    'measures':[{'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,
                                 'tempo_changes':changes,'events':[]}],
                    'play_order':['1'],'unresolved':[],'mapping_unresolved':[]}
                review={'complete':True,'reviewed_measures':['1'],'viewed_sources':[str(source.resolve())],
                        'viewed_pdf':True,'notes':'Controlled fixture'}
                with self.assertRaises(ValueError):
                    submit_transcription(task,score,review)
                self.assertEqual(resume(task)['status'],'needs_music_review')
                self.assertNotIn('transcription',resume(task))
                self.assertEqual(pdf.read_bytes(),b'accepted PDF')

    def test_reviewed_complete_score_exports_repeat_meter_tempo_and_exact_events(self):
        from midi_workflow import request_conversion, submit_transcription, export_complete, resume
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';source=root/'original.png'
            pdf.write_bytes(b'pdf fixture');source.write_bytes(b'source fixture')
            task=root/'midi'
            request_conversion(task,pdf,[source],'请将完整谱转成MIDI',requested_midi=True)
            transcription={'title':'Four measures','mapping_unresolved':[], 'policy':{'default_velocity':96,'grace':'explicit beat and duration, before main'},
                'measures':[
                    {'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[{'beat':'0','duration':'1','note':36,'velocity':96,'voice':'lower'}]},
                    {'id':'2','beats':'3','meter':[3,4],'tempo_bpm':180,'events':[{'beat':'1/3','duration':'1/3','note':38,'velocity':80,'voice':'upper'}]}],
                'play_order':['1','2','1','2'], 'unresolved':[]}
            review={'complete':True,'reviewed_measures':['1','2'], 'viewed_sources':[str(source.resolve())], 'viewed_pdf':True,'notes':'Fixture statement for state test, not visual acceptance'}
            submit_transcription(task,transcription,review)
            result=export_complete(task)
            actual=result['readback']
            self.assertEqual(actual['end_tick'],6720)
            self.assertEqual(actual['tempos'],[[0,500000],[1920,333333],[3360,500000],[5280,333333]])
            self.assertEqual(actual['time_signatures'],[[0,4,4],[1920,3,4],[3360,4,4],[5280,3,4]])
            self.assertEqual([e['tick'] for e in actual['events']],[0,2080,3360,5440])
            self.assertEqual(result['status'],'midi_reviewed')
            self.assertEqual(resume(task)['output'],result['output'])
            self.assertEqual(pdf.read_bytes(),b'pdf fixture')

    def test_export_directory_symlink_preserves_outside_files_and_rejects_success(self):
        from midi_workflow import request_conversion, submit_transcription, export_complete, resume
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';source=root/'source.png'
            pdf.write_bytes(b'accepted PDF');source.write_bytes(b'original')
            task=root/'midi'
            request_conversion(task,pdf,[source],'完整 MIDI',requested_midi=True)
            score={'title':'complete','policy':{'default_velocity':96},'mapping_unresolved':[],'unresolved':[],
                   'measures':[{'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[]}],'play_order':['1']}
            review={'complete':True,'reviewed_measures':['1'],'viewed_pdf':True,'viewed_sources':[str(source.resolve())],'notes':'state fixture'}
            submit_transcription(task,score,review)
            outside=root/'outside';outside.mkdir()
            marker=outside/'user.mid';marker.write_bytes(b'user file')
            (task/'exports').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):
                export_complete(task)
            self.assertEqual(list(outside.iterdir()),[marker])
            self.assertEqual(marker.read_bytes(),b'user file')
            self.assertEqual(pdf.read_bytes(),b'accepted PDF')
            recovered=resume(task)
            self.assertNotEqual(recovered['status'],'midi_reviewed')
            self.assertNotIn('output',recovered)

    def test_unresolved_mapping_preserves_pdf_and_rejects_delivery(self):
        from midi_workflow import request_conversion, submit_transcription, export_complete
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'reviewed.pdf';pdf.write_bytes(b'accepted PDF');image=root/'source.png';image.write_bytes(b'original')
            task=root/'task';request_conversion(task,pdf,[image],'另给完整MIDI',requested_midi=True)
            score={'title':'ambiguous','policy':{'default_velocity':96},'mapping_unresolved':['ride vs crash'],'unresolved':[],
                   'measures':[{'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[]}],'play_order':['1']}
            review={'complete':True,'reviewed_measures':['1'],'viewed_pdf':True,'viewed_sources':[str(image.resolve())],'notes':'state fixture'}
            submit_transcription(task,score,review)
            with self.assertRaisesRegex(ValueError,'unresolved'):
                export_complete(task)
            self.assertEqual(pdf.read_bytes(),b'accepted PDF')
            self.assertFalse((task/'exports').exists())

    def test_resume_rejects_changed_transcription_without_new_musical_review(self):
        from midi_workflow import request_conversion, submit_transcription, resume
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';pdf.write_bytes(b'pdf');source=root/'source.png';source.write_bytes(b'image');task=root/'task'
            request_conversion(task,pdf,[source],'MIDI',requested_midi=True)
            score={'title':'reviewed','policy':{'default_velocity':96},'mapping_unresolved':[],'unresolved':[],
                   'measures':[{'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[]}],'play_order':['1']}
            review={'complete':True,'reviewed_measures':['1'],'viewed_pdf':True,'viewed_sources':[str(source.resolve())],'notes':'state fixture'}
            submit_transcription(task,score,review)
            p=task/'midi-record.json';record=json.loads(p.read_text());record['transcription']['measures'][0]['tempo_bpm']=200;p.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'transcription'):
                resume(task)

    def test_readback_failure_retains_pdf_then_resumes_without_retranscribing(self):
        from midi_workflow import request_conversion, submit_transcription, export_complete, resume
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';pdf.write_bytes(b'accepted');source=root/'source.png';source.write_bytes(b'image');task=root/'task'
            request_conversion(task,pdf,[source],'MIDI',requested_midi=True)
            score={'title':'reviewed','policy':{'default_velocity':96},'mapping_unresolved':[],'unresolved':[],
                   'measures':[{'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[]}],'play_order':['1']}
            review={'complete':True,'reviewed_measures':['1'],'viewed_pdf':True,'viewed_sources':[str(source.resolve())],'notes':'state fixture'}
            submit_transcription(task,score,review)
            with patch('midi_export.inspect_midi',side_effect=ValueError('corrupt actual MIDI')):
                with self.assertRaises(ValueError):export_complete(task)
            self.assertEqual(resume(task)['status'],'midi_failed')
            self.assertEqual(pdf.read_bytes(),b'accepted')
            self.assertNotIn('output',resume(task))
            self.assertEqual(export_complete(task)['status'],'midi_reviewed')

    def test_changed_original_cannot_reuse_prior_complete_musical_review(self):
        from midi_workflow import request_conversion, resume
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';pdf.write_bytes(b'PDF');source=root/'source.png';source.write_bytes(b'original');task=root/'task'
            request_conversion(task,pdf,[source],'完整MIDI',requested_midi=True)
            source.write_bytes(b'replaced')
            with self.assertRaisesRegex(ValueError,'source'):
                resume(task)
            self.assertEqual(pdf.read_bytes(),b'PDF')

    def test_partial_written_measure_play_order_cannot_hide_complex_measure(self):
        from midi_workflow import request_conversion, submit_transcription
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';pdf.write_bytes(b'PDF');source=root/'source.png';source.write_bytes(b'original');task=root/'task'
            request_conversion(task,pdf,[source],'完整MIDI',requested_midi=True)
            score={'title':'full','policy':{'default_velocity':96},'mapping_unresolved':[],'unresolved':[],
                   'measures':[{'id':'simple'},{'id':'complex'}],'play_order':['simple']}
            review={'complete':True,'reviewed_measures':['simple','complex'],'viewed_pdf':True,'viewed_sources':[str(source.resolve())],'notes':'state fixture'}
            with self.assertRaisesRegex(ValueError,'every written measure'):
                submit_transcription(task,score,review)

    def test_full_visually_reviewed_score_matches_independent_events_including_grace(self):
        from midi_workflow import request_conversion, submit_transcription, export_complete
        from fractions import Fraction
        from collections import Counter
        evidence=Path(__file__).resolve().parents[1]/'docs/experiments/issue-57-midi'
        score=json.loads((evidence/'transcription.json').read_text())
        independent=json.loads((evidence/'independent-events.json').read_text())
        source=evidence/'full-score.png'
        with tempfile.TemporaryDirectory() as d:
            task=Path(d)/'midi'
            request_conversion(task,evidence/'full-score.pdf',[source],'完整MIDI',requested_midi=True)
            submit_transcription(task,score,{'complete':True,'reviewed_measures':['1','2','3'],
                'viewed_pdf':True,'viewed_sources':[str(source.resolve())],
                'notes':'Regression replay of actual separately recorded complete visual review; test does not re-view images'})
            actual=export_complete(task)['readback']
        expected=Counter();offset=Fraction(0)
        for measure in independent['sequence']:
            for event in independent[f'measure{measure}']:
                expected[(int((offset+Fraction(event['beat']))*480),int(Fraction(event['duration'])*480),event['note'],event['velocity'],9)]+=1
            offset+=4 if measure in (1,3) else 3
        observed=Counter((e['tick'],e['duration_ticks'],e['note'],e['velocity'],e['channel']) for e in actual['events'])
        self.assertEqual(observed,expected)
        self.assertEqual(actual['end_tick'],8640)
        self.assertEqual(actual['tempos'],[[0,500000],[1920,375000],[3360,500000],[5280,375000],[6720,600000]])

@unittest.skipUnless(importlib.util.find_spec('mido'),'optional Mido absent')
class PlayableMidiTests(unittest.TestCase):
    def test_explicit_approximation_keeps_original_limits_and_pairs_actual_notes(self):
        from midi_workflow import request_conversion, submit_playable_transcription, export_complete, resume
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';source=root/'source.png';task=root/'task'
            pdf.write_bytes(b'accepted');source.write_bytes(b'original')
            request_conversion(task,pdf,[source],'能跑就行',requested_midi=True)
            original={'title':'uncertain','policy':{'velocity':96},'unresolved':['rit unspecified'],'mapping_unresolved':['no legend'],
                'measures':[{'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[{'beat':'0','duration':'1','note':None,'velocity':96,'voice':'upper'}]}],'play_order':['1','1']}
            adapted=json.loads(json.dumps(original));adapted['measures'][0]['events'][0]['note']=49
            review={'complete':True,'reviewed_measures':['1'],'viewed_sources':[str(source.resolve())],'viewed_pdf':True,'notes':'controlled state fixture'}
            submit_playable_transcription(task,original,adapted,review,authorization='允许近似，能跑就行',assumptions=['crossed oval -> crash49; constant tempo for uncertain rit'],adjustments=[])
            result=export_complete(task)
            self.assertEqual(result['status'],'midi_playable')
            self.assertFalse(result['playback_approval']['reliable'])
            self.assertEqual(result['playback_approval']['original_transcription'],original)
            self.assertEqual(result['transcription']['unresolved'],['rit unspecified'])
            self.assertEqual(result['readback']['end_tick'],3840)
            self.assertEqual([e['note'] for e in result['readback']['events']],[49,49])
            self.assertEqual(pdf.read_bytes(),b'accepted')
            self.assertEqual(resume(task)['status'],'midi_playable')
            saved=json.loads((task/'midi-record.json').read_text());saved['playback_approval']['assumptions']=['silently changed'];(task/'midi-record.json').write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError,'playback approval'):
                resume(task)

    def test_playable_approval_cannot_omit_a_written_measure_or_original_limits(self):
        from midi_workflow import request_conversion, submit_playable_transcription, resume
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'score.pdf';source=root/'source.png';task=root/'task'
            pdf.write_bytes(b'accepted');source.write_bytes(b'original')
            request_conversion(task,pdf,[source],'能跑就行',requested_midi=True)
            original={'title':'uncertain','policy':{'velocity':96},'unresolved':['rit'], 'mapping_unresolved':[],
                'measures':[{'id':'1','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[]},
                            {'id':'2','beats':'4','meter':[4,4],'tempo_bpm':120,'events':[]}],'play_order':['1','2']}
            review={'complete':True,'reviewed_measures':['1','2'],'viewed_sources':[str(source.resolve())],'viewed_pdf':True,'notes':'controlled state fixture'}
            for field in ('measures','play_order','unresolved'):
                with self.subTest(field=field):
                    adapted=json.loads(json.dumps(original));adapted[field]=adapted[field][:-1]
                    with self.assertRaisesRegex(ValueError,'preserve'):
                        submit_playable_transcription(task,original,adapted,review,authorization='近似',assumptions=['GM convention'],adjustments=[])
            with self.assertRaisesRegex(ValueError,'authorization'):
                submit_playable_transcription(task,original,original,review,authorization='',assumptions=['GM convention'],adjustments=[])
            self.assertEqual(resume(task)['status'],'needs_music_review')
            self.assertEqual(pdf.read_bytes(),b'accepted')
