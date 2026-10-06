"""Recover an ordered score using only evidence between neighboring windows."""
import hashlib
from pathlib import Path
import tempfile

import cv2
import numpy as np
from PIL import Image
from drum_score import ConversionError, analyze_frame, sample_video


def comparison_mask(region, group):
    spacing = group['spacing']
    top = int(round(group['top'] - spacing * 3))
    bottom = int(round(group['bottom'] + spacing * 5))
    pixels = np.asarray(region.crop((0, top, region.width, bottom)).convert('RGB'))
    # Only a tall colored overlay is ignored in analysis. Colored notation
    # remains part of row identity, and printable source pixels stay untouched.
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    mask = gray < 180
    colored = np.ptp(pixels, axis=2) > 45
    cursor_columns = colored.sum(axis=0) > pixels.shape[0] * .65
    if cursor_columns.sum() < pixels.shape[1] * .12:
        mask &= ~(colored & cursor_columns[None, :])
    for line in range(5):
        y = int(round(group['top'] + line * spacing - top))
        mask[max(0, y - 2):y + 3] = False
    return mask


def same_row(left, right):
    a, b = left['mask'], right['mask']
    if abs(a.shape[0] - b.shape[0]) > 3 or abs(a.shape[1] - b.shape[1]) > 3:
        return False
    if a.shape != b.shape:
        b = cv2.resize(b.astype(np.uint8), (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    union = np.count_nonzero(a | b)
    return union > 30 and np.count_nonzero(a ^ b) / union < .08


def save_row(candidate, output, index):
    name = f'images/row-{index:04d}.png'
    candidate['image'].save(output / name)
    return {'id': f'row-{index:04d}', 'image': name, 'timestamp': candidate['timestamp'], 'bbox': candidate['bbox'], 'staff_top': candidate['staff_top'], 'staff_spacing': candidate['staff_spacing'], 'content_sha256': hashlib.sha256((output / name).read_bytes()).hexdigest()}


def window_rows(image, timestamp):
    analysis = analyze_frame(image, allow_partial=True)
    region = image.crop(analysis['bbox']).convert('RGB')
    bbox = analysis['bbox']
    rows = []
    for group, (top, bottom) in zip(analysis['groups'], analysis['row_bounds']):
        rows.append({'mask': comparison_mask(region, group), 'image': region.crop((0, top, region.width, bottom)), 'timestamp': timestamp, 'bbox': [bbox[0], bbox[1] + top, bbox[2], bbox[1] + bottom], 'staff_top': bbox[1] + group['top'], 'staff_spacing': group['spacing']})
    return analysis, region, rows


def restore_rows(source, output, metadata, decisions=None):
    output = Path(output)
    (output / 'images').mkdir(parents=True, exist_ok=True)
    (output / 'evidence').mkdir(parents=True, exist_ok=True)
    delivered, seams, header = [], [], None
    previous, first, last = None, None, None
    decisions = decisions or {}
    accepted, gaps = {}, []

    def evidence(image, timestamp, index):
        name = f'evidence/window-{index:04d}.png'
        image.save(output / name)
        return {'timestamp': timestamp, 'image': name}

    def uncertain(kind, question, item, position, reference=None, candidates=None, overlap_counts=None):
        issue = {'id': f'{kind}-{position:04d}-{int(round(item["timestamp"] * 1000)):08d}', 'kind': kind, 'question': question, 'timestamp': item['timestamp'], 'image': item['image'], 'position': position, 'status': 'unresolved', 'choices': ['supplement', 'accept_missing']}
        if kind == 'no_overlap':
            issue['choices'].append('confirm_join')
        if kind == 'ambiguous_repeat':
            issue['choices'].extend(['confirm_repeat', 'confirm_hold'])
        if overlap_counts:
            issue['overlap_candidates'] = overlap_counts
            issue['choices'].append('confirm_overlap')
        decision = decisions.get(issue['id'], {})
        action = decision.get('action')
        if action == 'supplement':
            from resume_score import validate_supplement, digest
            supplied = None
            try:
                if not decision.get('image_sha256') or digest(decision['image']) == decision['image_sha256']:
                    supplied = validate_supplement(decision.get('image', ''), output, issue)
            except OSError:
                pass
            if supplied is not None:
                if kind == 'cursor_occlusion':
                    delivered[position] = supplied
                else:
                    delivered.append(supplied)
                accepted[issue['id']] = dict(decision, image_sha256=digest(decision['image']))
                return decision
        elif action == 'accept_missing':
            gaps.append({'id': issue['id'], 'position': position, 'timestamp': item['timestamp'], 'question': question, 'replace_row': kind == 'cursor_occlusion'})
            accepted[issue['id']] = decision
            return decision
        elif action in issue['choices'] and (action != 'confirm_overlap' or decision.get('overlap') in (overlap_counts or [])):
            accepted[issue['id']] = decision
            return decision
        if reference:
            issue['reference'] = reference
        error = ConversionError(kind, question)
        error.issues = [issue]
        candidate_rows = []
        for index, row in enumerate(candidates or []):
            record = save_row(row, output, len(delivered) + index + 1)
            record['proposed_position'] = position + index
            record['confirmed'] = False
            candidate_rows.append(record)
        error.progress = {'rows': delivered, 'header': header, 'seams': seams, 'boundaries': {'start': first, 'end': item}, 'candidate_rows': candidate_rows, 'continuation': {'requires_original_video': True, 'requires_replay': True, 'stop_timestamp': item['timestamp'], 'confirmed_prefix_rows': len(delivered)}, 'decisions': accepted, 'gaps': gaps, 'limitations': [gap['question'] for gap in gaps]}
        raise error

    with tempfile.TemporaryDirectory(prefix='drum-score-') as scratch:
        frames = sample_video(source, scratch)
        for frame_index, (timestamp, file) in enumerate(frames):
            with Image.open(file) as image:
                try:
                    analysis, region, current = window_rows(image, timestamp)
                except ConversionError as error:
                    if not previous:
                        raise
                    item = evidence(image, timestamp, frame_index)
                    uncertain('unreadable_window', '该时间窗口无法确认完整谱行，不能跳过后声称整曲完整。', item, len(delivered), previous['evidence'])
                    continue
                item = None
                if previous is None:
                    item = evidence(image, timestamp, frame_index)
                    first = item
                    if analysis['partial_top']:
                        uncertain('start_gap', '视频开头存在上边缘残行，无法证明曲谱从完整开头开始。', item, 0, candidates=current)
                    top = analysis['row_bounds'][0][0]
                    head = region.crop((0, 0, region.width, top))
                    if (np.asarray(head.convert('L')) < 180).any():
                        head.save(output / 'images/header.png')
                        bbox = analysis['bbox']
                        header = {'image': 'images/header.png', 'timestamp': timestamp, 'bbox': [bbox[0], bbox[1], bbox[2], bbox[1] + top]}
                    for row in current:
                        delivered.append(save_row(row, output, len(delivered) + 1))
                else:
                    prior = previous['rows']
                    overlaps = [count for count in range(1, min(len(prior), len(current)) + 1) if all(same_row(a, b) for a, b in zip(prior[-count:], current[:count]))]
                    exact = len(prior) == len(current) and len(current) in overlaps
                    forced_count = None
                    if exact and len(overlaps) > 1 and abs(prior[0]['staff_top'] - current[0]['staff_top']) >= current[0]['staff_spacing'] * 2:
                        item = evidence(image, timestamp, frame_index)
                        choice = uncertain('ambiguous_repeat', '重复行在画面中发生位移，无法区分停留画面和再次演奏的段落。', item, len(delivered), previous['evidence'], current)
                        if choice['action'] != 'confirm_hold':
                            exact = False
                            forced_count = 0
                    if exact:
                        # A held frame or slow scroll whose complete row identities are unchanged.
                        previous['rows'] = current
                        previous['analysis'] = analysis
                        previous.update(file=file, timestamp=timestamp, frame_index=frame_index)
                        last = {'timestamp': timestamp, 'file': file, 'partial_bottom': analysis['partial_bottom']}
                        continue
                    item = evidence(image, timestamp, frame_index)
                    with Image.open(previous['file']) as before_image:
                        previous['evidence'] = evidence(before_image, previous['timestamp'], previous['frame_index'])
                    if forced_count is None and len(overlaps) != 1:
                        error_kind = 'no_overlap' if not overlaps else 'ambiguous_overlap'
                        choice = uncertain(error_kind, '相邻谱面窗口没有唯一可确认的有序重叠，需核对是否缺行或重复段落。', item, len(delivered), previous['evidence'], current, overlaps)
                        forced_count = choice.get('overlap', 0)
                    count = overlaps[0] if forced_count is None else forced_count
                    shifts = [a['staff_top'] - b['staff_top'] for a, b in zip(prior[-count:], current[:count])] if count else []
                    anchor = previous['anchor_rows']
                    accumulated = [a['staff_top'] - b['staff_top'] for a, b in zip(anchor[-count:], current[:count])] if count else []
                    if forced_count is None and (min(shifts) < -min(row['staff_spacing'] for row in current) or min(accumulated) < min(row['staff_spacing'] for row in current) * 2):
                        choice = uncertain('ambiguous_motion', '行内容有重叠，但没有足够的向上推进位置证据，需核对顺序。', item, len(delivered), previous['evidence'], current, [count])
                        count = choice.get('overlap', 0)
                    if count == len(current):
                        # Rows leaving the top edge add no new content. Keep the
                        # earlier anchor to prove cumulative motion at the next join.
                        previous.update(rows=current, analysis=analysis, evidence=item, file=file, timestamp=timestamp, frame_index=frame_index)
                        last = {'timestamp': timestamp, 'file': file, 'partial_bottom': analysis['partial_bottom']}
                        continue
                    seam = {'id': f'seam-{len(seams) + 1:04d}', 'position': len(delivered), 'overlap_rows': count, 'before': previous['evidence'], 'after': item, 'vertical_shift': float(np.median(shifts)) if shifts else None, 'cumulative_vertical_shift': float(np.median(accumulated)) if accumulated else None, 'matched_rows': [row['id'] for row in delivered[-count:]] if count else []}
                    seams.append(seam)
                    for row in current[count:]:
                        delivered.append(save_row(row, output, len(delivered) + 1))
                previous = {'rows': current, 'anchor_rows': current, 'analysis': analysis, 'evidence': item, 'file': file, 'timestamp': timestamp, 'frame_index': frame_index}
                last = {'timestamp': timestamp, 'file': file, 'partial_bottom': analysis['partial_bottom']}
        if not previous:
            raise ConversionError('decode_failed', '视频中没有可读取的完整谱行。')
        with Image.open(last['file']) as image:
            end = evidence(image, last['timestamp'], len(frames))
        if last['partial_bottom']:
            uncertain('end_gap', '视频结尾存在下边缘残行，无法确认末尾谱段完整。', end, len(delivered), previous['evidence'])
    return header, delivered, {'seams': seams, 'boundaries': {'start': first, 'end': end}, 'decisions': accepted, 'gaps': gaps, 'limitations': [gap['question'] for gap in gaps]}
