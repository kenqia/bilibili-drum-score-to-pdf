"""Argparse boundary without reflecting rejected user input."""
import argparse
import json


class PublicParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({'status': 'failed', 'error': {'code': 'invalid_request',
            'message': '命令参数无效，请使用 --help 查看支持的参数。'}}, ensure_ascii=False))
        raise SystemExit(2)
