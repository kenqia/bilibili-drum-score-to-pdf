"""Conservative scope selection from observed score structure and real pixels."""
import cv2
import numpy as np
from PIL import Image

from .imaging import system_groups, verify_edges
from .video_seek import ConversionError


def _observe(path, region):
    with Image.open(path) as original:
        image = original.convert('RGB').crop(region)
    with image:
        rgb = np.asarray(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        try:
            _, staffs = system_groups(image, detailed=True)
        except ConversionError:
            staffs = []
        ink = (gray < 140).astype(np.uint8)
        chroma = rgb.max(axis=2).astype(int) - rgb.min(axis=2)
        colorful = (chroma > 35).astype(np.uint8)
        count, _, stats, _ = cv2.connectedComponentsWithStats(
            cv2.morphologyEx(colorful, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)))
        covers = [list(map(int, row[:4])) for row in stats[1:] if
                  gray.size * .04 < row[4] < gray.size * .6 and row[3] > image.height * .35]
        # A photograph can contain disconnected colored patches separated by
        # gray pixels. Its whole observed color extent still bounds an overlay.
        ys, xs = np.nonzero(colorful)
        if not covers and len(xs) > gray.size * .01:
            x, y, w, h = int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
            if .04 < w * h / gray.size < .6 and h > image.height * .35:
                covers = [[x, y, w, h]]
        if not staffs:
            horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                np.ones((1, max(20, image.width // 8)), np.uint8))
            staff_fragments = np.count_nonzero(horizontal.sum(axis=1) > image.width * .15) >= 5
            edge_fragment = False
            if (gray > 190).mean() > .5 and not covers:
                try:
                    verify_edges(image)
                except ConversionError:
                    edge_fragment = True
            return {'kind': 'obstructed_score' if covers and staff_fragments else
                    'score' if edge_fragment else
                    'black' if (rgb.max(axis=2) < 40).mean() > .9 else 'non_score',
                    'staff_count': 0, 'cover_boxes': covers, 'edge_fragment': edge_fragment}
        # A notation key has isolated symbols, labels below each staff, and no
        # internal measure bars. A short musical example with bars stays score.
        legend = len(staffs) == 2
        for y, spacing in staffs:
            top, bottom = int(y), int(y + 4 * spacing)
            bars = ink[top:bottom + 1].mean(axis=0) > .85
            interior = bars[int(image.width * .08):int(image.width * .94)]
            labels = ink[min(image.height, bottom + int(spacing * 1.5)):
                         min(image.height, bottom + int(spacing * 7))]
            occupied = labels.any(axis=0) if labels.size else np.zeros(image.width, bool)
            clusters = np.count_nonzero(np.diff(np.r_[False, occupied, False].astype(int)) == 1)
            # A stem can cross all five lines too. One isolated vertical run
            # is insufficient to identify musical measures in a labelled key.
            bar_runs = np.count_nonzero(np.diff(np.r_[False, interior, False].astype(int)) == 1)
            upper = ink[max(0, top - int(spacing * 8)):max(0, top - int(spacing))]
            beams = cv2.morphologyEx(upper, cv2.MORPH_OPEN,
                np.ones((1, max(8, int(spacing * 3))), np.uint8)) if upper.size else upper
            legend &= bar_runs <= 1 and clusters >= 12 and not beams.any()
        return {'kind': 'notation_example' if legend else 'obstructed_score' if covers else 'score',
                'staff_count': len(staffs), 'cover_boxes': covers}


def select(paths, records, region, start, end, *, explicit, check):
    """Select one unambiguous score run; preserve requested excerpts verbatim."""
    observed = []
    for path, record in zip(paths, records):
        check()
        observed.append({**_observe(path, region), 'timestamp': record['timestamp'],
                         'pts': record['pts'], 'time_base': record['time_base']})
    scope = {'mode': 'excerpt' if explicit else 'main_song',
             'requested_range_seconds': [start, end],
             'effective_range_seconds': [start, end], 'excluded_intervals': [],
             'observations': observed}
    if explicit:
        return paths, records, scope
    usable = [i for i, item in enumerate(observed) if item['kind'] == 'score']
    if not usable:
        scope['decision'] = 'uncertain'
        return paths, records, scope
    first, last = usable[0], usable[-1]
    # An interior interruption can contain unique music. Do not silently join
    # two songs or treat a short, similar musical example as expendable.
    for index in range(first, last + 1):
        if observed[index]['kind'] != 'score':
            raise ConversionError('ambiguous_scope',
                f'约 {records[index]["timestamp"]:.3f} 秒的主曲边界不明确，请指定开始和结束时间后重试。')
    # A covered first screen can be discarded only if a later actual frame
    # exposes the same notation. Position in the video alone is not evidence.
    for index, item in enumerate(observed):
        if item['kind'] != 'obstructed_score':
            continue
        check()
        with Image.open(paths[index]) as old, Image.open(paths[first]) as new:
            a = np.asarray(old.convert('RGB').crop(region))
            b = np.asarray(new.convert('RGB').crop(region))
        valid = np.ones(a.shape[:2], bool)
        for x, y, w, h in item['cover_boxes']:
            valid[y:y + h, x:x + w] = False
        ai, bi = (a.min(axis=2) < 140) & valid, (b.min(axis=2) < 140) & valid
        union = np.count_nonzero(ai | bi)
        # Global ink agreement cannot license losing even one unique visible
        # annotation. The same RGB tolerance protects replaced page fragments.
        visible = (a.min(axis=2) < 245) & valid
        lost = visible & np.any(np.abs(a.astype(np.int16) - b.astype(np.int16)) > 8, axis=2)
        if lost.any() or union < 128 or np.count_nonzero(ai & bi) / union < .8:
            raise ConversionError('ambiguous_scope',
                f'约 {item["timestamp"]:.3f} 秒存在无法确认被主曲覆盖的独有谱面，请指定时间范围后重试。')
        item['kind'] = 'covered_score_replaced'
        item['replacement_sample'] = first
        item['unobstructed_ink_iou'] = float(np.count_nonzero(ai & bi) / union)
        item['unobstructed_ink_union'] = int(union)
    adopted_start = records[first]['timestamp']
    adopted_end = records[last + 1]['timestamp'] if last + 1 < len(records) else end
    scope['effective_range_seconds'] = [adopted_start, adopted_end]
    for lo, hi in ((0, first), (last + 1, len(records))):
        cursor = lo
        while cursor < hi:
            finish = cursor + 1
            kind = observed[cursor]['kind']
            while finish < hi and observed[finish]['kind'] == kind:
                finish += 1
            scope['excluded_intervals'].append({
                'range_seconds': [start if cursor == 0 else records[cursor]['timestamp'],
                                  records[finish]['timestamp'] if finish < len(records) else end],
                'reason': kind, 'evidence_samples': [cursor, finish - 1]})
            cursor = finish
    return paths[first:last + 1], records[first:last + 1], scope
