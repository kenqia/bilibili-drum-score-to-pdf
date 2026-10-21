"""Automatic image conversion. Completion never means musical proofreading."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import ctypes
import sys
import time
from importlib.metadata import PackageNotFoundError, version

import video_seek
import public_video

ConversionError = video_seek.ConversionError
NOTICE = '图像处理自动整理，未经音乐校对；可能保留模糊、水印、播放标记或未检测出的拼接问题。'


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


def convert(source, output, *, progress=None):
    """Publish PDF, all previews and provenance together into a new directory.

    ``progress`` receives real stage names. Errors never include raw network
    addresses or third-party exception text. Existing output paths are refused.
    """
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ConversionError('output_exists', '结果路径已存在，请选择新的目录。')
    remote = isinstance(source, str) and '://' in source
    origin = {'kind': 'local'}
    if remote:
        try:
            origin = public_video.video_origin(source)
        except public_video.InputError as error:
            raise ConversionError(error.code, str(error)) from None
    elif not Path(source).is_file():
        raise ConversionError('invalid_input', '无法读取本地视频。请提供可播放的视频文件。')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    emit = progress or (lambda stage: None)
    try:
        with tempfile.TemporaryDirectory(prefix='.drum-score-', dir=output.parent) as temporary:
            work = Path(temporary)
            result_dir = work / 'result'
            result_dir.mkdir()
            if remote:
                emit('downloading')
                acquisition = work / 'acquisition'
                acquisition.mkdir()
                try:
                    local, origin = public_video.acquire(source, acquisition)
                except public_video.InputError as error:
                    raise ConversionError(error.code, str(error)) from None
            else:
                local = Path(source).absolute()
            emit('probing')
            source_hash = digest(local)
            metadata = video_seek.probe_video(local)
            result = _process(local, result_dir, metadata, emit)
            if digest(local) != source_hash:
                raise ConversionError('source_changed', '处理期间来源发生变化，未发布结果。')
            result.update(schema_version=1, status='complete', reliable=False,
                          program=_program_identity(),
                          source={**origin, 'sha256': source_hash, 'bytes': local.stat().st_size,
                                  'metadata': metadata, 'retained': not remote},
                          elapsed_seconds=time.monotonic() - started)
            (result_dir / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
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


def _process(source, output, metadata, emit):
    from . import imaging
    if metadata['duration'] > 1800 or metadata['width'] * metadata['height'] > 20_000_000:
        raise ConversionError('resource_limit', '视频超出时长或像素限制。')
    emit('sampling')
    frames = output / 'samples'
    frames.mkdir()
    paths = []
    references = []
    metrics = {'decode_elapsed': 0, 'seek_count': 0, 'decoded_reported_frames': 0, 'peak_temp_disk': 0}
    reader = video_seek.VideoReader(source, metadata, metrics)
    try:
        def consume(index, image):
            path = frames / f'{index:05d}.png'
            image.save(path, compress_level=1)
            paths.append(path)
            references.append(artifact(output, path))
        records = reader.sample_records(.5, consume)
        tail_record, tail_image = reader.read_record()
        try:
            if tail_record['timestamp'] > records[-1]['timestamp']:
                consume(len(paths), tail_image)
                records.append(tail_record)
        finally:
            tail_image.close()
    finally:
        reader.close()
    samples = [{**reference, **record, 'kind': 'native_frame'}
               for reference, record in zip(references, records)]
    emit('registering')
    region = imaging.detect_region(paths[::max(1, len(paths) // 60)])
    placements = imaging.register(paths, region)
    emit('composing')
    longshot = output / 'longshot.png'
    imaging.compose(paths, region, placements, longshot)
    emit('paginating')
    pdf, pages, strips, staffs = imaging.paginate(longshot, output)
    return {'warnings': [{'code': 'not_musically_proofread', 'message': NOTICE}],
            'pdf': artifact(output, pdf), 'pages': [artifact(output, page) for page in pages],
            'longshot': {**artifact(output, longshot), 'kind': 'derived_image'},
            'samples': samples, 'placements': placements, 'region': list(region),
            'page_regions': [list(strip) for strip in strips], 'staff_count': staffs,
            'metrics': metrics}
