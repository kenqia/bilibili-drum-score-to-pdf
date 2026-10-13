import copy, json, zipfile, xml.etree.ElementTree as E
from pathlib import Path
base=Path('/tmp/issue54-midi-results/audiveris')
with zipfile.ZipFile(base/'KiLLKiSS-vector-compact.mxl') as z:r=E.fromstring(z.read('KiLLKiSS-vector-compact.xml'))
measures=r.find('part').findall('measure'); attrs={}; snapshots=[]
for m in measures:
 a=m.find('attributes')
 if a is not None:
  for e in a:attrs[e.tag]=copy.deepcopy(e)
 snapshots.append(copy.deepcopy(attrs))
jobs=[]
for n in [1,2,10,23,27,32,67,75,110,111,112,113,134,135]:
 idx=n-1 if n<=10 else n-2
 root=E.Element('score-partwise',{'version':'4.0'}); root.append(copy.deepcopy(r.find('part-list')))
 part=E.SubElement(root,'part',{'id':'P1'}); m=copy.deepcopy(measures[idx])
 for e in list(m):
  if e.tag in ('print','attributes'):m.remove(e)
 a=E.Element('attributes')
 for e in snapshots[idx].values():a.append(e)
 m.insert(0,a);part.append(m)
 p=base/f'measure-{n:03d}.musicxml'; E.ElementTree(root).write(p,encoding='utf-8',xml_declaration=True)
 jobs.append({'in':str(p),'out':str(p.with_suffix('.mid'))})
(base/'jobs.json').write_text(json.dumps(jobs))
