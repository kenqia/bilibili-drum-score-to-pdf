"""Bounded, pixel-preserving boundaries between already detected staffs."""
import math

import cv2
import numpy as np


MAX_BAND_PIXELS = 2_000_000
MAX_WIDTH = 8192
MAX_PROBES = 512
MAX_PATH_RUNS = 512
MAX_TOTAL_RUNS = 8192


def _gray_edges(image):
    """Recognize only thin, uniform, neutral gray at the actual image edge."""
    limit = min(8, image.width // 100)
    result = []
    for direction in (1, -1):
        columns = []
        for offset in range(limit):
            x = offset if direction == 1 else image.width - 1 - offset
            with image.crop((x, 0, x + 1, image.height)) as column:
                rgb = np.asarray(column.convert('RGB'))[:, 0].astype(np.int16)
            low = rgb.min(axis=1)
            if (low.min() < 190 or low.max() - low.min() > 12
                    or (rgb.max(axis=1) - low).max() > 4 or not (low < 245).all()):
                break
            columns.append(x)
        if columns and len(columns) < limit:
            x = len(columns) if direction == 1 else image.width - 1 - len(columns)
            with image.crop((x, 0, x + 1, image.height)) as column:
                inside = np.asarray(column.convert('RGB')).min(axis=2)
            if (inside >= 245).mean() >= .98:
                result.extend(columns)
    return result


def _corridor(image, previous, current, edges):
    width, height = image.size
    begin = math.ceil(previous[0] + previous[1] * 5)
    end = math.floor(current[0] - current[1])
    top = max(0, math.floor(previous[0]))
    bottom = min(height, math.ceil(current[0] + current[1] * 4) + 1)
    if end <= begin or width > MAX_WIDTH or width * (bottom - top) > MAX_BAND_PIXELS:
        return None, 'bounded_or_no_corridor'
    with image.crop((0, top, width, bottom)) as band:
        rgb = np.asarray(band.convert('RGB'))
    # Keep the established RGB threshold, including pale/color marks. Gray
    # edge evidence affects detection only; delivery still copies every pixel.
    ink = (rgb.min(axis=2) < 245).astype(np.uint8)
    ink[:, edges] = 0
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    # Remove only isolated pale neutral components of at most eight pixels from detection.
    # They remain in delivered RGB. All larger/darker/color marks still veto cuts.
    incidental = []
    for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
        if area <= 8 and w <= 4 and h <= 4:
            pixels = rgb[y:y + h, x:x + w][labels[y:y + h, x:x + w] == label].astype(np.int16)
            if pixels.min() >= 240 and (pixels.max(axis=1) - pixels.min(axis=1)).max() <= 4:
                incidental.append(label)
    original_labels, original_stats = labels, stats
    if incidental:
        ink[np.isin(labels, incidental)] = 0
        _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    previous_end = math.ceil(previous[0] + previous[1] * 4) + 1 - top
    current_begin = math.floor(current[0]) - top
    upper = np.unique(labels[:previous_end])
    lower = np.unique(labels[current_begin:])
    upper, lower = upper[upper != 0], lower[lower != 0]
    if np.intersect1d(upper, lower).size:
        return None, 'component_spans_staffs'
    owners = np.zeros(len(stats), np.uint8)
    owners[upper], owners[lower] = 1, 2
    # A blank row cannot establish the meaning of a detached annotation.
    # Multiple gaps around an mf or circle would assign it to opposite staffs.
    # Keep the group whenever such substantive marks occupy this corridor.
    for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
        if owners[label] == 0 and top + y + h > begin and top + y < end:
            return None, 'detached_mark_ambiguous'
    blank = np.flatnonzero(~ink[begin - top:end - top].any(axis=1)) + begin
    separator = None
    if len(blank):
        runs = np.split(blank, np.flatnonzero(np.diff(blank) > 1) + 1)
        for run in sorted(runs, key=len, reverse=True):
            middle = float(np.median(run))
            for value in sorted(run.tolist(), key=lambda y: abs(y - middle)):
                if all(not (top + y < value < top + y + h)
                       for x, y, w, h, area in stats[1:]):
                    separator = value
                    break
            if separator is not None:
                break
    if separator is not None and all(not (top + y < separator < top + y + h)
                                     for x, y, w, h, area in original_stats[1:]):
        return np.full(width, separator, np.int32), 'incidental_blank_cut'
    ownership = owners[labels]
    yy = np.arange(bottom - top)[:, None] + top
    low = np.maximum(begin, np.where(ownership == 1, yy + 1, begin).max(axis=0))
    high = np.minimum(end - 1, np.where(ownership == 2, yy, end - 1).min(axis=0))
    levels = np.arange(begin, end)
    allowed = (levels[:, None] >= low) & (levels[:, None] <= high)
    # Even incidental pixels must remain complete in one delivered row.
    for label in incidental:
        x, y, w, h, _ = original_stats[label]
        start, stop = max(begin, top + y + 1), min(end, top + y + h)
        if start < stop:
            allowed[start - begin:stop - begin, x:x + w] = False
    middle = separator if separator is not None else (begin + end - 1) / 2
    bias = abs(levels - middle) / max(1, end - begin)
    cost = np.where(allowed[:, 0], bias, np.inf)
    parents = np.zeros(allowed.shape, np.int8)
    for x in range(1, width):
        choices = np.stack((np.r_[np.inf, cost[:-1]] + 1, cost,
                            np.r_[cost[1:], np.inf] + 1))
        choice = choices.argmin(axis=0)
        cost = np.where(allowed[:, x], choices.min(axis=0) + bias, np.inf)
        parents[:, x] = choice - 1
    if not np.isfinite(cost).any():
        return None, 'no_component_safe_path'
    index = int(cost.argmin())
    path = np.empty(width, np.int32)
    for x in range(width - 1, -1, -1):
        path[x] = begin + index
        index += int(parents[index, x])
    # Independent postcondition: no detected component may land on both sides.
    side = yy < path[None, :]
    above = np.unique(original_labels[side])
    below = np.unique(original_labels[~side])
    if np.intersect1d(above[above != 0], below[below != 0]).size:
        return None, 'component_ownership_conflict'
    return path, 'incidental_corridor_path' if separator is not None else 'component_safe_path'


def split(image, groups, staffs, *, max_output_pixels=None):
    """Refine merged groups only; untouched safe horizontal cuts stay exact."""
    width, height = image.size
    existing = {end for _, end in groups[:-1]}
    cuts = [np.zeros(width, np.int32)]
    records = []
    edges = _gray_edges(image) if len(groups) < len(staffs) else []
    probes = total_runs = 0
    for previous, current in zip(staffs, staffs[1:]):
        old = next((y for y in existing if previous[0] < y <= current[0]), None)
        if old is not None:
            path, reason = np.full(width, old, np.int32), 'existing_blank_cut'
        elif probes < MAX_PROBES:
            path, reason = _corridor(image, previous, current, edges)
            probes += 1
        else:
            path, reason = None, 'probe_limit'
        if path is not None:
            changes = np.r_[0, np.flatnonzero(np.diff(path)) + 1, width]
            if old is None and (len(changes) - 1 > MAX_PATH_RUNS
                                or total_runs + len(changes) - 1 > MAX_TOTAL_RUNS):
                path, reason, runs = None, 'path_complexity_limit', None
            else:
                cuts.append(path)
                runs = [[int(a), int(b), int(path[a])] for a, b in zip(changes[:-1], changes[1:])]
                total_runs += len(runs)
        else:
            runs = None
        records.append({'after_staff_y': previous[0], 'reason': reason, 'path_runs': runs})
    cuts.append(np.full(width, height, np.int32))
    # Shaped crops overlap in bounding-box height. Budget their padding and
    # extract()'s eight-pixel gaps before publishing a PDF that can be relaid out.
    if max_output_pixels is not None:
        pixels = width * (sum(int(b.max() - a.min()) for a, b in zip(cuts, cuts[1:]))
                          + 8 * (len(cuts) - 2))
        if pixels > max_output_pixels:
            cuts = [np.zeros(width, np.int32)]
            cuts.extend(np.full(width, y, np.int32) for _, y in groups[:-1])
            cuts.append(np.full(width, height, np.int32))
            for record in records:
                if record['reason'] != 'existing_blank_cut':
                    record.update(reason='output_pixel_limit', path_runs=None)
    medians = np.array([int(np.median(cut)) for cut in cuts])
    positions = np.array([y for y, _ in staffs])
    counts = np.diff(np.searchsorted(positions, medians)).tolist()
    return cuts, {'algorithm': 'component_corridor_v1', 'gray_edge_columns': edges,
                  'original_group_count': len(groups), 'group_count': len(cuts) - 1,
                  'max_staffs_per_group': max(counts), 'staffs_per_group': counts,
                  'boundaries': records,
                  'page_regions_coordinates': 'median_cut_y; exact column boundaries in path_runs'}


def crop(image, upper, lower):
    """Partition RGB exactly once; white is padding outside each row's mask."""
    top, bottom = int(upper.min()), int(lower.max())
    with image.crop((0, top, image.width, bottom)) as part:
        rgb = np.array(part.convert('RGB'))
    for begin in range(0, len(rgb), 256):
        rows = np.arange(top + begin, top + min(len(rgb), begin + 256))[:, None]
        outside = (rows < upper) | (rows >= lower)
        rgb[begin:begin + len(rows)][outside] = 255
    from PIL import Image
    return top, Image.fromarray(rgb)
