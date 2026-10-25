"""Distributed native observations before full sampling; uncertainty continues."""
import numpy as np

from . import video_seek


def inspect(source, metadata, metrics, check, *, start=0, end=None):
    from .imaging import system_groups
    end = metadata['duration'] if end is None else end
    if metadata['height'] < 9 or metadata['width'] < 20:
        raise video_seek.ConversionError('unsupported_layout', '画面尺寸不足以容纳可用五线谱。')
    reader = video_seek.VideoReader(source, metadata, metrics)
    observations = []
    try:
        for fraction in (0, .15, .3, .5, .7, .85, None):
            check()
            try:
                record, image = (reader.read_record(end=end) if fraction is None else
                    reader.read_record(start + (end - start) * fraction))
            except video_seek.ConversionError as error:
                if error.code != 'decode_failed':
                    raise
                # A low-frame-rate seek can land beyond the last native frame.
                # Full sequential sampling still determines source validity.
                continue
            try:
                if any((item['pts'], item['time_base']) == (record['pts'], record['time_base'])
                       for item in observations):
                    continue
                try:
                    _, staffs = system_groups(image)
                except video_seek.ConversionError:
                    staffs = 0
                gray = np.asarray(image.convert('L'))
                observations.append({**record, 'staff_structure': bool(staffs),
                    'paper_fraction': float((gray > 190).mean())})
            finally:
                image.close()
    finally:
        reader.close()
    # Absence at a few timestamps is not proof of absence between them.
    return {'decision': 'continue', 'reason': 'staff_observed' if any(
        item['staff_structure'] for item in observations) else 'uncertain',
        'observations': observations}
