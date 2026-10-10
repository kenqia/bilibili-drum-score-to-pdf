#!/usr/bin/env python3
"""Run a deterministic, exhaustive shard of unittest discovery."""
import argparse
import sys
import unittest
from pathlib import Path


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests', type=Path, default=Path(__file__).resolve().parents[1] / 'tests')
    parser.add_argument('--index', type=int, required=True, help='Zero-based shard index')
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--list', action='store_true', help='Print selected test IDs without running')
    args = parser.parse_args()
    if args.count < 1 or not 0 <= args.index < args.count:
        parser.error('Require count > 0 and 0 <= index < count')
    loader = unittest.TestLoader()
    tests = sorted(flatten(loader.discover(str(args.tests))), key=lambda test: test.id())
    if loader.errors:
        for error in loader.errors:
            print(error, file=sys.stderr)
        return 1
    selected = tests[args.index::args.count]
    if not selected:
        parser.error('Shard contains no tests')
    if args.list:
        for test in selected:
            print(test.id())
        return 0
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
