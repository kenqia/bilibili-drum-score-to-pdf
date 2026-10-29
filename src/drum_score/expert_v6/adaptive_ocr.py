# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
"""Video-local digit calibration. Weak-supervision, no score synthesis.

Training digits are obtained only from v4 OCR reads that passed multi-row
consistency checks; measured digits are extracted from *source video* patches.
A result is NEVER accepted from template likeness alone. Confidence requires
separate observations and contextual ordering, and outputs only metadata.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from itertools import combinations
import cv2
import numpy as np
from .bar_ocr import patches, batch_ocr


def _components(patch):
    # Original ROI coordinates are preserved by the v4 upscaled crop.
    gray=patch[:224,:256]
    fg=(gray<155).astype('uint8')
    count, labs, stat, cent=cv2.connectedComponentsWithStats(fg,8)
    parts=[]
    for j in range(1,count):
        x,y,w,h,area=map(int,stat[j])
        if (w<3 or w>89 or h<21 or h>131 or area<38 or
            x<4 or x+w>247 or y<7 or y+h>226):continue
        parts.append((x,y,w,h,area))
    return sorted(parts)


def groups(patch, count=None):
    """Find compact near-baseline aligned 1-3 glyph clusters (no OCR)."""
    parts=_components(patch)
    options=[]
    allowed=[count] if count else [2,3,1]
    for n in allowed:
        if n not in (1,2,3):continue
        for inds in combinations(range(len(parts)),n):
            ps=[parts[i] for i in inds]
            hs=[p[3] for p in ps]
            mid=[p[1]+p[3]*.5 for p in ps]
            # Reject unrelated notes / staff or differently positioned labels.
            if max(hs)/min(hs)>1.65 or max(mid)-min(mid)>max(11,.3*max(hs)):continue
            if n>1:
                gaps=[ps[j+1][0]-(ps[j][0]+ps[j][2]) for j in range(n-1)]
                if min(gaps)<-3 or max(gaps)>max(34,int(max(hs)*.7)):continue
            left=min(p[0] for p in ps);right=max(p[0]+p[2] for p in ps)
            if right-left>190:continue
            heights=float(np.mean(hs));area=sum(p[4] for p in ps)
            # Prefer compact, high-contrast, leftmost digits instead of adjacent music.
            geometry=heights/80-.006*max(0,left-100)-.003*(right-left)-.04*(max(mid)-min(mid))
            geometry+=min(.35,area/2000)
            options.append((round(geometry,3),ps))
    options.sort(key=lambda z:z[0],reverse=True)
    return options[:7]


def normalize_glyph(patch,part):
    x,y,w,h,_=part
    glyph=(patch[y:y+h,x:x+w]<155).astype('uint8')*255
    # Preserve aspect; compare typography after centering. No super-resolution claims.
    scale=min(26/max(w,1),40/max(h,1))
    neww=max(1,round(w*scale));newh=max(1,round(h*scale))
    glyph=cv2.resize(glyph,(neww,newh),interpolation=cv2.INTER_AREA)
    result=np.zeros((48,34),np.uint8)
    left=(34-neww)//2;top=(48-newh)//2
    result[top:top+newh,left:left+neww]=glyph
    return cv2.GaussianBlur(result,(3,3),.55).astype(np.float32)/255


def word_patch(image,ps):
    x=max(0,min(p[0] for p in ps)-6)
    y=max(0,min(p[1] for p in ps)-6)
    x2=min(image.shape[1],max(p[0]+p[2] for p in ps)+6)
    y2=min(image.shape[0],max(p[1]+p[3] for p in ps)+6)
    crop=image[y:y2,x:x2]
    h,w=crop.shape[:2]
    scale=min(2.6,160/max(h,1),220/max(w,1))
    resized=cv2.resize(crop,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_NEAREST)
    out=np.full((250,275),255,np.uint8)
    a=(250-resized.shape[0])//2;b=(275-resized.shape[1])//2
    out[a:a+resized.shape[0],b:b+resized.shape[1]]=resized
    return out


def local_ocr(snippets):
    """OCR isolated candidate number glyphs; distinct from v4 fixed-box OCR."""
    ims=[];links=[];details={}
    for row,frame,y in snippets:
        view_id=id(frame)
        for pidx,patch in enumerate(patches(frame,y)):
            gs=groups(patch,2)[:2]+groups(patch,3)[:1]
            # Only attempt groups that look like multi-character measure numbers.
            for ranking,ps in gs:
                if len(ps)<2:continue
                ims.append(word_patch(patch,ps));links.append((row,pidx,ranking,view_id))
    hits=batch_ocr(ims)
    cand=defaultdict(list)
    for idx,h in hits.items():
        row,pidx,geo,view_id=links[idx]
        for number,conf in h:
            cand[row].append({'value':number,'conf':round(conf,1),
                              'roi':pidx,'geometry':geo,'frame':view_id})
    for row,vals in cand.items():
        nums=Counter(q['value'] for q in vals)
        details[str(row)]={'votes':[{k:v for k,v in q.items() if k!='frame'} for q in vals[:28]], 'top':nums.most_common(3)}
    # This output is intentionally just hints; no unconfirmed OCR label is trusted.
    return dict(cand),details


def _trusted_template_samples(snippets,anchors):
    glyphs=defaultdict(list);used=[]
    for row,frame,cy in snippets:
        if row not in anchors:continue
        label=str(anchors[row]['value'])
        if len(label)>3:continue
        for patch in patches(frame,cy):
            candidates=groups(patch,len(label))
            if not candidates:continue
            score,ps=candidates[0]
            # Need a decent separation and baseline agreement.
            if score<-.35:continue
            for symbol,part in zip(label,ps):
                glyphs[symbol].append(normalize_glyph(patch,part))
            used.append({'row':row+1,'value':int(label),'glyphs':len(ps)})
    # Per-character support is counted by distinct anchored rows, not ROI snippets.
    independent=defaultdict(set)
    for q in used:
        for symbol in str(q['value']):independent[symbol].add(q['row'])
    # Prevent one incorrectly segmented row from being the sole evidence of a digit.
    trained={k:images[:35] for k,images in glyphs.items() if len(independent[k])>=2}
    return trained,used


def _similarity(a,b):
    return float(1-np.abs(a-b).mean())


def adaptive_hints(snippets,anchors,raw_hints):
    """Return conservative style-based candidate numbers and transparent evidence.

    The method never infers a glyph for a digit absent from trusted samples.
    Even high scores are advisory until sequence/independent view agreement.
    """
    trained,used=_trusted_template_samples(snippets,anchors)
    votes=defaultdict(list)
    for source_idx,(row,frame,cy) in enumerate(snippets):
        if row in anchors:continue
        for patch in patches(frame,cy)[:2]:
            for geo,ps in (groups(patch,2)[:2]+groups(patch,3)[:1]):
                if not 2<=len(ps)<=3:continue
                predictions=[];margins=[];similarities=[]
                for part in ps:
                    g=normalize_glyph(patch,part)
                    values=sorted(((max(_similarity(g,q) for q in exemplars),digit)
                                    for digit,exemplars in trained.items()),reverse=True)
                    if len(values)<2:break
                    top,runner=values[0],values[1]
                    if top[0]<.77 or top[0]-runner[0]<.035:break
                    predictions.append(top[1]);margins.append(top[0]-runner[0]);similarities.append(top[0])
                if len(predictions)==len(ps) and predictions[0]!='0':
                    val=int(''.join(predictions))
                    if 1<=val<=999:
                        votes[row].append({'value':val,'score':round(min(similarities),3),
                            'margin':round(min(margins),3),'source':source_idx})
    hints={};promoted={}
    for row,vals in sorted(votes.items()):
        counter=Counter(v['value'] for v in vals)
        top,numvotes=counter.most_common(1)[0]
        alternatives=counter.most_common(3)
        sources={v['source'] for v in vals if v['value']==top}
        minscore=max((v['score'] for v in vals if v['value']==top),default=0)
        hints[row]={'value':top,'votes':numvotes,'independent_views':len(sources),
                    'max_similarity':minscore,'alternatives':alternatives}
        # Adding confirmed anchors is forbidden without at least 3 preceding
        # trusted OCR anchors for style, independent observations and sequence.
        if len(anchors)<3 or len(sources)<2 or numvotes<3 or len(alternatives)>1 and alternatives[1][1]>=numvotes:continue
        before=[(i,v['value']) for i,v in anchors.items() if i<row]
        after=[(i,v['value']) for i,v in anchors.items() if i>row]
        if not before or not after:continue
        lb=max(before);rb=min(after)
        # All values are source pixel evidence; interpolation does not fabricate a label.
        if lb[1]<top<rb[1] and 1<=(top-lb[1])/(row-lb[0])<=16 and 1<=(rb[1]-top)/(rb[0]-row)<=16:
            promoted[row]={'value':top,'confidence':min(.8,.5+.045*numvotes),
                           'strength':'video_style_and_sequence','votes':numvotes}
    meta={'source':'in-video only','training_rows':len(set(q['row'] for q in used)),
          'digit_classes':sorted(trained),'sampled_digit_views':len(used),
          'style_candidates':{str(k):v for k,v in hints.items()},
          'promoted':{str(k):v for k,v in promoted.items()},
          'warning':'Self-trained number guesses are non-independent when from same frame; hints are not verified labels.'}
    return promoted,meta


def isolated_consensus(snippets,raw):
    """Supplement v4 word OCR with isolated-digit OCR while protecting against
    correlated crops, hallucinated extra digits, and temporal disagreement.
    Only a result seen in >=2 actual source frames can become a strong anchor,
    and it must not conflict with the baseline OCR candidate.
    """
    cand,details=local_ocr(snippets)
    new=dict(raw);added={};conflicts=[]
    # Extracting 3 shifted rectangles of one frame is NOT 3 independent views.
    # The source helper does not yet record timestamps, so favor strict
    # agreement with the old recognizer; count OCR methods rather than frames.
    for i,notes in cand.items():
        counts=Counter(q['value'] for q in notes if q['conf']>=60)
        if not counts:continue
        value,votes=counts.most_common(1)[0]
        second=counts.most_common(2)
        if len(second)>1 and second[1][1]>=votes:continue
        independent_views=len({q['frame'] for q in notes if q['value']==value and q['conf']>=60})
        old=raw.get(i)
        if old and old['value']!=value:
            conflicts.append({'row':i+1,'original':old['value'],'isolated':value,
                              'action':'neither_used_for_new_promotion'})
            continue
        if old and old['value']==value and old['strength']=='single' and votes>=2 and independent_views>=2:
            # Two different crop algorithms agreeing offers additional evidence,
            # but is still one underlying screenshot; mark explicitly.
            new[i]={**old,'strength':'agreement','confidence':min(.81,old['confidence']+.12),
                    'views':independent_views,'votes':old.get('votes',1)+votes,'source':'original_and_isolated_ocr'}
            added[i]=new[i]
        elif old is None and votes>=4 and independent_views>=2:
            # Require many consistent detections (across at most 2 frames and
            # three ROI variants) and contextual validation later.
            new[i]={'value':value,'strength':'agreement','confidence':min(.76,.55+.035*votes),
                    'views':independent_views,'votes':votes,'source':'isolated_ocr_distinct_video_frames_and_sequence'}
            added[i]=new[i]
    return new,{'new_or_upgraded':{str(i):v for i,v in added.items()},
                'disagreements':conflicts,'isolated_details':details,
                'limitation':'Counts in shifted ROIs are correlated; validated_anchors must still check sequence.'}
