"""Adaptive visual seek, ordered geometry, and a few extra clean candidates."""
from dataclasses import dataclass
from statistics import median
from PIL import Image
import cv2
import numpy as np
from score_detect import analyze_frame
from video_seek import ConversionError
from cursor_detect import cursor_occluded, obstruction_detected, stationary_overlays
from viewport_tracker import RowObservation, ViewportTracker, ViewportError, translation
from candidate_selector import select


@dataclass
class Viewport:
    timestamp: float
    frame: str
    rows: list
    detection: dict


class ViewportSampler:
    def __init__(self, reader, output, metrics):
        self.reader, self.output, self.metrics = reader, output, metrics
        self.tracker = ViewportTracker()
        self.cache = {}
        self.header = None
        self.transitions = []
        self.last = None
        self.overlays = []

    def observe(self, requested=None):
        if requested in self.cache:
            return self.cache[requested]
        timestamp, image = self.reader.read(requested)
        self.metrics['analyzed_frames'] += 1
        name = f'frames/{self.metrics["analyzed_frames"]:03d}.png'
        (self.output / 'frames').mkdir(exist_ok=True)
        image.save(self.output / name)
        self.last = (timestamp, name)
        detection = analyze_frame(image)
        x0, y0, x1, _ = detection['bbox']
        rows = []
        (self.output / 'observations').mkdir(exist_ok=True)
        for index, (group, bounds) in enumerate(zip(detection['groups'], detection['row_bounds'])):
            bbox = [x0, y0 + bounds[0], x1, y0 + bounds[1]]
            crop = image.crop(bbox)
            crop_name = f'observations/{self.metrics["analyzed_frames"]:03d}-{index}.png'
            crop.save(self.output / crop_name)
            rows.append(RowObservation(timestamp, bbox, y0 + group['top'], group['spacing'],
                                       cursor_occluded=cursor_occluded(crop, group['spacing']),
                                       obstruction_detected=obstruction_detected(crop, group['top'] - bounds[0], group['spacing'])
                                       or any(bbox[0] < b[2] and bbox[2] > b[0] and bbox[1] < b[3] and bbox[3] > b[1] for b in self.overlays),
                                       sharpness=float(cv2.Laplacian(np.asarray(crop.convert('L')), cv2.CV_64F).var()),
                                       original_crop=crop_name, source_frame=name))
        self.metrics['candidate_observations'] += len(rows)
        viewport = Viewport(timestamp, name, rows, detection)
        self.cache[requested] = viewport
        return viewport

    def accept(self, viewport):
        previous = self.tracker.previous
        shift = self.tracker.accept(viewport.rows)
        if shift:
            self.transitions.append({'timestamp': viewport.timestamp, 'scroll_delta': shift,
                                     'scroll_offset': self.tracker.scroll_offset, 'source_frame': viewport.frame})
            self.metrics['selected_keyframes'] += 1
        if previous and shift >= median(r.staff_spacing for r in previous) * 2:
            with Image.open(self.output / previous[0].source_frame) as old, Image.open(self.output / viewport.frame) as new:
                spacing = median(r.staff_spacing for r in previous)
                x0, y0, x1, y1 = viewport.detection['bbox']
                boxes = stationary_overlays(old, new, spacing)
                self.overlays.extend(b for b in boxes if x0 + spacing <= b[0] and b[2] <= x1 - spacing
                                     and y0 + spacing <= b[1] and b[3] <= y1 - spacing)
        for cached in self.cache.values():
            for row in cached.rows:
                if any(row.bbox[0] < box[2] and row.bbox[2] > box[0]
                       and row.bbox[1] < box[3] and row.bbox[3] > box[1] for box in self.overlays):
                    row.obstruction_detected = True
        return shift

    def run(self):
        for requested in (0, .5, 2, 4):
            if requested >= self.reader.metadata['duration']:
                raise ViewportError('unsupported_layout')
            try:
                current = self.observe(requested)
                break
            except ConversionError as error:
                if error.code != 'unsupported_layout' or requested == 4:
                    raise
        if current.detection['partial_top']:
            raise ViewportError('start_partial')
        self.header = {'timestamp': current.timestamp, 'bbox': current.detection['header_bbox'],
                       'source_frame': current.frame}
        self.accept(current)
        self.metrics['selected_keyframes'] = 1
        step, advancing, stationary_since = 2.0, False, current.timestamp
        duration = self.reader.metadata['duration']
        while current.timestamp + step < duration - .1:
            target = current.timestamp + step
            probe = self.observe(target)
            try:
                shift = translation(current.rows, probe.rows)
            except ViewportError:
                if step <= .5:
                    raise
                step /= 2
                continue
            pitch = median(b.staff_y - a.staff_y for a, b in zip(current.rows, current.rows[1:]))
            if shift > pitch * .8 and step > 1:
                step /= 2
                continue
            moving = shift > median(r.staff_spacing for r in probe.rows)
            if moving and target + .3 < duration:
                stable = self.observe(target + .3)
                if translation(probe.rows, stable.rows) > median(r.staff_spacing for r in probe.rows) * .5:
                    if step <= .5:
                        raise ViewportError('ambiguous_scroll')
                    step /= 2
                    continue
            self.accept(probe)
            current = probe
            if moving:
                advancing, step, stationary_since = True, 2.0, current.timestamp
            else:
                cap = 16.0 if current.timestamp - stationary_since >= 24 else 8.0
                step = min(step * 2, cap if advancing else 32.0)
        tail = self.observe()
        self.accept(tail)
        if tail.detection['partial_bottom']:
            raise ViewportError('end_partial')
        # Extra observations stay inside the row's observed time interval.
        budget = 12
        for track in self.tracker.rows:
            try:
                select(track)
                continue
            except ViewportError:
                pass
            begin, end = track.observations[0].timestamp, track.observations[-1].timestamp
            for fraction in (.25, .5, .75):
                if budget <= 0:
                    break
                budget -= 1
                viewport = self.observe(begin + (end - begin) * fraction)
                neighbors = sorted(self.cache.values(), key=lambda v: v.timestamp)
                previous = max((v for v in neighbors if v.timestamp < viewport.timestamp), key=lambda v: v.timestamp, default=None)
                if previous is None:
                    continue
                shift = translation(previous.rows, viewport.rows)
                offsets = [r.global_y - o.staff_y for r in self.tracker.rows for o in r.observations
                           if o.source_frame == previous.frame]
                if not offsets:
                    continue
                offset = median(offsets) + shift
                for row in viewport.rows:
                    if abs(row.staff_y + offset - track.global_y) < row.staff_spacing * .25:
                        track.observations.append(row)
                try:
                    select(track)
                    break
                except ViewportError:
                    continue
            select(track)
        return self.tracker.rows
