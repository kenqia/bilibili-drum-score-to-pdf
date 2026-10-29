# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
#!/usr/bin/env python3
"""Extract printable drum-score rows from videos with vertical scrolling/page changes.

Uses computer vision rather than musical OCR: detects five-line staves,
tracks their chronological order, collects clean views, and builds A4 PDFs.
No machine-learning models or Internet required.

Install: pip install opencv-python numpy pillow pymupdf
Usage: python drumscore_extractor.py input.mp4 -o output.pdf --interval 1
       python drumscore_extractor.py input.mp4 -o output.pdf --debug output_rows.jpg

Caveats: assumes full-width horizontal five-line drum staves, stable X scale,
and monotonically advancing score (vertical scroll / page changes).
"""
import argparse, os, sys, math, statistics, hashlib
from dataclasses import dataclass, field
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps
from . import pdf_backend as fitz
@dataclass
class Row:
    image: np.ndarray
    feature: np.ndarray
    pitch: float
    visits: int = 1
    best_score: float = 999.0
    candidates: list = field(default_factory=list)
    first_seen: float = 0.0
    is_title: bool = False


def get_samples(path, interval, start=0., finish=None):
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f'cannot open video: {path}')
    fps=cap.get(cv2.CAP_PROP_FPS) or 25
    total=cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration=total/fps
    last=duration-0.15 if finish is None else min(duration-0.15,finish)
    for sec in np.arange(start, max(start,last)+.00001, interval):
        cap.set(cv2.CAP_PROP_POS_MSEC, 1000*float(sec))
        ok,bgr=cap.read()
        if ok: yield float(sec), bgr
    cap.release()


def find_staves(frame):
    """Detect 5-line drum staves via horizontal line detector, tolerant of gray lines."""
    h,w=frame.shape[:2]
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    local_bg=cv2.GaussianBlur(gray,(1,19),0)
    dark=cv2.subtract(local_bg,gray)
    binary=(dark>8).astype(np.uint8)*255
    binary=cv2.morphologyEx(binary,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(7,1)))
    horizontal=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(25,w//13),1)))
    hist=np.sum(horizontal[:,int(.03*w):int(.97*w)]>0,axis=1)
    line_ys=np.flatnonzero(hist>w*.115)
    # An actual staff line can occupy two adjacent rows due to antialiasing.
    groups=[]
    for y in line_ys:
        if not groups or y>groups[-1][-1]+1: groups.append([int(y)])
        else: groups[-1].append(int(y))
    lines=[float(np.mean(group)) for group in groups]
    staves=[]
    for y in lines:
        if not staves or y-staves[-1][-1]>14: staves.append([y])
        else: staves[-1].append(y)
    out=[]
    for group in staves:
        if not (4<=len(group)<=7):continue
        diffs=np.diff(group)
        pitch=float(np.median(diffs))
        if not (3.5<=pitch<=11.5):continue
        if max(diffs)>pitch*1.65:continue
        cy=float(np.mean(group))
        y0=max(0,int(cy-2.1*pitch));y1=min(h,int(cy+2.1*pitch)+1)
        xhist=(horizontal[y0:y1,:]>0).sum(axis=0)
        xs=np.flatnonzero(xhist>=min(3,len(group)))
        if len(xs)>w*.10:
            left,right=int(xs.min()),int(xs.max())
        else:
            left,right=int(w*.03),int(w*.97)
        out.append((cy,pitch,left,right))
    return out


def row_feature(bgr,cy,pitch,left=None,right=None):
    """Black notation features, stripped of colored highlight and bright watermarks."""
    h,w=bgr.shape[:2]
    extent=int(round(pitch*5.2))
    cy=int(round(cy))
    a=max(0,cy-extent);b=min(h,cy+extent)
    left=max(0,(left if left is not None else 0)-7)
    right=min(w,(right if right is not None else w)+8)
    ink=bgr[a:b,left:right]
    gray=cv2.cvtColor(ink,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(ink,cv2.COLOR_BGR2HSV)
    mask=((gray<168)&(hsv[:,:,1]<110)).astype(np.uint8)*255
    # Remove long horizontal staff lines: they are common to every row.
    lines=cv2.morphologyEx(mask,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(28,w//12),1)))
    mask=cv2.subtract(mask,lines)
    # Keep the whole X span for bar numbers, not just the repeating drum notes.
    mask=cv2.resize(mask,(426,70),interpolation=cv2.INTER_AREA)
    return mask>55


def row_score(bgr):
    """Smaller is better. Prefer no ad/highlight and enough black score pixels."""
    hsv=cv2.cvtColor(bgr,cv2.COLOR_BGR2HSV)
    gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
    hh,ww=bgr.shape[:2]
    colored=((hsv[:,:,1]>36)&(hsv[:,:,2]>68)).sum()
    # Blue cursors/yellow highlighters and saturated banners are penalized.
    return colored/(hh*ww) * 30 + max(0,(0.019-(gray<135).mean())) * 20


def normalized_image(frame, cy, height, first_header=False):
    h,w=frame.shape[:2]
    top=max(0,int(round(cy-height*.52)))
    bot=min(h,int(round(cy+height*.48)))
    if first_header and cy>height*.78:
        top=0
    # Do not add foreign marks from the video frame border.
    return frame[top:bot].copy()


def compare(f1,f2):
    # Black-ink F1 similarity; robust to 1 px staff detection jitter and moving cursor.
    # Some patterns are repetitive, hence confidence must come from sequence context.
    union=np.count_nonzero(f1|f2)
    if union<80:return 0.
    return np.count_nonzero(f1&f2)/union


def align_rows(rows, features):
    n=len(rows);m=len(features)
    if n==0: return 0,0.,0
    start=max(0,n-m-7)
    # Align last visible systems to the tail of the known complete score.
    # One or two systems of overlap is enough for jump-scrolling videos.
    best=None
    for k in range(start,n+1):
        pairs=[(i,k+i) for i in range(m) if 0<=k+i<n]
        if not pairs:continue
        sims=[compare(features[i],rows[j].feature) for i,j in pairs]
        good=[s for s in sims if s>=.46]
        if not good:continue
        # Penalize ungrounded overlaps; favor consecutive actual matches.
        strength=sum((s-.36) for s in good)-.25*(len(sims)-len(good))
        if len(good)==1 and good[0]<.70:strength-=.2
        strength+=.009*k  # prefer forward chronological consistency
        if best is None or strength>best[0]:best=(strength,k,max(good),len(good))
    if best is None:return n,0.,0
    strength,k,quality,count=best
    if strength<.17:return n,0.,0
    # No retroactive jumps to old repeats (a repeated groove isn't a repeated staff).
    return k,quality,count


def clean_row(row):
    """Choose least-obscured color view. Replace bright-colored overlay with clean pixels
    from alternate exposures *only* if sources align perfectly.
    """
    # Store best single view; preserve pixels under any persistent watermark.
    if row.is_title:
        # Preserve earliest full title even after candidate pool replacement.
        best=(row.best_score,row.image)
    else:
        best=min(row.candidates,key=lambda q:q[0]) if row.candidates else (row.best_score,row.image)
    source=best[1]
    # Convert to grayscale for printing. Desaturate yellow highlights by
    # substituting grayscale intensity from clean portions when possible.
    gray=cv2.cvtColor(source,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(source,cv2.COLOR_BGR2HSV)
    bright_colored=(hsv[:,:,1]>45)&(hsv[:,:,2]>150)
    if bright_colored.any():
        # white highlight background, but don't remove ink in nearly-black pixels.
        gray[bright_colored & (gray>185)]=255
    # Many videos have slightly gray backgrounds; increase paper white gently.
    # Crucially do not binarize because that would drop gray staff lines.
    gray=cv2.convertScaleAbs(gray,alpha=1.10,beta=-8)
    return gray


def pack_pdf(rows,outpath,per_page=9,margin_mm=10,debug=None,keep_blank=False):
    page_w,page_h=fitz.paper_size('a4')
    m=margin_mm*72/25.4
    content_w=page_w-2*m
    pdf=fitz.open()
    img_list=[]
    for r in rows:
        im=clean_row(r)
        # Trim excessive blank area on left/right? Default preserves bar numbers.
        img_list.append(im)
    if debug:
        thumbs=[]
        for i,im in enumerate(img_list):
            sm=cv2.resize(im,(600,max(24,int(im.shape[0]*600/im.shape[1]))))
            cv2.putText(sm,str(i+1),(4,14),cv2.FONT_HERSHEY_SIMPLEX,.4,(110,),1)
            thumbs.append(sm)
        if thumbs:
            sep=np.ones((6,600),np.uint8)*190
            long=np.vstack([j for item in thumbs for j in (item,sep)])
            cv2.imwrite(str(debug),long)
    if not rows:return pdf
    # Standard A4 layout: preserve aspect ratio and avoid stretching staff glyphs.
    # Variable number of rows per page if very tall title header consumes space.
    i=0
    while i<len(img_list):
        sub=img_list[i:i+per_page]
        # Fit width, then scale down all rows together if the page is too tall.
        v_heights=[im.shape[0]*content_w/im.shape[1] for im in sub]
        spacing=8
        factor=min(1.,(page_h-2*m-spacing*(len(sub)-1))/sum(v_heights))
        page=pdf.new_page(width=page_w,height=page_h)
        top=m
        for im,base_h in zip(sub,v_heights):
            _,data=cv2.imencode('.png',im)
            ht=base_h*factor;wd=content_w*factor
            x=(page_w-wd)/2
            page.insert_image(fitz.Rect(x,top,x+wd,top+ht),stream=data.tobytes())
            top+=ht+spacing
        i+=len(sub)
    outpath.parent.mkdir(parents=True,exist_ok=True)
    pdf.save(str(outpath),garbage=4,deflate=True)
    pdf.close()


def has_large_occlusion(frame):
    h,w=frame.shape[:2]
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    if gray.mean()<145: return True
    blob=(gray<80).astype(np.uint8)*255
    # Raw components only: closing would incorrectly merge dense musical notes.
    n,lab,stats,ct=cv2.connectedComponentsWithStats(blob)
    for x,y,bw,bh,area in stats[1:]:
        if area>h*w*.032 and bw>w*.14 and bh>h*.19:
            return True
    return False


def extract(path,interval=1.0,debug=None,verbose=True,start=0.,end=None,skip_occlusion=True):
    rows=[]; stats={'seen':0,'staff_detected':0,'appended':0,'ambiguous':0,'no_overlap':0,'occluded_frames':0}
    height_hist=[]
    for sec,frame in get_samples(path,interval,start=start,finish=end):
        stats['seen']+=1
        if skip_occlusion and has_large_occlusion(frame):
            stats['occluded_frames']+=1
            continue
        h,w=frame.shape[:2]
        staff=find_staves(frame)
        if len(staff)<1:continue
        median_pitch=statistics.median(x[1] for x in staff)
        centers=[x[0] for x in staff]
        gaps=[b-a for a,b in zip(centers,centers[1:]) if b-a>=median_pitch*6]
        row_height=statistics.median(gaps) if gaps else median_pitch*12.3
        row_height=min(row_height,h*.33)
        height_hist.append(row_height)
        sample=[]
        for j,(cy,pitch,left,right) in enumerate(staff):
            border_margin=min(row_height*.44,pitch*5.7)
            if cy<border_margin or cy>h-border_margin:continue
            feat=row_feature(frame,cy,pitch,left,right)
            if feat.sum()<60:continue
            im=normalized_image(frame,cy,row_height,first_header=(not rows and j==0))
            quality=row_score(im)
            sample.append((im,feat,pitch,quality))
        if not sample: continue
        if skip_occlusion and any(q[3]>2.0 for q in sample):
            stats['occluded_frames']+=1
            continue # wait for an unobscured exposure; do not splice ad as musical staff
        stats['staff_detected']+=len(sample)
        features=[x[1] for x in sample]
        offset,match_quality,matching_count=align_rows(rows,features)
        if rows and matching_count==0:stats['no_overlap']+=1
        if rows and matching_count==1:stats['ambiguous']+=1
        for j,(im,feat,pitch,qual) in enumerate(sample):
            index=offset+j
            if index < len(rows):
                r=rows[index]
                sim=compare(feat,r.feature)
                if sim>.48:
                    r.visits+=1
                    if len(r.candidates)<10:
                        r.candidates.append((qual,im))
                    elif qual<max(r.candidates,key=lambda q:q[0])[0]:
                        worst=max(range(len(r.candidates)),key=lambda k:r.candidates[k][0])
                        r.candidates[worst]=(qual,im)
                    if qual<r.best_score and abs(im.shape[0]-r.image.shape[0])<6:
                        r.best_score=qual;r.image=im
                # otherwise overlap alignment unreliable, do not overwrite.
            elif index>=len(rows):
                r=Row(image=im,feature=feat,pitch=pitch,best_score=qual,first_seen=sec,candidates=[(qual,im)],is_title=(len(rows)==0 and j==0 and im.shape[0]>row_height*1.45))
                rows.append(r);stats['appended']+=1
        if verbose and int(sec)%30==0 and abs(sec-round(sec))<0.001:
            print(f'  {sec:5.0f}s: {len(rows)} systems, {len(sample)} visible, overlap={matching_count}',flush=True)
    if verbose:print('  Final:',len(rows),'staff rows; stats:',stats,flush=True)
    return rows,stats


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('video',type=Path,help='MP4 video with complete vertical/page-flowing five-line drum score')
    parser.add_argument('-o','--output',type=Path,default=None,help='output printable A4 PDF')
    parser.add_argument('--interval',type=float,default=1.0,help='seconds between inspected frames (default 1)')
    parser.add_argument('--rows-per-page',type=int,default=9,help='target systems per A4 page (default 9)')
    parser.add_argument('--start',type=float,default=0.,help='ignore opening seconds (e.g., to skip intro animations)')
    parser.add_argument('--end',type=float,default=None,help='stop before this video time in seconds')
    parser.add_argument('--keep-overlays',action='store_true',help='do not reject suspicious dark/advertisement frames')
    parser.add_argument('--debug',type=Path,help='also export a tall numbered overview JPEG/PNG')
    args=parser.parse_args()
    if args.interval<=0 or args.rows_per_page<1:parser.error('invalid interval or rows-per-page')
    out=args.output or args.video.with_suffix('.pdf')
    print('Processing:',args.video)
    rows,stats=extract(args.video,interval=args.interval,start=args.start,end=args.end,skip_occlusion=not args.keep_overlays)
    if not rows:sys.exit('ERROR: no five-line staves detected; video layout not supported')
    pack_pdf(rows,out,per_page=args.rows_per_page,debug=args.debug)
    print('Saved:',out,'--',len(rows),'detected rows')
    if stats['ambiguous']>=3 or stats['no_overlap']>=2 or stats['occluded_frames']>=8:
        print('Review advised: video contains jumps or repeated score rows that could confuse alignment.')

if __name__=='__main__':main()
