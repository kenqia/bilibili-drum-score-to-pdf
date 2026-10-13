import xml.etree.ElementTree as E,json
from pathlib import Path
base=Path('/tmp/issue54-midi-results/audiveris');out=base/'exchange-corrected';out.mkdir(exist_ok=True);jobs=[]
for p in sorted(base.glob('measure-*.musicxml')):
 r=E.parse(p).getroot()
 for e in r.findall('part-list/score-part/midi-instrument/midi-unpitched'):e.text=str(int(e.text)+1)
 measure=r.find('part/measure'); direction=E.Element('direction');E.SubElement(direction,'sound',{'tempo':'200'}); measure.insert(1,direction)
 target=out/p.name; E.ElementTree(r).write(target,encoding='utf-8',xml_declaration=True)
 jobs.append({'in':str(target),'out':str(target.with_suffix('.mid'))})
(out/'jobs.json').write_text(json.dumps(jobs))
