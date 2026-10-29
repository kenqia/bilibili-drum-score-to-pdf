# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
#!/usr/bin/env python3
"""Source-frame-aware staff boundary reconstruction for DrumScore v6.

Never synthesizes musical symbols. Each extracted row is cropped anew from
actual MP4 frames. Staff centers define a regular lattice (including plausible
missed staves), and content valleys decide the boundaries between rows.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, math, statistics, collections, html
import numpy as np
import cv2
from .legacy_extractor import find_staves, compare
from .drumscore_v2 import System, Observation, capture_obs, score_image, crop_uncolored_fusion


@dataclass
class CropResult:
    image: np.ndarray
    time: float
    source_y: float
    top: int
    bottom: int
    spacing: float
    edge_risk: float
    quality: float
    note: str
    old_height: int
    used_ghost_staves: bool
    source_height: int


def median_staff_spacing(staves, fallback=95.):
    """Fundamental of row lattice, not naive median of observed gaps (2x if missed)."""
    if not staves:return fallback
    pitch = float(np.median([s[1] for s in staves]))
    expected = max(38., 12.85*pitch)
    ys = sorted(float(s[0]) for s in staves)
    gaps = np.diff(ys)
    candidates=[]
    for d in gaps:
        if d<expected*.6: continue
        k = int(np.clip(round(d/expected),1,4))
        step = float(d/k)
        if expected*.74 <= step <= expected*1.32:
            candidates.append(step)
    if len(candidates)>=2:return float(np.median(candidates))
    if candidates:return float(.65*candidates[0]+.35*expected)
    return float(expected if pitch>0 else fallback)


def lattice_centers(staves, row_y, spacing):
    """Fill a missed staff in any regular >1.5x gap, including HURT's 2x gap."""
    raw=sorted([float(s[0]) for s in staves]+[float(row_y)])
    uniq=[]
    for y in raw:
        if not uniq or y-uniq[-1]>spacing*.18:uniq.append(y)
    centers=[uniq[0]];ghost=False
    for y in uniq[1:]:
        delta=y-centers[-1]
        n=int(np.clip(round(delta/spacing),1,5))
        if n>=2 and abs(delta/n-spacing) <= spacing*.19:
            base=centers[-1]
            for k in range(1,n):centers.append(base+delta*k/n);ghost=True
        centers.append(y)
    return centers,ghost


def paper_ink_profile(frame):
    """Inexpensive rowwise ink density excluding color cursors and side banners."""
    h,w=frame.shape[:2];x1=int(w*.07);x2=max(x1+1,int(w*.94))
    part=frame[:,x1:x2]
    gray=cv2.cvtColor(part,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(part,cv2.COLOR_BGR2HSV)
    black=(gray<164)&((hsv[:,:,1]<115)|(gray<80))
    profile=np.mean(black,axis=1).astype(np.float32)
    return cv2.GaussianBlur(profile[:,None],(1,0),2.2).ravel()


def valley(profile,center,spacing,core,low,high):
    """Prefer the whitespace valley, but do not wander into the staff core."""
    lower=int(max(low,center-spacing*.18))
    upper=int(min(high,center+spacing*.18))
    lower=max(0,lower);upper=min(len(profile)-1,upper)
    if upper<=lower:return int(np.clip(round(center),0,len(profile)-1))
    choices=np.arange(lower,upper+1)
    # Excessively large displacement may cut unrelated staff marks; prefer midpoint.
    val=profile[choices] + .018*((choices-center)/max(spacing,1))**2
    return int(choices[int(np.argmin(val))])


def candidate_bounds(frame,row_y,staves,spacing,keep_title=False):
    h=frame.shape[0]
    ys,has_ghost=lattice_centers(staves,row_y,spacing)
    idx=int(np.argmin(np.abs(np.asarray(ys)-row_y)))
    center=ys[idx]
    before=ys[idx-1] if idx else center-spacing
    after=ys[idx+1] if idx+1<len(ys) else center+spacing
    # Prevent a detected 'neighbor' on a divergent lattice from causing broad crops.
    if center-before>spacing*1.5:before=center-spacing
    if after-center>spacing*1.5:after=center+spacing
    mid_top=.5*(before+center);mid_bot=.5*(after+center)
    profile=paper_ink_profile(frame)
    top=valley(profile,mid_top,spacing,center,center-spacing*.73,center-spacing*.24)
    bottom=valley(profile,mid_bot,spacing,center,center+spacing*.24,center+spacing*.73)
    if keep_title:top=0
    top=max(0,int(top));bottom=min(h,int(bottom))
    # An edge at which ink continues is suspicious. Higher => likely cut/collision.
    band=4
    dtop=float(profile[min(h-1,top)])
    dbot=float(profile[min(h-1,bottom)])
    edge_risk=max(dtop,dbot)
    return top,bottom,edge_risk,has_ghost


def center_for_observation(frame,obs):
    h,w=frame.shape[:2];scale=min(1.,960./w)
    if obs.y>0:return float(obs.y/scale), 'stored_staff_location'
    # Independent legacy matching stores y=0. Recover its actual location.
    found=capture_obs(frame,obs.t,None)
    if obs.feature is None or not np.any(obs.feature):return None,'no_staff_feature'
    options=[(compare(obs.feature,c.feature),c.y/scale) for c in found]
    if not options:return None,'staff_match_absent'
    v,y=max(options)
    return (float(y),'legacy_feature_match') if v>=.52 else (None,'legacy_match_weak')


def equalize_paper(img):
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg=cv2.GaussianBlur(gray,(0,0),sigmaX=24,sigmaY=17)
    return np.uint8(np.clip(gray+.84*(250-bg)+5,0,255))


def proposed_crop(frame,obs,source_y,keep_title,original_height):
    h,w=frame.shape[:2];scale=min(1.,960./w)
    small=cv2.resize(frame,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA) if scale<1 else frame
    staves_small=find_staves(small)
    staves=[(q[0]/scale,q[1]/scale,q[2],q[3]) for q in staves_small]
    fallback=(obs.pitch/scale)*12.85 if obs.pitch>2 else h/5
    spacing=median_staff_spacing(staves,fallback=fallback)
    top,bottom,edge_risk,ghost=candidate_bounds(frame,source_y,staves,spacing,keep_title)
    if bottom-top<max(22,spacing*.52):return None
    img=frame[top:bottom].copy()
    quality,color=score_image(img)
    # Penalize ink density at crop edges, incomplete view and excessive height.
    border=min(source_y-top,bottom-source_y)
    if border<spacing*.31:quality+=2.0
    if top==0 and not keep_title:quality+=.4
    if bottom>=h-1:quality+=.4
    quality+=12.*max(0,edge_risk-.015)+.075*abs((bottom-top)-spacing)/max(1,spacing)
    return CropResult(img,float(obs.t),float(source_y),top,bottom,round(spacing,2),
                      round(edge_risk,4),round(quality,4),'real_video_frame',
                      int(original_height),bool(ghost),h)


def choose_source_views(video,rows,max_views=4,rescan=True,overrides=None):
    """Build enhanced crops without changing row order/IDs or OCR evidence.

    returns images, row reports. A failed expansion falls back to the v5 crop.
    """
    overrides=overrides or {}; cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():raise RuntimeError('Video cannot be opened: '+str(video))
    total=float(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=cap.get(cv2.CAP_PROP_FPS) or 25
    duration=total/fps
    cache=collections.OrderedDict()
    def frame_at(t):
        key=round(float(t),3)
        if key in cache:
            cache.move_to_end(key);return cache[key]
        cap.set(cv2.CAP_PROP_POS_MSEC,1000*key);ok,frame=cap.read()
        if not ok:return None
        cache[key]=frame
        if len(cache)>9:cache.popitem(last=False)
        return frame
    results=[];reports=[]
    for idx,row in enumerate(rows):
        choices=sorted(row.observations,key=lambda o:o.score)
        initial=choices[:max_views]
        unique={round(o.t,2):o for o in initial}
        requested=overrides.get(str(idx+1),{})
        # A user-specified time is allowed only if the row matches a genuine video staff.
        if 'time_s' in requested:
            from copy import copy
            sub=copy(row.best());sub.t=float(requested['time_s']);unique[round(sub.t,2)]=sub
        # Extra scans for edge-clipped rows and missing-staff recovered rows.
        if rescan and (len(unique)<=1 or row.flags):
            from copy import copy
            t=row.best().t
            for shift in (-1.5,-.5,.5,1.5):
                nt=t+shift
                if 0<nt<duration and len(unique)<max_views+3:
                    sub=copy(row.best());sub.t=nt;unique[round(nt,2)]=sub
        candidates=[];fail=[]
        for obs in unique.values():
            fr=frame_at(obs.t)
            if fr is None:continue
            y,method=center_for_observation(fr,obs)
            if y is None:
                fail.append(method);continue
            # For a novel time: verify the same staff is still at this location.
            # For stable page shots use global binary similarity, not its timestamps.
            if abs(obs.t-row.best().t)>.1:
                anchor=frame_at(row.best().t)
                if anchor is not None:
                    a=cv2.resize(cv2.cvtColor(anchor,cv2.COLOR_BGR2GRAY),(128,72))<138
                    b=cv2.resize(cv2.cvtColor(fr,cv2.COLOR_BGR2GRAY),(128,72))<138
                    overlap=np.count_nonzero(a&b)/max(1,np.count_nonzero(a|b))
                    if overlap<.58:continue
            title=(idx==0 and (getattr(row,'is_title',False) or
                   row.best().image.shape[0]>1.55*max(1,obs.pitch/min(1,960/fr.shape[1])*12.85)))
            result=proposed_crop(fr,obs,y,title,row.best().image.shape[0])
            if result is not None:
                if requested.get('top_delta_px') is not None or requested.get('bottom_delta_px') is not None:
                    a=max(0,int(result.top+int(requested.get('top_delta_px',0))))
                    b=min(fr.shape[0],int(result.bottom+int(requested.get('bottom_delta_px',0))))
                    if b-a>=30:
                        result.top=a;result.bottom=b;result.image=fr[a:b].copy()
                        result.note='user_adjusted_video_crop'
                candidates.append(result)
        if candidates:
            chosen=min(candidates,key=lambda x:x.quality)
            img=equalize_paper(chosen.image)
            # Conservative comparison: a longer crop is not necessarily more correct;
            # highlight risk if height diverges wildly from expected lattice.
            risk=[]
            if chosen.edge_risk>.055:risk.append('possible_symbol_crosses_crop_boundary')
            if chosen.top==0 and idx>0:risk.append('touches_top_of_video')
            if chosen.bottom>=chosen.source_height-1:risk.append('touches_bottom_of_video')
            if abs((chosen.bottom-chosen.top)-chosen.spacing)>chosen.spacing*.23 and idx>0:risk.append('unusual_crop_height')
            if row.flags:risk.append('preexisting_row_uncertainty')
            improvements=[]
            if chosen.old_height>chosen.spacing*1.30 and idx>0:improvements.append('v5_oversized_row_corrected')
            if chosen.used_ghost_staves:risk.append('reconstructed_missing_staff_lattice')
            report={'row':idx+1,'bar':row.start_bar,'source_time_s':round(chosen.time,2),
                    'source_y':round(chosen.source_y,1),'top_px':chosen.top,'bottom_px':chosen.bottom,
                    'old_crop_px':chosen.old_height,'new_crop_px':chosen.bottom-chosen.top,
                    'spacing_px':chosen.spacing,'edge_ink':chosen.edge_risk,
                    'alternates_evaluated':len(candidates),'issues':risk,'quality_score':chosen.quality,
                    'original_flags':row.flags,'improvements':improvements,'note':chosen.note}
        else:
            img=crop_uncolored_fusion(row)
            report={'row':idx+1,'bar':row.start_bar,'source_time_s':round(row.best().t,2),
                    'old_crop_px':img.shape[0],'new_crop_px':img.shape[0],
                    'alternates_evaluated':0,'issues':['no_safe_source_crop','manual_review_needed'],
                    'reason':fail,'original_flags':row.flags,'note':'v5_fallback'}
        results.append(img);reports.append(report)
    cap.release()
    return results,reports


def emit_images_pdf(images,output,rows_per_page=8,margin_mm=10,overview=None,info=None):
    """A4, use real heights and never squeeze two staves over one another."""
    from . import pdf_backend as fitz
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    w,h=fitz.paper_size('a4');m=margin_mm*72/25.4;cw=w-2*m
    pdf=fitz.open();page=None; y=m;count=0;prev_width=None
    for i,img in enumerate(images):
        ih,iw=img.shape[:2]
        scale=cw/iw;actual_h=ih*scale
        gap=8.0
        if actual_h>h-2*m:
            scale=(h-2*m)/ih;actual_h=ih*scale
        if page is None or count>=rows_per_page or (count>0 and y+actual_h>h-m):
            page=pdf.new_page(width=w,height=h);y=m;count=0
        ww=iw*scale;xx=(w-ww)/2
        ok,buff=cv2.imencode('.png',img)
        if ok:page.insert_image(fitz.Rect(xx,y,xx+ww,y+actual_h),stream=buff.tobytes())
        y+=actual_h+gap;count+=1
    if overview:
        thumbs=[]
        for i,img in enumerate(images):
            ww=960;hh=max(32,round(img.shape[0]*ww/img.shape[1]))
            scaled=cv2.resize(img,(ww,hh),interpolation=cv2.INTER_AREA)
            header=np.full((23,ww),248,np.uint8)
            record=info[i] if info is not None else {}
            flag='CHECK' if record.get('issues') else 'OK'
            cv2.putText(header,f'{i+1:02d}  t={record.get("source_time_s",0):.1f}s  {flag}  old/new={record.get("old_crop_px",0)}/{record.get("new_crop_px",0)}',(6,16),cv2.FONT_HERSHEY_SIMPLEX,.40,60,1,cv2.LINE_AA)
            thumbs += [header,scaled,np.full((3,ww),205,np.uint8)]
        if thumbs:cv2.imwrite(str(overview),np.vstack(thumbs))
    pdf.save(str(output),garbage=4,deflate=True);pages=len(pdf);pdf.close()
    return pages


def make_crop_audit(path,images,info):
    import base64
    entries=[]
    for img,d in zip(images,info):
        reduced=cv2.resize(img,(min(900,img.shape[1]),max(24,round(img.shape[0]*min(900,img.shape[1])/img.shape[1]))))
        ok,buff=cv2.imencode('.jpg',reduced,[cv2.IMWRITE_JPEG_QUALITY,80]);src='data:image/jpeg;base64,'+base64.b64encode(buff).decode('ascii') if ok else ''
        entries.append('<section><header><b>谱行 '+str(d['row'])+'</b>　源视频 '+str(d['source_time_s'])+'s　裁剪 '+str(d['old_crop_px'])+' → '+str(d['new_crop_px'])+' px　<span>'+html.escape(', '.join(d['issues']) or '无自动发现的裁剪疑点')+'</span></header><img src="'+src+'"></section>')
    doc='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>DrumScore v6 边界审计</title><style>body{font:14px/1.5 system-ui,sans-serif;max-width:1100px;margin:30px auto;color:#1e293b}section{padding:14px;border:1px solid #ddd;margin:12px 0;border-radius:9px}header{margin-bottom:7px}span{color:#a16207}img{width:100%;height:auto}small{color:#64748b}</style><h1>DrumScore v6 · 谱行裁剪完整性检查</h1><p>来源于视频实际帧，自动裁剪不保证所有符号均完整；标记为 CHECK 的行值得人工复核。</p>'''+''.join(entries)+'</html>'
    Path(path).write_text(doc,encoding='utf8')
