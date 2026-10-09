"""Local veto for established geometric pairs; never create spatial identities."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from agent_performance import ACTIVE, stage
from cursor_detect import cursor_occluded, obstruction_detected
from video_seek import ConversionError


def local_ink(image, sighting):
    """Read a staff-anchored window so a smaller submitted crop cannot hide notes."""
    y, spacing = round(sighting['staff_y']), sighting['spacing']
    if spacing < 2 or spacing > image.height/12:
        return None, 'unreliable_five_line_spacing', 0
    top, bottom = y-round(4*spacing), y+round(8*spacing)
    box = sighting['bbox']
    if not sighting['complete'] or top < 0 or bottom > image.height:
        return None, 'partial_or_missing_margin', 0
    if box[1] > y-3*spacing or box[3] < y+7*spacing:
        return None, 'unverified_full_boundary', 0
    # Five long staff lines establish the visible horizontal extent independently of crop.
    window = image.crop((0, top, image.width, bottom))
    gray = np.asarray(window.convert('L'))
    analyzed_pixels = int(gray.size)
    ink = (gray < 180).astype(np.uint8)
    support = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(25, image.width//4)), np.uint8))
    ys = [y-top+round(n*spacing) for n in range(5)]
    bands = [support[max(0,line-2):line+3].max(axis=0) for line in ys]
    common = np.logical_and.reduce(bands)
    columns = np.flatnonzero(common)
    if len(columns) < image.width*.45:
        return None, 'unreliable_five_line_support', analyzed_pixels
    left, right = int(columns[0]), int(columns[-1])+1
    if box[0] > left or box[2] < right:
        return None, 'crop_excludes_native_staff', analyzed_pixels
    left, right = max(0,left-round(spacing)), min(image.width,right+round(spacing))
    native = window.crop((left,0,right,window.height))
    gray = np.asarray(native.convert('L'))
    if cursor_occluded(native,spacing) or obstruction_detected(native,y-top,spacing):
        return None, 'cursor_or_obstruction', analyzed_pixels
    if float((gray > 210).mean()) < .75:
        return None, 'unreliable_clean_background', analyzed_pixels
    ink = (gray < 180).astype(np.uint8)
    dense = cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(12,round(spacing*2)),)*2,np.uint8))
    if int(dense.sum()) >= spacing*spacing*4:
        return None, 'possible_dense_overlay', analyzed_pixels
    for line in ys:
        ink[max(0,line-2):line+3] = 0
    _,_,stats,_ = cv2.connectedComponentsWithStats(ink,8)
    if any(w >= spacing*2 and h >= spacing*6 for x,z,w,h,area in stats[1:]):
        return None, 'possible_overlay', analyzed_pixels
    if int(ink.sum()) < max(100,spacing*spacing):
        return None, 'insufficient_notation_ink', analyzed_pixels
    return ink, None, analyzed_pixels


def compare(before, after, a, b):
    ink_a, reason_a, pixels_a = local_ink(before,a)
    ink_b, reason_b, pixels_b = local_ink(after,b)
    result = dict(status='uncertain', reason=reason_a or reason_b or 'unreliable_alignment',
                  analyzed_pixels=pixels_a+pixels_b)
    if ink_a is None or ink_b is None or ink_a.shape != ink_b.shape or abs(a['spacing']-b['spacing']) > .1:
        return result
    # Native codec noise gets a small fixed tolerance; no scaling or output reconstruction.
    kernel = np.ones((3,3),np.uint8)
    missing_a = np.logical_and(ink_a,cv2.dilate(ink_b,kernel)==0)
    missing_b = np.logical_and(ink_b,cv2.dilate(ink_a,kernel)==0)
    unmatched = (int(missing_a.sum())+int(missing_b.sum()))/(int(ink_a.sum())+int(ink_b.sum()))
    result.update(unmatched_ink_fraction=round(unmatched,6),notation_ink=[int(ink_a.sum()),int(ink_b.sum())])
    if unmatched <= .08:
        result.update(status='not_contradicted',reason='local_ink_not_contradicted')
    elif unmatched >= .45:
        result.update(status='conflict',reason='contradictory_local_notation')
    else:
        result.update(reason='ambiguous_local_notation')
    return result


def check_pairs(task, decision, packet, audits=None):
    """Called only after v3/v4 geometry validation for explicitly lazy observations."""
    if task is None:
        raise ConversionError('invalid_decision','内容检查缺少已核验的任务来源。')
    frames = {f['id']:f for f in packet['frames']}
    parts = decision['segments'] if decision['schema_version']==4 else [decision]
    checks=[]
    with stage('content_validation'):
        for part in parts:
            sightings={s['id']:s for s in part['observations']}
            for transition in part['transitions']:
                first,last=frames[transition['from_frame']],frames[transition['to_frame']]
                with Image.open(Path(task)/first['path']) as old, Image.open(Path(task)/last['path']) as new:
                    for pair in transition['matches']:
                        a,b=(sightings[i] for i in pair)
                        result=compare(old,new,a,b)
                        result.update(from_frame=first['id'],to_frame=last['id'],matches=pair,
                            source_sha256=packet['source']['sha256'],frame_sha256=[first['sha256'],last['sha256']],
                            pts=[first['pts'],last['pts']],time_base=[first['time_base'],last['time_base']],
                            proposed_bboxes=[a['bbox'],b['bbox']],staff_y=[a['staff_y'],b['staff_y']],spacing=[a['spacing'],b['spacing']],
                            analysis_windows=[[0,round(s['staff_y'])-round(4*s['spacing']),f['width'],round(s['staff_y'])+round(8*s['spacing'])]
                                              for s,f in ((a,first),(b,last))],
                            start=first['timestamp'],end=last['timestamp'],before_image=first['id'],after_image=last['id'],
                            scope='proposed_geometric_pair_only',identity_established_by_content=False)
                        if 'id' in part:
                            result['segment_id']=part['id']
                        checks.append(result)
                        recorder=ACTIVE.get()
                        if recorder is not None:
                            count=recorder.operation.setdefault('metrics',{}).setdefault('content_validation',dict(pair_checks=0,analyzed_pixels=0,conflict_checks=0,uncertain_checks=0))
                            count['pair_checks']+=1;count['analyzed_pixels']+=result['analyzed_pixels']
                            count['conflict_checks']+=result['status']=='conflict'
                            count['uncertain_checks']+=result['status']=='uncertain'
                            recorder.save()
        if audits is not None:
            audits.extend(checks)
        unresolved=[c for c in checks if c['status']!='not_contradicted']
        if unresolved:
            error=ConversionError('review_required','原生局部内容冲突或证据不可靠，请修正对应、完整裁剪或补采干净来源。')
            error.issues=unresolved
            raise error
    return checks
