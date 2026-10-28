#!/usr/bin/env python3
"""Switch a prepared release with matching configuration and verified data root.

Default is read-only preflight. Backup/upgrade and installed-release acceptance
must be completed before this transaction; see docs/script-product/operations.md.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import time

from service_baseline import collect, check

UNITS = ['drum-score-web.service', 'drum-score-worker.service']


def fingerprint(path):
    info = path.lstat()
    if not path.is_file() or path.is_symlink():
        raise ValueError('Expected regular configuration file')
    return info.st_dev, info.st_ino, hashlib.sha256(path.read_bytes()).hexdigest()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Switch:
    def __init__(self, plan, report, run=None):
        self.plan = plan
        self.report = Path(report)
        self.run = run or self.command
        self.changed = {}
        self.previous = {}
        self.link_changed = False
        self.public = False
        self.stopped = False
        self.events = []

    @staticmethod
    def command(args):
        return subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def event(self, name):
        self.events.append(name)
        # This report contains stage names only. Never capture command/config output.
        self.report.write_text(json.dumps({'events': self.events, 'public': self.public}) + '\n')

    def atomic(self, path, data, track=True):
        descriptor, temporary = tempfile.mkstemp(prefix='.drum-switch-', dir=path.parent)
        temporary = Path(temporary)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o644)
                os.fsync(stream.fileno())
            identity = fingerprint(temporary)
            os.replace(temporary, path)
            # Publication is recorded BEFORE parent fsync can fail.
            if track:
                self.changed[path] = identity
            sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def flip(self, target):
        current = Path(self.plan['current'])
        temporary = current.with_name('.drum-current-' + os.urandom(8).hex())
        try:
            temporary.symlink_to(target)
            os.replace(temporary, current)
            self.link_changed = True
            sync_directory(current.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def preflight(self):
        p = self.plan
        old, new = p['old'], p['new']
        if not Path(p['current']).is_symlink() or Path(p['current']).resolve() != Path(old['release']):
            raise ValueError('Current release changed')
        if not p.get('private_check') or not all(isinstance(v, str) for v in p['private_check']):
            raise ValueError('A private acceptance command is required')
        if p['private_port'] == p['public_port']:
            raise ValueError('Private acceptance must use a separate port')
        for baseline in (old, new):
            with sqlite3.connect(Path(baseline['database']).as_uri() + '?mode=ro', uri=True) as db:
                if db.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('queued','running','cancelling','finishing')").fetchone()[0]:
                    raise ValueError('Drain all old work before preparing the upgrade')
            check(collect(baseline['release'], baseline['database'], baseline['configs'], fingerprint_data=True), baseline)
        if old['database'] == new['database'] or old['release'] == new['release']:
            raise ValueError('Prepared release and data root must be distinct')
        if set(old['configs']) != {item['path'] for item in p['profiles']}:
            raise ValueError('Every old profile must have a replacement')
        for item in p['profiles']:
            path = Path(item['path'])
            fingerprint(path)
            for phase in ('private', 'public'):
                replacement = Path(item[phase])
                fingerprint(replacement)
                data = replacement.read_bytes()
                if hashlib.sha256(data).hexdigest() != new['configs'].get(str(replacement.absolute())):
                    raise ValueError('Replacement profile changed')
                if str(Path(new['database']).parent).encode() not in data:
                    raise ValueError('Profile does not bind the prepared data root')
                if str(Path(p['current'])).encode() not in data:
                    raise ValueError('Profile must use the current release link')
        # Check installed payload, not just the wheel supplied to pip.
        identity = json.loads((Path(new['release']) / 'release-identity.json').read_text())
        site = Path(new['release']) / 'venv/lib/python3.12/site-packages'
        expected = identity['package_files']
        actual = {str(f.relative_to(site)): hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in (site / 'drum_score').rglob('*')
                  if f.is_file() and '__pycache__' not in f.parts and f.suffix != '.pyc'}
        if actual != expected:
            raise ValueError('Installed package differs from release identity')

    def health(self, port):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            try:
                connection.request('GET', '/')
                response = connection.getresponse()
                response.read(1024)
                if response.status == 200:
                    return
            except OSError:
                pass
            finally:
                connection.close()
            time.sleep(.25)
        raise RuntimeError('HTTP health check failed')

    def rollback(self):
        p = self.plan
        if self.public:
            # Stop admission and retain all newly accepted task state.
            self.run(['systemctl', 'stop', UNITS[0]])
            self.safe_event('public_failure_new_data_preserved')
            return
        if self.stopped:
            self.run(['systemctl', 'stop', *UNITS])
        for path, identity in reversed(list(self.changed.items())):
            if fingerprint(path) != identity:
                raise ValueError('Configuration changed externally; manual recovery required')
            self.atomic(path, self.previous[path], track=False)
        if self.link_changed:
            if Path(p['current']).resolve() != Path(p['new']['release']):
                raise ValueError('Release changed externally; manual recovery required')
            self.flip(p['old']['release'])
        if self.stopped:
            self.run(['systemctl', 'daemon-reload'])
            self.run(['systemctl', 'start', *UNITS])
        self.safe_event('rolled_back')

    def safe_event(self, name):
        try:
            self.event(name)
        except OSError:
            print('deployment_report_unavailable', file=sys.stderr)

    def execute(self):
        self.preflight()
        self.report.parent.mkdir(parents=True, exist_ok=True)
        # Save recoverable configuration BEFORE any service mutation.
        backup = self.report.with_suffix('.rollback')
        backup.mkdir(mode=0o700)
        for index, item in enumerate(self.plan['profiles']):
            path = Path(item['path'])
            self.previous[path] = path.read_bytes()
            with (backup / str(index)).open('xb') as stream:
                stream.write(self.previous[path])
                stream.flush()
                os.fsync(stream.fileno())
        (backup / 'plan.json').write_text(json.dumps(self.plan, indent=2) + '\n')
        sync_directory(backup)
        sync_directory(backup.parent)
        self.event('preflight_complete')
        try:
            # The prepared root must be from this exact stopped baseline.
            # Running services could have changed the source after backup/upgrade.
            self.stopped = True
            self.run(['systemctl', 'stop', *UNITS])
            # Caller supplied a stopped snapshot; compare row-free DB digest now.
            for name in ('old', 'new'):
                database = Path(self.plan[name]['database'])
                if (hashlib.sha256(database.read_bytes()).hexdigest() != self.plan[name]['database_sha256']
                        or self.plan[name]['wal_sha256'] is not None
                        or Path(str(database) + '-wal').exists()):
                    raise ValueError('Prepared snapshot changed; repeat backup/upgrade while stopped')
            for item in self.plan['profiles']:
                path = Path(item['path'])
                if path.read_bytes() != self.previous[path]:
                    raise ValueError('Configuration changed externally')
                self.atomic(path, Path(item['private']).read_bytes())
            self.flip(self.plan['new']['release'])
            self.run(['systemctl', 'daemon-reload'])
            self.run(['systemctl', 'start', *UNITS])
            self.health(self.plan['private_port'])
            self.run(self.plan['private_check'])
            self.event('private_acceptance_passed')
            # Public boundary must precede ANY configuration exposing the new service.
            self.public = True
            for item in self.plan['profiles']:
                path = Path(item['path'])
                if fingerprint(path) != self.changed[path]:
                    raise ValueError('Configuration changed externally')
                self.atomic(path, Path(item['public']).read_bytes())
            self.run(['systemctl', 'daemon-reload'])
            self.run(['systemctl', 'restart', UNITS[0]])
            self.health(self.plan['public_port'])
            self.event('complete')
        except BaseException:
            self.safe_event('failed')
            try:
                self.rollback()
            except BaseException:
                self.safe_event('rollback_incomplete')
                raise
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute and not args.report:
        parser.error('--execute requires --report in a private directory')
    try:
        switch = Switch(json.loads(args.plan.read_text()), args.report or Path('unused'))
        if args.execute:
            import fcntl
            lock = Path(switch.plan['current']).parent / '.drum-deploy.lock'
            with lock.open('a') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                switch.execute()
        else:
            switch.preflight()
            print('preflight_complete; no services or files changed')
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print('deployment_refused: ' + type(error).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
