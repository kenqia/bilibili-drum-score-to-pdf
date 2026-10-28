#!/usr/bin/env python3
"""Read-only deployment identity. Never read task rows or emit configuration text."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from drum_score.schema import validate_schema, normalized_sql, V1_STATEMENTS, V2_STATEMENTS, V3_STATEMENTS, V4_STATEMENTS, SCHEMA_STATEMENTS


def digest(data):
    return hashlib.sha256(data).hexdigest()


def schema_identity(database):
    # mode=ro prevents accidental creation; no immutable=1 (live WAL must be seen).
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        validate_schema(db, version=version)
        statements = sorted(normalized_sql(row[0]) for row in db.execute(
            "SELECT sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"))
    return {'version': version, 'sha256': digest(json.dumps(statements).encode())}


def collect(release, database, configs, *, fingerprint_data=False):
    identity = json.loads((Path(release) / 'release-identity.json').read_text())
    commit = identity.get('commit', identity.get('source_commit'))
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Invalid release commit')
    result = {'format': 1, 'commit': commit, 'release': str(Path(release).resolve()),
            'database': str(Path(database).resolve()), 'schema': schema_identity(database),
            'configs': {str(Path(path).absolute()): digest(Path(path).read_bytes()) for path in configs}}
    if fingerprint_data:
        with Path(database).open('rb') as stream:
            result['database_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        wal = Path(str(database) + '-wal')
        if wal.exists():
            raise ValueError('Checkpoint and close the stopped database before planning')
        result['wal_sha256'] = None
    return result


def check(actual, expected, repository=None, candidate=None):
    if actual != expected:
        raise ValueError('Deployment baseline changed')
    if repository is not None:
        result = subprocess.run(['git', '-C', str(repository), 'merge-base', '--is-ancestor',
                                 actual['commit'], candidate], capture_output=True)
        if result.returncode:
            raise ValueError('Candidate does not include deployed commit')


def check_candidate(baseline, repository, candidate):
    check(baseline, baseline, repository, candidate)
    # The running checker must be the candidate's schema implementation.
    schema_path = Path(__file__).resolve().parents[1] / 'src/drum_score/schema.py'
    committed = subprocess.check_output(['git', '-C', str(repository), 'show',
                                         candidate + ':src/drum_score/schema.py'])
    if schema_path.read_bytes() != committed:
        raise ValueError('Run the checker from the candidate schema checkout')
    versions = {1: V1_STATEMENTS, 2: V2_STATEMENTS, 3: V3_STATEMENTS, 4: V4_STATEMENTS, 5: SCHEMA_STATEMENTS}
    statements = versions.get(baseline['schema']['version'])
    if statements is None:
        raise ValueError('Unknown deployed schema')
    expected = digest(json.dumps(sorted(normalized_sql(sql) for sql in statements)).encode())
    if expected != baseline['schema']['sha256']:
        raise ValueError('Candidate does not recognize deployed schema structure')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--config', type=Path, action='append')
    parser.add_argument('--baseline', type=Path, help='Check a collected identity locally without server files')
    parser.add_argument('--expected', type=Path)
    parser.add_argument('--stopped-snapshot', action='store_true', help='Fingerprint a stopped, checkpointed database for deployment')
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--candidate')
    args = parser.parse_args()
    if bool(args.repository) != bool(args.candidate):
        parser.error('--repository and --candidate must be paired')
    if args.baseline and not args.repository:
        parser.error('--baseline requires --repository and --candidate')
    if not args.baseline and not (args.release and args.database and args.config):
        parser.error('collection requires --release, --database and --config')
    try:
        if args.baseline:
            check_candidate(json.loads(args.baseline.read_text()), args.repository, args.candidate)
            print('candidate_baseline_compatible')
            return 0
        actual = collect(args.release, args.database, args.config, fingerprint_data=args.stopped_snapshot)
        if args.expected:
            check(actual, json.loads(args.expected.read_text()), args.repository, args.candidate)
        elif args.repository:
            check(actual, actual, args.repository, args.candidate)
        print(json.dumps(actual, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.CalledProcessError) as error:
        print('baseline_refused: ' + type(error).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
