"""Native score geometry shared by navigation, anchors and source freezing.

These checks preserve visible ink. They do not recognize music or approve
hidden notation. Algorithms and tolerances are shared without task mutation.
"""
import math

import cv2
import numpy as np
from PIL import Image
import reconstruction as geometry

# Bound worker contention in the per-frame geometry pipeline.
cv2.setNumThreads(2)


def detect(image):
    """Detect white-paper five-line systems and retain their off-staff ink.

    No OCR or musical inference: bar ranges stay unknown. Partial systems are
    deferred to a later complete observation rather than reconstructed.
    """
    rgb = np.asarray(image.convert('RGB'))
    bright = (rgb.min(axis=2) >= 190).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bright)
    if count < 2:
        return [], [], []
    paper = stats[1:][np.argmax(stats[1:, cv2.CC_STAT_AREA])]
    x, y, w, h, area = map(int, paper)
    if area < image.width * image.height * .08:
        return [], [], []
    mask = geometry.ink_mask(image)[y:y+h, x:x+w]
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
        np.ones((1, max(24, w // 8)), np.uint8))
    ys = np.flatnonzero((horizontal > 0).sum(axis=1) >= max(24, w * .15))
    runs = np.split(ys, np.where(np.diff(ys) > 1)[0] + 1)
    lines = [int(np.median(run)) for run in runs if len(run)]
    groups, used, detected_lines = [], set(), {}
    i = 0
    while i + 4 < len(lines):
        candidate = lines[i:i+5]
        spaces = np.diff(candidate)
        spacing = float(np.median(spaces))
        if spacing >= 3 and np.max(np.abs(spaces-spacing)) <= max(1.5, spacing*.18):
            # All five staff lines must share a real horizontal extent.
            coverage = horizontal[candidate] > 0
            common = np.flatnonzero(coverage.sum(axis=0) >= 4)
            if len(common) >= max(24, w*.15):
                groups.append((candidate[0], spacing, int(common[0]), int(common[-1])))
                detected_lines[candidate[0]]=candidate
                used.update(candidate)
                i += 5
                continue
        i += 1
    if not groups:
        return [], [], [{'code': 'partial_staff', 'bbox': [x,y,x+w,y+h]}] if lines else []
    # A long horizontal with a downward leg above the next staff is a local
    # off-staff mark. Keep it with that row, not with a remote viewport fragment.
    associated = {top: [] for top, _, _, _ in groups}
    for line in sorted(set(lines) - used):
        following = next((group for group in groups if group[0] > line), None)
        if following is None:
            continue
        top, spacing, left, right = following
        columns = np.flatnonzero(horizontal[line] > 0)
        if not len(columns) or not 4*spacing < top-line <= 9*spacing:
            continue
        if columns[0] < left + (right-left)*.2:
            continue
        leg = max(2, round(spacing))
        if any(np.count_nonzero(mask[line:min(h, line+leg+1), max(0, col-1):col+2].any(axis=1)) >= leg
               for col in (int(columns[0]), int(columns[-1]))):
            associated[top].append(line)
            used.add(line)
    # Choose genuinely blank separators. Ink reaching a boundary is reported.
    separators = []
    for left, right in zip(groups, groups[1:]):
        low, high = round(left[0]+4*left[1]+left[1]), round(right[0]-3*right[1])
        if associated[right[0]]:
            high = min(high, min(associated[right[0]]))
        blanks = np.flatnonzero((mask[max(0,low):max(low,high)] > 0).sum(axis=1) == 0) + low
        separators.append(int(blanks[len(blanks)//2]) if len(blanks) else (low+high)//2)
    first_top = max(0, round(groups[0][0]-8*groups[0][1]))
    low,high=max(0,round(first_top-2*groups[0][1])),min(h,round(first_top+2*groups[0][1]))
    blank=np.flatnonzero((mask[low:high]>0).sum(axis=1)==0)+low
    if len(blank) and first_top > 0:
        first_top=int(blank[np.argmin(np.abs(blank-first_top))])
    regions, risks = [], []
    if np.any(mask[:first_top]):
        hy, hx = np.where(mask[:first_top] > 0)
        regions.append({'kind': 'header', 'bbox': [x+int(hx.min()), y+int(hy.min()),
            x+int(hx.max())+1, y+int(hy.max())+1]})
        margin=groups[0][1]
        if hy.min()<margin or hx.min()<margin or hx.max()>w-1-margin:
            risks.append({'code':'crop_edge','bbox':regions[-1]['bbox']})
    for index, (top, spacing, left, right) in enumerate(groups):
        low = first_top if index == 0 else separators[index-1]
        high = separators[index] if index < len(separators) else h
        # Do not include a partial next system at the viewport bottom.
        partial = [v for v in lines if v not in used and v > top+4*spacing]
        if index == len(groups)-1 and partial:
            boundary=min(high,max(round(top+5*spacing),round(min(partial)-3*spacing)))
            separator_low=round(top+5*spacing)
            blank=np.flatnonzero((mask[separator_low:boundary]>0).sum(axis=1)==0)+separator_low
            high=int(blank[len(blank)//2]) if len(blank) else boundary
        band = mask[low:high]
        iy, ix = np.where(band > 0)
        if not len(ix):
            continue
        bx0, bx1 = max(0, int(ix.min())-round(spacing)), min(w, int(ix.max())+round(spacing)+1)
        by0, by1 = max(low, low+int(iy.min())-round(spacing)), min(high, low+int(iy.max())+round(spacing)+1)
        box = [x+bx0,y+by0,x+bx1,y+by1]
        region = {'kind':'system', 'bbox':box, 'staff_top': y+top-box[1],
            'staff_spacing':spacing, 'bar_range':None,
            'evidence': {'five_lines': [y+line for line in detected_lines[top]],
                'paper_bbox':[x,y,x+w,y+h], 'spacing_margin':spacing,
                'staff_left': x+left, 'staff_right': x+right,
                'associated_horizontal_lines': [y+line for line in associated[top]]}}
        regions.append(region)
        if (np.any(band[0]) or np.any(band[-1]) or ix.min()<spacing or ix.max()>w-1-spacing or
                (low==0 and iy.min()<spacing) or (high==h and iy.max()>h-low-1-spacing)):
            risks.append({'code':'crop_edge', 'bbox':box})
        # A bright occluder can erase several staff lines simultaneously.
        present=[]
        for line_y in (round(top+n*spacing) for n in range(5)):
            present.append(np.any(mask[max(0,line_y-2):min(h,line_y+3)]>0,axis=0))
        missing=np.flatnonzero(np.stack(present).sum(axis=0)[left:right+1]<=2)+left
        gaps=np.split(missing,np.where(np.diff(missing)>1)[0]+1)
        for gap in gaps:
            if len(gap)>spacing*2:
                risks.append({'code':'unreadable_music','bbox':[x+int(gap[0]),y+round(top-spacing),
                    x+int(gap[-1])+1,y+round(top+5*spacing)],'evidence':'simultaneous_staff_interruption'})
        # Detect large solid occluders inside the staff, not watermarks by name.
        dark = (band > 0).astype(np.uint8)
        # Strip thin connected staff lines before measuring solid rectangles;
        # otherwise a black occluder joins the whole staff and dilutes density.
        solid=cv2.morphologyEx(dark,cv2.MORPH_OPEN,
            np.ones((max(3,round(spacing*2)),max(3,round(spacing*3))),np.uint8))
        n, _, components, _ = cv2.connectedComponentsWithStats(solid)
        for cx,cy,cw,ch,ca in components[1:]:
            if (cw > spacing*3 and ch > spacing*2 and ca/(cw*ch) > .85 and
                    low+cy < top+4*spacing and low+cy+ch > top):
                risks.append({'code':'unreadable_music', 'bbox':[x+int(cx),y+low+int(cy),x+int(cx+cw),y+low+int(cy+ch)]})
    deferred = []
    for line in sorted(set(lines) - used):
        spacing = min(groups, key=lambda group: abs(group[0]-line))[1]
        if (not deferred or line+y-deferred[-1]['lines'][-1] > spacing*1.5 or
                line+y-deferred[-1]['lines'][0] > spacing*4.5):
            deferred.append({'code': 'partial_staff', 'lines': [], 'spacing': spacing,
                             'paper_bbox': [x,y,x+w,y+h]})
        deferred[-1]['lines'].append(y+line)
    for partial in deferred:
        columns = np.flatnonzero(np.any(horizontal[[v-y for v in partial['lines']]] > 0, axis=0))
        partial['bbox'] = [x+int(columns[0]), max(y, round(partial['lines'][0]-3*partial['spacing'])),
                           x+int(columns[-1])+1, min(y+h, round(partial['lines'][-1]+partial['spacing']))]
    return regions, risks, deferred


def signature(image):
    # Ignore bright playback highlights; preserve dark notation at native size.
    return geometry.ink_mask(image)


def playback_boxes(first, second):
    """Identify a narrow tall coloured trace in each original frame."""
    if first.size != second.size:
        return []
    boxes = []
    for image in (first, second):
        rgb = np.asarray(image.convert('RGB')).astype(np.int16)
        colour = (rgb.max(axis=2) - rgb.min(axis=2) > 45) & (rgb.min(axis=2) < 150)
        columns = np.flatnonzero(colour.sum(axis=0) >= 48)
        runs = [run for run in np.split(columns, np.where(np.diff(columns) > 1)[0] + 1) if len(run)]
        traces = []
        for run in runs:
            rows = np.flatnonzero(colour[:, run].any(axis=1))
            if (len(run) <= max(2, image.width * .005) and len(rows) >= 48 and
                    np.ptp(rows) >= 64 and len(rows) >= np.ptp(rows) * .7):
                traces.append((int(run[0]), int(rows[0]), int(run[-1]) + 1, int(rows[-1]) + 1))
        if len(traces) > 1:
            return []
        boxes.append(traces[0] if traces else None)
    if boxes[0] == boxes[1]:
        return []
    return boxes


def same_observation(first, second):
    """Ignore moving cursor bounds while preserving every outside ink change."""
    left, right = signature(first), signature(second)
    if same_ink(left, right):
        return True
    boxes = playback_boxes(first, second)
    if not boxes or any(box is None for box in boxes):
        return False
    left, right = left.copy(), right.copy()
    for x0, y0, x1, y1 in boxes:
        margin = max(2, math.ceil((x1-x0)/2))
        left[max(0, y0-margin):y1+margin, max(0, x0-margin):x1+margin] = 0
        right[max(0, y0-margin):y1+margin, max(0, x0-margin):x1+margin] = 0
    return same_ink(left, right)


def same_row(first, old, second, new, spacing):
    left = row_signature(first, old, spacing=spacing)
    right = row_signature(second, new, spacing=spacing)
    if same_ink(left, right):
        return True
    boxes = playback_boxes(first, second)
    for row, box in zip((old, new), boxes or (None, None)):
        if box is None:
            continue
        x0, y0, x1, y1 = box
        if not (y0 < row['bbox'][3] and y1 > row['bbox'][1]):
            continue
        top = row['bbox'][1]+row['staff_top']
        if y0 > top-spacing or y1 < top+5*spacing:
            return False
        origin = round(top)-8*spacing
        margin = max(2, math.ceil((x1-x0)/2))
        low, high = max(0, y0-origin-margin), min(left.shape[0], y1-origin+margin)
        left[low:high, max(0, x0-margin):x1+margin] = 0
        right[low:high, max(0, x0-margin):x1+margin] = 0
    if same_ink(left, right):
        return True
    def clipped(row):
        paper = row['evidence']['paper_bbox']
        return row['bbox'][1] <= paper[1]+row['staff_spacing'] or row['bbox'][3] >= paper[3]-row['staff_spacing']
    kernel = np.ones((3, 3), np.uint8)
    if clipped(old) and not clipped(new):
        return not np.any((left > 0) & (cv2.dilate(right, kernel) == 0))
    if clipped(new) and not clipped(old):
        return not np.any((right > 0) & (cv2.dilate(left, kernel) == 0))
    return False


def same_ink(a,b):
    if a.shape != b.shape:
        return False
    difference=cv2.absdiff(a,b)>32
    if not np.any(difference):
        return True
    # Raster edges may shift one pixel under lossy encoding. Added isolated ink
    # has no opposing source ink nearby and receives no minimum-size tolerance.
    foreground_a=(a>96).astype(np.uint8)
    foreground_b=(b>96).astype(np.uint8)
    kernel=np.ones((3,3),np.uint8)
    unmatched=((foreground_a>0)&(cv2.dilate(foreground_b,kernel)==0)) | ((foreground_b>0)&(cv2.dilate(foreground_a,kernel)==0))
    if not np.any(unmatched):
        return True
    # Two narrow tall displaced traces identify a moving playback cursor by
    # geometry. A lone small mark or an ordinary symbol edit is not a cursor.
    for traces in (difference, unmatched):
        columns = np.flatnonzero(traces.sum(axis=0) > 0)
        runs = np.split(columns, np.where(np.diff(columns) > 1)[0] + 1)
        if len(runs) != 2 or any(len(run) > max(2, a.shape[1] * .005) for run in runs):
            continue
        extents = [np.flatnonzero(traces[:, run].any(axis=1)) for run in runs]
        tolerance = max(2, max(map(len, runs)))
        if (all(len(rows) >= 48 and np.ptp(rows) >= 64 and
                len(rows) >= np.ptp(rows) * .7 for rows in extents) and
                abs(extents[0][0] - extents[1][0]) <= tolerance and
                abs(extents[0][-1] - extents[1][-1]) <= tolerance):
            return True
    # Overlapping cursor positions can merge into one difference run. Require
    # both a removed and an added tall trace, and retain every unmatched pixel
    # outside their narrow bounds, including isolated notation changes.
    boxes = []
    for trace in ((foreground_a > 0) & (foreground_b == 0),
                  (foreground_b > 0) & (foreground_a == 0)):
        columns = np.flatnonzero(trace.sum(axis=0) >= 48)
        if not len(columns) or np.ptp(columns) + 1 > max(2, a.shape[1] * .01):
            break
        rows = np.flatnonzero(trace[:, columns].any(axis=1))
        if np.ptp(rows) < 64 or len(rows) < np.ptp(rows) * .7:
            break
        boxes.append((int(columns[0]), int(rows[0]), int(columns[-1]), int(rows[-1])))
    if len(boxes) == 2 and all(abs(boxes[0][i] - boxes[1][i]) <= 2 for i in (1, 3)):
        residual = unmatched.copy()
        for left, top, right, bottom in boxes:
            residual[max(0, top - 1):bottom + 2, max(0, left - 1):right + 2] = False
        if not np.any(residual):
            return True
    return False


def row_signature(image, region, *, core=False, spacing=None):
    x0,y0,x1,y1=region['bbox']
    top=round(y0+region['staff_top'])
    spacing=round(region['staff_spacing']) if spacing is None else spacing
    low=top if core else top-8*spacing
    high=top+(5 if core else 10)*spacing
    canvas=Image.new('RGB',(image.width,high-low),'white')
    source_low=max(y0,low,0)
    source_high=min(y1,high,image.height)
    if source_low<source_high:
        canvas.paste(image.crop((x0,source_low,x1,source_high)),(x0,source_low-low))
    return geometry.ink_mask(canvas)


def native_visible_match(old, new, native, *, preserve_missing=False):
    shift=round(new['bbox'][1]+new['staff_top']-old['bbox'][1]-old['staff_top'])
    left=native(old['capture'])
    right=native(new['capture'])
    # Compare the union of both detected bands within the visible frames.
    # Intersection alone would silently discard an added off-staff mark that
    # expands the new crop beyond the old crop. The old full native frame also
    # proves whether apparent new ink is a previously visible moving header.
    x0=max(0,min(old['bbox'][0],new['bbox'][0]))
    x1=min(left.shape[1],right.shape[1],max(old['bbox'][2],new['bbox'][2]))
    y0=max(min(old['bbox'][1],new['bbox'][1]-shift),0,-shift)
    y1=min(max(old['bbox'][3],new['bbox'][3]-shift),left.shape[0],right.shape[0]-shift)
    if x1<=x0 or y1<=y0:
        return False
    first=left[y0:y1,x0:x1]
    second=right[y0+shift:y1+shift,x0:x1]
    if same_ink(first,second):
        return True
    kernel=np.ones((3,3),np.uint8)
    old_unmatched=(first>0)&(cv2.dilate(right,kernel)[y0+shift:y1+shift,x0:x1]==0)
    new_unmatched=(second>0)&(cv2.dilate(left,kernel)[y0:y1,x0:x1]==0)
    if not np.any(old_unmatched) and not np.any(new_unmatched):
        return True
    if preserve_missing and not np.any(new_unmatched):
        return True
    def clipped(row):
        paper=row['evidence']['paper_bbox']
        box=row['bbox']
        spacing=row['staff_spacing']
        return box[1]<=paper[1]+spacing or box[3]>=paper[3]-spacing
    # A viewport fragment can lose formerly visible ink. It must introduce no
    # ink absent from the complete source; tiny additions have no tolerance.
    if clipped(new) and not clipped(old):
        return not np.any(new_unmatched)
    if clipped(old) and not clipped(new):
        return not np.any(old_unmatched)
    return False


def spatial_continuation(old_rows, new_rows, old_cores, new_cores, native):
    """Require two independent unchanged native rows for a unique scroll shift.

    Zero displacement cannot explain changed music. Only the common visible
    native patches are compared for scrolling viewport fragments; unchanged
    staff bodies alone never erase a changed off-staff mark.
    """
    anchors=[]
    for i,old in enumerate(old_rows):
        for j,new in enumerate(new_rows):
            shift=round(new['bbox'][1]+new['staff_top']-old['bbox'][1]-old['staff_top'])
            if abs(shift)>2 and same_ink(old_cores[i],new_cores[j]) and native_visible_match(old,new,native):
                anchors.append((i,j,shift))
    supported=[]
    for shift in sorted({item[2] for item in anchors}):
        matches=[item for item in anchors if abs(item[2]-shift)<=2]
        if len({m[0] for m in matches})>=2 and len({m[1] for m in matches})>=2:
            if not supported or abs(shift-supported[-1])>2:
                supported.append(shift)
    if len(supported)!=1:
        return {}
    shift=supported[0]
    mapping={}
    for j,new in enumerate(new_rows):
        possible=[]
        for i,old in enumerate(old_rows):
            actual=round(new['bbox'][1]+new['staff_top']-old['bbox'][1]-old['staff_top'])
            if abs(actual-shift)<=2 and native_visible_match(old,new,native,preserve_missing=True):
                possible.append(i)
        if len(possible)==1:
            mapping[j]=possible[0]
    return mapping

