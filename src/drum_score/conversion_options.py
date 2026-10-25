"""Shared, strict conversion options for Python, CLI, queue and HTTP."""
import math
from .video_seek import ConversionError

DEFAULT_OPTIONS = {'start_seconds': 0, 'end_seconds': None, 'region_percent': None,
                   'ignore_fixed_overlays': True}


def normalize_options(options=None):
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options) - set(DEFAULT_OPTIONS):
        raise ConversionError('invalid_request', '高级选项字段无效。')
    values = {**DEFAULT_OPTIONS, **options}
    def number(value):
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    start, end = values['start_seconds'], values['end_seconds']
    if not number(start) or start < 0 or (end is not None and (not number(end) or end <= start)):
        raise ConversionError('invalid_request', '开始和结束时间必须为有限秒数，开始不小于零，结束大于开始。')
    region = values['region_percent']
    if region is not None:
        if (not isinstance(region, (list, tuple)) or len(region) != 4
            or not all(number(value) for value in region)
            or not (0 <= region[0] < region[2] <= 100 and 0 <= region[1] < region[3] <= 100)):
            raise ConversionError('invalid_request', '谱区须按完整画面的左、上、右、下百分比填写，范围为0到100，右下须大于左上。')
        values['region_percent'] = list(region)
    if type(values['ignore_fixed_overlays']) is not bool:
        raise ConversionError('invalid_request', '自动忽略固定覆盖物须为布尔值。')
    return values


def resolve_options(options, metadata):
    start = options['start_seconds']
    end = metadata['duration'] if options['end_seconds'] is None else options['end_seconds']
    if start >= metadata['duration'] or end > metadata['duration']:
        raise ConversionError('invalid_request', '所选时间范围超出来源视频时长。')
    region = options['region_percent']
    if region is not None:
        region = tuple(int(value * dimension / 100) for value, dimension in
                       zip(region, (metadata['width'], metadata['height']) * 2))
        if region[0] >= region[2] or region[1] >= region[3]:
            raise ConversionError('invalid_request', '所选谱区在原画面中不足一个像素。')
    return start, end, region
