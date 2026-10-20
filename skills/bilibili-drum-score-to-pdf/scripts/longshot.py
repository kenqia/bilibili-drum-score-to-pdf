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
from PIL import Image

import score_task
from score_task import ReconstructionError, digest, load, save, write_path
from video_seek import VideoReader

WORKFLOW = 'longshot/1'
NOTICE = '近似重绘，局部符号可能含模型推测，未经逐符号校对。'
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


def _shift(previous, current, maximum):
    correlation = np.correlate(previous, current, mode='full')
    scores = correlation[len(previous) - 1:len(previous) + maximum]
    # Normalize the actual overlap. Otherwise an unshifted pair of similar
    # five-line systems wins merely because it contains more staff pixels.
    old_energy = np.cumsum((previous * previous)[::-1])[::-1][:maximum + 1]
    new_energy = np.cumsum(current * current)[len(current) - 1 - np.arange(maximum + 1)]
    scores = scores / np.maximum(np.sqrt(old_energy * new_energy), 1e-9)
    offset = int(np.argmax(scores))
    confidence = float(scores[offset])
    return offset, confidence


def _runs(indices):
    return np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1) if len(indices) else []


def system_boxes(image):
    """Find staff systems, splitting only in visible whitespace between them."""
    gray = np.asarray(image.convert('L'))
    height, width = gray.shape
    mask = (gray < 180).astype(np.uint8)
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
             'staff_top': staff[0] - top, 'staff_spacing': staff[1]}
            for top, bottom, staff in zip(splits, splits[1:], groups)]


class _Composer:
    def __init__(self, width, height, max_jump):
        self.width, self.height, self.max_jump = width, height, min(max_jump, height - 1)
        self.ink = np.zeros((height, width), np.uint32)
        self.counts = np.zeros(height, np.uint32)
        self.offset = self.extent = 0
        self.previous = None
        self.frames, self.group_size, self.samples = [], 0, []
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
        delta, confidence = (0, 1.) if self.previous is None else _shift(self.previous, profile, self.max_jump)
        if delta:
            self.flush()
            self.offset += delta
        self.samples.append({'displacement': self.offset, 'delta': delta, 'confidence': round(confidence, 4)})
        self.previous = profile
        if self.first is None:
            self.first = image.copy()
        if self.last is not None:
            self.last.close()
        self.last = image.copy()
        if len(self.frames) < 13:
            self.frames.append(gray)
        else:
            self.frames[self.group_size % 13] = gray
        self.group_size += 1

    def image(self):
        self.flush()
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
                                    'source_kind': 'longshot', 'source_sha256': source['sha256']})
            reference = {'path': str(image_path.relative_to(task)), 'sha256': digest(image_path),
                         'width': image.width, 'height': image.height}
        sample_path = directory / 'samples.json'
        sample_path.write_text(json.dumps(samples, ensure_ascii=False), encoding='utf-8')
        endpoints = []
        for name, image, sample in (('first', composer.first, samples[0]), ('last', composer.last, samples[-1])):
            path = directory / f'{name}.png'
            image.save(path)
            endpoints.append({'path': str(path.relative_to(task)), 'sha256': digest(path),
                              **{k: sample[k] for k in ('pts', 'time_base', 'timestamp')}})
        score_task.invalidate_selection(record)
        record.pop('agent_review_contract', None)
        record.pop('freeze', None)
        record.pop('source_review', None)
        record.update(workflow=WORKFLOW, regions=regions, rough=reference, rough_chunks=[reference],
                      status='needs_longshot_review', longshot={'image': reference,
                      'samples': {'path': str(sample_path.relative_to(task)), 'sha256': digest(sample_path)},
                      'endpoints': endpoints, 'system_count': len(regions), 'interval': interval,
                      'max_jump': max_jump, 'review': None,
                      'warnings': [{'code': 'low_alignment_confidence', 'timestamp': s['timestamp']}
                                   for s in samples if s['confidence'] < .48]})
        save(task, record)
        return record['longshot']
    finally:
        reader.close()
        composer.close()


def review_longshot(task, title, notes, accepted=True):
    record = load(task)
    if not is_longshot(record) or not isinstance(title, str) or not title.strip() or not isinstance(notes, str) or not notes.strip() or type(accepted) is not bool:
        raise ReconstructionError('需要长截图、谱名和整体查看记录。', code='invalid_request')
    record['longshot']['review'] = {'accepted': accepted, 'notes': notes}
    record.update(title=title.strip(), source_review={'complete': accepted, 'notes': notes,
                  'producer': 'agent_overall_longshot', 'unresolved': [] if accepted else [notes]},
                  status='ready_to_redraw' if accepted else 'needs_longshot_review')
    score_task.freeze(record, 'longshot')
    save(task, record)
    return record


def handoff(record):
    return {'phase': 'longshot_review', 'status': 'blocked' if record['longshot'].get('review') else 'pending',
            'artifacts': {'longshot': record['longshot']},
            'next': {'operation': 'review-longshot', 'required_fields': ['title', 'notes'],
                     'instruction': '整体查看长图和首尾。检查明显漏行、重复、裁断；蓝标、水印和局部模糊不阻塞。'}}
