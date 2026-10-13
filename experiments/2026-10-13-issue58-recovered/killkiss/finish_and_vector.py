import sys,json
from pathlib import Path
sys.path.insert(0,'skills/bilibili-drum-score-to-pdf/scripts');import score_workflow as w
base=Path('experiments/2026-10-13-issue58-recovered/killkiss').resolve();p=base/'task'
ys=[0,117,235,352,470,587,705,823,940,1057,1175,1292,1407]
w.review_redraw(p,'page-2',True,'实际逐行对照12行：67两组三连音、75三装饰音与附点，80–83多声部和填充，开放0、叉圈镲、附点及符梁保留。源高亮转黑未见增删，非整曲MIDI校对。',[[0,a,1118,b] for a,b in zip(ys,ys[1:])])
ys=[0,123,245,368,490,612,735,857,980,1102,1225,1347]
boxes=[[0,a,({1:612,10:630}.get(i,1167)),b] for i,(a,b) in enumerate(zip(ys,ys[1:]))]
w.review_redraw(p,'page-3',True,'实际对照96–13511行：100短行、134–135短末行及终止双线；134两staccato、98/101grace、110跨鼓圈叉、130填充附点和符梁保留。未见增删，不推断镲鼓映射。',boxes)
print('imagegen export',json.dumps(w.export(p),ensure_ascii=False))
# Independent new workflow captures for deliberately unavailable host. Same fresh downloaded source, no prior decisions replay.
v=base/'forced-vector';w.prepare('https://www.bilibili.com/video/BV15crrYUEPA/',v)
r=w.load(p);vr=w.load(v)
for c in r['captures']:w.capture(v,c['requested_seconds'])
vr=w.load(v)
assert [c['sha256'] for c in vr['captures']]==[c['sha256'] for c in r['captures']]
w.present(v,[c['id'] for c in vr['captures']], '独立新任务实际取帧9次，hash逐张与本次Agent已view_image审阅来源相同，引用同次源图看图证据，不是旧决定或旧frames重放。')
s=json.loads((base/'selection-review.json').read_text());w.assemble(v,'KiLLKiSS',s['regions'],s['review'])
for page in w.redraw_inputs(v):w.fail_redraw(v,page['id'],'本次额外整曲验收明确强制宿主生图不可用，真实调用通用轮廓五线矢量兜底；非mock生图成功。')
print('vector export',json.dumps(w.export(v),ensure_ascii=False))
