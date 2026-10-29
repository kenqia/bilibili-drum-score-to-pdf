"""Detached annotation groups supported by same-column vertical evidence only."""
import math

import numpy as np

MAX_COMPONENTS = 4096
MAX_RAY_PIXELS = 20_000_000


def assign(rgb, labels, stats, owners, *, top, begin, end, spacing):
    """Return ownership without letting detached marks become reference ink."""
    if len(stats) > MAX_COMPONENTS:
        return None, [], 'annotation_component_limit'
    # Conservatively treat all detached ink sharing a vertical band as one
    # annotation, regardless of horizontal letter spacing. This can over-group
    # unrelated marks and refuse a cut, but cannot assign sparse R R L letters
    # separately or separate a frame from text contained within its height.
    candidates = sorted((int(y), int(y + h), label)
                        for label, (_, y, _, h, _) in enumerate(stats[1:], 1)
                        if owners[label] == 0)
    membership = []
    band_end = -1
    tolerance = max(2, math.ceil(spacing * .25))
    for y, stop, label in candidates:
        if not membership or y > band_end + tolerance:
            membership.append([])
            band_end = stop
        else:
            band_end = max(band_end, stop)
        membership[-1].append(label)
    # Freeze reference ownership. No inferred annotation can support another.
    anchor = owners[labels]
    black = rgb.max(axis=2) < 180
    reference = np.where(black, anchor, 0)
    result = owners.copy()
    records = []
    ray_pixels = 0
    for members in membership:
        boxes = stats[members]
        x0, y0 = boxes[:, :2].min(axis=0)
        x1 = int((boxes[:, 0] + boxes[:, 2]).max())
        y1 = int((boxes[:, 1] + boxes[:, 3]).max())
        x0, y0 = int(x0), int(y0)
        if y1 + top <= begin or y0 + top >= end:
            continue
        ray_pixels += (x1 - x0) * len(labels)
        if ray_pixels > MAX_RAY_PIXELS:
            return None, records, 'annotation_ray_limit'
        group = np.isin(labels[y0:y1, x0:x1], members)
        distances = []
        covered = 0
        for local_x in range(x1 - x0):
            pixels = np.flatnonzero(group[:, local_x])
            if not len(pixels):
                continue
            covered += 1
            first, last = y0 + int(pixels[0]), y0 + int(pixels[-1])
            column = reference[:, x0 + local_x]
            above = np.flatnonzero(column[:first] != 0)
            below = np.flatnonzero(column[last + 1:] != 0)
            # First hits carry their established staff ownership. A lower
            # staff's upward stem must never be relabeled as upper staff ink.
            hits = {}
            if len(above):
                y = int(above[-1])
                hits[int(column[y])] = first - y
            if len(below):
                y = last + 1 + int(below[0])
                owner = int(column[y])
                hits[owner] = min(hits.get(owner, float('inf')), y - last)
            if 1 in hits and 2 in hits:
                distances.append((hits[1], hits[2]))
        evidence = {'bbox': [x0, y0 + top, x1 - x0, y1 - y0],
                    'components': [int(value) for value in members],
                    'covered_columns': covered, 'paired_columns': len(distances),
                    'reference': 'frozen_anchored_dark_rgb_max_lt_180',
                    'reason': 'vertical_evidence_missing', 'owner': None}
        records.append(evidence)
        if len(distances) < max(3, math.ceil(covered * .6)):
            return None, records, 'detached_mark_ambiguous'
        values = np.asarray(distances, dtype=float)
        medians = np.median(values, axis=0)
        difference = values[:, 1] - values[:, 0]
        margin = max(2., spacing * .5)
        upper_votes = float((difference >= margin).mean())
        lower_votes = float((difference <= -margin).mean())
        evidence.update(median_upper_staff_distance=float(medians[0]),
                        median_lower_staff_distance=float(medians[1]),
                        upper_vote_fraction=upper_votes, lower_vote_fraction=lower_votes)
        if (upper_votes >= .8 and lower_votes <= .1
                and medians[1] - medians[0] >= margin and medians[1] >= 1.5 * medians[0]):
            owner = 1
        elif (lower_votes >= .8 and upper_votes <= .1
              and medians[0] - medians[1] >= margin and medians[0] >= 1.5 * medians[1]):
            owner = 2
        else:
            evidence['reason'] = 'vertical_columns_conflict_or_tie'
            return None, records, 'detached_mark_ambiguous'
        result[members] = owner
        evidence.update(owner=owner, reason='vertical_columns_agree')
    return result, records, 'vertical_groups_assigned'
