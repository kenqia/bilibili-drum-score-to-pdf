"""Website-only fallback to the supplied kit, inside the existing task owner."""
from contextlib import redirect_stderr, redirect_stdout
import json
from pathlib import Path
import subprocess
import time

from .conversion_options import DEFAULT_OPTIONS
from .video_seek import ConversionError

ELIGIBLE_ERRORS = frozenset({'unsupported_layout', 'discontinuity'})


def eligible(error, options):
    return error.code in ELIGIBLE_ERRORS and options == DEFAULT_OPTIONS


def process(source, output, scratch, metadata, emit, budget, primary_error):
    """Retain kit decisions; adapt only execution, delivery and provenance."""
    from .core import artifact, NOTICE
    from .expert_v6.drumscore_auto_v6 import main

    budget.check()
    emit('expert_fallback')
    scratch.mkdir()
    output.mkdir()
    target = scratch / 'score.pdf'
    # The task owner still enforces wall time, RSS, disk and cancellation while
    # the unmodified kit executes. Raw logs and private paths stay private.
    try:
        with (scratch / 'engine.log').open('w') as log, redirect_stdout(log), redirect_stderr(log):
            report = main([str(source), '-o', str(target), '--no-ocr'])
    except (Exception, SystemExit):
        raise ConversionError('expert_failed', '两种整理方法都没能生成可用 PDF。') from None
    budget.check(force_disk=True)
    count = report['result']['pages']
    if type(count) is not int or not 1 <= count <= 64:
        raise ConversionError('resource_limit', '备用方法的结果超过页面限制，未发布结果。')
    pdf = output / 'score.pdf'
    target.rename(pdf)
    emit('paginating')
    try:
        subprocess.run(['pdftoppm', '-png', '-scale-to', '1400', str(pdf), str(output / 'page')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=max(.001, min(60, budget.deadline - time.monotonic())))
    except (OSError, subprocess.SubprocessError):
        budget.check()
        raise ConversionError('preview_failed', '无法生成备用方法结果的全部页面预览。') from None
    pages = sorted(output.glob('page-*.png'))
    if len(pages) != count:
        raise ConversionError('preview_failed', '备用方法结果的页面预览不完整。')
    budget.check(force_disk=True)
    origin = json.loads((Path(__file__).parent / 'expert_v6/ORIGIN.json').read_text())
    # Requested OpenCV times are not decoded PTS or native-frame provenance.
    evidence = {
        'engine': 'DrumScore v6', 'version': '6.0.0', 'ocr_enabled': False,
        'archive_sha256': origin['archive_sha256'], 'primary_error': primary_error.code,
        'audit_status': report['audit']['status'], 'audit_flags': len(report['audit']['flags']),
        'crop_suspects': report['v6_integrity']['suspect_rows'], 'native_timestamps_recorded': False,
        'image_processing': 'kit_grayscale_equalization_and_color_fusion',
        'rows': [{'row': crop['row'], 'requested_time_seconds': crop['source_time_s'],
                  'pts': None, 'time_base': None, 'issues': crop['issues']}
                 for crop in report['v6_integrity']['crops']],
    }
    return {
        'conversion': {'options': dict(DEFAULT_OPTIONS), 'effective_range_seconds': [0, metadata['duration']],
                       'is_excerpt': False, 'engine': 'expert_v6', 'needs_review': True},
        'warnings': [{'code': 'not_musically_proofread', 'message': NOTICE},
                     {'code': 'expert_fallback_needs_review',
                      'message': '这份谱子是用备用方法整理的，更容易出现重复、缺行或边缘被裁掉，彩色记号可能变成灰色。请对照原视频仔细看一遍。'}],
        'pdf': artifact(output, pdf), 'pages': [artifact(output, page) for page in pages],
        'samples': [], 'expert': evidence,
        'staff_count': report['result']['rows'],
        'metrics': {'decode_elapsed': None, 'seek_count': None, 'decoded_reported_frames': None,
                    'peak_temp_disk': None},
    }
