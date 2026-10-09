"""Ordered segments reset spatial coordinates; visible boundaries remain mandatory."""
from agent_continuity import continuous_rows, waiting, text
from agent_regions import native_rows, invalid


def ordered_segments(decision, packet, presented):
    segments, boundaries = decision['segments'], decision['boundaries']
    frames = {f['id']: f for f in packet['frames']}
    if not isinstance(segments, list) or not segments or len(segments) > 100:
        invalid('缺少有界有序谱面段。')
    fields = {'id','frames','rows','observations','transitions','extras','outside_rows_verified','evidence'}
    flattened, ids = [], []
    for segment in segments:
        if not isinstance(segment,dict) or set(segment)!=fields or not text(segment['id']) or not text(segment['evidence']):
            invalid('谱面段字段或依据非法。')
        sf=segment['frames']
        if not isinstance(sf,list) or not sf or any(not isinstance(f,str) or f not in frames for f in sf):
            invalid('谱面段帧引用非法。')
        ids.append(segment['id']);flattened.extend(sf)
    if len(set(ids))!=len(ids) or flattened!=list(frames):
        waiting('谱面段缺帧、重复、回跳或顺序非法。')
    chosen, audits, extras = [], [], []
    for segment in segments:
        sf = segment['frames']
        if type(segment['outside_rows_verified']) is not bool:
            invalid('行外符号核查状态非法。')
        if not segment['outside_rows_verified']:
            waiting('标题、速度或行外符号仍未核查。')
        subpacket = {**packet,'frames':[frames[f] for f in sf]}
        subdecision = {**decision, **{k:segment[k] for k in ('rows','observations','transitions')},
                       'coverage':dict(first_frame=sf[0],last_frame=sf[-1],unresolved=[])}
        rows, audit = continuous_rows(subdecision, subpacket, presented)
        for row in rows:
            row.update(index=len(chosen),id=f'agent-row-{len(chosen):03d}',segment_id=segment['id'])
            chosen.append(row)
        regions = segment['extras']
        if not isinstance(regions,list) or len(regions)>20:
            invalid('行外区域列表非法。')
        for extra in regions:
            if not isinstance(extra,dict) or set(extra)!={'kind','placement','region'} or extra['kind'] not in ('title','notation') or extra['placement'] not in ('before_rows','after_rows'):
                invalid('行外区域类型非法。')
        natives=native_rows({'rows':[e['region'] for e in regions]},subpacket,presented) if regions else []
        for extra,native in zip(regions,natives):
            if any(native['frame_id']==r['frame_id'] and native['bbox'][1]<r['bbox'][3] and native['bbox'][3]>r['bbox'][1] for r in rows):
                waiting('行外区域与谱行重复交叠。')
            same_frame=[r for r in rows if r['frame_id']==native['frame_id']]
            if same_frame and ((extra['placement']=='before_rows' and native['bbox'][3]>min(r['bbox'][1] for r in same_frame)) or
                               (extra['placement']=='after_rows' and native['bbox'][1]<max(r['bbox'][3] for r in same_frame))):
                waiting('行外区域的打印位置与原帧行序矛盾。')
            native.update(segment_id=segment['id'],kind=extra['kind'],placement=extra['placement'])
            extras.append(native)
        audits.append(dict(id=segment['id'],**audit,extras=len(regions),outside_rows_verified=True,evidence=segment['evidence']))
    coverage=decision['coverage']
    if not isinstance(coverage,dict) or set(coverage)!={'first_frame','last_frame','unresolved'}:
        invalid('覆盖字段非法。')
    if coverage['first_frame']!=flattened[0] or coverage['last_frame']!=flattened[-1] or not isinstance(coverage['unresolved'],list) or coverage['unresolved']:
        waiting('首尾或段间覆盖仍有疑点。')
    if not isinstance(boundaries,list) or len(boundaries)!=len(segments)-1:
        waiting('谱面段边界证据缺失。')
    bf={'from_segment','to_segment','from_frame','to_frame','change','relation','before_complete','after_complete','continuity_verified','evidence_images','unresolved','evidence'}
    for left,right,b in zip(segments,segments[1:],boundaries):
        if not isinstance(b,dict) or set(b)!=bf or not text(b['evidence']):
            invalid('换页边界字段或依据非法。')
        if any(type(b[k]) is not bool for k in ('before_complete','after_complete','continuity_verified')) or not isinstance(b['unresolved'],list):
            invalid('换页边界状态非法。')
        if b['change'] not in ('page_turn','scale','layout_jump') or b['relation'] not in ('next','skip','backward','uncertain'):
            invalid('换页变化或次序判断非法。')
        before,after=left['frames'][-1],right['frames'][0]
        if (b['from_segment'],b['to_segment'],b['from_frame'],b['to_frame'])!=(left['id'],right['id'],before,after):
            waiting('边界必须是相邻段的前后真实观察。')
        refs=b['evidence_images']
        if not isinstance(refs,list) or any(not isinstance(i,str) or i not in presented for i in refs) or not {before,after,'comparison'}<=set(refs):
            invalid('换页缺少前后原图与对照证据。')
        if b['change']!='page_turn' or b['relation']!='next' or b['unresolved'] or not all(b[k] for k in ('before_complete','after_complete','continuity_verified')):
            waiting('跳页、倒退、比例或布局突变、未决接续不在支持页序内。')
        if any(not s['complete'] for segment,fid in ((left,before),(right,after)) for s in segment['observations'] if s['frame_id']==fid):
            waiting('换页边缘仍有残行，不能宣称完整边界。')
    audit=dict(scope='observed_ordered_segments',segments=audits,boundaries=boundaries,unresolved=[],
               first_frame=flattened[0],last_frame=flattened[-1],hidden_content_proven_absent=False)
    return chosen,audit,extras
