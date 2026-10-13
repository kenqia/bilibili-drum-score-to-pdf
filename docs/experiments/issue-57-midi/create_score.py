from pathlib import Path
import xml.etree.ElementTree as E
r=E.Element('score-partwise',version='4.0');w=E.SubElement(r,'work');E.SubElement(w,'work-title').text='Complete percussion review study'
ident=E.SubElement(r,'identification');E.SubElement(ident,'creator',type='composer').text='Controlled complete-score acceptance fixture'
pl=E.SubElement(r,'part-list');p=E.SubElement(pl,'score-part',id='P1');E.SubElement(p,'part-name').text='Drumset'
for key,name in [(36,'Bass drum'),(38,'Snare'),(46,'Open hi-hat'),(49,'Crash')]:
 i=E.SubElement(p,'score-instrument',id=f'I{key}');E.SubElement(i,'instrument-name').text=name
 i=E.SubElement(p,'midi-instrument',id=f'I{key}');E.SubElement(i,'midi-channel').text='10';E.SubElement(i,'midi-unpitched').text=str(key+1)
p=E.SubElement(r,'part',id='P1')
def direction(m,text=None,tempo=None,dynamic=None):
 d=E.SubElement(m,'direction',placement='below' if tempo==160 else 'above');t=E.SubElement(d,'direction-type')
 if text:E.SubElement(t,'words').text=text
 if dynamic:E.SubElement(E.SubElement(t,'dynamics'),dynamic)
 if tempo:
  met=E.SubElement(t,'metronome');E.SubElement(met,'beat-unit').text='quarter';E.SubElement(met,'per-minute').text=str(tempo);E.SubElement(d,'sound',tempo=str(tempo))
def measure(n,meter,tempo):
 m=E.SubElement(p,'measure',number=str(n));a=E.SubElement(m,'attributes');E.SubElement(a,'divisions').text='48';t=E.SubElement(a,'time');E.SubElement(t,'beats').text=str(meter);E.SubElement(t,'beat-type').text='4';c=E.SubElement(a,'clef');E.SubElement(c,'sign').text='percussion';direction(m,tempo=tempo);return m
def note(m,key,duration,kind,voice=1,dot=False,tuplet=False,grace=False,chord=False,beam=None):
 n=E.SubElement(m,'note')
 if grace:E.SubElement(n,'grace',slash='yes')
 if chord:E.SubElement(n,'chord')
 if key is None:E.SubElement(n,'rest')
 else:
  u=E.SubElement(n,'unpitched');step,octave={36:('F',4),38:('C',5),46:('G',5),49:('A',5)}[key];E.SubElement(u,'display-step').text=step;E.SubElement(u,'display-octave').text=str(octave)
 if not grace:E.SubElement(n,'duration').text=str(duration)
 if key:E.SubElement(n,'instrument',id=f'I{key}')
 E.SubElement(n,'voice').text=str(voice);E.SubElement(n,'type').text=kind
 if dot:E.SubElement(n,'dot')
 if tuplet:
  t=E.SubElement(n,'time-modification');E.SubElement(t,'actual-notes').text='3';E.SubElement(t,'normal-notes').text='2';E.SubElement(t,'normal-type').text='eighth'
 if key:
  E.SubElement(n,'stem').text='up' if voice==1 else 'down'
  if key in (46,49):E.SubElement(n,'notehead').text='x'
  if key==46:E.SubElement(E.SubElement(n,'notations'),'technical');E.SubElement(n.find('notations/technical'),'open-string')
 if beam:
  E.SubElement(n,'beam',number='1').text=beam
 return n
m=measure(1,4,120);direction(m,'Legend: bottom-space oval = Bass drum GM36; C5 oval = Snare GM38\nG5 x+o = Open hi-hat GM46; A5 x = Crash GM49\nVelocity: unmarked96, f112, p64, grace48. Grace1/16 beat before main.\nRepeat playback resets first-measure velocity to96.\nGrace cuts preceding same-drum release at its onset; notation unchanged.')
b=E.SubElement(m,'barline',location='left');E.SubElement(b,'repeat',direction='forward')
for j in range(3):
 n=note(m,38,16,'eighth',tuplet=True,beam=['begin','continue','end'][j]);nts=n.find('notations')
 if nts is None:nts=E.SubElement(n,'notations')
 if j in (0,2):E.SubElement(nts,'tuplet',type='start' if j==0 else 'stop',number='1')
note(m,38,0,'eighth',grace=True);note(m,38,36,'eighth',dot=True,beam='begin');note(m,38,12,'16th',beam='end')
note(m,46,24,'eighth',beam='begin');note(m,46,24,'eighth',beam='end');note(m,49,48,'quarter')
E.SubElement(E.SubElement(m,'backup'),'duration').text='192'
for key in [36,None,36,None]:note(m,key,48,'quarter',voice=2)
m=measure(2,3,160);direction(m,dynamic='f');note(m,38,48,'quarter');note(m,38,48,'quarter');note(m,None,48,'quarter');b=E.SubElement(m,'barline',location='right');E.SubElement(b,'repeat',direction='backward',times='2')
m=measure(3,4,100);direction(m,dynamic='p');note(m,None,192,'whole');b=E.SubElement(m,'barline',location='right');E.SubElement(b,'bar-style').text='light-heavy'
E.ElementTree(r).write(str(Path(__file__).resolve().parent/'source.musicxml'),encoding='utf-8',xml_declaration=True)
