"""Thin JSON command line adapter."""
import argparse
import json
from .core import ConversionError, convert


def main(argv=None):
    parser = argparse.ArgumentParser(description='把固定比例白底纵向滚动鼓谱视频整理为 A4 PDF。')
    parser.add_argument('source', help='本地视频或公开 HTTPS B站 BV 链接')
    parser.add_argument('--output', required=True, help='必须不存在的新结果目录')
    args = parser.parse_args(argv)
    try:
        result = convert(args.source, args.output)
    except ConversionError as error:
        result = {'status': 'failed', 'error': {'code': error.code, 'message': str(error)}}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0
