import sys,json
from pathlib import Path
sys.path.insert(0,'skills/bilibili-drum-score-to-pdf/scripts')
import score_workflow as w
p=Path('experiments/2026-10-13-issue58-recovered/killkiss/task').resolve()
r=w.load(p)
w.present(p,[x['id'] for x in r['captures']+r['probes']], '实际 view_image 查看 9 张原生来源、10 张导航，核对有序上滚与同一行重叠；140秒专补80行；208.5秒确认最终134–135行后无新增。')
regions=[dict(capture='capture-0001',bbox=[35,190,1855,394],kind='header',position='header')]
# Fresh viewed row positions; staff coordinates measured on new original frames.
selected=[(1,1,484),(6,1,675),(12,1,866),(16,2,540),(20,2,731.5),(24,2,922.5),(28,3,79),(32,3,270),(36,3,461),(40,3,652.5),(44,3,843.5),(48,4,259),(52,4,450),(56,4,641),(60,4,832),(64,5,247.5),(68,5,438.5),(72,5,630),(76,5,821),(80,9,365),(84,6,168.5),(88,6,359.5),(92,6,551),(96,6,742),(100,6,933),(102,7,219),(106,7,410),(110,7,601),(114,7,792.5),(118,8,207.5),(122,8,399),(126,8,590),(130,8,781),(134,8,972)]
for number,cap,staff in selected:
 top=max(20,round(staff-90));bottom=min(1080,round(staff+101));right={100:990,134:1010}.get(number,1855)
 regions.append(dict(capture=f'capture-{cap:04d}',bbox=[35,top,right,bottom],kind='system',staff_top=staff-top,staff_spacing=13.75,position=f'measures-start-{number}'))
review=dict(viewed_captures=[x['id'] for x in r['captures']],complete=True,unresolved=[],scope='whole score 135 measures, 34 systems',continuity='Printed starts 1,6,12,16 then four-measure rows; rest10–11 accounts jump6→12; 100–101 short row then102; overlap confirmed44,60,76,84,88,92,118; omitted incomplete rows only after obtaining full new source.',first_last='0秒完整标题和第1行；191秒完整134–135结尾，208.5秒仍此结尾下白区无新谱。',notes='实际看图核对 KiLLKiSS / Ave Mujica / 陈老师，200BPM 4/4，34完整行135小节，10–11多小节休止，67三连音，75装饰音，100短行和134–135短末行。高亮保留音符形状，不推断未知镲鼓件。')
w.assemble(p,'KiLLKiSS',regions,review)
pages=w.redraw_inputs(p)
Path('experiments/2026-10-13-issue58-recovered/killkiss/selection-review.json').write_text(json.dumps(dict(regions=regions,review=review),ensure_ascii=False,indent=2))
print(json.dumps(pages,ensure_ascii=False))
