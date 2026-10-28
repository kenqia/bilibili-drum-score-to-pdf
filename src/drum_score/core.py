"""Automatic image conversion. Completion never means musical proofreading."""
from pathlib import Path
import hashlib
import json
import math
import os
import tempfile
import ctypes
import sys
import time
from importlib.metadata import PackageNotFoundError, version

from . import video_seek
from . import public_video
from .conversion_options import normalize_options, resolve_options

ConversionError = video_seek.ConversionError
NOTICE = '图像处理自动整理，未经音乐校对；可能保留模糊、水印、播放标记或未检测出的拼接问题。'
DEFAULT_LIMITS = {'wall_seconds': 600, 'input_bytes': 256 * 1024**2,
                  'temp_bytes': 1024**3, 'rss_bytes': 1024**3}


class ResourceBudget:
    def __init__(self, limits, cancel=None):
        if limits is not None and not isinstance(limits, dict):
            raise ConversionError('invalid_request', '资源限制参数无效。')
        values = {**DEFAULT_LIMITS, **(limits or {})}
        if set(values) != set(DEFAULT_LIMITS) or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
                for value in values.values()):
            raise ConversionError('invalid_request', '资源限制参数无效。')
        self.limits = values
        self.deadline = time.monotonic() + values['wall_seconds']
        self.cancel = cancel or (lambda: False)
        self.root = None
        self._peak_temp = 0
        self._next_disk_check = 0

    def check(self, *, force_disk=False):
        if self.cancel():
            raise ConversionError('cancelled', '转换已取消，未发布结果。')
        if time.monotonic() >= self.deadline:
            raise ConversionError('resource_limit', '转换超过总处理时限，未发布结果。')
        if self.root is not None and (force_disk or time.monotonic() >= self._next_disk_check):
            self._next_disk_check = time.monotonic() + .2
            total = 0
            for path in self.root.rglob('*'):
                try:
                    if path.is_file() and not path.is_symlink():
                        total += path.stat().st_size
                except FileNotFoundError:
                    pass
            self._peak_temp = max(self._peak_temp, total)
            if total > self.limits['temp_bytes']:
                raise ConversionError('resource_limit', '临时文件超过任务磁盘额度，未发布结果。')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def artifact(root, path):
    path = Path(path)
    return {'path': path.relative_to(root).as_posix(), 'sha256': digest(path), 'bytes': path.stat().st_size}


def _program_identity():
    package = Path(__file__).resolve().parent
    source_hash = hashlib.sha256()
    for path in sorted(package.glob('*.py')):
        source_hash.update(path.name.encode('utf-8'))
        source_hash.update(b'\0')
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                source_hash.update(chunk)
    try:
        package_version = version('bilibili-drum-score-to-pdf')
    except PackageNotFoundError:
        package_version = 'unknown'
    return {'name': 'bilibili-drum-score-to-pdf', 'version': package_version,
            'source_sha256': source_hash.hexdigest()}


def convert(source, output, *, options=None, progress=None, limits=None, cancel=None):
    options = normalize_options(options)
    from .supervision import run
    return run(source, output, options=options, progress=progress, limits=limits, cancel=cancel)


def _convert(source, output, *, options=None, progress=None, limits=None, cancel=None, prepared=None):
    """Publish PDF, all previews and provenance together into a new directory.

    ``progress`` receives real stage names. Errors never include raw network
    addresses or third-party exception text. Existing output paths are refused.
    """
    options = normalize_options(options)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ConversionError('output_exists', '结果路径已存在，请选择新的目录。')
    budget = ResourceBudget(limits, cancel)
    remote = isinstance(source, str) and '://' in source
    origin = {'kind': 'local'}
    if remote:
        try:
            origin = public_video.video_origin(source)
        except public_video.InputError as error:
            raise ConversionError(error.code, str(error)) from None
    elif not Path(source).is_file():
        raise ConversionError('invalid_input', '无法读取本地视频。请提供可播放的视频文件。')
    elif Path(source).stat().st_size > budget.limits['input_bytes']:
        raise ConversionError('resource_limit', '来源文件超过输入大小限制。')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    notify = progress or (lambda stage: None)
    phase_seconds = {}
    current_phase, phase_started = 'preparing', started
    def emit(stage):
        nonlocal current_phase, phase_started
        now = time.monotonic()
        phase_seconds[current_phase] = phase_seconds.get(current_phase, 0) + now - phase_started
        current_phase, phase_started = stage, now
        notify(stage)
    try:
        with tempfile.TemporaryDirectory(prefix='.drum-score-', dir=output.parent) as temporary:
            work = Path(temporary)
            budget.check()
            result_dir = work / 'result'
            result_dir.mkdir()
            if prepared is not None and not prepared.get('bypass'):
                local = Path(prepared['path'])
                origin = prepared['origin']
                if digest(local) != prepared['sha256']:
                    raise ConversionError('source_changed', '缓存来源发生变化，未发布结果。')
            elif remote:
                budget.check()
                emit('downloading')
                acquisition = work / 'acquisition'
                acquisition.mkdir()
                try:
                    local, origin = public_video.acquire(source, acquisition,
                        timeout=max(.1, budget.deadline - time.monotonic()),
                        max_bytes=int(budget.limits['input_bytes']))
                    if prepared and prepared.get('bypass'):
                        origin['cache'] = {'status': prepared.get('bypass_reason', 'bypass_version'), 'published_at': None, 'expires_at': None}
                except public_video.InputError as error:
                    raise ConversionError(error.code, str(error)) from None
            else:
                local = Path(source).absolute()
            emit('probing')
            budget.check()
            if local.stat().st_size > budget.limits['input_bytes']:
                raise ConversionError('resource_limit', '来源文件超过输入大小限制。')
            source_hash = digest(local)
            metadata = video_seek.probe_video(local)
            result = _process(local, result_dir, metadata, emit, budget, options)
            if digest(local) != source_hash:
                raise ConversionError('source_changed', '处理期间来源发生变化，未发布结果。')
            phase_seconds[current_phase] = phase_seconds.get(current_phase, 0) + time.monotonic() - phase_started
            result['metrics']['phase_seconds'] = dict(phase_seconds)
            result.update(schema_version=1, status='complete', reliable=False,
                          program=_program_identity(),
                          source={**origin, 'sha256': source_hash, 'bytes': local.stat().st_size,
                                  'metadata': metadata, 'retained': not remote},
                          elapsed_seconds=time.monotonic() - started)
            (result_dir / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            budget.check()
            _publish(result_dir, output)
        try:
            emit('complete')
        except Exception:
            # Publication is the commit point. Notification failure cannot
            # turn a committed result into a reported conversion failure.
            pass
        return result
    except ConversionError:
        raise
    except Exception:
        raise ConversionError('conversion_failed', '转换失败，未发布结果。请检查来源或选择新的结果目录。') from None


def _publish(source, output):
    if sys.platform == 'linux':
        # Linux atomic exclusive directory publication, including symlink and
        # empty-directory races. Plain POSIX rename replaces an empty directory.
        libc = ctypes.CDLL(None, use_errno=True)
        if not hasattr(libc, 'renameat2'):
            raise ConversionError('publication_unavailable', '系统不支持独占原子发布。')
        result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(output), 1)
        if result:
            number = ctypes.get_errno()
            if number in (17, 39):
                raise ConversionError('output_exists', '结果路径已存在，请选择新的目录。')
            raise OSError(number, 'exclusive publication failed')
    elif os.name == 'nt':
        try:
            os.rename(source, output)
        except FileExistsError:
            raise ConversionError('output_exists', '结果路径已存在，请选择新的目录。') from None
    else:
        raise ConversionError('publication_unavailable', '系统不支持独占原子发布。')


def _process(source, output, metadata, emit, budget, options):
    from . import imaging
    if metadata['duration'] > 600 or metadata['width'] * metadata['height'] > 4_200_000:
        raise ConversionError('resource_limit', '视频超出时长或像素限制。')
    start, end, manual_region = resolve_options(options, metadata)
    budget.check()
    frames = output / 'samples'
    frames.mkdir()
    paths = []
    metrics = {'decode_elapsed': 0, 'seek_count': 0, 'decoded_reported_frames': 0, 'peak_temp_disk': 0}
    from .visual_preflight import inspect as visual_preflight
    preflight = visual_preflight(source, metadata, metrics, budget.check, start=start, end=end)
    emit('sampling')
    reader = video_seek.VideoReader(source, metadata, metrics)
    try:
        def consume(index, image):
            budget.check()
            path = frames / f'{index:05d}.png'
            image.save(path, compress_level=1)
            paths.append(path)
        records = reader.sample_records(.5, consume, verify_motion=True, start=start, end=end)
        if not records:
            raise ConversionError('invalid_request', '所选区间没有可解码的原生帧。')
        tail_record, tail_image = reader.read_record(end=end)
        try:
            if tail_record['timestamp'] > records[-1]['timestamp']:
                consume(len(paths), tail_image)
                tail_record['native_motion_max_luma_difference'] = records[-1].get(
                    'native_trailing_motion_max_luma_difference', 0.0)
                tail_record['native_intermediate_frames'] = max(0, records[-1].get('native_trailing_frames', 0) - 1)
                records.append(tail_record)
        finally:
            tail_image.close()
    finally:
        reader.close()
    emit('registering')
    region = manual_region if manual_region is not None else imaging.detect_region(
        paths[::max(1, len(paths) // 60)], budget_check=budget.check)
    from .registration_flow import register_refined
    from .fixed_overlays import detect as detect_fixed_overlays
    invalid, overlay_comparisons = (detect_fixed_overlays(paths, region, budget.check)
        if options['ignore_fixed_overlays'] else (None, 0))
    refinement_reader = video_seek.VideoReader(source, metadata, metrics)
    supplemental = 0
    def refine(timestamp):
        nonlocal supplemental
        budget.check()
        record, image = refinement_reader.read_record(timestamp)
        try:
            path = frames / f'refined-{supplemental:05d}.png'
            supplemental += 1
            image.save(path, compress_level=1)
            budget.check(force_disk=True)
            return path, record
        finally:
            image.close()
    try:
        placements, registration = register_refined(paths, region, records, refine, budget.check, invalid=invalid)
        registration.update(invalid_pixels=int(invalid.sum()) if invalid is not None else 0, overlay_comparisons=overlay_comparisons)
    finally:
        refinement_reader.close()
    samples = [{**artifact(output, path), **record, 'kind': 'native_frame'}
               for path, record in zip(paths, records)]
    registration['match_region'] = list(region)
    if manual_region is None:
        from .score_borders import trim as trim_score_borders
        region = trim_score_borders([paths[item['sample']] for item in placements], region, budget.check)
    emit('composing')
    longshot = output / 'longshot.png'
    imaging.compose(paths, region, placements, longshot)
    emit('paginating')
    pdf, pages, strips, staffs = imaging.paginate(longshot, output)
    return {'conversion': {'options': options, 'effective_range_seconds': [start, end],
                           'is_excerpt': start > 0 or end < metadata['duration']},
            'warnings': [{'code': 'not_musically_proofread', 'message': NOTICE}],
            'pdf': artifact(output, pdf), 'pages': [artifact(output, page) for page in pages],
            'longshot': {**artifact(output, longshot), 'kind': 'derived_image'},
            'samples': samples, 'placements': placements, 'region': list(region),
            'page_regions': [list(strip) for strip in strips], 'staff_count': staffs,
            'metrics': metrics, 'registration': registration, 'preflight': preflight}
