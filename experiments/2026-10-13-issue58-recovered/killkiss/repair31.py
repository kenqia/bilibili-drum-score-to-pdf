import sys,json
from pathlib import Path
sys.path.insert(0,'skills/bilibili-drum-score-to-pdf/scripts');import score_workflow as w
base=Path('experiments/2026-10-13-issue58-recovered/killkiss').resolve();s=json.loads((base/'selection-review.json').read_text());s['regions'][7]=dict(capture='capture-0010',bbox=[35,377,1855,568],kind='system',staff_top=90,staff_spacing=13.625,position='measures-start-28')
s['review']['viewed_captures'].append('capture-0010');s['review']['notes']+=' 独立root复核发现86秒31grace被固定水印覆盖；78秒实际新补采完整28–31行，31grace清楚，无像素修补。此前vector与生图旧导出保留为被替代失败版本。'
(base/'selection-review-repaired.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
for name in ('task','forced-vector'):
 p=base/name
 if name=='forced-vector':w.capture(p,78)
 r=w.load(p);assert r['captures'][-1]['id']=='capture-0010'
 w.present(p,['capture-0010'],'实际查看78秒原帧完整28行，新位置避开固定水印，31grace笔划完整；forced-vector独立新帧hash与已view图相同。')
 w.assemble(p,'KiLLKiSS',s['regions'],s['review']);pages=w.redraw_inputs(p)
 if name=='forced-vector':
  for page in pages:w.fail_redraw(p,page['id'],'整曲额外验收强制生图不可用；31水印失败修复后重新正常矢量转描。')
  print('vector',w.export(p)['pdf'])
 else:print('pages',json.dumps(pages));print('request',json.dumps(w.begin_redraw(p,'page-1','实际已view本次新78秒28行与原粗拼：31grace避开水印；保留全11系统音乐。')))
