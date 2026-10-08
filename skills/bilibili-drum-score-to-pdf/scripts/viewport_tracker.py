"""Ordered staff geometry over one fixed-scale, upward-moving score."""
from dataclasses import dataclass, field
from statistics import median


class ViewportError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass
class RowObservation:
    timestamp: float
    bbox: list
    staff_y: float
    staff_spacing: float
    complete: bool = True
    cursor_occluded: bool = False
    obstruction_detected: bool = False
    sharpness: float = 0
    original_crop: str = ''
    source_frame: str = ''


@dataclass
class RowTrack:
    index: int
    global_y: float
    observations: list = field(default_factory=list)
    selected_observation: RowObservation | None = None


def translation(old, new):
    """Find a unique contiguous old suffix / new prefix overlap."""
    old = [r for r in old if r.complete]
    new = [r for r in new if r.complete]
    if min(len(old), len(new)) < 2:
        raise ViewportError('no_overlap')
    spacing = median(r.staff_spacing for r in old)
    if any(abs(r.staff_spacing / spacing - 1) > .06 for r in new):
        raise ViewportError('unsupported_layout')
    tolerance = spacing * .22
    if any(abs((r.bbox[2] - r.bbox[0]) / (old[0].bbox[2] - old[0].bbox[0]) - 1) > .01
           or abs(r.bbox[0] - old[0].bbox[0]) > tolerance for r in new):
        raise ViewportError('unsupported_layout')
    matches = []
    backward_count = 0
    for i in range(len(old)):
        count = min(len(old) - i, len(new))
        if count < 2:
            continue
        deltas = [old[i + k].staff_y - new[k].staff_y for k in range(count)]
        shift = median(deltas)
        if max(abs(d - shift) for d in deltas) > tolerance:
            continue
        if shift < -tolerance:
            backward_count = max(backward_count, count)
        else:
            matches.append((count, max(0, shift)))
    if not matches:
        raise ViewportError('no_overlap')
    best = max(count for count, _ in matches)
    if backward_count > best:
        raise ViewportError('no_overlap')
    shifts = [shift for count, shift in matches if count == best]
    if max(shifts) - min(shifts) > tolerance:
        raise ViewportError('ambiguous_scroll')
    return median(shifts)


class ViewportTracker:
    def __init__(self):
        self.rows = []
        self.previous = []
        self.scroll_offset = 0.0

    def accept(self, observations):
        complete = [r for r in observations if r.complete]
        if not complete:
            raise ViewportError('unsupported_layout')
        shift = translation(self.previous, complete) if self.previous else 0.0
        self.scroll_offset += shift
        tolerance = median(r.staff_spacing for r in complete) * .25
        for observation in complete:
            global_y = observation.staff_y + self.scroll_offset
            near = [r for r in self.rows if abs(r.global_y - global_y) <= tolerance]
            if near:
                near[0].observations.append(observation)
            else:
                if self.rows and global_y <= self.rows[-1].global_y:
                    raise ViewportError('ambiguous_scroll')
                self.rows.append(RowTrack(len(self.rows), global_y, [observation]))
        self.previous = complete
        return shift
