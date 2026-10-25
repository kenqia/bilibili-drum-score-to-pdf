"""Conservative automatic score region, adjacent registration and whole groups."""
import math

import cv2
import numpy as np
from PIL import Image

from .video_seek import ConversionError
from .registration import profile_of, shift_candidates, pick, LOCAL_GOOD


def detect_region(paths, *, budget_check=lambda: None):
    """Aggregate paper frequency without retaining a stack of native images."""
    frequency = None
    for path in paths:
        budget_check()
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
    sx, sy = width / mask.shape[1], height / mask.shape[0]
    candidates = []
    for x, y, w, h, area in stats[1:]:
        if area < mask.size * .05:
            continue
        candidates.append((max(0, math.floor(x * sx) - 3),
            max(0, math.floor(y * sy) - 3),
            min(width, math.ceil((x + w) * sx) + 3),
            min(height, math.ceil((y + h) * sy) + 3)))
    # Paper connectivity establishes the entire viewport, including titles and
    # marginal marks. Staff structure validates that viewport, never crops it.
    # Distributed native frames distinguish a stable score from a transient
    # white panel. Multiple supported panels remain ambiguous regardless of area.
    observations = sorted(set(np.linspace(0, len(paths) - 1,
                                         min(7, len(paths)), dtype=int).tolist()))
    support = [0] * len(candidates)

    def observe(index):
        budget_check()
        with Image.open(paths[index]) as image:
            for candidate, region in enumerate(candidates):
                budget_check()
                with image.crop(region) as crop:
                    try:
                        system_groups(crop)
                    except ConversionError as error:
                        if error.code != 'unsupported_layout':
                            raise
                    else:
                        support[candidate] += 1

    for index in observations:
        observe(index)
    if max(support, default=0) < 2:
        # A short or late score may fall between the distributed observations.
        # Inspect remaining already-sampled frames before deciding uncertainty.
        for index in range(len(paths)):
            if index not in observations:
                observe(index)
    # With no observed staff, a sole paper candidate remains uncertain and
    # continues through normal registration/pagination instead of pre-rejection.
    minimum = min(2, max(support, default=0))
    supported = [region for region, count in zip(candidates, support)
                 if count >= minimum]
    if len(supported) != 1:
        raise ConversionError('unsupported_layout', '无法从多帧五线结构唯一确认固定白底谱区。')
    return supported[0]



def _profile(image, invalid=None):
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return gray, profile_of(gray, np.zeros(gray.shape, dtype=bool) if invalid is None else invalid)


def _ink_overlap(old, new, delta, invalid=None):
    """Compare real aligned ink, excluding unknown pixels in either frame."""
    old, new = old[delta:], new[:len(new) - delta]
    valid = np.ones(old.shape[:2], dtype=bool) if invalid is None else (
        ~invalid[delta:] & ~invalid[:len(invalid) - delta])
    if valid.size == 0 or valid.mean() < .5:
        return 0.0, 0
    a = (np.min(old, axis=2) < 180) & valid
    b = (np.min(new, axis=2) < 180) & valid
    union = int(np.count_nonzero(a | b))
    return np.count_nonzero(a & b) / max(1, union), union


def _narrow_shift(previous, profile, old_pixels, pixels, paths, index, region, invalid=None):
    # Abrupt viewport changes can share less than a quarter of a frame.
    # Require unique local detail and dense independent pixel agreement;
    # a longer search alone never establishes a continuation.
    height = len(pixels)
    minimum = max(32, int(height * .08))
    candidates = shift_candidates(previous, profile, -2, height - minimum, minimum, top=12)
    proven = []
    for cost, shift, local in candidates:
        delta = max(0, int(round(shift)))
        similarity, ink = _ink_overlap(old_pixels, pixels, delta, invalid)
        if cost <= .1 and local <= LOCAL_GOOD and similarity >= .85 and ink >= 128:
            proven.append(delta)
    if not proven:
        return None
    # Confirm the same notation in another actual observation. This does not
    # use a speed prior to break ties between repeated music.
    if index + 1 >= len(paths):
        return None
    with Image.open(paths[index + 1]) as original:
        following = np.asarray(original.convert('RGB').crop(region))
    _, next_profile = _profile(Image.fromarray(following), invalid)
    next_candidates = shift_candidates(profile, next_profile, -2,
        height - max(16, height // 4), max(16, height // 4))
    next_shift, _ = pick(next_candidates, .1, strict=True, reject_ambiguity=True)
    if next_shift is None:
        return None
    next_delta = max(0, int(round(next_shift)))
    supported = []
    for delta in proven:
        if delta + next_delta <= height - minimum:
            similarity, ink = _ink_overlap(old_pixels, following, delta + next_delta, invalid)
            if similarity >= .85 and ink >= 128:
                supported.append(delta)
    if not supported or any(abs(delta - supported[0]) > 2 for delta in supported[1:]):
        return None
    return supported[0], {'candidate_deltas': proven, 'following_delta': next_delta}


def register(paths, region, *, observations=None,
             budget_check=lambda: None, allow_narrow=True, invalid=None, resume=None):
    placements = [] if resume is None else list(resume['placements'])
    previous, previous_pixels, position = ((None, None, 0) if resume is None else
        (resume['profile'], resume['pixels'], resume['position']))
    motion_since_previous = 0.0
    skipped_since_previous = 0
    previous_index = None if resume is None else resume['previous_index']
    first = 0 if previous_index is None else previous_index + 1
    for index in range(first, len(paths)):
        path = paths[index]
        budget_check()
        if observations is not None:
            motion_since_previous = max(motion_since_previous,
                observations[index].get('native_motion_max_luma_difference', 0.0))
            skipped_since_previous += observations[index].get('native_intermediate_frames', 0)
        with Image.open(path) as original:
            cropped = original.convert('RGB').crop(region)
            pixels = np.asarray(cropped)
            sparse_motion = ((motion_since_previous > 1.0 and skipped_since_previous > 0)
                or (observations is not None and observations[index].get('requires_unique_registration', False)))
            if previous_pixels is not None and not sparse_motion and np.array_equal(previous_pixels, pixels):
                # Exact pixels already passed paper/ink and overlap validation.
                # Keep native-motion ambiguity checks before skipping repeated work.
                placements.append({'sample': index, 'offset': position})
                previous_index = index
                motion_since_previous = 0.0
                skipped_since_previous = 0
                continue
            gray, profile = _profile(cropped, invalid)
        paper = (gray > 190).mean()
        ink = (gray < 110).mean()
        if paper < .5 or ink < .002:
            # Black intros and blank outros stay in provenance, not notation.
            continue
        transition = None
        if previous is not None:
            height = len(gray)
            minimum = max(16, int(.25 * height))
            # Only identical observations can skip the forward search. A small
            # near-zero cost can hide motion by a whole repeated system, whose
            # measure numbers contribute very little to the global profile.
            candidates = shift_candidates(previous, profile, -2, height - minimum, minimum)
            delta, cost = pick(candidates, .17, prefer=0, strict=False,
                               reject_ambiguity=sparse_motion)
            if delta is None and (allow_narrow(previous_index, index) if callable(allow_narrow) else allow_narrow):
                content_path = _narrow_shift(previous, profile, previous_pixels, pixels, paths, index, region, invalid)
                if content_path is not None:
                    delta, transition = content_path
            if delta is None:
                error = ConversionError('discontinuity', '无法可靠确认相邻采样的位移，未发布可能缺段的曲谱。')
                error.registration_interval = (previous_index, index)
                error.registration_resume = {'placements': placements, 'previous_index': previous_index,
                    'position': position, 'profile': previous, 'pixels': previous_pixels}
                raise error
            delta = max(0, int(round(delta)))
            # A similar profile is insufficient when notation in the overlap
            # differs. This prevents hiding a known failed continuation.
            similarity, valid_ink = _ink_overlap(previous_pixels, pixels, delta, invalid)
            if similarity < .45 or valid_ink < 32:
                error = ConversionError('discontinuity', '相邻画面重叠内容不一致，未发布可能缺段的曲谱。')
                error.registration_interval = (previous_index, index)
                error.registration_resume = {'placements': placements, 'previous_index': previous_index,
                    'position': position, 'profile': previous, 'pixels': previous_pixels}
                raise error
            position += delta
        placement = {'sample': index, 'offset': position}
        if transition is not None:
            placement['transition'] = {**transition, 'overlap_rows': height - delta,
                'ink_iou': float(similarity), 'valid_ink_pixels': valid_ink}
        placements.append(placement)
        previous, previous_pixels = profile, pixels
        previous_index = index
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


def system_groups(image, *, detailed=False):
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
    return list(zip(boundaries[:-1], boundaries[1:])), staffs if detailed else len(staffs)


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
    from .print_layout import render
    with Image.open(longshot) as image:
        layout = render(image, output)
    return output / 'score.pdf', sorted(output.glob('page-*.png')), layout['page_regions'], layout['staff_count']
