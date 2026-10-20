"""Vertical stitching and whole-system cuts; no sample-specific pixel cleanup.

Uses row-profile correlation and temporal medians, as in the user-provided
longshot tool. Original frames, derived longshots and actual views stay separate.
"""
import json
import math
from pathlib import Path
import uuid

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageChops

import score_task
from score_task import ReconstructionError, digest, load, save, write_path
from video_seek import VideoReader

WORKFLOW = 'longshot/1'
NOTICE = '近似重绘，局部符号可能含模型推测，未经逐符号校对。'
ORIGINAL_NOTICE = '原图直排，未经逐符号校对；长截图可能保留拼接、模糊或遮挡问题。'
VECTOR_NOTICE = '轮廓转描只保留可见外形，不能恢复被遮挡记谱，未经逐符号校对。'
PROMPT = ('将输入鼓谱清理重绘为白底黑色可打印谱面，去掉播放高亮和水印。'
          '保持标题、首尾、全部谱行数量和顺序，不增删整小节或整行，不改写整段音乐。'
          '允许根据可见上下文推测模糊或遮挡的局部符号。保持每行布局和比例，'
          '保留反复、休止、速度、拍号及行外记号，不加入装饰和说明文字。')


def is_longshot(record):
    return record.get('workflow') == WORKFLOW and bool(record.get('longshot'))


def _profile(gray):
    width = gray.shape[1]
    values = (gray[:, width // 20:width - width // 20:3] < 145).sum(axis=1).astype(np.float32)
    return (cv2.GaussianBlur(values[:, None], (1, 0), 1).ravel() -
            cv2.GaussianBlur(values[:, None], (1, 0), 24).ravel())


def _shift(previous, current, maximum, previous_ink, current_ink):
    correlation = np.correlate(previous, current, mode='full')
    scores = correlation[len(previous) - 1:len(previous) + maximum]
    # Normalize the actual overlap. Otherwise an unshifted pair of similar
    # five-line systems wins merely because it contains more staff pixels.
    old_energy = np.cumsum((previous * previous)[::-1])[::-1][:maximum + 1]
    new_energy = np.cumsum(current * current)[len(current) - 1 - np.arange(maximum + 1)]
    scores = scores / np.maximum(np.sqrt(old_energy * new_energy), 1e-9)
    peaks = np.flatnonzero((scores >= np.r_[-np.inf, scores[:-1]]) &
                           (scores >= np.r_[scores[1:], -np.inf]))
    # Repeated five-line profiles can offer nearly equal peaks. Compare visible
    # notation in two dimensions to distinguish an actual overlap from a
    # different system with similar row density. Ties prefer less movement.
    candidates = peaks[scores[peaks] >= scores.max() - .01]
    offset, best = int(candidates[0]), -1.
    for candidate in candidates:
        a = previous_ink[candidate:]
        b = current_ink[:len(current_ink) - candidate]
        similarity = np.count_nonzero(a & b) / max(1, np.count_nonzero(a | b))
        if similarity > best + .0001:
            offset, best = int(candidate), similarity
    confidence = float(scores[offset])
    return offset, confidence


def _runs(indices):
    return np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1) if len(indices) else []


def system_boxes(image):
    """Find staff systems, splitting only in visible whitespace between them."""
    gray = np.asarray(image.convert('L'))
    height, width = gray.shape
    mask = (gray < 225).astype(np.uint8)
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                 np.ones((1, max(20, width // 3)), np.uint8))
    bands = _runs(np.flatnonzero(horizontal.sum(axis=1) > width * .4))
    lines = [float(b.mean()) for b in bands if len(b) <= 6]
    staffs, index = [], 0
    while index + 4 < len(lines):
        gaps = np.diff(lines[index:index + 5])
        spacing = float(np.median(gaps))
        if 2 <= spacing <= 40 and np.max(np.abs(gaps - spacing)) <= max(1, spacing * .2):
            staffs.append((lines[index], spacing))
            index += 5
        else:
            index += 1
    if not staffs:
        raise ReconstructionError('长图中未找到五线谱；检查来源布局和长图。', code='longshot_no_systems')
    counts = (gray < 165).sum(axis=1)
    splits, groups = [0], [staffs[0]]
    for previous, current in zip(staffs, staffs[1:]):
        start = min(height, math.ceil(previous[0] + previous[1] * 5))
        end = max(start, math.floor(current[0] - current[1]))
        blanks = _runs(np.flatnonzero(counts[start:end] <= max(1, width // 500)))
        if blanks:
            gap = max(blanks, key=len)
            splits.append(start + int(gap[len(gap) // 2]))
            groups.append(current)
        # Interleaved notation stays in one continuous group.
    splits.append(height)
    return [{'bbox': [0, top, width, bottom], 'kind': 'system',
             'staff_top': staff[0] - top, 'staff_spacing': staff[1],
             'staves': [{'top': y - top, 'spacing': spacing} for y, spacing in staffs if top <= y < bottom]}
            for top, bottom, staff in zip(splits, splits[1:], groups)]


def _compact_breaks(regions, gray, scale, capacity, baseline):
    """Reduce page count within 10%, keeping at least four PDF points per space.

    Only existing blank system boundaries are candidates. Greedy feasibility
    plus integer bisection minimizes the tallest strip at the reduced count.
    These geometric candidates still require visual notation-ownership review.
    """
    spacings = [staff['spacing'] for row in regions
                for staff in row.get('staves', [{'spacing': row.get('staff_spacing', 0)}])]
    if not spacings or min(spacings) <= 0 or not baseline:
        return baseline, scale
    lower_scale = max(scale * .9, 4 / min(spacings))
    if lower_scale >= scale:
        return baseline, scale
    ends = [row['bbox'][3] for row in regions[:-1]
            if not np.any(gray[row['bbox'][3] - 1:row['bbox'][3] + 2] < 165)]
    ends.append(len(gray))

    def split(limit):
        cuts, top, previous = [], 0, 0
        for end in ends:
            if end - top > limit:
                if previous == top or end - previous > limit:
                    return None
                cuts.append(previous)
                top = previous
            previous = end
        return cuts

    upper = math.floor(capacity * scale / lower_scale + 1e-8)
    cuts = split(upper)
    if cuts is None or len(cuts) >= len(baseline):
        return baseline, scale
    target = len(cuts)
    low = math.ceil(len(gray) / (target + 1))
    while low < upper:
        middle = (low + upper) // 2
        candidate = split(middle)
        if candidate is not None and len(candidate) <= target:
            upper = middle
        else:
            low = middle + 1
    cuts = split(upper)
    return cuts, min(scale, capacity * scale / upper)


def _continuous_pages(task, record, margin=24, page_breaks=None):
    """Keep page interiors continuous; blank cuts remain visual candidates."""
    from reportlab.lib.pagesizes import A4
    from reconstruction import paginate
    source = record.get('watermark_cleanup', {}).get('image', record['longshot']['image'])
    regions = record['regions']
    width, height = source['width'], source['height']
    scale = base_scale = (A4[0] - 2 * margin) / width
    capacity = (A4[1] - 2 * margin) / scale
    automatic = page_breaks is None
    if automatic:
        # Reuse complete-unit balancing, then discard its artificial row gaps.
        placements, _ = paginate(regions, margin=margin, minimum_gap=0)
        page_breaks = [regions[a['region']]['bbox'][3] for a, b in zip(placements, placements[1:])
                       if a['page'] != b['page']]
    if (not isinstance(page_breaks, list) or len(page_breaks) > 511 or
            any(type(y) is not int or not 0 < y < height for y in page_breaks) or
            page_breaks != sorted(set(page_breaks))):
        raise ReconstructionError('分页切口需要按顺序、不重复的长图整数纵坐标。',
                                  code='invalid_request', field='page_breaks')
    with Image.open(score_task.artifact(task, source)) as image:
        gray = np.asarray(image.convert('L'))
        if automatic:
            page_breaks, scale = _compact_breaks(regions, gray, scale, capacity, page_breaks)
        for cut in page_breaks:
            # A geometric guard, not a claim about which staff owns a mark.
            if np.any(gray[max(0, cut - 1):min(height, cut + 2)] < 165):
                raise ReconstructionError('分页切口穿过可见记号；移到空隙并实际查看两侧。',
                                          code='invalid_request', field='page_breaks')
    bounds = [0, *page_breaks, height]
    capacity = (A4[1] - 2 * margin) / scale
    if any(bottom - top > capacity + .00001 for top, bottom in zip(bounds, bounds[1:])):
        raise ReconstructionError('连续谱面超出可打印高度；增加安全切口或调整边距。',
                                  code='invalid_request', field='page_breaks', action='layout')
    strips, placements = [], []
    for index, (top, bottom) in enumerate(zip(bounds, bounds[1:])):
        # Navigation crops are not semantic ownership boundaries. Assign them
        # by their staff anchor while pixel coverage is checked independently.
        indices = [i for i, row in enumerate(regions)
                   if top <= row['bbox'][1] + row.get('staff_top', 0) < bottom]
        for i in indices:
            row = regions[i]
            for staff in row.get('staves', [{'top': row.get('staff_top', 0), 'spacing': row.get('staff_spacing', 0)}]):
                y = row['bbox'][1] + staff['top']
                if not top <= y or y + 4 * staff['spacing'] >= bottom:
                    raise ReconstructionError('分页切口不能拆开五线组或连续行组。',
                                              code='invalid_request', field='page_breaks')
        if not indices:
            raise ReconstructionError('分页不能产生没有谱行的空白页。', code='invalid_request', field='page_breaks')
        box = [0, top, width, bottom]
        strips.append({'kind': 'continuous_page', 'width': width, 'height': bottom - top,
                       'image': source, 'crop_bbox': box, 'source_regions': indices})
        left = margin if scale == base_scale else (A4[0] - width * scale) / 2
        placements.append({'page': index + 1, 'region': index, 'scale': scale,
                           'bbox': [left, A4[1] - margin - (bottom - top) * scale,
                                    left + width * scale, A4[1] - margin]})
    return strips, placements


def redraw_boxes(image, originals):
    """Keep input groups when removing a marker opens a gap between staffs."""
    rows = system_boxes(image)
    if len(rows) == len(originals):
        return [row['bbox'] for row in rows]
    boxes, cursor = [], 0
    for original in originals:
        start, count = cursor, 0
        expected = len(original.get('staves', [])) or 1
        while cursor < len(rows) and count < expected:
            count += len(rows[cursor]['staves'])
            cursor += 1
        if count != expected:
            break
        boxes.append([0, rows[start]['bbox'][1], image.width, rows[cursor - 1]['bbox'][3]])
    if len(boxes) != len(originals) or cursor != len(rows):
        raise ReconstructionError('生成图谱行数量发生变化；定向修正一次或转矢量。',
                                  code='redraw_row_count', action='review-redraw accepted=false or fail-redraw')
    return boxes


class _Composer:
    def __init__(self, width, height, max_jump):
        self.width, self.height, self.max_jump = width, height, min(max_jump, height - 1)
        self.ink = np.zeros((height, width), np.uint32)
        self.counts = np.zeros(height, np.uint32)
        self.offset = self.extent = 0
        self.previous = self.previous_ink = None
        self.frames, self.group_size, self.samples = [], 0, []
        self.max_frames = max(1, min(13, 40_000_000 // (width * height)))
        self.first = self.last = None

    def flush(self):
        if not self.frames:
            return
        end = self.offset + self.height
        if end * self.width > 80_000_000:
            raise ReconstructionError('长截图超出像素资源限制。', code='resource_limit')
        if end > len(self.ink):
            capacity = max(end, min(len(self.ink) * 2, 80_000_000 // self.width))
            expanded = np.zeros((capacity, self.width), np.uint32)
            expanded[:len(self.ink)] = self.ink
            self.ink = expanded
            self.counts = np.pad(self.counts, (0, capacity - len(self.counts)))
        median = np.median(np.stack(self.frames), axis=0).astype(np.uint8)
        self.ink[self.offset:end] += 255 - median
        self.counts[self.offset:end] += 1
        self.extent = max(self.extent, end)
        self.frames, self.group_size = [], 0

    def add(self, index, image):
        gray = np.asarray(image.convert('L'))
        profile = _profile(gray)
        ink = gray[:, ::3] < 145
        empty = not np.any(profile) or np.count_nonzero(gray > 200) < gray.size // 4
        delta, confidence = ((0, 0.) if empty else
                             (0, 1.) if self.previous is None else
                             _shift(self.previous, profile, self.max_jump, self.previous_ink, ink))
        if delta:
            self.flush()
            self.offset += delta
        self.samples.append({'displacement': self.offset, 'delta': delta, 'confidence': round(confidence, 4)})
        if self.first is None:
            self.first = image.copy()
        if self.last is not None:
            self.last.close()
        self.last = image.copy()
        if empty:
            return
        self.previous = profile
        self.previous_ink = ink
        if len(self.frames) < self.max_frames:
            self.frames.append(gray)
        else:
            self.frames[self.group_size % self.max_frames] = gray
        self.group_size += 1

    def image(self):
        self.flush()
        if not self.extent:
            raise ReconstructionError('视频没有可合成的谱面。', code='longshot_no_systems')
        result = np.empty((self.extent, self.width), np.uint8)
        for start in range(0, self.extent, 512):
            end = min(start + 512, self.extent)
            result[start:end] = 255 - (self.ink[start:end] /
                                      np.maximum(self.counts[start:end, None], 1)).astype(np.uint8)
        return Image.fromarray(result)

    def close(self):
        for image in (self.first, self.last):
            if image is not None:
                image.close()


def _publish_image(task, directory, image, source_sha256):
    boxes = system_boxes(image)
    image_path = directory / 'score.png'
    image.save(image_path)
    regions = []
    for index, box in enumerate(boxes):
        path = directory / f'row-{index + 1:04d}.png'
        with image.crop(box['bbox']) as crop:
            crop.save(path)
            regions.append({**box, 'path': str(path.relative_to(task)), 'sha256': digest(path),
                            'width': crop.width, 'height': crop.height,
                            'position': f"longshot:{box['bbox'][1]}:{box['bbox'][3]}",
                            'source_kind': 'longshot', 'source_sha256': source_sha256})
    reference = {'path': str(image_path.relative_to(task)), 'sha256': digest(image_path),
                 'width': image.width, 'height': image.height}
    return reference, regions


def _retire_longshot(record):
    score_task.invalidate_selection(record)
    if record.get('longshot'):
        record.setdefault('longshot_history', []).append(record['longshot'])
    if record.get('watermark_cleanup'):
        record.setdefault('watermark_cleanup_history', []).append(record.pop('watermark_cleanup'))
    for key in ('agent_review_contract', 'freeze', 'source_review'):
        record.pop(key, None)


def stitch(task, interval=1., max_jump=400):
    """Publish versioned longshot and row crops, without registering a view."""
    if type(interval) not in (int, float) or not math.isfinite(interval) or interval <= 0 or type(max_jump) is not int or max_jump < 1:
        raise ReconstructionError('采样间隔和最大位移无效。', code='invalid_request')
    record = load(task)
    if any(page['status'] == 'calling' for page in record.get('redraw_pages', [])):
        raise ReconstructionError('先恢复已有生图调用，再重新拼接。')
    source = record['source']
    directory = write_path(task, Path('longshot') / uuid.uuid4().hex)
    directory.mkdir(parents=True)
    composer = _Composer(source['width'], source['height'], max_jump)
    reader = VideoReader(source['path'], source, record['metrics'])
    try:
        samples = reader.sample_records(interval, composer.add)
        tail, image = reader.read_record(None)
        try:
            if tail['pts'] != samples[-1]['pts'] or tail['time_base'] != samples[-1]['time_base']:
                composer.add(len(samples), image)
                samples.append(tail)
        finally:
            image.close()
        samples = [{**sample, **motion} for sample, motion in zip(samples, composer.samples)]
        with composer.image() as image:
            reference, regions = _publish_image(task, directory, image, source['sha256'])
        sample_path = directory / 'samples.json'
        sample_path.write_text(json.dumps(samples, ensure_ascii=False), encoding='utf-8')
        endpoints = []
        for name, image, sample in (('first', composer.first, samples[0]), ('last', composer.last, samples[-1])):
            path = directory / f'{name}.png'
            image.save(path)
            endpoints.append({'path': str(path.relative_to(task)), 'sha256': digest(path),
                              **{k: sample[k] for k in ('pts', 'time_base', 'timestamp')}})
        _retire_longshot(record)
        record.update(workflow=WORKFLOW, regions=regions, rough=reference, rough_chunks=[reference],
                      status='needs_longshot_review', longshot={'image': reference,
                      'samples': {'path': str(sample_path.relative_to(task)), 'sha256': digest(sample_path)},
                      'endpoints': endpoints, 'system_count': len(regions), 'interval': interval,
                      'max_jump': max_jump, 'review': None,
                      'warnings': [{'code': 'low_alignment_confidence', 'timestamp': s['timestamp']}
                                   for s in samples if s['confidence'] < .48]})
        save(task, record)
        return record['longshot']
    except Exception:
        # A failed retry still consumes the task's cumulative decode budget.
        # Keep its last valid selection and outputs rather than partial materials.
        previous = load(task)
        previous['metrics'] = record['metrics']
        save(task, previous)
        raise
    finally:
        reader.close()
        composer.close()


def review_longshot(task, title, notes, accepted=True):
    record = load(task)
    if not is_longshot(record) or not isinstance(title, str) or not title.strip() or not isinstance(notes, str) or not notes.strip() or type(accepted) is not bool:
        raise ReconstructionError('需要长截图、谱名和整体查看记录。', code='invalid_request')
    if not accepted or record.get('title') != title.strip():
        score_task.invalidate_output(record, 'overall_longshot_review')
    record['longshot']['review'] = {'accepted': accepted, 'notes': notes}
    record.update(title=title.strip(), source_review={'complete': accepted, 'notes': notes,
                  'producer': 'agent_overall_longshot', 'unresolved': [] if accepted else [notes]},
                  status='ready_to_redraw' if accepted else 'needs_longshot_review')
    score_task.freeze(record, 'longshot')
    save(task, record)
    return record


def clean_watermark(task, rectangles, source_sha256, notes, confirmed_safe):
    """Whiten only Agent-reviewed empty areas; preserve the unmodified longshot."""
    record = load(task)
    score_task.require_frozen(record)
    if (not is_longshot(record) or score_task.delivery_route(record) != 'original' or
            not isinstance(notes, str) or not notes.strip() or confirmed_safe is not True or
            source_sha256 != record['longshot']['image']['sha256'] or
            not isinstance(rectangles, list) or len(rectangles) > 128):
        raise ReconstructionError('需要当前长图及不含记谱、标题和署名的安全区域确认。',
                                  code='invalid_request', field='rectangles/source_sha256/confirmed_safe')
    source = record['longshot']['image']
    for box in rectangles:
        if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box) or
                not 0 <= box[0] < box[2] <= source['width'] or
                not 0 <= box[1] < box[3] <= source['height']):
            raise ReconstructionError('清理矩形必须位于当前长图内。', code='invalid_request', field='rectangles')
    previous = record.get('watermark_cleanup')
    if previous and previous['rectangles'] == rectangles:
        return previous
    if not rectangles:
        if previous:
            record.setdefault('watermark_cleanup_history', []).append(record.pop('watermark_cleanup'))
            score_task.invalidate_output(record, 'watermark_cleanup_revision')
            score_task.freeze(record, 'longshot')
            save(task, record)
        return {'image': source, 'rectangles': [], 'outside_unchanged': True}
    directory = write_path(task, Path('longshot') / uuid.uuid4().hex)
    directory.mkdir(parents=True)
    path = directory / 'cleaned.png'
    with Image.open(score_task.artifact(task, source)) as before:
        after = before.copy()
        try:
            drawing = ImageDraw.Draw(after)
            for left, top, right, bottom in rectangles:
                drawing.rectangle((left, top, right - 1, bottom - 1), fill='white')
            with ImageChops.difference(before, after) as difference:
                for box in rectangles:
                    difference.paste(0, tuple(box))
                if difference.getbbox() is not None:
                    raise ReconstructionError('清理修改了选区外像素，停止发布。')
            after.save(path)
        finally:
            after.close()
    cleaned = {'source': source, 'image': {'path': str(path.relative_to(task)), 'sha256': digest(path),
               'width': source['width'], 'height': source['height']},
               'rectangles': rectangles, 'notes': notes, 'confirmed_safe': True,
               'outside_unchanged': True, 'safety_producer': 'agent_visual_review'}
    if previous:
        record.setdefault('watermark_cleanup_history', []).append(previous)
    record['watermark_cleanup'] = cleaned
    score_task.invalidate_output(record, 'watermark_cleanup_revision')
    score_task.freeze(record, 'longshot')
    save(task, record)
    return cleaned


def repair_longshot(task, capture, bbox, target_bbox, source_sha256, notes):
    """Replace a local obstruction with same-size pixels from a decoded frame."""
    record = load(task)
    if (not is_longshot(record) or not isinstance(notes, str) or not notes.strip() or
            source_sha256 != record['longshot']['image']['sha256']):
        raise ReconstructionError('需要当前长图与实际补采说明。', code='invalid_request')
    if any(page['status'] == 'calling' for page in record.get('redraw_pages', [])):
        raise ReconstructionError('先恢复已有生图调用，再修复来源。')
    shot = next((item for item in record['captures'] if item['id'] == capture), None)
    source = record['longshot']['image']
    if shot is None:
        raise ReconstructionError('补采引用无效。', code='invalid_request', field='capture')
    for box, width, height in ((bbox, shot['width'], shot['height']),
                               (target_bbox, source['width'], source['height'])):
        if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box) or
                not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height):
            raise ReconstructionError('修复区域越界。', code='invalid_request', field='bbox/target_bbox')
    if (bbox[2] - bbox[0], bbox[3] - bbox[1]) != (target_bbox[2] - target_bbox[0], target_bbox[3] - target_bbox[1]):
        raise ReconstructionError('局部补采保持原比例，需要相同尺寸的区域。', code='invalid_request')
    directory = write_path(task, Path('longshot') / uuid.uuid4().hex)
    directory.mkdir(parents=True)
    with Image.open(score_task.artifact(task, source)) as before, Image.open(score_task.artifact(task, shot)) as frame:
        after = before.copy()
        patch = frame.crop(bbox).convert(before.mode)
        try:
            after.paste(patch, (target_bbox[0], target_bbox[1]))
            reference, regions = _publish_image(task, directory, after, record['source']['sha256'])
        finally:
            patch.close()
            after.close()
    previous = record['longshot']
    _retire_longshot(record)
    repaired = {**previous, 'image': reference, 'system_count': len(regions), 'review': None,
                'repairs': [*previous.get('repairs', []), {'before': source, 'source': shot,
                'bbox': bbox, 'target_bbox': target_bbox, 'notes': notes}]}
    record.update(regions=regions, rough=reference, rough_chunks=[reference],
                  status='needs_longshot_review', longshot=repaired)
    save(task, record)
    return repaired


def handoff(record):
    rejected = bool(record['longshot'].get('review'))
    return {'phase': 'longshot_review', 'status': 'blocked' if rejected else 'pending',
            'artifacts': {'longshot': record['longshot']},
            'next': {'operation': 'stitch' if rejected else 'review-longshot',
                     'required_fields': [] if rejected else ['title', 'notes'],
                     'instruction': '整体查看长图和首尾。检查明显漏行、重复、裁断；蓝标、水印和局部模糊不阻塞。'}}
