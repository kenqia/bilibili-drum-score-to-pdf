#!/usr/bin/env python3
"""Build and verify wheel and sdist from one committed, clean Git export."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(repository, *args):
    return subprocess.check_output(['git', '-C', str(repository), *args])


def verify_artifacts(source, wheel, sdist):
    expected = {p.relative_to(source / 'src').as_posix(): p.read_bytes()
                for p in (source / 'src/drum_score').rglob('*') if p.is_file()}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate wheel paths')
        actual = {n: archive.read(n) for n in names if n.startswith('drum_score/')}
        if actual != expected:
            raise ValueError('Wheel package files differ from committed source')
        if any(not n.startswith('drum_score/') and '.dist-info/' not in n for n in names):
            raise ValueError('Unexpected wheel payload')
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or any(m.issym() or m.islnk() for m in members):
            raise ValueError('Unexpected sdist members')
        actual = {m.name.split('/src/', 1)[1]: archive.extractfile(m).read()
                  for m in members if m.isfile() and '/src/drum_score/' in m.name}
        if actual != expected:
            raise ValueError('Sdist package files differ from committed source')
    return {name: sha(data) for name, data in sorted(expected.items())}


def build(repository, revision, output):
    commit = run(repository, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='drum-release-') as scratch:
        source = Path(scratch) / 'source'
        source.mkdir()
        exported = run(repository, 'archive', '--format=tar', commit)
        with tarfile.open(fileobj=io.BytesIO(exported)) as archive:
            if any(m.issym() or m.islnk() for m in archive.getmembers()):
                raise ValueError('Release source links are unsupported')
            archive.extractall(source, filter='data')
        # No PYTHONPATH/sitecustomize from the operator workspace during the build.
        import os
        env = {key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTHONHOME')}
        subprocess.run([sys.executable, '-m', 'build', '--outdir', str(output), str(source)],
                       check=True, cwd=scratch, env=env)
        wheels, sdists = list(output.glob('*.whl')), list(output.glob('*.tar.gz'))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ValueError('Expected exactly one wheel and sdist')
        files = verify_artifacts(source, wheels[0], sdists[0])
        identity = {'format': 1, 'commit': commit, 'package_files': files,
                    'artifacts': {p.name: sha(p.read_bytes()) for p in [wheels[0], sdists[0]]}}
        (output / 'release-identity.json').write_text(json.dumps(identity, indent=2, sort_keys=True) + '\n')
        return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        identity = build(args.repository, args.commit, args.output)
        print(json.dumps({'commit': identity['commit'], 'files': len(identity['package_files'])}))
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError, zipfile.BadZipFile) as error:
        print('release_refused: ' + type(error).__name__, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
