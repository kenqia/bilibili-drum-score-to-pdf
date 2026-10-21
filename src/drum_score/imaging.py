"""Conservative automatic score region, adjacent registration and whole groups."""
import math
import subprocess

import cv2
import numpy as np
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from .video_seek import ConversionError
from .registration import profile_of, shift_candidates, pick


def detect_region(paths):
    """Aggregate paper frequency without retaining a stack of native images."""
    frequency = None
    for path in paths:
        with Image.open(path) as image:
            width, height = image.size
            image.thumbnail((640, 640))
            rgb = np.asarray(image.convert('RGB'))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        chroma = rgb.max(axis=2).astype(int) - rgb.min(axis=2)
        paper = (gray > 190) & (chroma < 40)
        if frequency is None:
            frequency = np.zeros(paper.shape, np.float32)
        frequency += paper
    mask = (frequency / len(paths) > .5).astype(np.uint8)
    # Mostly white full-frame sources retain their margins and title exactly.
    if mask.mean() > .8:
        return (0, 0, width, height)
    size = max(9, (min(mask.shape) // 24) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count < 2:
        raise ConversionError('unsupported_layout', '未找到固定白底谱区。')
    x, y, w, h, area = stats[1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])]
    if area < mask.size * .05:
        raise ConversionError('unsupported_layout', '未找到足够大的固定白底谱区。')
    sx, sy = width / mask.shape[1], height / mask.shape[0]
    return (max(0, math.floor(x * sx) - 3), max(0, math.floor(y * sy) - 3),
            min(width, math.ceil((x + w) * sx) + 3), min(height, math.ceil((y + h) * sy) + 3))


def _profile(image):
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return gray, profile_of(gray, np.zeros(gray.shape, dtype=bool))


def register(paths, region, *, observations=None):
    placements = []
    previous, previous_pixels, position = None, None, 0
    motion_since_previous = 0.0
    skipped_since_previous = 0
    for index, path in enumerate(paths):
        if observations is not None:
            motion_since_previous = max(motion_since_previous,
                observations[index].get('native_motion_max_luma_difference', 0.0))
            skipped_since_previous += observations[index].get('native_intermediate_frames', 0)
        with Image.open(path) as original:
            cropped = original.convert('RGB').crop(region)
            pixels = np.asarray(cropped)
            gray, profile = _profile(cropped)
        paper = (gray > 190).mean()
        ink = (gray < 110).mean()
        if paper < .5 or ink < .002:
            # Black intros and blank outros stay in provenance, not notation.
            continue
        if previous is not None:
            height = len(gray)
            minimum = max(16, int(.25 * height))
            # Only identical observations can skip the forward search. A small
            # near-zero cost can hide motion by a whole repeated system, whose
            # measure numbers contribute very little to the global profile.
            sparse_motion = (motion_since_previous > 1.0 and skipped_since_previous > 0)
            if np.array_equal(previous_pixels, pixels) and not sparse_motion:
                delta = 0
            else:
                candidates = shift_candidates(previous, profile, -2, height - minimum, minimum)
                delta, cost = pick(candidates, .17, prefer=0, strict=False,
                                   reject_ambiguity=sparse_motion)
            if delta is None:
                raise ConversionError('discontinuity', '无法可靠确认相邻采样的位移，未发布可能缺段的曲谱。')
            delta = max(0, int(round(delta)))
            # A similar profile is insufficient when notation in the overlap
            # differs. This prevents hiding a known failed continuation.
            old = previous_pixels[delta:]
            new = pixels[:len(pixels) - delta]
            a = np.min(old, axis=2) < 180
            b = np.min(new, axis=2) < 180
            union = np.count_nonzero(a | b)
            similarity = np.count_nonzero(a & b) / max(1, union)
            if similarity < .45:
                raise ConversionError('discontinuity', '相邻画面重叠内容不一致，未发布可能缺段的曲谱。')
            position += delta
        placements.append({'sample': index, 'offset': position})
        previous, previous_pixels = profile, pixels
        motion_since_previous = 0.0
        skipped_since_previous = 0
    if not placements:
        raise ConversionError('unsupported_layout', '视频中未找到可用的白底五线谱。')
    return placements


def compose(paths, region, placements, output):
    width, height = region[2] - region[0], region[3] - region[1]
    total = placements[-1]['offset'] + height
    if width * total > 20_000_000:
        raise ConversionError('resource_limit', '派生长图超出像素限制。')
    # Keep source RGB. No chroma mask, whitening or inferred hidden symbols.
    result = Image.new('RGB', (width, total), 'white')
    end = 0
    for placement in placements:
        offset = placement['offset']
        with Image.open(paths[placement['sample']]) as image:
            crop = image.convert('RGB').crop(region)
            if end == 0:
                result.paste(crop, (0, 0))
            elif offset + height > end:
                # Preserve the first complete observation of each position.
                # No global search folds later repeated music into an old place.
                fresh = max(0, end - offset)
                result.paste(crop.crop((0, fresh, width, height)), (0, end))
        end = max(end, offset + height)
    result.save(output)
    result.close()


def system_groups(image):
    width, height = image.size
    rows = []
    counts = np.zeros(height, dtype=np.int64)
    # The morphology kernel is horizontal only. Independent 256-row strips
    # retain exact row detection while bounding gray/RGB/ink work buffers.
    for top in range(0, height, 256):
        with image.crop((0, top, width, min(height, top + 256))) as strip:
            gray = np.asarray(strip.convert('L'))
            horizontal = cv2.morphologyEx((gray < 225).astype(np.uint8), cv2.MORPH_OPEN,
                                         np.ones((1, max(20, width // 12)), np.uint8))
            rows.extend((top + np.flatnonzero(horizontal.sum(axis=1) > width * .3)).tolist())
            counts[top:top + strip.height] = (np.min(np.asarray(strip.convert('RGB')), axis=2) < 245).sum(axis=1)
    rows = np.asarray(rows, dtype=np.int64)
    runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1) if len(rows) else []
    lines = [float(run.mean()) for run in runs if 0 < len(run) <= 6]
    staffs = []
    index = 0
    while index + 4 < len(lines):
        gaps = np.diff(lines[index:index + 5])
        spacing = float(np.median(gaps))
        if 2 <= spacing <= 40 and np.max(abs(gaps - spacing)) <= max(1, spacing * .2):
            staffs.append((lines[index], spacing))
            index += 5
        else:
            index += 1
    if not staffs:
        raise ConversionError('unsupported_layout', '谱区中未找到可用五线谱。')
    # Use all RGB channels to protect colored marks from page boundaries.
    boundaries = [0]
    for previous, current in zip(staffs, staffs[1:]):
        begin = min(height, math.ceil(previous[0] + previous[1] * 5))
        end = max(begin, math.floor(current[0] - current[1]))
        blank = np.flatnonzero(counts[begin:end] == 0)
        gaps = np.split(blank, np.flatnonzero(np.diff(blank) > 1) + 1) if len(blank) else []
        if gaps:
            gap = max(gaps, key=len)
            boundaries.append(begin + int(gap[len(gap) // 2]))
    boundaries.append(height)
    return list(zip(boundaries[:-1], boundaries[1:])), len(staffs)


def _page_strips(groups, capacity):
    """Balance contiguous complete groups at the smallest feasible page count."""
    def split(limit):
        strips = []
        start = end = groups[0][0]
        for begin, finish in groups:
            if end > start and finish - start > limit + 1e-6:
                strips.append((start, end))
                start = begin
            end = finish
        strips.append((start, end))
        return strips

    count = len(split(capacity))
    low = max(max(end - start for start, end in groups),
              math.ceil((groups[-1][1] - groups[0][0]) / count))
    high = math.floor(capacity + 1e-6)
    while low < high:
        middle = (low + high) // 2
        if len(split(middle)) <= count:
            high = middle
        else:
            low = middle + 1
    return split(low)


def paginate(longshot, output):
    with Image.open(longshot) as image:
        groups, staff_count = system_groups(image)
        page_width, page_height = A4
        margin = 12
        scale = min((page_width - 2 * margin) / image.width,
                    (page_height - 2 * margin) / max(end - start for start, end in groups))
        capacity = (page_height - 2 * margin) / scale
        strips = _page_strips(groups, capacity)
        pdf = output / 'score.pdf'
        document = canvas.Canvas(str(pdf), pagesize=A4, invariant=1)
        for index, (start, end) in enumerate(strips):
            part = image.crop((0, start, image.width, end))
            document.drawImage(ImageReader(part), (page_width - image.width * scale) / 2,
                               page_height - margin - part.height * scale,
                               width=image.width * scale, height=part.height * scale)
            document.showPage()
            part.close()
        document.save()
    try:
        subprocess.run(['pdftoppm', '-png', '-scale-to', '1400', str(pdf), str(output / 'page')],
                       check=True, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        raise ConversionError('preview_failed', '无法生成全部页面预览，未发布 PDF。') from None
    pages = sorted(output.glob('page-*.png'))
    if len(pages) != len(strips):
        raise ConversionError('preview_failed', '页面预览不完整，未发布 PDF。')
    return pdf, pages, strips, staff_count
