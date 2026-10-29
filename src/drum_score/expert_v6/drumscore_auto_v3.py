# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
#!/usr/bin/env python3
"""DrumScore v3: MP4 -> image-faithful A4 sheet-music PDF.

Automatic page-cut extraction with chronological ordered overlap, detection-hole
recovery, and optional offline review. Smooth-scroll and uncertain videos use
v2 chronological tracker. Never transcribes or invents missing music symbols.
"""
from __future__ import annotations
import argparse, json, sys, statistics, math, shutil
from pathlib import Path
from dataclasses import dataclass
import cv2
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from .drumscore_v2 import (Observation,System,capture_obs,manual_observation,extract as scrolling_extract,
                          emit_pdf,create_review_html,write_metadata,applied_rows,score_image)
from .legacy_extractor import compare,has_large_occlusion,extract as legacy_extract

@dataclass
class Page:
    start:float
    end:float
    key_time:float=0.
    rows:list[System]|None=None
    def as_json(self):return {'start_s':round(self.start,1),'end_s':round(self.end,1),'key_s':round(self.key_time,1),'detected':len(self.rows or [])}

def frame_mask(frame):
    sm=cv2.resize(frame,(426,240),interpolation=cv2.INTER_AREA)
    g=cv2.cvtColor(sm,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(sm,cv2.COLOR_BGR2HSV)
    # Robust to yellow highlighter, blue playback line, and pastel watermarks.
    return ((g<133)&((hsv[:,:,1]<100)|(g<75)))[:,10:-10]

def mask_iou(a,b):
    return float(np.count_nonzero(a&b)/max(1,np.count_nonzero(a|b)))

def detect_pages(video,step=2.,min_page=7.):
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():raise RuntimeError(f'Cannot read {video}')
    fps=cap.get(cv2.CAP_PROP_FPS) or 25.
    duration=cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps
    times=np.arange(max(0.,1.),max(1.,duration-.1),max(.5,step))
    last=None;values=[];screens=[]
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000);ok,fr=cap.read()
        if not ok:continue
        mask=frame_mask(fr)
        sim=mask_iou(mask,last) if last is not None else 1.
        values.append((float(t),sim))
        last=mask
    cap.release()
    if not values:raise ValueError('No video frames')
    vals=np.array([s for t,s in values[1:]])
    # Large fraction of frame discontinuities => this is NOT a held-page video.
    jump_rate=float((vals<.50).mean()) if len(vals) else 0.
    candidates=[t for t,s in values if s<.48]
    # A fade can produce 2 consecutive jumps; keep a single page boundary.
    boundaries=[]
    for t in candidates:
        if not boundaries or t-boundaries[-1]>=min_page:boundaries.append(t)
    starts=[0.]+boundaries;ends=boundaries+[duration]
    pages=[Page(a,b) for a,b in zip(starts,ends) if b-a>=min_page*.65]
    return pages,{'jump_rate':round(jump_rate,3),'diff_median':round(float(np.median(vals)),3),'boundaries':boundaries,'length_s':round(duration,2),'mask_step_s':step}

def read_at(cap,t):
    cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000);ok,im=cap.read()
    return im if ok else None

def within_page_samples(page,interval=3.5):
    length=page.end-page.start
    if length<=7:return [page.start+length/2]
    lo=page.start+max(2.,length*.12);hi=page.end-max(2.,length*.10)
    times=np.arange(lo,hi+.01,max(2.,interval))
    if len(times)>17:
        times=np.linspace(lo,hi,17)
    if len(times)<4:times=np.linspace(lo,hi,4)
    return [float(t) for t in times]

def recover_gaps(obs,frame,t,spacing):
    """Repair a missed staff when an otherwise regular row lattice has a hole.

    Safeguards: need an unmistakable 2x staff spacing AND visible black notes
    in candidate crop; the row gets an explicit review flag.
    """
    result=[]
    for j,item in enumerate(obs):
        if j:
            before=obs[j-1];delta=item.y-before.y
            count=round(delta/spacing)
            if 2<=count<=3 and abs(delta/count-spacing)<spacing*.17:
                for k in range(1,count):
                    cy=before.y+delta*k/count
                    estimate=manual_observation(frame,t,cy,spacing)
                    gray=cv2.cvtColor(estimate.image,cv2.COLOR_BGR2GRAY)
                    # Ink density requires actual notation, not empty white space.
                    density=float((gray<135).mean())
                    if density<.018 or density>.50:continue
                    estimate.row_id=-1
                    result.append((estimate,['五线谱检测在规则行间距处漏检；已按行距自动补取，须核对']))
        result.append((item,[]))
    return result

def build_page(video,cap,page,spacing_hint=None,is_first=False):
    sample_times=within_page_samples(page)
    proposals=[]
    for t in sample_times:
        fr=read_at(cap,t)
        if fr is None:continue
        rows=capture_obs(fr,t,None,first=False)
        if not rows:continue
        # favor many reliably complete rows, and cleaner frames; ignore partial edges
        qual=sum(q.score for q in rows)/max(1,len(rows))
        metric=len(rows)*8.0-qual*.12
        proposals.append((metric,t,fr,rows))
    if not proposals:return False
    # Favor sufficiently full screens and avoid title/glossary transient frames.
    _,t,frame,anchor=max(proposals,key=lambda e:e[0])
    page.key_time=t
    gaps=[b.y-a.y for a,b in zip(anchor,anchor[1:]) if 75<(b.y-a.y)<190]
    # Ignore 2x lattice gaps caused by a fully missed staff.
    short=[v for v in gaps if v<=min(gaps)*1.34] if gaps else []
    spacing=float(np.median(short)) if short else spacing_hint
    # Staff centers come from analysis-scaled coordinates; native crop pixels differ.
    if not spacing:spacing=min(frame.shape[0]/4.7,112.)
    # Remove border-cut pseudo-staves: the next page usually offers a full copy.
    scaled_h=frame.shape[0]*min(1.,960/frame.shape[1])
    anchor=[o for o in anchor if o.y+spacing*.45 < scaled_h]
    if not anchor:return False
    anchor_full=recover_gaps(anchor,frame,t,spacing)
    rows=[]
    for ix,(ob,flags) in enumerate(anchor_full):
        r=System(flags=flags.copy());
        if is_first and ix==0 and ob.y>spacing*.80:
            # Title / copyright banner only on the initial musical page.
            original_height=ob.image.shape[0]
            ratio=frame.shape[1]/min(frame.shape[1],960)
            bottom=min(frame.shape[0],round((ob.y+spacing*.52)*ratio))
            if bottom>original_height+10:
                ob.image=frame[:bottom].copy();ob.score,ob.color_fraction=score_image(ob.image)
        r.add(ob)
        r.number_signature=measure_signature(frame,ob)
        r.is_title=bool(is_first and ix==0)
        rows.append(r)
    # Clean candidate pooling: only register alternate views if same y AND same ink.
    for _,tt,fr,candidates in proposals:
        if abs(tt-t)<.1:continue
        for r in rows:
            if getattr(r,'is_title',False):continue  # never lose the title to a tighter crop
            baseline=r.best()
            opts=[o for o in candidates if abs(o.y-baseline.y)<3.5]
            if not opts:continue
            closest=max(opts,key=lambda o:compare(o.feature,baseline.feature) if np.any(baseline.feature) else 0)
            if compare(closest.feature,baseline.feature)>.52:
                # Important: place photo needs consistent crop coordinates for fusion.
                r.add(closest)
    page.rows=rows
    return True

def row_sim(a:System,b:System):
    # Cross-page comparisons of clean distinct candidates, limited combinations.
    v1=sorted(a.observations,key=lambda v:v.score)[:3]
    v2=sorted(b.observations,key=lambda v:v.score)[:3]
    vals=[compare(i.feature,j.feature) for i in v1 for j in v2 if i.feature.shape==j.feature.shape]
    return max(vals,default=0.)

def measure_signature(frame,ob):
    """Tiny bar-number glyph patch above left side of the staff; no OCR required.

    This is used for *identity matching*, not as a fabricated numeric label.
    Some styles/positions produce blank patches, hence the fallback to notation.
    """
    cy=round(ob.y*frame.shape[1]/min(frame.shape[1],960))
    scale=frame.shape[1]/min(frame.shape[1],960)
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    y1=max(0,round(cy-42*scale));y2=min(gray.shape[0],round(cy-11*scale))
    x1=round(17*scale);x2=round(38*scale)
    if y2<=y1 or x2>gray.shape[1]:return None
    v=cv2.resize(gray[y1:y2,x1:x2],(21,31),interpolation=cv2.INTER_AREA)
    ink=(v<185).astype(np.uint8)
    n,lab,st,ctr=cv2.connectedComponentsWithStats(ink,connectivity=8)
    mask=np.zeros_like(ink)
    for k in range(1,n):
        x,y,w,h,a=st[k]
        if 2<=a<=60 and 3<=h<=16 and 1<=w<=9 and y<25:mask[lab==k]=1
    yy,xx=np.where(mask)
    if not len(xx):return None
    patch=mask[yy.min():yy.max()+1,xx.min():xx.max()+1]
    out=np.zeros((25,28),np.uint8)
    out[2:2+min(23,patch.shape[0]),2:2+min(26,patch.shape[1])]=patch[:23,:26]
    return out

def label_sim(a,b):
    a=getattr(a,'number_signature',None);b=getattr(b,'number_signature',None)
    if a is None or b is None:return None
    best=0.
    for dx in range(-2,3):
        for dy in range(-2,3):
            rolled=np.roll(a,(dy,dx),(0,1))
            best=max(best,float(np.count_nonzero(rolled & b)/max(1,np.count_nonzero(rolled|b))))
    return best

def find_overlap(previous:list[System],current:list[System]):
    """Conservative ordered suffix/prefix matching (image + bar glyph evidence)."""
    n=min(len(previous),len(current));results=[]
    for overlap in range(1,n+1):
        ss=[row_sim(previous[-overlap+i],current[i]) for i in range(overlap)]
        lbs=[label_sim(previous[-overlap+i],current[i]) for i in range(overlap)]
        good_label=lambda i:lbs[i] is not None and lbs[i]>=.67
        if overlap==1:
            # Bar numbers rescue very different rendering; conversely weak image
            # alone is insufficient evidence when note rhythms are repetitive.
            valid=(ss[0]>=.68) or (ss[0]>=.44 and lbs[0] is not None and lbs[0]>=.46) or good_label(0)
        else:
            # Require every link to have *some* support: disallow the old bug
            # where two strong grooves deleted a third, genuinely new staff.
            supported=[(s>=.37 or (lb is not None and lb>=.64)) for s,lb in zip(ss,lbs)]
            valid=(all(supported) and (ss[0]>=.52 or good_label(0))
                   and (sum(s>=.59 for s in ss)+sum(good_label(i) for i in range(overlap))>=1))
            # At a page cut the first repeated staff may be pixel-identical,
            # while a second repeated staff has altered beams/highlights.
            if overlap==2 and ss[0]>=.84 and ss[1]>=.27:valid=True
        if not valid:continue
        score=sum((s-.31) for s in ss)+.11*sum((lb-.31) for lb in lbs if lb is not None)
        score+=.06*(overlap-1)
        if overlap==1 and good_label(0) and ss[0]<.44:
            score+=.34  # A clearly identical measure number rescues altered grooves
        results.append((score,overlap,float(np.mean(ss)),ss,lbs))
    if not results:return 0,0.,[],[]
    score,overlap,q,ss,lbs=max(results,key=lambda x:x[0])
    if score<.13:return 0,q,ss,lbs
    return overlap,q,ss,lbs

def page_extract(video,scan_step=2.,sample_step=3.5,verbose=True):
    pages,stat=detect_pages(video,step=scan_step)
    cap=cv2.VideoCapture(str(video))
    scenes=[]
    spacing_hint=None
    for p in pages:
        ok=build_page(video,cap,p,spacing_hint,is_first=len(scenes)==0)
        if not ok:continue
        if len(p.rows)<2:continue
        ys=[r.best().y for r in p.rows]
        gaps=[b-a for a,b in zip(ys,ys[1:]) if 75<b-a<180]
        if gaps:spacing_hint=float(np.median(gaps))
        scenes.append(p)
        if verbose:print(f'page {len(scenes):2d}  {p.start:5.1f}..{p.end:5.1f}s  key={p.key_time:6.1f}s  rows={len(p.rows)}',flush=True)
    cap.release()
    if not scenes:return [],{'mode':'page','detector':stat,'pages':[]}
    # Initial scene with oversized legend map must not enter musical score.
    # For those, later page transitions and score structure do the right thing.
    output=[];last=None;links=[];uncertain=[]
    for ii,page in enumerate(scenes):
        detected=page.rows
        if last is None:
            output.extend(detected);last=detected;links.append({'page':ii+1,'new_rows':len(detected),'overlap':0,'similarities':[]})
            continue
        overlapping,q,sims,labels=find_overlap(last,detected)
        # A score can move up by exactly one row-height while exposing the
        # next line(s), rather than replacing the entire screen. In that case
        # the *prefix* of the next view is the same as the previous full view.
        # Require coherent geometric displacement AND two good ink matches;
        # ordinary repeated drum grooves alone are insufficient evidence.
        if len(detected)>len(last)>=2:
            shifts=[detected[j].best().y-last[j].best().y for j in range(len(last))]
            scores=[row_sim(last[j],detected[j]) for j in range(len(last))]
            if (max(shifts)-min(shifts)<11 and -170<np.median(shifts)<-24
                and scores[0]>.49 and scores[1]>.49
                and min(scores[2:],default=1.)>.18):
                overlapping=len(last)
                q=float(np.mean(scores));sims=scores
                labels=[label_sim(last[j],detected[j]) for j in range(len(last))]
        fresh=detected[overlapping:]
        # Improvements from later observation: prefer clean, uncut notation.
        for i in range(overlapping):
            ri=len(output)-len(last)+len(last)-overlapping+i
            if 0<=ri<len(output):
                old=output[ri];new=detected[i]
                for ob in new.observations:
                    if row_sim(old,new)>.38:old.add(ob)
        if overlapping==0 and len(last)>=3 and len(detected)>=3:
            uncertain.append(ii+1)
            # no evidence => KEEP notation; don't silently discard by resemblance
            detected[0].flags.append('新一屏与前一屏没有可信的重叠证据；可能存在重复谱行，需检查')
        output.extend(fresh)
        links.append({'page':ii+1,'new_rows':len(fresh),'overlap':overlapping,'mean_similarity':round(q,3),'similarities':[round(s,3) for s in sims],'measure_glyph_scores':[round(v,3) if v is not None else None for v in labels]})
        last=detected
    stats={'mode':'page','detector':stat,'pages':[p.as_json() for p in scenes],'transitions':links,'uncertain_pages':uncertain,'repaired_rows':sum(any('补取' in v for v in r.flags) for r in output),'total_rows':len(output)}
    return output,stats

def convert_legacy_rows(oldrows):
    """Adapt proven v1 staff observations to v3 PDF/review/metadata pipeline."""
    result=[]
    for old in oldrows:
        q,c=score_image(old.image)
        first=Observation(old.image,old.feature,0.,old.pitch,old.first_seen,q,c)
        sysrow=System();sysrow.add(first)
        if not old.is_title:
            for candidate_score,photo in old.candidates:
                if len(sysrow.observations)>=11:break
                if photo.shape!=old.image.shape:continue
                s,color=score_image(photo)
                sysrow.add(Observation(photo,old.feature,0.,old.pitch,old.first_seen,s,color))
        result.append(sysrow)
    return result

def run_ensemble(video,mode,rows,stats,quality_interval=1.):
    """Independent second extractor safeguards existing successful input types.

    This decision uses ONLY observed quality/continuity; no filenames,
    artist names, or video-specific time lists. Human anchors are never used.
    """
    if mode=='scroll':
        sub=stats.get('tracking',{})
        # Zero-conflict scrolling (e.g. HD NIGHT DANCER) needs no slower backup.
        if sub.get('unverified_transitions',0)<=2 and sub.get('conflicting_links',0)<=3:
            stats['ensemble']={'checked':False,'chosen':'chronological-scroll','reason':'low transition conflicts'}
            return rows,stats
    old,ls=legacy_extract(video,interval=quality_interval,verbose=False)
    legacy_confident=(ls.get('ambiguous',999)<=2 and ls.get('no_overlap',999)<=2
                      and ls.get('occluded_frames',999)<=max(5,ls.get('seen',0)*.018))
    delta=abs(len(old)-len(rows))/max(1,len(rows))
    choose=False
    if old and legacy_confident:
        if mode=='scroll':
            sub=stats.get('tracking',{})
            choose=(len(old)<len(rows)*.90 and
                    (sub.get('conflicting_links',0)>=4 or sub.get('unverified_transitions',0)>=3))
        else:
            # In repeated grooves a false overlap can delete many real bars.
            # Favor the older high-confidence chronology if it retains >9% more.
            choose=len(old)>len(rows)*1.09
    stats['ensemble']={'checked':True,'legacy_rows':len(old), 'initial_rows':len(rows),
                       'legacy_metrics':ls, 'legacy_credible':legacy_confident,
                       'disagreement_fraction':round(delta,3),
                       'chosen':'legacy-staff-matcher' if choose else mode,
                       'reason':('legacy corroborated additional score rows' if choose
                                 else 'page/scroll result retained; independent baseline insufficiently confident or not richer')}
    if delta>.14:
        stats['ensemble']['warning']='Two automatic methods disagree materially; inspect the review image for omissions/repeats.'
    return (convert_legacy_rows(old) if choose else rows),stats

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path,help='Any vertical-scroll / upward page-cut score MP4')
    p.add_argument('-o','--output',type=Path,default=None)
    p.add_argument('--mode',choices=['auto','page','scroll'],default='auto')
    p.add_argument('--interval',type=float,default=1.,help='Scroll-track sampling interval in seconds')
    p.add_argument('--rows-per-page',type=int,default=8)
    p.add_argument('--scan-step',type=float,default=2.)
    p.add_argument('--apply',type=Path,help='Review JSON from offline HTML')
    p.add_argument('--no-ensemble',action='store_true',help='Speed-up: disable independent fallback cross-check')
    args=p.parse_args()
    if args.interval<=0 or args.scan_step<=0 or args.rows_per_page<1:p.error('interval and scan-step must be >0, rows-per-page >=1')
    if not args.video.exists():p.error('MP4 does not exist')
    target=args.output or args.video.with_suffix('.pdf')
    target.parent.mkdir(parents=True,exist_ok=True)
    pages,info=detect_pages(args.video,args.scan_step)
    mode=args.mode
    if mode=='auto':mode='page' if info['jump_rate']<.165 and len(pages)>=2 else 'scroll'
    print(f'Auto-selected: {mode}; scene-switch rate={info["jump_rate"]}, scenes={len(pages)}',flush=True)
    if mode=='page':rows,stats=page_extract(args.video,args.scan_step)
    else:
        rows,st=scrolling_extract(args.video,interval=args.interval)
        stats={'mode':'scroll','detector':info,'tracking':st,'total_rows':len(rows)}
    if not rows:raise SystemExit('No score rows found: please inspect the source video')
    if not args.no_ensemble:
        cap=cv2.VideoCapture(str(args.video));native_width=cap.get(cv2.CAP_PROP_FRAME_WIDTH);cap.release()
        if native_width<1200:
            rows,stats=run_ensemble(args.video,mode,rows,stats,quality_interval=1.)
        else:
            stats['ensemble']={'checked':False,'chosen':mode,'reason':'High-resolution baseline skipped for performance'}
    if args.apply:rows=applied_rows(rows,args.apply)
    base=target.with_suffix('')
    report=Path(str(base)+'_report.json')
    overview=Path(str(base)+'_overview.png')
    review=Path(str(base)+'_review.html')
    pages_count=emit_pdf(rows,target,rows_per_page=args.rows_per_page,numbered_png=overview)
    data=write_metadata(rows,stats,report)
    data['version']='3.0.0'
    data['method']='automatic dual-mode + independent legacy fallback + review flags'
    data['statistics']['total_rows']=len(rows)
    report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    create_review_html(rows,review)
    print(json.dumps({'input':str(args.video),'pdf':str(target),'mode':mode,'algorithm':stats.get('ensemble',{}).get('chosen',mode),'rows':len(rows),'pdf_pages':pages_count,'review':str(review),'report':str(report)},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
