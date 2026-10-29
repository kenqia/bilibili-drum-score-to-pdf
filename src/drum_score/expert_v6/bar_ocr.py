# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
"""Conservative score-bar-number hints for video raster notation.

This is *not* a general-purpose OCR engine. It reads a limited, pre-staff
left-margin region, combines alternative crops, and refuses low-confidence
predictions. False positives never directly rewrite or delete notation.
"""
from __future__ import annotations
import re
import cv2
import numpy as np


def patches(frame, cy):
    """Two plausible regions above the left portion of a drum staff.

    Video has wildly different margins and styles; return multiple crops and
    let downstream scoring decide. The model deliberately excludes the staff.
    """
    h,w=frame.shape[:2]
    scale=w/min(960,w)
    cy=int(round(cy*scale))
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    result=[]
    for x0,x1,y0,y1 in ((14,46,-49,-17),(17,43,-44,-15),(12,48,-37,-12)):
        x0,x1=int(x0*scale),int(x1*scale)
        a,b=cy+int(y0*scale),cy+int(y1*scale)
        if a<0 or b>h or b<=a or x1>w:continue
        crop=gray[a:b,x0:x1]
        if (crop<208).mean()<.008:continue
        crop=cv2.resize(crop,(256,224),interpolation=cv2.INTER_CUBIC)
        crop=cv2.threshold(crop,205,255,cv2.THRESH_BINARY)[1]
        # Do not treat musical staff lines as glyphs.
        horizontal=cv2.morphologyEx(255-crop,cv2.MORPH_OPEN,
                                    cv2.getStructuringElement(cv2.MORPH_RECT,(135,1)))
        crop=cv2.max(crop,horizontal)
        out=np.full((250,275),255,np.uint8);out[:224,:256]=crop
        result.append(out)
    return result


def batch_ocr(images):
    """Run OCR in safe bounded-height batches, retaining global snippet IDs.

    Tesseract rejects images taller than ~32767 pixels, so never create an
    unbounded contact sheet. Process in <= 40-strip chunks.
    """
    if not images:return {}
    try:
        import pytesseract
    except ImportError:
        return {}
    stride=250
    result={}
    for offset in range(0,len(images),40):
        subset=images[offset:offset+40]
        board=np.concatenate(subset,axis=0)
        try:
            data=pytesseract.image_to_data(board,config='--psm 11 -c tessedit_char_whitelist=0123456789',
                                          output_type=pytesseract.Output.DICT)
        except Exception:
            # The PDF exporter must still function if the optional OCR fails.
            continue
        for j,value in enumerate(data['text']):
            value=value.strip()
            if not re.fullmatch(r'\d{1,3}',value):continue
            idx=int((data['top'][j]+data['height'][j]/2)//stride)
            if idx>=len(subset):continue
            number=int(value)
            conf=float(data['conf'][j])
            if not 1<=number<=999 or conf<45:continue
            result.setdefault(offset+idx,[]).append((number,conf))
    return result


def temporal_votes(snippet_rows):
    """Batch process prebuilt (row_index, frame, center_y) evidence.

    Return only confirmed values where two independent crops agree at useful
    confidence, or a single exceptionally strong read; otherwise raw hints.
    """
    board=[];mapping=[]
    for row_id,frame,center in snippet_rows:
        for crop in patches(frame,center):
            mapping.append(row_id)
            board.append(crop)
    if not board:return {},{}
    recognized=batch_ocr(board)
    evidence={}
    for idx,cands in recognized.items():
        row=mapping[idx]
        evidence.setdefault(row,[]).extend(cands)
    clean={}
    for row,hits in evidence.items():
        by_num={}
        for number,confidence in hits:
            by_num.setdefault(number,[]).append(confidence)
        # Trust multiple detections of the same number in shifted ROIs,
        # or one extremely strong candidate only as a weak anchor.
        winners=sorted(by_num.items(),key=lambda v:(len(v[1])>=2, max(v[1]),sum(v[1])),reverse=True)
        if not winners:continue
        num,confs=winners[0]
        if len(confs)>=2 and max(confs)>=65 and not any(
            len(other)>=2 and max(other)>=max(confs)-12 for n,other in winners[1:]):
            clean[row]={'value':num,'confidence':min(0.95,0.50+.0025*sum(confs)),
                        'strength':'agreement','votes':len(confs)}
        elif len(confs)==1 and confs[0]>=90 and len(winners)==1:
            clean[row]={'value':num,'confidence':0.63,'strength':'single','votes':1}
    return clean,{str(k):[{'number':n,'ocr_conf':round(c,1)} for n,c in v] for k,v in evidence.items()}


def validated_anchors(raw):
    """Use progression context to validate read bar numbers. No invented bars.

    Only numeric anchors with multiple independent confirmations and at least
    one consistent other anchor survive; weak singletons remain hints.
    """
    evidence={i:info for i,info in raw.items() if info['strength']=='agreement'}
    accepted={}
    # A measure number should advance monotonically. Count intervening rows:
    # 1-16 bars per staff is plausible; 4 is typical but not assumed exact.
    for i,info in evidence.items():
        supporters=[j for j,p in evidence.items() if j!=i and
                    1<=abs(j-i)<=12 and
                    (p['value']-info['value'])*(j-i)>0 and
                    1<=abs(p['value']-info['value'])/abs(j-i)<=16]
        if supporters:accepted[i]=info
    return accepted


def audit_sequence(rows,verified,raw,overlap_stats,mode):
    n=len(rows)
    flags=[];checks=[]
    for i,r in enumerate(rows):
        if r.flags:
            flags.append({'type':'extractor_flag','row':i+1,'message':'; '.join(r.flags),'severity':'review'})
    anchors=sorted(verified)
    deltas=[(verified[b]['value']-verified[a]['value'])/(b-a) for a,b in zip(anchors,anchors[1:])
            if b>a and verified[b]['value']>verified[a]['value'] and b-a<=7]
    typical=None
    if len(deltas)>=2:
        values=np.array(deltas)
        mid=float(np.median(values))
        typical=round(mid,2)
    for a,b in zip(anchors,anchors[1:]):
        va,vb=verified[a]['value'],verified[b]['value'];distance=b-a
        diff=vb-va
        item={'after_row':a+1,'before_row':b+1,'bar_a':va,'bar_b':vb,'row_steps':distance,
              'bar_difference':diff,'status':'unchecked'}
        if diff<=0:
            item['status']='non_monotonic';flags.append({'type':'non_monotonic','row':b+1,'severity':'review',
                'message':f'小节编号疑似倒退/重复：{va} → {vb}。不能单凭 OCR 删除谱行。'})
        elif typical is not None and distance<=8 and diff/distance>max(typical*1.65,typical+2.5):
            item['status']='possible_missing';flags.append({'type':'possible_missing','row':b+1,'severity':'review',
                'message':f'两个验证数字之间可能跳过谱行：{va} → {vb}，相隔 {distance} 行。'})
        elif typical is not None and distance<=8 and diff/distance<typical*.45:
            item['status']='possible_duplicate';flags.append({'type':'possible_duplicate','row':b+1,'severity':'review',
                'message':f'两段之间可能重复：{va} → {vb}。请对照视频。'})
        else:item['status']='plausible'
        checks.append(item)
    if len(verified)<3:
        flags.append({'type':'insufficient_ocr','row':None,'severity':'information',
            'message':'足够可靠的小节数字锚点不足，无法证明整首曲子的数字连续性。'})
    if mode=='page':
        for transition in overlap_stats.get('transitions',[]):
            if transition.get('page',0)==1:continue
            if transition.get('overlap',0)==0:
                flags.append({'type':'unverified_transition','row':None,'severity':'review',
                    'page':transition['page'],'message':f'第 {transition["page"]} 屏与前屏无可靠重叠；可能是正常换屏，也可能有重复/漏谱。'})
    quality='needs_review' if any(f['severity']=='review' for f in flags) else 'partial_evidence'
    return {'status':quality,'row_count':n,'ocr_confirmed':len(verified),'ocr_candidate_rows':len(raw),
            'expected_bars_per_row':typical,'bar_checks':checks,'flags':flags,
            'limits':'OCR 数字仅用于审计。没有原始制谱文件或逐音符人工验证，不能证明全曲无漏音符。'}
