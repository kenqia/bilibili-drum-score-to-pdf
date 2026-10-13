"""Agent's handwritten full written-measure review, preserving unresolved music."""
import sys,json,copy,hashlib
from fractions import Fraction as F
from pathlib import Path
sys.path.insert(0,'skills/bilibili-drum-score-to-pdf/scripts')
import midi_workflow as mw
base=Path('experiments/2026-10-13-issue58-recovered/killkiss').resolve();task=base/'task'
record=json.loads((task/'record.json').read_text())
pilot=json.loads(Path('docs/experiments/issue-55-midi/source-benchmark.json').read_text())
known={m['number']:m for m in pilot['measures']}
# These are Agent-reviewed NEW source rows. Tapes retain printed voices, not generated output interpretation.
Q='H:q H+S:q H:q H+S:q'
B='K:e K:e R:q K:e K:e R:e K:e'
B1='R:e K:e R:e K:e K:e K:e R:q'
B16='R:e K:s K:s R:e K:e K:e K:e R:q'
BF='R:e K:e R:e K:s K:s R:e K:s K:s R:q'
A='R:q H+S:q H:e S:e C2:q'
AB='R:e K:e R:q K:e K:e R:e K:e'
AB16='R:e K:s K:s R:q K:e K:e R:e K:e'
tapes={}
def row(start,up,lo):
 for i,(a,b) in enumerate(zip(up,lo)):tapes[start+i]=[a,b]
row(3,['C2+S:q R:e C1+S:e R:q F:s F:de','C2+S:q R:e H+S:e R:q H+S:q','R:e C1+S:e C2+S:q F:s F:de S:s S:s S:s S:s'],['K:e K:e R:e K:s K:s R:e K:s K:s','R:e K:e K:q K:e K:e R:e K:e','K:q R:e K:s K:s R:e K:s K:s R:q'])
row(6,['C1:q H+S:q H:q H+S:q',Q,'C2+S:q R:e C1+S:e R:q H+S:e H+S:e','R:e C1+S:e C2+S:q F:s F:de S:s S:s S:s S:s'],[B,'K:e K:e R:e K:e R:e K:e R:e K:s K:s','K:e K:e K:q K:e K:e R:q','K:q R:e K:s K:s R:e K:s K:s R:q'])
row(12,['C1:q H+S:q H:q H+S:q',Q,Q,'H:q H+S:q F:s F:de H+S:q'],[B,B1,B,BF])
row(16,[Q,Q,Q,'H:q H+S:q F:s F:de C2+S:q'],[B,B16,B,BF])
row(20,['C1:q H+S:q H:q H+S:q',Q,Q,'H:q H+S:q F:s F:de H+S:q'],[B,B1,B,BF])
row(24,[Q,Q,Q,'R:q C2+S:e S:s S:s S:e T:e F:e F:e'],[B,B16,'K:e K:e R:e K:e R:e K:e K:q','K:e K:e R:q R:q R:q'])
row(28,['C1:q R:q R:q R:q','R:q R:q R:q R:e','R:q R:q R:q R:q','R:q R:q R:e gF+F:q'],['K:q R:q R:q R:q','R:q R:q R:q K:e','K:q R:q R:q R:q','R:q R:q R:e K:e R:q'])
row(32,['C2:q C2:q C2+S:q C2:q','C2+S:e C2:e C2+S:q C2:q C2+S:q','C2:q C2:q C2+S:q C2:q','C2+S:e C2:e C2+S:q C2:q C2+S:q'],['K:s K:s K:s K:s K:s K:s K:s K:s R:q K:q','R:q K:e K:e R:e K:e R:q','K:s K:s K:s K:s K:s K:s K:s K:s R:q K:q','R:q K:e K:e R:e K:e R:e K:e'])
row(36,['C2+S:q H+S:q H+S:e R:e H+S:e R:e','R:q H+S:q H+S:q F:s F:de','C2+S:q H+S:q H+S:e R:e H+S:e R:e','R:q H+S:q H+S:q H+S:q'],['R:e K:e R:e K:e R:e K:e K:q','K:e K:e R:e K:e R:e K:s K:s R:e K:s K:s','R:e K:e R:e K:e R:e K:e K:q','K:e K:e R:e K:e R:e K:e K:e K:s K:s'])
row(40,['C2+S:q R:e C1+S:e R:q gF+F:q','R:e C1+S:e R:q C1+S:q C2+S:q','M+F:e M+F:e R:e M+F:e M+F:q C1+S:q','R:q R:q R:q R:e C1:e'],['R:e K:e K:q K:e K:e R:e K:e','K:q K:e K:e R:e K:e R:e K:s K:s','R:q R:q R:q R:e K:e','R:q R:q R:q R:e K:e'])
for start in (44,48):
 row(start,[A,A,A,'R:q H+S:q T:s T:de S:e C2:e'],[AB,AB16,'R:e K:s K:s R:q K:e K:e R:e K:s K:s','R:e K:s K:s R:e K:e K:e K:s K:s R:e K:e'])
row(52,['R:e S:e H:q H+S:e S:e C1:e C2:e','R:e S:e H:q H+S:q S:e C2:e','R:e S:e H:q H+S:e S:e C1:e C2:e','R:e S:e H:q H+S:q H+S:q'],['R:q K:e K:e R:q K:e K:e','R:q K:e K:s K:s R:e K:e R:e K:e','R:q K:e K:e R:q K:e K:e','R:q K:q R:e K:s K:s R:e K:e'])
row(56,['C2+S:q H+S:q H+S:q H+S:q','H+S:q H+S:q H+S:q H+S:q','S:s T:s F:s F:s R:e T:s T:s F:s F:de F:s T:s F:e','C1+S:q R:q R:q R:e'],['R:e K:e R:e K:e R:e K:e R:e K:e','R:e K:e R:e K:e R:e K:e R:e K:s K:s','R:q K:ds K:ds R:e K:s K:s R:de K:e','R:q R:q R:q R:e K:s K:s'])
row(60,['C2+S:q R:e C1+S:e R:q C2+S:q','C2+S:q R:e C1+S:e R:q F:s F:de','C2+S:q R:e H+S:e R:q H+S:q','R:e C1+S:e C2+S:q F:s F:de S:s S:s S:s S:s'],['R:e K:e K:q K:e K:e R:e K:e','R:e K:e K:q K:s K:s R:e K:s K:s','R:e K:e K:q K:e K:e R:e K:e','K:q R:e K:s K:s R:e K:s K:s R:q'])
row(64,['C1:q H+S:q H:q H+S:q',Q,'C2+S:q R:e C1+S:e R:q H+S:e H+S:e','R:e H+S:e H+S:q S:t T:t T:t T:t F:t F:t'],[B,'K:e K:e R:e K:e R:e K:e K:e K:s K:s','R:e K:e K:q K:e K:e R:q','K:q R:e K:s K:s R:q R:q'])
row(68,['C1:q R:q H:q R:q','H:q R:q H:q R:e C1:e','C1:q R:q H:q R:q','H:q R:q H:q R:q'],['K:q R:q R:q R:q','R:q R:q R:q K:e R:e','K:q R:q R:q R:q','R:w'])
row(72,['C1:q R:q H:q R:q','H:q R:q H:q R:e C1:e','C1:q R:q H:q R:q','H:q R:e K:s K:s gT+T:de gS+S:s R:e gF+F:e'],['K:q R:q R:q R:q','R:q R:q R:q K:e R:e','K:q R:q R:q R:q','R:w'])
row(76,['C2:q R:q H+S:q H:q','H:e S:e H:q H:e S:e H:q','C2+S:q H:q C2+S:q H:q','H:e S:e H:q C1+S:e S:e T:e T:e'],['K:q R:e K:e R:q K:e K:e','R:q K:e K:s K:s R:e K:e R:q','K:q R:e K:e R:q K:e K:e','R:q K:e K:s K:s R:q R:q'])
row(80,['C2:q H:q H+S:q H:q','H:e S:e H:q H:e S:e H:q','C2+M+F:e M+F:e M+F:e M+F:e M+F:e M+F:e M+F:e M+F:e','M+F:e M+F:e gS+S:e S:s S:s S:e S:e S:e S:e'],['K:q R:e K:e R:q K:e K:e','R:q K:e K:s K:s R:e K:e R:q','K:q R:q R:q R:q','R:w'])
row(84,['C1:q H+S:q H:q H+S:q',Q,Q,'H:q H+S:q H:q H+S:de T:s'],['K:e K:e R:e K:e R:e K:e R:q','K:e K:e R:e K:e R:e K:e R:q','K:e K:e R:e K:s K:s R:e K:e R:q','K:e K:e R:e K:e R:e K:e R:q'])
row(88,[Q,Q,Q,'H+S:e T:e T:e S:e S:e S:e F:e F:e'],['K:e K:e R:e K:e R:e K:s K:s R:e K:e','K:e K:e R:e K:e R:e K:e R:e K:e','K:e K:e R:e K:e R:e K:e R:e K:e','K:q R:q R:q R:q'])
row(92,['C1:q C2+S:q C1:q C2+S:q','C2+S:e C1:e C1+S:e S:e C2+S:q C1+S:q','C1:q C2+S:q C1:q C2+S:q','C2+S:e C1:e C1+S:q C2+S:e C1+S:e C1+S:q'],['K:q R:e K:s K:s R:q K:e K:e','R:q K:e K:e R:q R:q','K:q R:e K:e R:q K:e K:e','R:q K:e K:s K:s R:q K:e K:e'])
row(96,['C1+S:q H+S:q H+S:q H+S:q','H+S:q H+S:q H+S:q H+S:q','gS+S:q R:q C1+S:e C2:e C1:e C2:e','R:e T:s T:s F:s F:de T:s T:de S:s S:s S:e'],['R:e K:e R:e K:e R:e K:e R:e K:e','R:e K:e R:e K:e R:e K:e R:e K:s K:s','R:q R:q R:q K:e K:e','R:e K:s K:s R:e K:s K:s R:e K:e R:q'])
row(100,['R:q R:q R:q R:q','R:q R:q gS+S:q R:e C1:e'],['R:w','R:q R:q R:q R:e K:e'])
row(102,['R:q C2+S:e T:e F:e C2:e','R:q H+S:q S:s S:s S:s S:s S:s S:s C2:e','R:q C2+S:q H:q S:e C2:e','R:q C1+S:q T:s T:de S:e C2:e'],['R:e K:s K:s R:e K:s K:s R:q R:e K:e','R:e K:e R:q R:q R:e K:e','R:e K:s K:s R:e K:e K:e K:s K:s R:e K:e','R:e K:s K:s R:e K:s K:s R:e K:s K:s R:e K:e'])
row(106,[A,A,'R:q H+S:q H:q H+S:q','T:s T:de F:s F:de S:s S:s S:s S:s S:s S:s C2:e'],[AB,AB16,'R:e K:e R:q K:e K:e R:e K:s K:s','R:e K:s K:s R:e K:s K:s R:q R:e K:e'])
row(110,['R:e S:e H:q H+S:e S:e C1:e C2:e','R:e S:e H:q H+S:q S:e C2:e','R:e S:e H:q H+S:e S:e C1:e C2:e','R:e S:e H:q T:s T:de C2+S:q'],['R:q K:e K:e R:q K:e K:e','R:q K:e K:s K:s R:e K:e R:e K:e','R:q K:e K:s K:s R:q K:e K:e','R:q K:e K:s K:s R:e K:s K:s R:e K:e'])
row(114,['C2+S:q H+S:q H+S:q H+S:q','H+S:q H+S:q H+S:q H+S:q',tapes[58][0],'C1+S:q R:q R:q R:e'],[tapes[56][1],tapes[57][1],tapes[58][1],tapes[59][1]])
row(118,tapes[60:64] if False else [tapes[i][0] for i in range(60,64)],[tapes[i][1] for i in range(60,64)])
row(122,['C1:q H+S:q H:q H+S:q',Q,Q,'H:q H+S:q C2:q T:s T:de C2+S:q'],['K:e K:e R:e K:s K:s R:e K:e R:e K:e','K:e K:e R:e K:s K:s R:e K:e R:e K:e','K:e K:e R:e K:s K:s R:e K:e R:e K:e','K:e K:e R:e K:s K:s R:e K:s K:s K:s K:s K:s K:s'])
row(126,[Q,Q,Q,Q],['R:e K:e R:e K:e R:e K:e R:e K:e','R:e K:e R:e K:s K:s R:e K:s K:s K:s K:s K:s K:s','R:e K:e R:e K:e R:e K:e R:e K:e','R:e K:s K:s R:e K:s K:s R:e K:e R:e K:s K:s'])
row(130,['C2+S:q R:e C1+S:e R:q C2+S:q','R:e T:s T:s F:s F:de C2+S:e T:e F:s F:de','F:s F:de S:s S:s S:s S:s R:e T:s T:s F:s F:de','F:s F:de F:s F:de F:s F:de C1+S:q'],['R:e K:e K:q K:e K:e R:e K:e','K:q R:e K:s K:s K:de R:de K:s K:s','R:e K:s K:s R:q K:de K:s R:e K:s K:s','R:e K:e R:e K:e R:e K:e R:q'])
# Complex marked exactness is not promoted merely because symbols were entered.
complex_ids={3,5,8,9,31,37,40,41,42,47,51,54,55,58,61,63,65,66,76,77,79,81,82,83,87,91,93,95,98,99,102,103,104,105,108,109,116,119,121,125,127,129,131,132,133}
dur={'q':F(1),'e':F(1,2),'s':F(1,4),'de':F(3,4),'ds':F(3,8),'w':F(4),'t':F(1,3)}
symbol={36:'filled-oval bass-low',38:'filled-oval snare-middle',43:'filled-oval floor-tom lower',46:'x with open0 above-staff',48:'filled-oval high-tom',47:'filled-oval middle-tom',49:'lower crossed oval cymbal',57:'higher crossed oval cymbal'}
measures=[];unresolved=[]
for n in range(1,136):
 m={'id':str(n),'beats':'4','meter':[4,4],'tempo_bpm':200,'events':[],'rests':[]}
 if n in known:
  k=known[n];m['voice_tapes']=k['voice_tapes'];m['events']=copy.deepcopy(k['events'])
  for e in m['events']:e['symbol']=symbol.get(e['note'],f"source pitch mapped {e['note']} in prior pilot");e['note']=None
  m['review_basis']='previous independent notation pilot compared to newly viewed original source, author mapping not reused'
 else:
  m['voice_tapes']=tapes[n]
  for voice,tape in enumerate(tapes[n],1):
   beat=F(0)
   for token in tape.split():
    names,code=token.split(':');duration=dur[code]
    if names=='R':m['rests'].append({'beat':str(beat),'duration':str(duration),'voice':voice})
    else:
     for name in names.split('+'):
      if name.startswith('g'):
       m['events'].append({'beat':str(max(F(0),beat-F(1,16))),'duration':'1/16','notation_duration':'grace untimed','symbol':name[1:],'grace':True,'note':None,'velocity':64,'voice':voice,'playback_convention':'before principal, not literal measured source duration'})
      else:m['events'].append({'beat':str(beat),'duration':str(duration),'notation_duration':str(duration),'symbol':name,'note':None,'velocity':96,'voice':voice})
    beat+=duration
   if beat!=4:m.setdefault('unresolved',[]).append(f'voice {voice} tape sums {beat}, needs exact rest/beam reread')
  if n in complex_ids:m.setdefault('unresolved',[]).append('fresh source reviewed but exact complex voice/beam/dotted timing not independently confirmed; candidate tape only')
 region=next(i for i in reversed(range(1,len(record['regions']))) if int(record['regions'][i]['position'].split('-')[-1])<=n);reg=record['regions'][region];m['source']={'region':region,'capture':reg['capture'],'sha256':reg['sha256'],'position':reg['position']}
 if n in (10,11):m['rests']=[{'beat':'0','duration':'4','voice':1,'notation':'2-bar multimeasure rest'}]
 for issue in m.get('unresolved',[]):unresolved.append({'measure':str(n),'reason':issue})
 measures.append(m)
trans={'title':'KiLLKiSS','measures':measures,'play_order':[str(n) for n in range(1,136)],'policy':'Candidate exact rational engraved durations; grace policy1/16 quarter beat before principal64velocity; other velocity96; no repeat signs observed; all GM notes null while author legend remains unresolved. Complex unchecked candidate timings preserved as unresolved, not reliable MIDI.','mapping_unresolved':['No author drum legend: preserve C1/C2 higher/lower crossedoval separately, Hopen0, S/T/M/F/K symbols; no invented GM mapping.'],'unresolved':unresolved,'symbol_legend':{'C1':'lower crossed oval cymbal','C2':'higher crossed oval cymbal','H':'x open0 above staff','S':'filled-oval snare position','T':'filled-oval high-tom position','M':'filled-oval middle-tom position','F':'filled-oval lower tom position','K':'filled-oval lowest bass position'}}
(base/'whole-music-candidate.json').write_text(json.dumps(trans,ensure_ascii=False,indent=2))
pdf=task/record['output']['pdf'];sources=[task/c['path'] for c in record['captures']];mp=base/'midi-task';before=hashlib.sha256(pdf.read_bytes()).hexdigest()
mw.request_conversion(mp,pdf,sources,'Issue #58要求完整KiLLKiSS整曲MIDI，保留未知映射及复杂逐小节未决项。',requested_midi=True)
mw.submit_transcription(mp,trans,{'complete':True,'reviewed_measures':trans['play_order'],'viewed_pdf':True,'viewed_sources':list(map(lambda x:str(x.resolve()),sources)),'notes':'Agent实际查看新原谱所有34行与最终PDF，逐小节记录135个written IDs、原源位置、候选voice tapes与fractionevents。complete仅表示全谱审阅覆盖；复杂小节和无作者鼓映射仍在unresolved，不宣称音乐正确或MIDIpassed。'})
try:mw.export_complete(mp)
except ValueError as e:(base/'midi-export-rejection.json').write_text(json.dumps({'error':str(e),'pdf_before':before,'pdf_after':hashlib.sha256(pdf.read_bytes()).hexdigest(),'status':mw.resume(mp)['status'],'written_measures':135,'candidate_events':sum(len(m['events']) for m in measures),'candidate_unresolved':len(unresolved),'model_cost':None},indent=2))
print('measures',len(measures),'events',sum(len(m['events']) for m in measures),'unresolved',len(unresolved),'midi',mw.resume(mp)['status'])
