"""Small provenance records for real observations; no continuation state."""
from dataclasses import asdict
import hashlib
import json
from PIL import Image
from pdf_export import PRINTABLE_WIDTH_INCHES
from video_seek import ConversionError


def save_crop(output, source_frame, bbox, stem):
    with Image.open(output / source_frame) as frame:
        crop = frame.convert('RGB').crop(bbox)
    original, printable = f'{stem}-original.png', f'{stem}.png'
    crop.save(output / original)
    crop.convert('L').save(output / printable)
    return {'source_frame': source_frame, 'bbox': bbox, 'original_image': original, 'image': printable,
            'original_sha256': hashlib.sha256((output / original).read_bytes()).hexdigest()}


def export_rows(output, tracks):
    rows = []
    for track in tracks:
        chosen = track.selected_observation
        dpi = (chosen.bbox[2] - chosen.bbox[0]) / PRINTABLE_WIDTH_INCHES
        if dpi < 150:
            raise ConversionError('low_resolution', '原生谱行宽度不足以达到 150 effective DPI。')
        row = save_crop(output, chosen.source_frame, chosen.bbox, f'row-{track.index:03d}')
        row.update(id=f'row{track.index}', index=track.index, global_y=track.global_y, timestamp=chosen.timestamp,
                   staff_y=chosen.staff_y, staff_spacing=chosen.staff_spacing,
                   selected_candidate=asdict(chosen), observations=[asdict(o) for o in track.observations],
                   quality={'native_width': chosen.bbox[2] - chosen.bbox[0], 'effective_dpi': round(dpi, 3),
                            'sharpness': chosen.sharpness, 'cursor_occluded': chosen.cursor_occluded,
                            'obstruction_detected': chosen.obstruction_detected, 'complete': chosen.complete})
        rows.append(row)
    return rows


def persist(result, output, origin=None):
    if origin:
        result['origin'] = origin
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result
