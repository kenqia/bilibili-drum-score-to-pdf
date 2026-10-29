# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
#!/usr/bin/env python3
"""DrumScore v2 - chronological staff tracking + clean-frame compositing + review editor.
For vertical-scrolling / upward page-cut five-line music notation videos.
No score reconstruction and no guarantee of musical correctness.
"""
from __future__ import annotations
import argparse, base64, html, json, math, statistics, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import cv2
import numpy as np
from . import pdf_backend as fitz
from .legacy_extractor import find_staves, row_feature, compare, has_large_occlusion

@dataclass
class Observation:
    image:np.ndarray
    feature:np.ndarray
    y:float
    pitch:float
    t:float
    score:float
    color_fraction:float
    row_id:int=-1

@dataclass
class System:
    observations:list[Observation]=field(default_factory=list)
    feature:Optional[np.ndarray]=None
    first:float=0.
    last:float=0.
    flags:list[str]=field(default_factory=list)
    start_bar:Optional[int]=None  # Optional human-confirmed anchor in page-shot recipes

    def add(self, obs):
        if not self.observations:
            self.feature=obs.feature
            self.first=obs.t
        self.last=obs.t
        # Candidate selection with visual variation from color overlay and timestamps.
        if len(self.observations)<14:
            self.observations.append(obs)
        else:
            existing=self.observations
            worst=max(range(len(existing)),key=lambda i:existing[i].score)
            if obs.score<existing[worst].score-.005:
                existing[worst]=obs
        if obs.score<min(o.score for o in self.observations):
            self.feature=obs.feature

    def best(self):
        return min(self.observations,key=lambda o:o.score)


def score_image(img):
    hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    color=((hsv[:,:,1]>42)&(hsv[:,:,2]>92))
    color_fr=float(color.mean())
    # Color cursor/highlight is unwanted. Large saturated banners are worst.
    too_dark=(gray<100).mean()
    # Score quality is primarily color occlusion, then too much black artifact.
    q=color_fr*13 + max(0,too_dark-.17)*15
    return float(q),color_fr


def capture_obs(fr,t,staff,analysis_width=960,first=False):
    """Detection on scaled analysis image, cropping from native-resolution frame."""
    h,w=fr.shape[:2]
    ratio=min(1.0,analysis_width/w)
    small=cv2.resize(fr,(round(w*ratio),round(h*ratio)),interpolation=cv2.INTER_AREA) if ratio<1 else fr
    staves=find_staves(small)
    if not staves:return []
    centers=[q[0] for q in staves]; pitch=float(statistics.median(q[1] for q in staves))
    gaps=[v-u for u,v in zip(centers,centers[1:]) if v-u>pitch*6]
    gap=float(statistics.median(gaps)) if gaps else pitch*12.3
    gap=min(gap,small.shape[0]*.33)
    out=[]
    for j,(cy,p,left,right) in enumerate(staves):
        # Crop must include the notes above and below staff. Avoid clipped staves.
        if cy < min(gap*.37,p*5.5) or cy > small.shape[0]-min(gap*.40,p*5.3): continue
        feat=row_feature(small,cy,p,left,right)
        if feat.sum()<52:continue
        ty=max(0,int((cy-gap*.52)/ratio))
        by=min(h,int((cy+gap*.48)/ratio))
        if j==0 and first and cy>gap*.78:ty=0  # capture title above the initial score
        if by-ty<18:continue
        img=fr[ty:by].copy()
        q,c=score_image(img)
        out.append(Observation(img,feat,float(cy),float(p),float(t),q,c))
    return out


def candidate_similarity(a,b):
    return compare(a.feature,b.feature)


def stationary_link(prev,cur):
    """Prefer actual y position when screen is static or creeping slowly."""
    pairs=[];used=set()
    for i,a in enumerate(prev):
        choices=[]
        for j,b in enumerate(cur):
            if j in used:continue
            dy=abs(a.y-b.y)
            if dy>8:continue
            sim=candidate_similarity(a,b)
            if sim>.42: choices.append((sim-.009*dy,j,sim))
        if choices:
            val,j,sim=max(choices)
            pairs.append((i,j));used.add(j)
    if len(pairs)>=2 and len(pairs)>=min(len(cur),len(prev))*.55:
        # No backward travel; matching to fixed screen rows overrules similar grooves.
        return pairs
    return []


def temporal_link(prev,cur):
    """For smooth upward scrolling: match via content *and* a common vertical motion."""
    offsets={j-i for i in range(len(prev)) for j in range(len(cur))}
    best=None
    for d in offsets:
        pairs=[(i,i+d) for i in range(len(prev)) if 0<=i+d<len(cur)]
        good=[]
        for i,j in pairs:
            sim=candidate_similarity(prev[i],cur[j])
            dy=cur[j].y-prev[i].y
            if sim>.59 and -115<dy<15:good.append((i,j,sim,dy))
        if len(good)<2:continue
        median_dy=np.median([q[3] for q in good]);coherent=[x for x in good if abs(x[3]-median_dy)<14]
        if len(coherent)<2:continue
        strength=sum(x[2]-.47 for x in coherent)+.22*len(coherent)-.1*(len(pairs)-len(coherent))
        if best is None or strength>best[0]:best=(strength,[(x[0],x[1]) for x in coherent])
    return best[1] if best else []


def jump_link(prev,cur):
    """Hard page switch: only accept strong, ordered tail-to-head overlaps."""
    options=[]
    for d in range(-len(prev)+1,len(cur)):
        pairs=[(i,i+d) for i in range(len(prev)) if 0<=i+d<len(cur)]
        if not pairs:continue
        # Require suffix of previous and prefix of current (typical forward page turn).
        if not (pairs[-1][0]==len(prev)-1 and pairs[0][1]==0):continue
        sims=[candidate_similarity(prev[i],cur[j]) for i,j in pairs]
        strong=[(i,j,s) for (i,j),s in zip(pairs,sims) if s>.72]
        if not strong:continue
        score=sum(s-.55 for _,_,s in strong)-.16*(len(pairs)-len(strong))
        options.append((score,strong,pairs))
    if not options:return []
    score,strong,pairs=max(options,key=lambda x:x[0])
    if score<.15:return []
    # Single overlap is possible but uncertain. Require 0.8 exactness.
    if len(strong)==1 and strong[0][2]<.80:return []
    return [(i,j) for i,j,s in strong]


def assign(prev,cur,rows,stats):
    if not prev:
        for ob in cur:
            ob.row_id=len(rows);s=System();s.add(ob);rows.append(s)
        return
    links=stationary_link(prev,cur)
    strategy='stationary'
    if not links:
        links=temporal_link(prev,cur);strategy='motion'
    if not links:
        links=jump_link(prev,cur);strategy='jump'
    if links:
        offsets=[prev[i].row_id-j for i,j in links]
        k=int(round(statistics.median(offsets)))
        if any(abs(o-k)>0 for o in offsets):
            # Inconsistent fingerprint alignment: never silently collapse.
            stats['conflicting_links']+=1
            links=[]
    if not links:
        stats['unverified_transitions']+=1
        k=len(rows)
        for ob in cur:
            ob.row_id=len(rows);s=System(flags=['在跳屏处追加；可能需要核对与上一屏是否重叠']);s.add(ob);rows.append(s)
        return
    stats[strategy+'_matches']+=1
    n_added=0
    for j,ob in enumerate(cur):
        index=k+j
        # Never insert before accumulated chronology: mark instead.
        if index<0:
            stats['conflicting_links']+=1;continue
        if index<len(rows):
            sim=candidate_similarity(rows[index].observations[-1],ob)
            # y tracking is authoritative on stationary pages. For new shot require resemblance.
            if (strategy=='stationary' and abs(rows[index].observations[-1].y-ob.y)<8) or sim>.58:
                ob.row_id=index;rows[index].add(ob)
            else:
                # Do not assign contradicting content to an established row.
                stats['conflicting_links']+=1
        elif index==len(rows):
            ob.row_id=index;s=System();s.add(ob);rows.append(s);n_added+=1
        else:
            # Shouldn't happen for chronological page progression.
            stats['conflicting_links']+=1
    stats['rows_added']+=n_added


def extract(video,interval=1.0,start=0.,end=None,verbose=True):
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():raise RuntimeError(f'Cannot open {video}')
    fps=cap.get(cv2.CAP_PROP_FPS) or 25
    duration=float(cap.get(cv2.CAP_PROP_FRAME_COUNT))/fps
    stop=min(duration-.1,end if end is not None else duration)
    rows=[];prev=[]
    stats={key:0 for key in ['frames','occluded','stationary_matches','motion_matches','jump_matches','unverified_transitions','conflicting_links','rows_added']}
    for t in np.arange(start,stop,max(.10,interval)):
        cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000)
        ok,fr=cap.read()
        if not ok:continue
        stats['frames']+=1
        # Filtering only *giant* opaque obstructions. Don't delete notes over highlights.
        if has_large_occlusion(cv2.resize(fr,(852,round(fr.shape[0]*852/fr.shape[1]))) if fr.shape[1]>1000 else fr):
            stats['occluded']+=1;continue
        cur=capture_obs(fr,t,True,first=not rows)
        if not cur:continue
        assign(prev,cur,rows,stats)
        prev=[o for o in cur if o.row_id>=0]
        if verbose and stats['frames']%40==0:
            print(f'  {t:5.1f}s: {len(rows)} rows, transitions={stats["unverified_transitions"]}',flush=True)
    cap.release()
    return rows,stats


def crop_uncolored_fusion(system):
    """Borrow uncolored pixels from same-sized time samples, then flatten paper lighting."""
    best=system.best();base=best.image
    g0=cv2.cvtColor(base,cv2.COLOR_BGR2GRAY).astype(np.float32)
    hsv0=cv2.cvtColor(base,cv2.COLOR_BGR2HSV)
    current_color=(hsv0[:,:,1]>42)&(hsv0[:,:,2]>92)
    merged=g0.copy()
    unresolved=current_color.copy()
    # Only pixels whose base sample has a colored overlay may be substituted.
    for cand in sorted(system.observations,key=lambda o:o.score):
        if cand is best or abs(cand.image.shape[0]-base.shape[0])>2 or cand.image.shape[1]!=base.shape[1]:continue
        alt=cand.image
        if alt.shape!=base.shape: continue  # avoid one-pixel staff displacement corrupting fine notation
        gray=cv2.cvtColor(alt,cv2.COLOR_BGR2GRAY)
        hsv=cv2.cvtColor(alt,cv2.COLOR_BGR2HSV)
        usable=(hsv[:,:,1]<25)&(hsv[:,:,2]>65)
        # avoid merging if note edges move substantially due to a frame jump
        bmask=cv2.Canny(cv2.cvtColor(base,cv2.COLOR_BGR2GRAY),70,150)
        amask=cv2.Canny(gray,70,150)
        common=((bmask>0)&(amask>0)).sum()
        total=((bmask>0)|(amask>0)).sum()
        if total>0 and common/total <.35:continue
        restore=unresolved&usable
        merged[restore]=gray[restore];unresolved[restore]=False
        if not unresolved.any():break
    # Local illumination correction removes pastel background and pale watermarks
    # without hallucinating notation. Uses broad blur rather than hard threshold.
    paper=cv2.GaussianBlur(merged,(0,0),sigmaX=24,sigmaY=17)
    output=np.uint8(np.clip(merged+.84*(250-paper)+5,0,255))
    return output


def emit_pdf(rows,path,rows_per_page=8,margin_mm=10,numbered_png=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    w,h=fitz.paper_size('a4');m=margin_mm*72/25.4;cw=w-2*m
    pdf=fitz.open()
    ims=[crop_uncolored_fusion(r) for r in rows]
    if numbered_png:
        thumbs=[]
        for i,img in enumerate(ims):
            ww=960;hh=max(32,round(img.shape[0]*ww/img.shape[1]))
            out=cv2.resize(img,(ww,hh),interpolation=cv2.INTER_AREA)
            out=cv2.copyMakeBorder(out,22,0,0,0,cv2.BORDER_CONSTANT,value=248)
            cv2.putText(out,f'{i+1:02d}   {rows[i].first:.1f}s   views={len(rows[i].observations)}   {"CHECK" if rows[i].flags else ""}',(5,15),cv2.FONT_HERSHEY_SIMPLEX,.38,75,1,cv2.LINE_AA)
            thumbs.append(out)
        if thumbs:
            long=np.vstack([x for im in thumbs for x in (im,np.full((3,960),196,np.uint8))]);cv2.imwrite(str(numbered_png),long)
    for start in range(0,len(ims),rows_per_page):
        images=ims[start:start+rows_per_page];p=pdf.new_page(width=w,height=h)
        heights=[img.shape[0]*cw/img.shape[1] for img in images]
        fac=min(1.0,(h-2*m-7*(len(images)-1))/sum(heights))
        y=m
        for img,hh in zip(images,heights):
            scaled_w=cw*fac;scaled_h=hh*fac;xx=(w-scaled_w)/2
            ok,buff=cv2.imencode('.png',img)
            if ok:p.insert_image(fitz.Rect(xx,y,xx+scaled_w,y+scaled_h),stream=buff.tobytes())
            y+=scaled_h+7
    pdf.save(str(path),garbage=4,deflate=True)
    count=len(pdf);pdf.close()
    return count


def write_metadata(rows,stats,path):
    data={'version':'2.0.0','method':'chronological y-tracking + image matching','statistics':stats,'systems':[]}
    for i,r in enumerate(rows,1):
        b=r.best()
        data['systems'].append({'id':i,'time_s':round(r.first,2),'best_time_s':round(b.t,2),'views':len(r.observations),'quality':round(b.score,3),'flags':r.flags,'order':i,'include':True,'first_bar':r.start_bar})
    Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    return data


def create_review_html(rows,path):
    """Standalone offline row organizer; exports JSON consumable with --apply."""
    js=[]
    for i,r in enumerate(rows,1):
        im=crop_uncolored_fusion(r)
        if im.shape[1]>1100:im=cv2.resize(im,(1100,round(im.shape[0]*1100/im.shape[1])))
        _,buf=cv2.imencode('.jpg',im,[cv2.IMWRITE_JPEG_QUALITY,88])
        js.append({'id':i,'src':'data:image/jpeg;base64,'+base64.b64encode(buf.tobytes()).decode('ascii'),'t':round(r.first,1),'best':round(r.best().t,1),'flags':r.flags,'bar':r.start_bar})
    payload=json.dumps(js,ensure_ascii=False)
    template=r'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DrumScore v2 谱行校对</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f5f8;color:#202936;margin:0}.bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #cbd5e1;padding:12px 16px;z-index:9;display:flex;gap:12px;align-items:center;flex-wrap:wrap}button{border:1px solid #94a3b8;border-radius:7px;padding:7px 10px;background:white;cursor:pointer}.primary{background:#0f172a;color:white}#rows{margin:20px auto;max-width:1100px}.system{background:#fff;padding:12px;margin-bottom:12px;border:1px solid #d9dfe7;border-radius:10px}.system img{width:100%;object-fit:contain}.system.muted{opacity:.4}.head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}small{color:#64748b}.warn{color:#a16207}.left{margin-left:auto}details{max-width:750px}summary{cursor:pointer}</style></head><body><div class="bar"><b>DrumScore v2 · 离线校对</b><small>可调整顺序、删除重复行、保留疑似缺失提示</small><button class="primary" onclick="save()">导出校订 JSON</button><span id="count"></span></div><main id="rows"></main>
<script>let entries=__PAYLOAD__.map(x=>({...x,include:true}));
function render(){let root=document.getElementById('rows');root.innerHTML='';entries.forEach((e,i)=>{let box=document.createElement('section');box.className='system'+(e.include?'':' muted');let hd=document.createElement('div');hd.className='head';let title=document.createElement('b');title.textContent=`显示序号 ${i+1} · 原谱行 ${e.id}${e.bar===null?'':` · 小节 ${e.bar}`}`;hd.append(title);let detail=document.createElement('small');detail.textContent=`首次出现 ${e.t}s · 最佳取帧 ${e.best}s`;hd.append(detail);if(e.flags.length){let f=document.createElement('small');f.className='warn';f.textContent='⚠ '+e.flags.join('; ');hd.append(f)}let spacer=document.createElement('span');spacer.className='left';hd.append(spacer);for(let [label,fn] of [['↑',()=>move(i,-1)],['↓',()=>move(i,1)],[''+(e.include?'排除':'恢复'),()=>{e.include=!e.include;render()}]]){let b=document.createElement('button');b.textContent=label;b.onclick=fn;hd.append(b)}box.append(hd);let im=document.createElement('img');im.src=e.src;im.loading='lazy';box.append(im);root.append(box)});document.getElementById('count').textContent=`共 ${entries.length} 行 / 保留 ${entries.filter(x=>x.include).length} 行`}
function move(i,d){let j=i+d;if(j<0||j>=entries.length)return;[entries[i],entries[j]]=[entries[j],entries[i]];render()}
function save(){let data={version:'2.0.0',systems:entries.map((e,i)=>({id:e.id,order:i+1,include:e.include}))};let blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});let link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='drumscore_review.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)}render();</script></body></html>'''
    Path(path).write_text(template.replace('__PAYLOAD__',payload),encoding='utf-8')


def manual_observation(frame, t, cy, height, title=False):
    h,w=frame.shape[:2]
    top=max(0,round(cy-height*.53));bottom=min(h,round(cy+height*.47))
    if title:top=0
    im=frame[top:bottom].copy()
    score,cf=score_image(im)
    # Manual rows are identified through user-chosen location, not invented note features.
    return Observation(im,np.zeros((70,426),bool),float(cy),0.0,float(t),score,cf)


def extract_shots(video, recipe_path, verbose=True):
    """User-guided page stitching: explicit timestamps / accepted detected indexes.
    This is the recommended fallback for videos with abrupt page changes,
    transparent banners, failed five-line recognition, or repeated grooves.
    Recipe format is specified in README and examples.
    """
    recipe=json.loads(Path(recipe_path).read_text(encoding='utf8'))
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():raise RuntimeError(f'Cannot open {video}')
    rows=[]
    stats={'frames':0,'manual_scenes':len(recipe['scenes']), 'manual_rows':0,
           'occluded':0,'stationary_matches':0,'motion_matches':0,
           'jump_matches':0,'unverified_transitions':0,'conflicting_links':0,'rows_added':0}
    for scene_ix,scene in enumerate(recipe['scenes']):
        t=float(scene['time_s'])
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read()
        if not ok:raise ValueError(f'Cannot seek to {t}s for scene {scene_ix}')
        stats['frames']+=1
        obs=capture_obs(frame,t,None,first=(scene_ix==0))
        selected=scene.get('indexes',list(range(len(obs))))
        if verbose:print(f'  Scene {scene_ix+1}: {t:.1f}s; staff rows={len(obs)}, keep={selected}',flush=True)
        for ii in selected:
            if not 0<=ii<len(obs):raise ValueError(f'At {t}s, staff index {ii} absent: only {len(obs)} detected')
            o=obs[ii];system=System();system.add(o)
            # Optional multiple samples within same stable page, by matching row position
            # and a strong notation fingerprint, not guessed pixel content.
            for delta in ([] if (scene_ix==0 and ii==selected[0]) else scene.get('alternates_s',[])):
                nt=t+float(delta)
                if nt<0:continue
                cap.set(cv2.CAP_PROP_POS_MSEC,nt*1000)
                got,fr=cap.read()
                if not got:continue
                extras=capture_obs(fr,nt,None)
                possible=[q for q in extras if abs(q.y-o.y)<2.8 and compare(q.feature,o.feature)>.68]
                if possible:system.add(min(possible,key=lambda x:x.score))
            if 'first_bars' in scene:
                jj=selected.index(ii)
                system.start_bar=int(scene['first_bars'][jj])
            rows.append(system)
        scene_start=len(rows)-len(selected)
        for manual in scene.get('manual',[]):
            o=manual_observation(frame,t,float(manual['center_y']),float(manual['height']),bool(manual.get('title',False)))
            system=System(flags=[f'手工裁剪：{manual.get("label","特殊谱行")}；请核对音符完整性'])
            system.add(o)
            if 'first_bar' in manual:system.start_bar=int(manual['first_bar'])
            for delta in manual.get('alternates_s',scene.get('alternates_s',[])):
                nt=t+float(delta)
                cap.set(cv2.CAP_PROP_POS_MSEC,nt*1000)
                good,fr=cap.read()
                if good and fr.shape==frame.shape:
                    system.add(manual_observation(fr,nt,float(manual['center_y']),float(manual['height'])))
            # By default manual entries are appended after selected rows. For placement
            # within this scene supply before_index (0-based among the scene selected items).
            place=int(manual.get('before_index',len(selected)))
            # Append first, then optionally move before a selected staff.
            rows.append(system)
            if place<len(selected):rows.insert(scene_start+place,rows.pop())
            stats['manual_rows']+=1
    cap.release()
    stats['rows_added']=len(rows)
    anchors=[r.start_bar for r in rows if r.start_bar is not None]
    if anchors:
        stats['anchored_rows']=len(anchors)
        for a,b in zip(anchors,anchors[1:]):
            if b<=a:stats['conflicting_links']+=1
        if stats['conflicting_links']:print('WARNING: first-bar anchors are not strictly increasing; review recipe!')
    return rows,stats


def applied_rows(rows,path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    by_id={i+1:row for i,row in enumerate(rows)}
    ordered=sorted(data['systems'],key=lambda v:v.get('order',v['id']))
    return [by_id[int(s['id'])] for s in ordered if s.get('include',True) and int(s['id']) in by_id]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path)
    p.add_argument('-o','--output',type=Path)
    p.add_argument('--interval',type=float,default=1.0)
    p.add_argument('--start',type=float,default=0)
    p.add_argument('--end',type=float,default=None)
    p.add_argument('--rows-per-page',type=int,default=8)
    p.add_argument('--apply',type=Path,help='JSON exported from review HTML; rerun extractor and apply new order/deletions')
    p.add_argument('--no-review',action='store_true')
    p.add_argument('--shots',type=Path,help='JSON page-shot recipe: exact times, row indexes, optional manual crops')
    args=p.parse_args()
    if args.interval<=0 or args.rows_per_page<1:p.error('interval and rows-per-page must be >0')
    output=args.output or args.video.with_suffix('.pdf');output.parent.mkdir(parents=True,exist_ok=True)
    print('Analyzing:',args.video,flush=True)
    rows,stats=extract_shots(args.video,args.shots) if args.shots else extract(args.video,args.interval,args.start,args.end)
    if not rows:sys.exit('No full five-line staves detected')
    stem=output.with_suffix('')
    if not args.no_review:
        write_metadata(rows,stats,Path(str(stem)+'_report.json'))
        create_review_html(rows,Path(str(stem)+'_review.html'))
    if args.apply:rows=applied_rows(rows,args.apply)
    png=Path(str(stem)+'_overview.png')
    pages=emit_pdf(rows,output,args.rows_per_page,numbered_png=png)
    print(json.dumps({'pdf':str(output),'rows':len(rows),'pages':pages,'stats':stats,'overview':str(png)},ensure_ascii=False,indent=2))
    if stats['unverified_transitions'] or stats['conflicting_links']:
        print('IMPORTANT: Review the numbered overview/HTML: transitions may contain duplicates or gaps.')

if __name__=='__main__':main()
