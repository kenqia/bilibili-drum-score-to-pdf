"""Recover an ordered score using only evidence between neighboring windows."""
import hashlib
from pathlib import Path
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageFilter
from drum_score import ConversionError, analyze_frame, sample_video, staff_lines
from quality_score import assess, cursor_regions, printable, quality_report
from central_obstruction import split_white_bbox, complementary_windows


def comparison_mask(region, group, row_bounds, screen_reference=None, bbox=None):
    # Rasterized staff-line centers vary by half a pixel during a real scroll.
    # Use a fixed staff-relative band rather than changing its size with those
    # variations; registration handles the remaining subpixel observation error.
    spacing = int(round(group['spacing']))
    top = int(round(group['top'] - spacing * 6))
    bottom = top + spacing * 16
    comparison = Image.new('RGB', (region.width, bottom - top), 'white')
    source_start, source_stop = max(0, top), min(region.height, bottom)
    # Keep actual context for proving a changing row cut. If a lower crop
    # contains a next-row accent before its staff enters the viewport, the
    # translated observation must show that accent outside the corrected cut.
    comparison.paste(region.crop((0, source_start, region.width, source_stop)), (0, source_start - top))
    pixels = np.asarray(comparison)
    # Colored notation counts as ink too; only the detected playback cursor is ignored.
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    colored = (np.ptp(pixels, axis=2) > 20) & (pixels.min(axis=2) < 220)
    mask = (gray < 180) | colored
    if screen_reference is not None:
        # A translucent, screen-fixed white watermark can brighten a real stem
        # past the absolute threshold. Its initial score-free header provides
        # the actual backdrop at those screen coordinates. Require visible
        # contrast against that observation, never assume obscured ink exists.
        screen_top = bbox[1] + top
        low, high = max(0, -screen_top), min(len(mask), screen_reference.height - screen_top)
        if high > low:
            baseline = np.asarray(screen_reference.crop((bbox[0], screen_top + low,
                                                         bbox[2], screen_top + high)))
            valid = baseline.min(axis=2) >= 190
            # A one-pixel backdrop fringe varies with codec rasterization.
            bright = np.where(valid, cv2.cvtColor(baseline, cv2.COLOR_RGB2GRAY), 255).astype(np.uint8)
            backdrop = cv2.erode(bright, np.ones((3, 3), np.uint8))
            contrast = np.zeros(gray.shape, dtype=np.int16)
            contrast[low:high] = backdrop.astype(np.int16) - gray[low:high].astype(np.int16)
            threshold = backdrop.astype(np.int16) - 20
            mask[low:high] = np.where(valid, (gray[low:high] < threshold) | colored[low:high], mask[low:high])
            # The real watermark's codec shimmer produces isolated one-pixel
            # gray specks. Retain connected faint notation and every original
            # dark/colored pixel; this rule only rejects tiny weak gray islands
            # introduced by the backdrop-relative comparison, never PDF pixels.
            # Preserve even two-pixel stems with >=35 levels of real contrast.
            count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
            for index in range(1, count):
                x, y, width, height, area = stats[index]
                if area <= 2:
                    component = labels[y:y + height, x:x + width] == index
                    weak = ((gray[y:y + height, x:x + width] >= 180)
                            & (contrast[y:y + height, x:x + width] < 35)
                            & ~colored[y:y + height, x:x + width])
                    if weak[component].all():
                        mask[y:y + height, x:x + width][component] = False
    _, ignored = cursor_regions(comparison, spacing)
    # Enlarged comparison margins can leave the actual score window. Such
    # pixels are unavailable evidence, not PIL's default black crop padding.
    ignored[:source_start - top] = True
    ignored[source_stop - top:] = True
    domain = np.zeros(mask.shape, dtype=bool)
    low = max(source_start, row_bounds[0]) - top
    high = min(source_stop, row_bounds[1]) - top
    domain[low:high] = True
    return mask & domain, ignored & domain, pixels, mask, ignored, domain


def registered_row(left, right):
    """Bounded, uniquely fitted comparison coordinates; never used for output."""
    a, b = left['mask'], right['mask']
    height, width = a.shape
    if abs(height - b.shape[0]) > 3 or abs(width - b.shape[1]) > max(3, width * .005):
        return None
    candidates = []
    kernel = np.ones((3, 3), dtype=np.uint8)
    near_a = cv2.dilate(a.astype(np.uint8), kernel).astype(bool)
    scales = {(1., 1.), (width / b.shape[1], height / b.shape[0])}
    for sx, sy in sorted(scales):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                transform = np.float32([[sx, 0, dx], [0, sy, dy]])
                shifted = cv2.warpAffine(b.astype(np.float32), transform, (width, height), flags=cv2.INTER_LINEAR) >= .5
                hidden = cv2.warpAffine(right['ignored'].astype(np.float32), transform, (width, height), flags=cv2.INTER_LINEAR, borderValue=1) > 0
                support = cv2.warpAffine(np.ones(b.shape, dtype=np.uint8), transform, (width, height), flags=cv2.INTER_NEAREST).astype(bool)
                # Registration cannot crop away visible notation at either edge.
                inverse = cv2.invertAffineTransform(transform)
                back_support = cv2.warpAffine(np.ones(a.shape, dtype=np.uint8), inverse, (b.shape[1], b.shape[0]), flags=cv2.INTER_NEAREST).astype(bool)
                domain = cv2.warpAffine(right['row_domain'].astype(np.uint8), transform, (width, height), flags=cv2.INTER_NEAREST).astype(bool)
                common = left['row_domain'] & domain
                excluded_a = a & ~left['ignored'] & ~common
                excluded_b = shifted & ~hidden & ~common
                if excluded_a.any() or excluded_b.any():
                    context = cv2.warpAffine(right['context_mask'].astype(np.float32), transform, (width, height), flags=cv2.INTER_LINEAR) >= .5
                    context_hidden = cv2.warpAffine(right['context_ignored'].astype(np.float32), transform, (width, height), flags=cv2.INTER_LINEAR, borderValue=1) > 0
                    near_context = cv2.dilate(context.astype(np.uint8), kernel).astype(bool)
                    near_left_context = cv2.dilate(left['context_mask'].astype(np.uint8), kernel).astype(bool)
                    # A changing crop cannot discard notation. The other real
                    # window must expose the excluded ink at its translated
                    # location, outside that row's whitespace boundary.
                    if ((excluded_a & (~near_context | context_hidden)).any()
                            or (excluded_b & (~near_left_context | left['context_ignored'])).any()):
                        continue
                fitted_a, fitted_b = a & common, shifted & common
                back_common = cv2.warpAffine(common.astype(np.uint8), inverse, (b.shape[1], b.shape[0]), flags=cv2.INTER_NEAREST).astype(bool)
                if ((fitted_a & ~left['ignored'] & ~support).any()
                        or (b & back_common & ~right['ignored'] & ~back_support).any()):
                    continue
                available = ~(left['ignored'] | hidden)
                near_fitted_a = cv2.dilate(fitted_a.astype(np.uint8), kernel).astype(bool)
                near_b = cv2.dilate(fitted_b.astype(np.uint8), kernel).astype(bool)
                distant = ((fitted_a & ~near_b) | (fitted_b & ~near_fitted_a)) & available
                cost = (np.count_nonzero(distant), np.count_nonzero((fitted_a ^ fitted_b) & available))
                candidates.append((cost, dx, dy, fitted_b, hidden, sx, sy, common, fitted_a))
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: candidate[0])
    best = candidates[0]
    # Equal fits do not establish a unique registration.
    if any(candidate[0] == best[0] and (not np.array_equal(candidate[3], best[3])
                                                 or not np.array_equal(candidate[4], best[4]))
           for candidate in candidates[1:]):
        return None
    _, dx, dy, b, hidden, sx, sy, common, a = best
    near_a = cv2.dilate(a.astype(np.uint8), kernel).astype(bool)
    available = ~(left['ignored'] | hidden)
    near_b = cv2.dilate(b.astype(np.uint8), kernel).astype(bool)
    unmatched = ((a & ~near_b) | (b & ~near_a)) & available
    pixels = cv2.warpAffine(right['pixels'], np.float32([[sx, 0, dx], [0, sy, dy]]),
                            (width, height), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    if unmatched.any():
        # H.264 chroma ringing around the native blue rest bar crosses the
        # color threshold by up to 27 levels in the real 12, 15 and 125 second observations.
        # Only near-white blue fringes beside shared ink qualify.
        # Black notation and colored additions with actual contrast still fail.
        residual = np.abs(left['pixels'].astype(np.int16) - pixels.astype(np.int16)).max(axis=2)
        shared_edge = cv2.dilate((a & b & available).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        left_blue = left['pixels'][:, :, 2].astype(np.int16) - left['pixels'][:, :, 0] >= 5
        right_blue = pixels[:, :, 2].astype(np.int16) - pixels[:, :, 0] >= 5
        fringe = ((left['pixels'].min(axis=2) >= 200) & (pixels.min(axis=2) >= 200)
                  & left_blue & right_blue & (residual <= 32) & shared_edge)
        # At 183 seconds the watermark exposes one gray row-number edge
        # at 227 instead of 230. At 199 seconds a near-white beam fringe
        # differs by 29 levels. Require grayscale pixels beside shared ink;
        # changed faint notes and missing stems retain larger residuals.
        gray_fringe = ((left['pixels'].min(axis=2) >= 180) & (pixels.min(axis=2) >= 180)
                       & (np.ptp(left['pixels'], axis=2) <= 5) & (np.ptp(pixels, axis=2) <= 5)
                       & ((residual <= 8) | ((left['pixels'].min(axis=2) >= 200)
                                                & (pixels.min(axis=2) >= 200) & (residual <= 32)))
                       & shared_edge)
        unmatched &= ~(fringe | gray_fringe)
    if np.count_nonzero((a | b) & available) <= 30 or unmatched.any():
        return None
    transform = np.float32([[sx, 0, dx], [0, sy, dy]])
    context = cv2.warpAffine(right['context_mask'].astype(np.float32), transform, (width, height), flags=cv2.INTER_LINEAR) >= .5
    context_hidden = cv2.warpAffine(right['context_ignored'].astype(np.float32), transform, (width, height), flags=cv2.INTER_LINEAR, borderValue=1) > 0
    return dict(right, mask=context, ignored=context_hidden, pixels=pixels,
                registration={'scale_x': sx, 'scale_y': sy, 'dx': dx, 'dy': dy,
                              'screen_staff_shift': float(right['staff_top'] - left['staff_top']),
                              'policy': 'unique_bounded_comparison_only'})


def same_row(left, right):
    return registered_row(left, right) is not None


def same_cursor_position(left, right):
    # Content matching cannot assign an observation from a later repeated row.
    # Cursor recovery supports only a local held window, below half staff spacing.
    a, b = left['bbox'], right['bbox']
    allowance = min(left['staff_spacing'], right['staff_spacing']) / 2
    return (abs(left['staff_top'] - right['staff_top']) < allowance
            and abs(a[1] - b[1]) < allowance
            and abs(a[0] - b[0]) <= 3)


def save_row(candidate, output, index):
    name = f'images/row-{index:04d}.png'
    quality = candidate.get('quality') or assess(candidate['image'], candidate['staff_spacing'])
    original = f'images/original-row-{index:04d}.png'
    candidate['image'].save(output / original)
    printable(candidate['image']).save(output / name)
    return {'id': f'row-{index:04d}', 'image': name, 'original_image': original, 'quality': quality, 'observations': [{'timestamp': candidate['timestamp'], 'bbox': candidate['bbox'], 'cursor_occluded': quality['cursor_occluded'], 'sharpness': round(quality['sharpness'], 3)}], 'timestamp': candidate['timestamp'], 'bbox': candidate['bbox'], 'staff_top': candidate['staff_top'], 'staff_spacing': candidate['staff_spacing'], 'content_sha256': hashlib.sha256((output / name).read_bytes()).hexdigest()}


def window_rows(image, timestamp, screen_reference=None):
    if split_white_bbox(image) is not None:
        raise ConversionError('central_obstruction', '中央遮挡分割白底谱面，需要同处真实互补观察确认。')
    analysis = analyze_frame(image, allow_partial=True)
    region = image.crop(analysis['bbox']).convert('RGB')
    bbox = analysis['bbox']
    rows = []
    lines = staff_lines(region)
    pixels = np.asarray(region)
    ink = ((cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY) < 180)
           | ((np.ptp(pixels, axis=2) > 20) & (pixels.min(axis=2) < 220)))
    for group, (top, bottom) in zip(analysis['groups'], analysis['row_bounds']):
        crop = region.crop((0, top, region.width, bottom))
        mask, ignored, comparison_pixels, context_mask, context_ignored, row_domain = comparison_mask(region, group, (top, bottom), screen_reference, bbox)
        quality = assess(crop, group['spacing'])
        below = int(round(group['bottom'] + group['spacing'] * 5))
        quality['lower_boundary_supported'] = (any(line > group['bottom'] + 1 for line in lines)
                                               or not ink[below:].any())
        rows.append({'mask': mask, 'ignored': ignored, 'pixels': comparison_pixels, 'context_mask': context_mask,
                     'context_ignored': context_ignored, 'row_domain': row_domain, 'quality': quality, 'image': crop, 'timestamp': timestamp, 'bbox': [bbox[0], bbox[1] + top, bbox[2], bbox[1] + bottom], 'staff_top': bbox[1] + group['top'], 'staff_spacing': group['spacing']})
    return analysis, region, rows


def blurred_observation(image, references):
    """Fit a short blur to actual endpoints for analysis, never for PDF pixels."""
    observed = np.asarray(image.convert('RGB')).astype(np.int16)
    # Strong blur can erase a tiny supported mark below the residual threshold.
    # Do not fit it even when both endpoints look identical.
    for radius in range(1, 4):
        residuals = []
        for reference in references:
            candidate = np.asarray(reference.filter(ImageFilter.GaussianBlur(radius))).astype(np.int16)
            residual = np.abs(observed - candidate).max(axis=2).astype(np.float32)
            # A local bound catches small marks that a whole-window average hides.
            residuals.append(float(cv2.blur(residual, (3, 3)).max()))
        if max(residuals) <= 8:
            return {'blur_radius': radius, 'maximum_local_residual': round(max(residuals), 3)}
    return None


def clear_non_score_card(image):
    """Recognize a uniform card or crisp text; uncertain imagery is not ignorable."""
    pixels = np.asarray(image.convert('RGB')).astype(np.int16)
    # Allow only near-identical pixels, including video encoding variation.
    # Faint lines, gradients and other low-contrast imagery are still uncertain.
    if np.max(pixels.max(axis=(0, 1)) - pixels.min(axis=(0, 1))) <= 2:
        return True
    gray = np.asarray(image.convert('L'))
    background = float(np.median(gray))
    foreground = (np.abs(gray.astype(float) - background) > 35).astype(np.uint8)
    # Even a single partial staff line prevents classification as a title card.
    staff_signal = (np.abs(gray.astype(float) - background) > 2).astype(np.uint8)
    horizontal = cv2.morphologyEx(staff_signal, cv2.MORPH_OPEN,
                                 np.ones((1, max(35, image.width // 32)), np.uint8))
    if horizontal.any() or foreground.mean() > .08:
        return False
    count, _, stats, _ = cv2.connectedComponentsWithStats(foreground, 8)
    components = [box for box in stats[1:] if box[4] >= 8]
    if len(components) < 3:
        return False
    if any(box[2] > image.width * .15 or box[3] > image.height * .15 for box in components):
        return False
    edges = cv2.Laplacian(gray, cv2.CV_64F)
    # Sharpness is measured on the actual foreground, not diluted by empty pixels.
    return float((edges[foreground.astype(bool)] ** 2).mean()) >= 1000


def restore_rows(source, output, metadata, decisions=None):
    output = Path(output)
    (output / 'images').mkdir(parents=True, exist_ok=True)
    (output / 'evidence').mkdir(parents=True, exist_ok=True)
    delivered, seams, header = [], [], None
    previous, first, last = None, None, None
    screen_reference, comparison_backdrop = None, None
    decisions = decisions or {}
    accepted, gaps = {}, []
    best_candidates = {}
    first_prefix_depth = 0
    cursor_runs, cursor_unproven = {}, {}
    pending, recoveries, unreadable = [], [], []
    ignored_edges = []
    followup = None

    def cursor_observation(row, position):
        # Masked matching is provisional. A run needs complementary real cursor
        # positions, all visible pixels consistent, then an actual clear row.
        run = cursor_runs.get(position)
        if run is not None and not same_cursor_position(run, row):
            # A proved scroll ends a stationary observation run. Its already
            # complete complementary coverage may be checked against an actual
            # earlier clean observation at that same screen position. Never
            # borrow visibility from the translated window to fill unknowns.
            clean = best_candidates[position]
            aligned = (registered_row(run, clean)
                       if not run['ignored'].any() and position not in cursor_unproven
                       and not clean['quality']['cursor_occluded']
                       and same_cursor_position(run, clean) else None)
            if aligned is not None:
                name = f'evidence/cursor-reference-{position:04d}-{int(round(clean["timestamp"] * 1000)):08d}.png'
                clean['image'].save(output / name)
                clear_item = {'timestamp': clean['timestamp'], 'image': name,
                              'registration': aligned['registration']}
                delivered[position].setdefault('cursor_recoveries', []).append({
                    'before': {'timestamp': run['timestamp'], 'image': run['image']},
                    'after': clear_item, 'clear_timestamp': clean['timestamp'],
                    'completed_timestamp': run['observations'][-1],
                    'observations': run['observations'], 'evidence': run['evidence'],
                    'policy': 'complementary_stationary_visible_pixels_with_prior_clean_row'})
                del cursor_runs[position]
                run = None
        if row['quality']['cursor_occluded']:
            if run is None:
                name = f'evidence/cursor-{position:04d}-{int(round(row["timestamp"] * 1000)):08d}.png'
                row['image'].save(output / name)
                run = {'timestamp': row['timestamp'], 'image': name,
                       'mask': row['mask'].copy(), 'ignored': row['ignored'].copy(), 'pixels': row['pixels'].copy(),
                       'context_mask': row['context_mask'].copy(),
                       'context_ignored': row['context_ignored'].copy(), 'row_domain': row['row_domain'].copy(),
                       'bbox': row['bbox'], 'staff_top': row['staff_top'],
                       'staff_spacing': row['staff_spacing'], 'observations': [],
                       'evidence': [{'timestamp': row['timestamp'], 'image': name}]}
                cursor_runs[position] = run
            else:
                aligned = registered_row(run, row) if same_cursor_position(run, row) else None
                compatible = aligned is not None
                if not compatible:
                    name = f'evidence/cursor-conflict-{position:04d}-{int(round(row["timestamp"] * 1000)):08d}.png'
                    row['image'].save(output / name)
                    cursor_unproven.setdefault(position, {'timestamp': row['timestamp'], 'image': name})
                elif compatible:
                    exposed = run['ignored'] & ~aligned['ignored']
                    if exposed.any():
                        name = f'evidence/cursor-{position:04d}-{int(round(row["timestamp"] * 1000)):08d}.png'
                        row['image'].save(output / name)
                        run['evidence'].append({'timestamp': row['timestamp'], 'image': name,
                                                'registration': aligned['registration']})
                    run['mask'][exposed] = aligned['mask'][exposed]
                    run['pixels'][exposed] = aligned['pixels'][exposed]
                    run['context_mask'][exposed] = aligned['mask'][exposed]
                    run['context_ignored'][exposed] = False
                    run['ignored'] &= aligned['ignored']
            run['observations'].append(row['timestamp'])
        elif run is not None:
            name = f'evidence/cursor-clear-{position:04d}-{int(round(row["timestamp"] * 1000)):08d}.png'
            row['image'].save(output / name)
            aligned = registered_row(run, row) if same_cursor_position(run, row) else None
            clear_item = {'timestamp': row['timestamp'], 'image': name}
            if aligned is not None:
                clear_item['registration'] = aligned['registration']
            delivered[position].setdefault('cursor_followups', []).append(clear_item)
            item = {'timestamp': run['timestamp'], 'image': run['image']}
            if (position in cursor_unproven or run['ignored'].any() or aligned is None):
                cursor_unproven.setdefault(position, item)
            else:
                delivered[position].setdefault('cursor_recoveries', []).append({
                    'before': item, 'after': clear_item, 'clear_timestamp': row['timestamp'],
                    'observations': run['observations'], 'evidence': run['evidence'],
                    'policy': 'complementary_same_position_visible_pixels_then_clear_row'})
            del cursor_runs[position]

    def track(row, position=None):
        nonlocal first_prefix_depth
        if position is None:
            if not delivered:
                # The real title/tempo lives inside the first crop. A sharper
                # later crop may be missing it after scrolling out of view.
                prefix_height = max(0, int(row['staff_top'] - row['bbox'][1] - row['staff_spacing'] * 4))
                prefix = np.asarray(row['image'].convert('RGB'))[:prefix_height]
                if prefix.size:
                    ink = ((cv2.cvtColor(prefix, cv2.COLOR_RGB2GRAY) < 180)
                           | ((np.ptp(prefix, axis=2) > 20) & (prefix.min(axis=2) < 220)))
                    occupied = np.where(ink.any(axis=1))[0]
                    if len(occupied):
                        first_prefix_depth = row['staff_top'] - row['bbox'][1] - int(occupied[0])

            position = len(delivered)
            delivered.append(save_row(row, output, position + 1))
            best_candidates[position] = row
            cursor_observation(row, position)
            return position
        record = delivered[position]
        if position not in best_candidates:
            return position  # Explicitly supplied content is never replaced.
        observation = {'timestamp': row['timestamp'], 'bbox': row['bbox'], 'cursor_occluded': row['quality']['cursor_occluded'], 'sharpness': round(row['quality']['sharpness'], 3)}
        observations = record.get('observations', []) + [observation]
        cursor_recoveries = record.get('cursor_recoveries', [])
        cursor_followups = record.get('cursor_followups', [])
        old = best_candidates[position]
        def rank(candidate):
            return (not candidate['quality']['cursor_occluded'], candidate['quality'].get('lower_boundary_supported', False),
                    candidate['quality']['sharpness'], -candidate['timestamp'])
        retains_prefix = position != 0 or row['staff_top'] - row['bbox'][1] >= first_prefix_depth - 2
        if retains_prefix and rank(row) > rank(old):
            delivered[position] = save_row(row, output, position + 1)
            best_candidates[position] = row
        delivered[position]['observations'] = observations
        if cursor_recoveries:
            delivered[position]['cursor_recoveries'] = cursor_recoveries
        if cursor_followups:
            delivered[position]['cursor_followups'] = cursor_followups
        cursor_observation(row, position)
        return position

    def evidence(image, timestamp, index):
        name = f'evidence/window-{index:04d}.png'
        image.save(output / name)
        return {'timestamp': timestamp, 'image': name}

    def uncertain(kind, question, item, position, reference=None, candidates=None, overlap_counts=None):
        issue = {'id': f'{kind}-{position:04d}' if kind == 'cursor_occlusion' else f'{kind}-{position:04d}-{int(round(item["timestamp"] * 1000)):08d}', 'kind': kind, 'question': question, 'timestamp': item['timestamp'], 'image': item['image'], 'position': position, 'status': 'unresolved', 'choices': ['supplement', 'accept_missing']}
        if kind in {'ambiguous_overlap', 'ambiguous_motion', 'ambiguous_repeat'}:
            issue['choices'].remove('supplement')
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
        error.progress = {'rows': delivered, 'header': header, 'seams': seams, 'comparison_backdrop': comparison_backdrop, 'recoveries': recoveries, 'unreadable_observations': unreadable, 'ignored_edges': ignored_edges, 'readable_followup': followup, 'boundaries': {'start': first, 'end': item}, 'candidate_rows': candidate_rows, 'continuation': {'requires_original_video': True, 'requires_replay': True, 'stop_timestamp': item['timestamp'], 'confirmed_prefix_rows': len(delivered)}, 'decisions': accepted, 'gaps': gaps, 'limitations': [gap['question'] for gap in gaps], 'quality': quality_report(metadata, delivered)}
        raise error

    with tempfile.TemporaryDirectory(prefix='drum-score-') as scratch:
        frames = sample_video(source, scratch)
        frame_count = 0
        consumed = []
        for frame_index, (timestamp, file) in enumerate(frames):
            frame_count = frame_index + 1
            # Keep just the prior readable reference and current batch. Pending
            # observations already have durable evidence copies in the task.
            retained = {item['file'] for item in (previous, last) if item}
            for old in consumed[:]:
                if old not in retained:
                    old.unlink(missing_ok=True)
                    consumed.remove(old)
            consumed.append(file)
            with Image.open(file) as image:
                try:
                    analysis, region, current = window_rows(image, timestamp, screen_reference)
                except ConversionError as error:
                    item = evidence(image, timestamp, frame_index)
                    unreadable.append(dict(item))
                    # Keep the failure value, not its traceback and decoded pixels.
                    pending.append({'evidence': item, 'file': output / item['image'], 'error': (error.code, str(error)), 'non_score': clear_non_score_card(image)})
                    continue
                if (screen_reference is not None and not analysis['partial_top']
                        and current[0]['staff_top'] - current[0]['staff_spacing'] * 6 >= screen_reference.height):
                    # Refresh while the whole comparison band is still below
                    # this margin. Video-overlay opacity can vary over time.
                    screen_reference = image.crop((0, 0, image.width, screen_reference.height)).convert('RGB')
                    screen_reference.save(output / 'evidence/comparison-backdrop.png')
                    comparison_backdrop['reference'] = {'timestamp': timestamp,
                                                         'image': 'evidence/comparison-backdrop.png'}
                if pending and not previous and all(entry['non_score'] for entry in pending):
                    ignored_edges.append({'edge': 'start', 'start_timestamp': pending[0]['evidence']['timestamp'], 'end_timestamp': pending[-1]['evidence']['timestamp'], 'observations': [entry['evidence'] for entry in pending], 'policy': 'uniform_or_crisp_text_card_without_staff_signal'})
                    pending.clear()
                if pending:
                    followup = evidence(image, timestamp, frame_index)
                    recovered = []
                    same_position = previous and previous['analysis']['bbox'] == analysis['bbox'] and len(previous['rows']) == len(current) and all(abs(a['staff_top'] - b['staff_top']) <= 1 and same_row(a, b) for a, b in zip(previous['rows'], current))
                    if same_position and timestamp - previous['timestamp'] <= 3:
                        with Image.open(previous['file']) as before:
                            references = [before.convert('RGB'), image.convert('RGB')]
                        for entry in pending:
                            with Image.open(entry['file']) as blurred:
                                match = blurred_observation(blurred, references)
                            if match is None:
                                break
                            recovered.append(dict(entry['evidence'], **match))
                    central = None
                    # This limited proof requires a unique held occurrence, a
                    # bounded run, and complementary real visibility. Identical
                    # clean brackets alone never establish hidden contents.
                    unique_rows = same_position and all(
                        sum(same_row(a, b) for a in previous['rows']) == 1 for b in current)
                    if unique_rows and timestamp - previous['timestamp'] <= 6:
                        from contextlib import ExitStack
                        with ExitStack() as stack:
                            before = stack.enter_context(Image.open(previous['file']))
                            observations = [(entry['evidence'], stack.enter_context(Image.open(entry['file']))) for entry in pending]
                            central = complementary_windows(before, image, observations)
                    if central is not None:
                        with Image.open(previous['file']) as before:
                            before_item = evidence(before, previous['timestamp'], previous['frame_index'])
                        recoveries.append({'before': before_item, 'after': followup,
                                           'observations': central, 'coverage_complete': True,
                                           'row_ids': [delivered[index]['id'] for index in previous['indices']],
                                           'policy': 'complementary_split_white_windows_then_actual_clean_rows',
                                           'pixel_mapping': 'actual_clean_row_no_stitching'})
                    elif len(recovered) == len(pending):
                        with Image.open(previous['file']) as before:
                            before_item = evidence(before, previous['timestamp'], previous['frame_index'])
                        recoveries.append({'before': before_item, 'after': evidence(image, timestamp, frame_index), 'observations': recovered, 'policy': 'same_position_clear_bracket_and_local_blur_residual'})
                    else:
                        if not previous:
                            first = pending[0]['evidence']
                        else:
                            with Image.open(previous['file']) as before:
                                previous['evidence'] = evidence(before, previous['timestamp'], previous['frame_index'])
                        uncertain('unreadable_window', '已检查后续清晰画面，但无法用相邻真实观察确认该模糊窗口连续完整。请补图或明确接受缺失。', pending[0]['evidence'], len(delivered), previous['evidence'] if previous else None, current if not previous else None)
                    pending.clear()
                item = None
                if previous is None:
                    item = evidence(image, timestamp, frame_index)
                    first = first or item
                    reference_bottom = analysis['bbox'][1] + analysis['row_bounds'][0][0]
                    screen_reference = image.crop((0, 0, image.width, reference_bottom)).convert('RGB')
                    comparison_backdrop = {'reference': item, 'bbox': [0, 0, image.width, reference_bottom],
                                           'policy': 'visible_ink_contrast_against_observed_bright_header',
                                           'minimum_visible_contrast': 20, 'minimum_reference_channel': 190}
                    if analysis['partial_top']:
                        uncertain('start_gap', '视频开头存在上边缘残行，无法证明曲谱从完整开头开始。', item, 0, candidates=current)
                    top = analysis['row_bounds'][0][0]
                    head = region.crop((0, 0, region.width, top))
                    if (np.asarray(head.convert('L')) < 180).any():
                        head.save(output / 'images/original-header.png')
                        printable(head).save(output / 'images/header.png')
                        bbox = analysis['bbox']
                        header = {'image': 'images/header.png', 'original_image': 'images/original-header.png', 'timestamp': timestamp, 'bbox': [bbox[0], bbox[1], bbox[2], bbox[1] + top]}
                    current_indices = [track(row) for row in current]
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
                        for position, row in zip(previous['indices'], current):
                            track(row, position)
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
                    current_indices = previous['indices'][-count:] if count else []
                    for position, row in zip(current_indices, current[:count]):
                        track(row, position)
                    if count == len(current):
                        # Rows leaving the top edge add no new content. Keep the
                        # earlier anchor to prove cumulative motion at the next join.
                        previous.update(rows=current, indices=current_indices, analysis=analysis, evidence=item, file=file, timestamp=timestamp, frame_index=frame_index)
                        last = {'timestamp': timestamp, 'file': file, 'partial_bottom': analysis['partial_bottom']}
                        continue
                    seam = {'id': f'seam-{len(seams) + 1:04d}', 'position': len(delivered), 'overlap_rows': count, 'before': previous['evidence'], 'after': item, 'vertical_shift': float(np.median(shifts)) if shifts else None, 'cumulative_vertical_shift': float(np.median(accumulated)) if accumulated else None, 'matched_rows': [row['id'] for row in delivered[-count:]] if count else []}
                    seam['registrations'] = [dict(row_id=delivered[position]['id'], **match['registration'])
                                             for position, left, right in zip(current_indices, prior[-count:], current[:count])
                                             if (match := registered_row(left, right)) is not None] if count else []
                    seams.append(seam)
                    current_indices += [track(row) for row in current[count:]]
                previous = {'rows': current, 'indices': current_indices, 'anchor_rows': current, 'analysis': analysis, 'evidence': item, 'file': file, 'timestamp': timestamp, 'frame_index': frame_index}
                last = {'timestamp': timestamp, 'file': file, 'partial_bottom': analysis['partial_bottom']}
        if not previous:
            if pending:
                raise ConversionError(*pending[0]['error'])
            raise ConversionError('decode_failed', '视频中没有可读取的完整谱行。')
        trailing_card = None
        if pending and not last['partial_bottom'] and all(entry['non_score'] for entry in pending):
            ignored_edges.append({'edge': 'end', 'start_timestamp': pending[0]['evidence']['timestamp'], 'end_timestamp': pending[-1]['evidence']['timestamp'], 'observations': [entry['evidence'] for entry in pending], 'policy': 'uniform_or_crisp_text_card_without_staff_signal'})
            trailing_card = pending[-1]['evidence']
            pending.clear()
        if pending:
            uncertain('unreadable_window', '视频结尾仍不清晰，没有后续真实清晰画面可确认末尾完整。', pending[0]['evidence'], len(delivered), previous['evidence'])
            last = {'timestamp': pending[-1]['evidence']['timestamp'], 'file': pending[-1]['file'], 'partial_bottom': False}
            pending.clear()
        with Image.open(last['file']) as image:
            end = evidence(image, last['timestamp'], frame_count)
        if trailing_card:
            end = trailing_card
        if last['partial_bottom']:
            uncertain('end_gap', '视频结尾存在下边缘残行，无法确认末尾谱段完整。', end, len(delivered), previous['evidence'])
    for position in cursor_unproven.keys() | cursor_runs.keys():
        delivered[position]['cursor_content_unproven'] = True
    for position, record in enumerate(delivered):
        if record.get('quality', {}).get('cursor_occluded') or position in cursor_unproven or position in cursor_runs:
            item = cursor_unproven.get(position) or cursor_runs.get(position) or {'timestamp': record['timestamp'], 'image': record['original_image']}
            item = {'timestamp': item['timestamp'], 'image': item['image']}
            references = record.get('cursor_followups', [])
            uncertain('cursor_occlusion', '该谱行的光标遮挡观察没有同位置互补清晰证据，无法证明隐藏内容相同。请补充完整谱行，或明确接受此处缺失；不会擦除或猜补被挡音符。', item, position, references[-1] if references else None)
    return header, delivered, {'seams': seams, 'comparison_backdrop': comparison_backdrop, 'recoveries': recoveries, 'unreadable_observations': unreadable, 'ignored_edges': ignored_edges, 'boundaries': {'start': first, 'end': end}, 'decisions': accepted, 'gaps': gaps, 'limitations': [gap['question'] for gap in gaps], 'quality': quality_report(metadata, delivered)}
