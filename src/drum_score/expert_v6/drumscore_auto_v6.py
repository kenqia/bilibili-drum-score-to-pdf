# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
#!/usr/bin/env python3
"""DrumScore v6 — automatic MP4 to printable PDF with evidence audit.

Upward scrolling / page-cut complete five-line video scores. Upgrades v3 with:
small-bar-number candidate reading, cross-row consistency validation, targeted
re-sampling, provenance, uncertainty report, and conservative print output.
Never fabricates missing notes. Never deletes a row based on OCR alone.
"""
from __future__ import annotations
import argparse,json,sys,copy,time
from pathlib import Path
import cv2
import numpy as np
from .drumscore_auto_v3 import (detect_pages,page_extract,run_ensemble)
from .drumscore_v2 import (extract as scrolling_extract,capture_obs,emit_pdf,
                          create_review_html,write_metadata,applied_rows)
from .legacy_extractor import compare
from .bar_ocr import temporal_votes,validated_anchors,audit_sequence
from .adaptive_ocr import isolated_consensus, adaptive_hints
from .sequence_v5 import coherent_subset
from .staff_integrity import choose_source_views, emit_images_pdf, make_crop_audit

VERSION='6.0.0'


def sample_row_regions(video,rows,max_views=2):
    """Gather visual evidence, not guesses; no inferred bar numbers."""
    cap=cv2.VideoCapture(str(video));observations=[];cached={}
    ncap=0
    for i,row in enumerate(rows):
        use=sorted(row.observations,key=lambda o:o.score)[:max_views]
        for obs in use:
            if obs.y<=0:
                # Legacy extractor sets y=0: re-detect row in source frame via image fingerprint.
                key=round(obs.t,2)
                if key not in cached:
                    cap.set(cv2.CAP_PROP_POS_MSEC,float(key)*1000);ok,fr=cap.read()
                    if ok:cached[key]=(fr,capture_obs(fr,key,None))
                if key not in cached:continue
                fr,detected=cached[key]
                matches=sorted(((compare(obs.feature,d.feature),d) for d in detected),
                               key=lambda q:q[0],reverse=True)
                if not matches or matches[0][0]<.52:continue
                center=matches[0][1].y
            else:
                key=round(obs.t,2)
                if key not in cached:
                    cap.set(cv2.CAP_PROP_POS_MSEC,float(key)*1000);ok,fr=cap.read()
                    if ok:cached[key]=(fr,None)
                if key not in cached:continue
                fr=cached[key][0];center=obs.y
            observations.append((i,fr,center));ncap+=1
    cap.release()
    return observations,{'views_examined':ncap,'source_frames':len(cached)}


def merge_second_reads(orig,extra):
    """Merge independent capture votes; conflict is marked, not silently resolved."""
    merged=dict(orig)
    contradictions=[]
    for row,v in extra.items():
        if row in merged and merged[row]['value']!=v['value']:
            contradictions.append({'row':row+1,'first':merged[row]['value'],'new':v['value']})
            merged.pop(row,None)
        elif row not in merged:
            merged[row]=v
    return merged,contradictions


def resample_suspect_views(video,rows,stats,flags,cap_per_target=5):
    """Targeted return to the *original video*, not extrapolation of absent music.

    Extra frames only improve an existing row if visual correspondence is strong.
    Suspicious scene cuts also get small 0.5--2.0 s samples around the cut; any
    unmatched staff is reported for review, never silently inserted into PDF.
    """
    flagged={int(f['row'])-1 for f in flags if f.get('row') is not None}
    pages=stats.get('pages',[]) if stats.get('mode')=='page' else []
    links=stats.get('transitions',[])
    starts=[];running=0
    for j,link in enumerate(links):
        if j:
            starts.append((j,running,link))
        running+=link.get('new_rows',0)
    for j,index,link in starts:
        if link.get('overlap',0)==0:
            flagged.update(x for x in (index-1,index) if 0<=x<len(rows))
    for i,row in enumerate(rows):
        if row.flags:flagged.add(i)
    flagged={i for i in flagged if 0<=i<len(rows)}
    cap=cv2.VideoCapture(str(video));visited={};retaken=0;scored=0;added=0
    for idx in sorted(flagged):
        row=rows[idx]
        base=row.best()
        before=base.score
        shifts=[-4,-2,-.75,.75,2,4][:cap_per_target]
        for delta in shifts:
            t=base.t+delta
            if t<0:continue
            key=round(t,2)
            if key not in visited:
                cap.set(cv2.CAP_PROP_POS_MSEC,1000*key);ok,fr=cap.read()
                if ok:visited[key]=fr
            if key not in visited:continue
            frame=visited[key];retaken+=1
            new=capture_obs(frame,key,None)
            if not new:continue
            old_feature=base.feature
            opts=sorted([(compare(old_feature,c.feature),c) for c in new],
                        key=lambda q:q[0],reverse=True)
            if not opts:continue
            sim,candidate=opts[0]
            if sim<.72:continue
            if (candidate.image.shape[1]!=base.image.shape[1] or
                abs(candidate.image.shape[0]-base.image.shape[0])>3):continue
            # Screen position need not remain fixed in scrolling mode.
            scored+=1
            if candidate.score < before-0.04:
                row.add(candidate);added+=1
    cut_checks=[]
    if pages and links:
        for j,index,link in starts:
            if link.get('overlap',0)>0:continue
            boundary=pages[j]['start_s'] if j<len(pages) else None
            if boundary is None:continue
            scan=[]
            for delta in (-2.,-1.,-.4,.4,1.,2.):
                t=float(boundary+delta)
                if t<0:continue
                key=round(t,2)
                if key not in visited:
                    cap.set(cv2.CAP_PROP_POS_MSEC,1000*key);ok,fr=cap.read()
                    if ok:visited[key]=fr
                if key not in visited:continue
                found=capture_obs(visited[key],key,None)
                neighbors=rows[max(0,index-5):min(len(rows),index+5)]
                unmatched=0
                for ob in found:
                    sim=max((compare(ob.feature,r.feature) for r in neighbors if r.feature is not None),default=0.)
                    if sim<.33:unmatched+=1
                scan.append({'time_s':key,'staves':len(found),'unmatched_vs_neighbor_rows':unmatched})
            cut_checks.append({'at_s':round(float(boundary),2),'next_page':j+1,
                               'scan':scan,'action':'reported_for_review_not_auto_inserted'})
    cap.release()
    return {'targeted_rows':[i+1 for i in sorted(flagged)],
            'extra_frames_read':len(visited),'candidate_frames_tested':retaken,
            'matched_candidates':scored,'cleaner_views_added':added,
            'unverified_cut_rescans':cut_checks}


def make_audit_html(path,report,review_path):
    import html
    flags=report['audit']['flags']
    chunks=[]
    for q in flags:
        label=f'谱行 {q["row"]}' if q.get('row') else f'画面 {q["page"]}' if q.get('page') else '全曲'
        chunks.append('<tr><td>'+html.escape(label)+'</td><td>'+html.escape(q['type'])+'</td><td>'+html.escape(q['message'])+'</td></tr>')
    rows=''.join(chunks) or '<tr><td colspan="3">未找到自动审计警报（不等于音乐完整性证明）</td></tr>'
    bars=''.join(f'<span class="pill">{int(i)+1}: {v["value"]}</span>' for i,v in sorted(report['bar_number_anchors'].items(),key=lambda v:int(v[0])))
    trusted=set(report['bar_number_anchors'])
    seen=report.get('systems',[])
    candidate_lines=[]
    for i,info in sorted(report.get('bar_number_hints',{}).items(),key=lambda p:int(p[0])):
        if i in trusted:continue
        idx=int(i)
        moment=seen[idx].get('best_time_s') if idx<len(seen) else None
        momenttext=f'{moment:.1f}s' if isinstance(moment,(int,float)) else '未知'
        candidate_lines.append(f'<tr><td>{idx+1}</td><td>{html.escape(str(info["value"]))}</td><td>{momenttext}</td><td>候选，不作确定小节编号</td></tr>')
    for i,hint in sorted(report.get('v5_style_learning',{}).get('style_candidates',{}).items(),key=lambda p:int(p[0])):
        if i in trusted or i in report.get('bar_number_hints',{}):continue
        idx=int(i)
        moment=seen[idx].get('best_time_s') if idx<len(seen) else None
        momenttext=f'{moment:.1f}s' if isinstance(moment,(int,float)) else '未知'
        candidate_lines.append(f'<tr><td>{idx+1}</td><td>{int(hint["value"])}</td><td>{momenttext}</td><td>字形相似度提示（未经核实）</td></tr>')
    candidate_html=''.join(candidate_lines) or '<tr><td colspan="4">暂无未确认数字候选</td></tr>'
    content=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DrumScore v6 数字连续性审计</title><style>
    body{{font:15px/1.6 system-ui,-apple-system,sans-serif;max-width:1100px;margin:32px auto;padding:0 16px;color:#1f2937}}h1{{font-size:24px}}.muted{{color:#586477}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}.pill{{display:inline-block;background:#eff6ff;padding:4px 9px;border-radius:30px;margin:3px;font-size:13px}}a{{color:#1d4ed8}}.warn{{background:#fff7e3;border-left:4px solid #f59e0b;padding:10px 15px}}
    </style></head><body><h1>DrumScore v6 · 小节号连续性检查</h1><p class="warn">注意：小节数字与图像匹配只能发现部分错误，无法证明每个音符正确。出现疑点请打开原视频核对。</p>
    <p>自动输出 {report['audit']['row_count']} 行谱；OCR 原始候选 {report['audit']['ocr_candidate_rows']} 行；通过跨行校验的编号 {report['audit']['ocr_confirmed']} 个。视频内学习字形：{len(report.get('v5_style_learning',{}).get('digit_classes',[]))} 类。状态：<strong>{html.escape(report['audit']['status'])}</strong></p><p><a href="{html.escape(review_path.name)}">打开逐行图像校对页面</a></p><h2>可信小节编号锚点</h2><p>{bars or '暂无足够可靠的数字锚点。'}</p><h2>低清视频内字形学习</h2><p>自学习数字种类：{', '.join(report.get('v5_style_learning',{}).get('digit_classes',[])) or '无（可信种子不足）'}。候选谱行数：{len(report.get('v5_style_learning',{}).get('style_candidates',{}))}。<strong>模板相似度仅为提示，仍需独立画面与前后行顺序校验。</strong></p><h2>未确认小节号候选（需要原视频核对）</h2><table><thead><tr><th>谱行</th><th>候选数字</th><th>视频时间</th><th>状态</th></tr></thead><tbody>{candidate_html}</tbody></table><h2>疑点和证据局限</h2><table><thead><tr><th>位置</th><th>分类</th><th>自动判断</th></tr></thead><tbody>{rows}</tbody></table><p class="muted">重新取帧：{report['resampling']['extra_frames_read']} 个画面；加入更清晰候选：{report['resampling']['cleaner_views_added']} 个。未证实的内容不会自动补写。</p></body></html>'''
    path.write_text(content,encoding='utf8')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path)
    p.add_argument('-o','--output',type=Path,default=None)
    p.add_argument('--mode',choices=['auto','page','scroll'],default='auto')
    p.add_argument('--interval',type=float,default=1.0)
    p.add_argument('--scan-step',type=float,default=2.0)
    p.add_argument('--rows-per-page',type=int,default=8)
    p.add_argument('--no-ensemble',action='store_true')
    p.add_argument('--no-ocr',action='store_true',help='Disable optional Tesseract OCR')
    p.add_argument('--no-rescan',action='store_true',help='Skip targeted re-sampling')
    p.add_argument('--apply',type=Path,help='JSON exported by the offline row editor')
    p.add_argument('--no-integrity',action='store_true',help='v5-style fixed crop output (comparison)')
    p.add_argument('--no-integrity-rescan',action='store_true',help='skip extra video-frame attempts for crop repair')
    p.add_argument('--crop-overrides',type=Path,help='JSON with row-index keys and optional time_s / top_delta_px / bottom_delta_px')
    args=p.parse_args(argv)
    if not args.video.is_file():p.error('Input video not found')
    if args.interval<=0 or args.scan_step<=0 or args.rows_per_page<1:p.error('sampling intervals and rows-per-page must be positive')
    target=args.output or args.video.with_suffix('.pdf')
    target.parent.mkdir(parents=True,exist_ok=True)
    t0=time.perf_counter()
    pages,info=detect_pages(args.video,args.scan_step)
    mode=args.mode if args.mode!='auto' else ('page' if info['jump_rate']<.165 and len(pages)>=2 else 'scroll')
    print('v6 selected:',mode,'scene rate:',info['jump_rate'],'scenes:',len(pages),flush=True)
    if mode=='page':rows,stats=page_extract(args.video,args.scan_step)
    else:
        rows,tracking=scrolling_extract(args.video,interval=args.interval)
        stats={'mode':'scroll','detector':info,'tracking':tracking,'total_rows':len(rows)}
    if not rows:raise SystemExit('No full score rows identified; inspect original MP4')
    if not args.no_ensemble:
        cap=cv2.VideoCapture(str(args.video));width=cap.get(cv2.CAP_PROP_FRAME_WIDTH);cap.release()
        if width<1200:rows,stats=run_ensemble(args.video,mode,rows,stats,quality_interval=1.)
        else:stats['ensemble']={'checked':False,'chosen':mode,'reason':'HD backup skipped for runtime'}
    # Video-level row ID is authoritative, not OCR, and existing v3 output is preserved.
    if args.apply:rows=applied_rows(rows,args.apply)
    raw={};raw_evidence={};ocr_meta={}
    if not args.no_ocr:
        snippets,ocr_meta=sample_row_regions(args.video,rows)
        raw,raw_evidence=temporal_votes(snippets)
    verified=validated_anchors(raw)
    for i,anchor in verified.items():rows[i].start_bar=anchor['value']
    audit=audit_sequence(rows,verified,raw,stats,mode)
    if not args.no_rescan:
        recheck=resample_suspect_views(args.video,rows,stats,audit['flags'])
    else:recheck={'targeted_rows':[],'extra_frames_read':0,'candidate_frames_tested':0,'matched_candidates':0,'cleaner_views_added':0,'unverified_cut_rescans':[]}
    # Re-run OCR only for rows which now have new visual evidence, strictly advisory.
    if recheck['cleaner_views_added'] and not args.no_ocr:
        touched=set(x-1 for x in recheck['targeted_rows'])
        snips,_=sample_row_regions(args.video,[rows[i] for i in sorted(touched)])
        ocr2,_=temporal_votes(snips)
        mapped={idx:v for idx,v in zip(sorted(touched),[ocr2.get(k) for k in range(len(touched))]) if v is not None}
        raw,contradictions=merge_second_reads(raw,mapped)
        verified=validated_anchors(raw)
        audit=audit_sequence(rows,verified,raw,stats,mode)
    else:contradictions=[]
    # v5: within-video glyph isolation, optional local font learning and sequence crosschecks.
    # Re-sample source frames for OCR but never fabricate/edit the notation images.
    v5_snippets=[]
    adaptive_stats={'source_frames':0,'views_examined':0}
    if not args.no_ocr:
        v5_snippets,adaptive_stats=sample_row_regions(args.video,rows,max_views=3)
        raw,isolated_meta=isolated_consensus(v5_snippets,raw)
        verified=validated_anchors(raw)
        promoted,style_meta=adaptive_hints(v5_snippets,verified,raw)
        # Only cross-validated style estimates can be elevated; never override OCR.
        for i,detail in promoted.items():
            if i not in raw:
                raw[i]=detail
        verified=validated_anchors(raw)
        # v5 global path filter: a locally well-supported but wrong read such as
        # 33 in the middle of 49-53 must not be called verified.
        verified,rejected_bars,expected_step=coherent_subset(verified)
        audit=audit_sequence(rows,verified,raw,stats,mode)
        if rejected_bars:
            for bad in rejected_bars:
                audit['flags'].append({'type':'global_ocr_outlier','row':bad['row'],
                    'severity':'review','message':f"OCR 读取 {bad['read']} 与整体小节顺序冲突，已从可信锚点降级为候选。"})
            audit['status']='needs_review'
    else:
        rejected_bars=[];expected_step=None
        isolated_meta={'disabled':True};style_meta={'disabled':True}
    # Keep the review page and JSON synchronized with final trusted anchors.
    for row in rows:
        row.start_bar=None
    for i,anchor in verified.items():
        rows[i].start_bar=anchor['value']
    if contradictions:
        audit['flags'].append({'type':'ocr_disagreement','row':None,'severity':'review',
                               'message':'重新取帧后 OCR 候选冲突，已将冲突编号从证据中移除。'})
        audit['status']='needs_review'
    base=target.with_suffix('')
    overview=Path(str(base)+'_overview.png')
    review=Path(str(base)+'_review.html')
    report_path=Path(str(base)+'_report.json')
    audit_page=Path(str(base)+'_audit.html')
    crop_info=[];crop_images=[]
    if args.no_integrity:
        number_pages=emit_pdf(rows,target,rows_per_page=args.rows_per_page,numbered_png=overview)
    else:
        overrides={}
        if args.crop_overrides:
            payload=json.loads(args.crop_overrides.read_text(encoding='utf8'))
            overrides=payload.get('rows',payload)
        crop_images,crop_info=choose_source_views(args.video,rows,rescan=not args.no_integrity_rescan,overrides=overrides)
        number_pages=emit_images_pdf(crop_images,target,rows_per_page=args.rows_per_page,overview=overview,info=crop_info)
        make_crop_audit(Path(str(base)+'_crop_audit.html'),crop_images,crop_info)
    
    data=write_metadata(rows,stats,report_path)
    data.update({'version':VERSION,'method':'v5 dual-mode OCR sequencing + v6 local-lattice full-staff recrop and crop-audit',
                 'audit':audit,'bar_number_anchors':{str(i):v for i,v in verified.items()},
                 'bar_number_hints':{str(i):v for i,v in raw.items()},
                 'ocr_meta':ocr_meta,'ocr_raw_votes':raw_evidence,
                 'v5_isolated_ocr':isolated_meta,'v5_style_learning':style_meta,
                 'v5_evidence_frames':adaptive_stats,
                 'v5_global_sequence':{'expected_bars_per_row':expected_step,'excluded_ocr':rejected_bars},
                 'resampling':recheck,'ocr_conflicts':contradictions,
                 'v6_integrity':{'enabled':not args.no_integrity, 'crops':crop_info,
                  'suspect_rows':sum(bool(x.get('issues')) for x in crop_info),
                  'source_frame_recrops':sum(x.get('alternates_evaluated',0) for x in crop_info)},
                 'result':{'rows':len(rows),'pages':number_pages,'seconds':round(time.perf_counter()-t0,1)},
                 'warning':'PDF is a reconstruction of visible notation, not a guarantee of score completeness or correctness.'})
    data['statistics']['total_rows']=len(rows)
    report_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    if crop_images:
        # The editor must display the actual printed v6 crop, not the v5 source crop.
        from copy import copy
        from .drumscore_v2 import Observation, System, score_image
        showing=[]
        for row,img,rec in zip(rows,crop_images,crop_info):
            obj=copy(row)
            b=copy(row.best())
            b.image=cv2.cvtColor(img,cv2.COLOR_GRAY2BGR)
            b.t=rec['source_time_s']
            b.score,b.color_fraction=score_image(b.image)
            obj.observations=[b]
            showing.append(obj)
        create_review_html(showing,review)
    else:create_review_html(rows,review)
    make_audit_html(audit_page,data,review)
    print(json.dumps({'pdf':str(target),'rows':len(rows),'pdf_pages':number_pages,
                      'mode':mode,'v3_ensemble':stats.get('ensemble',{}).get('chosen',mode),
                      'ocr_verified':len(verified),'ocr_candidates':len(raw),
                      'audit_status':audit['status'],'flags':len(audit['flags']),
                      'resampled':recheck['extra_frames_read'],
                      'style_digits':style_meta.get('digit_classes',[]),
                      'style_suggestions':len(style_meta.get('style_candidates',{})),
                      'integrity_suspects':data['v6_integrity']['suspect_rows'],
                      'crop_audit':str(Path(str(base)+'_crop_audit.html')),
                      'audit':str(audit_page)},ensure_ascii=False,indent=2),flush=True)
    return data

if __name__=='__main__':main()
