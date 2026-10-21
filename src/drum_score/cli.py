"""Thin JSON command line adapter."""
from .arguments import PublicParser
import json
from .core import ConversionError, convert


def main(argv=None):
    parser = PublicParser(prog='drum-score', description='把固定比例白底纵向滚动鼓谱视频整理为 A4 PDF。')
    parser.add_argument('source', help='本地视频或公开 HTTPS B站 BV 链接')
    parser.add_argument('--output', required=True, help='必须不存在的新结果目录')
    parser.add_argument('--timeout', type=float, default=600, help='包含获取与发布的总秒数，默认600')
    parser.add_argument('--max-input-mib', type=float, default=256, help='来源大小上限MiB，默认256')
    parser.add_argument('--max-temp-mib', type=float, default=1024, help='采样临时文件额度MiB，默认1024')
    parser.add_argument('--max-rss-mib', type=float, default=1024, help='采样任务进程树RSS额度MiB，默认1024')
    args = parser.parse_args(argv)
    try:
        result = convert(args.source, args.output, limits={'wall_seconds': args.timeout,
            'input_bytes': args.max_input_mib * 1024**2, 'temp_bytes': args.max_temp_mib * 1024**2,
            'rss_bytes': args.max_rss_mib * 1024**2})
    except ConversionError as error:
        result = {'status': 'failed', 'error': {'code': error.code, 'message': str(error)}}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0
