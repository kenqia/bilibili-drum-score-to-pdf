"""Shared explicit web/worker resource options; no implicit configuration files."""
from .core import DEFAULT_LIMITS, ResourceBudget


def add_storage_arguments(parser):
    parser.add_argument('--retention-seconds', type=float, default=86400, help='完成结果保留秒数，默认86400')
    parser.add_argument('--diagnostic-seconds', type=float, default=3600, help='失败/取消/中断诊断保留秒数，默认3600')
    parser.add_argument('--diagnostic-mib', type=float, default=8, help='全局脱敏诊断文字额度MiB，默认8')
    parser.add_argument('--min-free-mib', type=float, default=512, help='磁盘可用空间保留底线MiB，默认512')
    parser.add_argument('--retained-mib', type=float, default=4096, help='任务目录总逻辑字节额度MiB，默认4096')
    parser.add_argument('--max-temp-mib', type=float, default=1024, help='单次暂存上限与准入预留MiB，默认1024')
    parser.add_argument('--record-mib', type=float, default=256, help='整理记录内容和未完成预留额度MiB，默认256')
    parser.add_argument('--record-retention-seconds', type=float, default=604800, help='操作结束后的记录保留秒数，默认604800')


def storage_options(args):
    return dict(retention_seconds=args.retention_seconds, diagnostic_seconds=args.diagnostic_seconds,
        diagnostic_bytes=args.diagnostic_mib * 1024**2, min_free_bytes=args.min_free_mib * 1024**2,
        retained_bytes=args.retained_mib * 1024**2, job_temp_bytes=args.max_temp_mib * 1024**2,
        record_bytes=args.record_mib * 1024**2, record_retention_seconds=args.record_retention_seconds)


def add_conversion_arguments(parser):
    parser.add_argument('--timeout', type=float, default=DEFAULT_LIMITS['wall_seconds'])
    parser.add_argument('--max-input-mib', type=float, default=DEFAULT_LIMITS['input_bytes'] / 1024**2)
    parser.add_argument('--max-rss-mib', type=float, default=DEFAULT_LIMITS['rss_bytes'] / 1024**2)


def conversion_options(args):
    return ResourceBudget(dict(wall_seconds=args.timeout, input_bytes=args.max_input_mib * 1024**2,
        rss_bytes=args.max_rss_mib * 1024**2, temp_bytes=args.max_temp_mib * 1024**2)).limits
