#!/usr/bin/env python3
"""Switch a prepared release with matching configuration and verified data root.

Default is read-only preflight. Backup/upgrade and installed-release acceptance
must be completed before this transaction; see docs/script-product/operations.md.
"""
import argparse
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import shlex
import re
import sys
import tempfile
import time

from service_baseline import collect, check

UNITS = ['drum-score-web.service', 'drum-score-worker.service']


def fingerprint(path):
    info = path.lstat()
    if not path.is_file() or path.is_symlink():
        raise ValueError('Expected regular configuration file')
    return info.st_dev, info.st_ino, info.st_ctime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def link_identity(path):
    info = path.lstat()
    if not path.is_symlink():
        raise ValueError('Expected release symlink')
    return info.st_dev, info.st_ino, info.st_ctime_ns, os.readlink(path)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def profile_command(path, role, current, data_root, port=None):
    section = None
    commands = []
    reset = False
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith('['):
            section = line
        if section == '[Service]' and line.startswith('ExecStart='):
            value = line.removeprefix('ExecStart=')
            if not value:
                reset = True
            else:
                commands.append(value)
    if not reset or len(commands) != 1 or any(c in commands[0] for c in ('\\', '$', '%')):
        raise ValueError('Expected one literal reset ExecStart command')
    argv = shlex.split(commands[0])
    if not argv or argv[0] != str(current) + '/venv/bin/drum-score-' + role:
        raise ValueError('Unexpected profile executable')
    def option(name, expected):
        for token in argv[1:]:
            if token.startswith('--'):
                option_name = token.split('=', 1)[0]
                if name.startswith(option_name) and token != name:
                    raise ValueError('Protected options require complete separate tokens')
        if argv.count(name) != 1 or argv.index(name) + 1 >= len(argv) or argv[argv.index(name) + 1] != str(expected):
            raise ValueError('Unexpected profile option')
    option('--data-root', data_root)
    if role == 'web':
        option('--host', '127.0.0.1')
        option('--port', port)
    return argv


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
        self.initial_link = None
        self.published_link = None
        self.profile_identities = {}
        self.commands = {}
        self.replacements = {}
        self.report_stream = None

    @staticmethod
    def command(args):
        output = subprocess.PIPE if args[:2] == ['systemctl', 'show'] else subprocess.DEVNULL
        return subprocess.run(args, check=True, stdout=output, stderr=subprocess.DEVNULL)

    def event(self, name):
        self.events.append(name)
        # This report contains stage names only. Never capture command/config output.
        info = os.fstat(self.report_stream.fileno())
        current = self.report.lstat()
        if self.report.is_symlink() or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError('Report changed externally')
        self.report_stream.seek(0)
        self.report_stream.truncate()
        self.report_stream.write(json.dumps({'events': self.events, 'public': self.public}) + '\n')
        self.report_stream.flush()
        os.fsync(self.report_stream.fileno())

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
                self.changed[path] = fingerprint(path)
            sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def flip(self, target):
        current = Path(self.plan['current'])
        expected = self.published_link if self.link_changed else self.initial_link
        if link_identity(current) != expected:
            raise ValueError('Release changed externally; manual recovery required')
        temporary = current.with_name('.drum-current-' + os.urandom(8).hex())
        try:
            temporary.symlink_to(target)
            published = link_identity(temporary)
            os.replace(temporary, current)
            self.published_link = published
            self.link_changed = True
            self.published_link = link_identity(current)
            sync_directory(current.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def preflight(self):
        p = self.plan
        old, new = p['old'], p['new']
        if not Path(p['current']).is_symlink() or Path(p['current']).resolve() != Path(old['release']):
            raise ValueError('Current release changed')
        self.initial_link = link_identity(Path(p['current']))
        if not p.get('private_check') or not all(isinstance(v, str) for v in p['private_check']):
            raise ValueError('A private acceptance command is required')
        if any(type(p[key]) is not int or not 1 <= p[key] <= 65535 for key in ('private_port', 'public_port')):
            raise ValueError('Ports must be integer TCP ports')
        if p['private_port'] == p['public_port']:
            raise ValueError('Private acceptance must use a separate port')
        for baseline in (old, new):
            with closing(sqlite3.connect(Path(baseline['database']).as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('queued','running','cancelling','finishing')").fetchone()[0]:
                    raise ValueError('Drain all old work before preparing the upgrade')
            check(collect(baseline['release'], baseline['database'], baseline['configs'], fingerprint_data=True), baseline)
        if old['database'] == new['database'] or old['release'] == new['release']:
            raise ValueError('Prepared release and data root must be distinct')
        if len(p['profiles']) != 2 or {item['role'] for item in p['profiles']} != {'web', 'worker'}:
            raise ValueError('Exactly one web and worker profile is required')
        if not {item['path'] for item in p['profiles']} <= set(old['configs']):
            raise ValueError('Every old profile must have a replacement')
        for item in p['profiles']:
            path = Path(item['path'])
            self.profile_identities[path] = fingerprint(path)
            for phase in ('private', 'public'):
                replacement = Path(item[phase])
                fingerprint(replacement)
                data = replacement.read_bytes()
                if hashlib.sha256(data).hexdigest() != new['configs'].get(str(replacement.absolute())):
                    raise ValueError('Replacement profile changed')
                self.replacements[item['path'], phase] = data
                self.commands[item['role'], phase] = profile_command(
                    replacement, item['role'], p['current'], Path(new['database']).parent,
                    p['private_port'] if phase == 'private' else p['public_port'])
            if item['role'] == 'worker' and Path(item['private']).read_bytes() != Path(item['public']).read_bytes():
                raise ValueError('Worker profiles must be identical')
        # Check installed payload, not just the wheel supplied to pip.
        identity = json.loads((Path(new['release']) / 'release-identity.json').read_text())
        site = Path(new['release']) / 'venv/lib/python3.12/site-packages'
        expected = identity['package_files']
        if any(f.is_symlink() for f in (site / 'drum_score').rglob('*')):
            raise ValueError('Installed package links are unsupported')
        actual = {str(f.relative_to(site)): hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in (site / 'drum_score').rglob('*')
                  if f.is_file() and '__pycache__' not in f.parts and f.suffix != '.pyc'}
        if actual != expected:
            raise ValueError('Installed package differs from release identity')

    def verify_effective(self, phase):
        for role, unit in zip(('web', 'worker'), UNITS):
            result = self.run(['systemctl', 'show', unit, '--property=ExecStart', '--value'])
            match = re.search(r'argv\[\]=(.*?) ;', result.stdout.decode())
            if not match or shlex.split(match.group(1)) != self.commands[role, phase]:
                raise ValueError('Effective systemd command differs from accepted profile')

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
        for item in p['profiles']:
            path = Path(item['path'])
            if path not in self.changed and fingerprint(path) != self.profile_identities[path]:
                raise ValueError('Configuration changed externally; manual recovery required')
        if self.link_changed:
            if Path(p['current']).resolve() != Path(p['new']['release']):
                raise ValueError('Release changed externally; manual recovery required')
            self.flip(p['old']['release'])
        elif link_identity(Path(p['current'])) != self.initial_link:
            raise ValueError('Release changed externally; manual recovery required')
        if self.stopped:
            self.run(['systemctl', 'daemon-reload'])
            self.run(['systemctl', 'start', *UNITS])
        self.safe_event('rolled_back')

    def safe_event(self, name):
        try:
            self.event(name)
        except (OSError, ValueError):
            print('deployment_report_unavailable', file=sys.stderr)

    def execute(self):
        self.preflight()
        self.report.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            self.report_stream = stream
            self.execute_prepared()

    def execute_prepared(self):
        # Save recoverable configuration BEFORE any service mutation.
        backup = self.report.with_suffix('.rollback')
        backup.mkdir(mode=0o700)
        for index, item in enumerate(self.plan['profiles']):
            path = Path(item['path'])
            if fingerprint(path) != self.profile_identities[path]:
                raise ValueError('Configuration changed externally')
            self.previous[path] = path.read_bytes()
            with (backup / str(index)).open('xb') as stream:
                stream.write(self.previous[path])
                stream.flush()
                os.fsync(stream.fileno())
        with (backup / 'plan.json').open('x') as stream:
            stream.write(json.dumps(self.plan, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
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
                if fingerprint(path) != self.profile_identities[path]:
                    raise ValueError('Configuration changed externally')
                self.atomic(path, self.replacements[item['path'], 'private'])
            self.flip(self.plan['new']['release'])
            self.run(['systemctl', 'daemon-reload'])
            self.verify_effective('private')
            self.run(['systemctl', 'start', *UNITS])
            self.health(self.plan['private_port'])
            self.run(self.plan['private_check'])
            self.event('private_acceptance_passed')
            # Public boundary must precede ANY configuration exposing the new service.
            if link_identity(Path(self.plan['current'])) != self.published_link:
                raise ValueError('Release changed externally')
            self.public = True
            for item in self.plan['profiles']:
                path = Path(item['path'])
                if fingerprint(path) != self.changed[path]:
                    raise ValueError('Configuration changed externally')
                self.atomic(path, self.replacements[item['path'], 'public'])
            self.run(['systemctl', 'daemon-reload'])
            self.verify_effective('public')
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
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError, sqlite3.Error) as error:
        print('deployment_refused: ' + type(error).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
