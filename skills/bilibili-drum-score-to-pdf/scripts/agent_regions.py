"""Validate native Agent boxes without letting detector proposals veto them."""
from video_seek import ConversionError

MAX_REFINEMENT = 8


def invalid(message):
    raise ConversionError('invalid_decision', message)


def box(value, frame):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) is not int for v in value):
        invalid('坐标必须是原帧整数、左闭右开矩形。')
    if not (0 <= value[0] < value[2] <= frame['width'] and 0 <= value[1] < value[3] <= frame['height']):
        invalid('坐标超出原帧或面积为零。')
    return value


def contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def covered(target, rectangles):
    # Check every cell cut by evidence edges, rather than trusting total area.
    xs = sorted({target[0], target[2]} | {max(target[0], min(target[2], x)) for r in rectangles for x in (r[0], r[2])})
    ys = sorted({target[1], target[3]} | {max(target[1], min(target[3], y)) for r in rectangles for y in (r[1], r[3])})
    return all(any(contains(r, [a, c, b, d]) for r in rectangles) for a, b in zip(xs, xs[1:]) for c, d in zip(ys, ys[1:]))


def native_rows(decision, observation, presented, script_rows=None):
    rows = decision['rows']
    if not isinstance(rows, list) or not rows or len(rows) > 200:
        invalid('缺少有序谱行或谱行数量过大。')
    frames = {f['id']: f for f in observation['frames']}
    images = {i['id']: i for i in observation['images']}
    fields = {'frame_id', 'coordinate_space', 'roi', 'bbox', 'evidence_images', 'complete', 'cursor', 'occlusion', 'boundary_verified', 'evidence'}
    chosen = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) not in (fields, fields | {'refinement'}):
            invalid('谱行决定字段非法。')
        if not isinstance(row['frame_id'], str) or row['frame_id'] not in frames or row['coordinate_space'] != 'native_pixels':
            invalid('帧引用或坐标空间非法，不能使用缩略图坐标。')
        frame = frames[row['frame_id']]
        roi, proposed = box(row['roi'], frame), box(row['bbox'], frame)
        if not contains(roi, proposed):
            invalid('谱行超出 Agent 指定的谱面 ROI。')
        if any(type(row[k]) is not bool for k in ('complete', 'boundary_verified')) or any(row[k] not in ('clear', 'present', 'uncertain') for k in ('cursor', 'occlusion')):
            invalid('完整性或遮挡判断非法。')
        if not isinstance(row['evidence'], str) or not row['evidence'].strip() or len(row['evidence']) > 2000:
            invalid('缺少谱行选择的可观察依据。')
        executed = proposed
        refinement = row.get('refinement')
        if refinement is not None:
            if not isinstance(refinement, dict) or set(refinement) != {'bbox', 'reason', 'boundary_verified'}:
                invalid('精修字段非法。')
            executed = box(refinement['bbox'], frame)
            if not contains(roi, executed) or any(abs(a - b) > MAX_REFINEMENT for a, b in zip(proposed, executed)):
                invalid('边界精修超过 8 原生像素或超出 ROI。')
            if not isinstance(refinement['reason'], str) or not refinement['reason'].strip() or len(refinement['reason']) > 2000:
                invalid('精修缺少原因。')
            if type(refinement['boundary_verified']) is not bool:
                invalid('精修边界核查状态非法。')
            if not refinement['boundary_verified']:
                raise ConversionError('review_required', '精修边界可能截掉行外符号，需要复查。')
        authority = (script_rows or {}).get(index)
        refs = row['evidence_images']
        if authority is None and (not isinstance(refs, list) or not refs or any(not isinstance(i, str) or i not in images or i not in presented for i in refs) or len(set(refs)) != len(refs)):
            invalid('原生细节证据引用非法。')
        if authority is not None and refs != []:
            invalid('脚本接受项不得借用未呈交的细节引用。')
        details = [images[i] for i in refs]
        if any(i.get('frame_id') != frame['id'] or i['kind'] not in ('detail', 'native_detail') for i in details):
            invalid('必须使用所选同一原帧的无标注原生细节。')
        if authority is None and (not covered(proposed, [i['bbox'] for i in details]) or not covered(executed, [i['bbox'] for i in details])):
            raise ConversionError('missing_evidence', '细节图没有覆盖完整建议与精修裁剪。')
        if not row['complete'] or not row['boundary_verified'] or row['cursor'] != 'clear' or row['occlusion'] != 'clear':
            raise ConversionError('review_required', '没有完整干净原帧或边界未核查，不得拼补。')
        if any(c['frame_id'] == frame['id'] and proposed[1] < c['bbox'][3] for c in chosen):
            raise ConversionError('review_required', '同帧谱行重复、交叠或顺序非法。')
        chosen.append(dict(id=f'agent-row-{index:03d}', frame_id=frame['id'], index=index, bbox=executed,
                           proposed_bbox=proposed, roi=roi, coordinate_space='native_pixels', complete=True, clean=True,
                           refinement=refinement))
        if authority is None:
            chosen[-1]['visual_judgment'] = {k: row[k] for k in ('complete','cursor','occlusion','boundary_verified','evidence','evidence_images')}
        else:
            chosen[-1]['script_acceptance'] = authority
    return chosen
