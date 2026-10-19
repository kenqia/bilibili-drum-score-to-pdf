#!/usr/bin/env python3
"""Install and verify a self-contained committed Skill package."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid


REPOSITORY = Path(__file__).resolve().parents[1]
CANONICAL = Path('skills/bilibili-drum-score-to-pdf')
MANIFEST = 'installation.json'


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(64 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def local_path(path):
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('安装和备份路径不能包含符号链接。')
    return path


def managed_path(root, relative):
    parts = PurePosixPath(relative)
    if (not isinstance(relative, str) or parts.is_absolute() or '..' in parts.parts or
            not parts.parts or chr(92) in relative or ':' in relative):
        raise ValueError('安装清单包含不安全路径。')
    path = root.joinpath(*parts.parts)
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('受管理文件不能是符号链接。')
    return path


def manifest(root):
    path = managed_path(root, MANIFEST)
    data = json.loads(path.read_text(encoding='utf-8'))
    files = data.get('files_sha256')
    if not isinstance(files, dict) or not files or not isinstance(data.get('source_commit'), str):
        raise ValueError('安装清单缺少提交或文件 hash。')
    for relative, sha in files.items():
        managed_path(root, relative)
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError('安装清单包含无效 hash。')
    return data


def verify_files(root, data):
    for relative, expected in data['files_sha256'].items():
        path = managed_path(root, relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f'受管理文件缺失或改变：{relative}')


def verify(root):
    root = local_path(root)
    data = manifest(root)
    verify_files(root, data)
    if (root / CANONICAL / 'SKILL.md').exists():
        raise ValueError('安装副本存在重复 Skill 入口。')
    if not (root / 'SKILL.md').is_file() or not any((root / p).is_file() for p in
            ('references/stage-recovery-layout.md', 'docs/agents/stage-recovery-layout.md')):
        raise ValueError('Skill 或正常流程文档缺失。')
    for relative in data['files_sha256']:
        path = root / relative
        if path.parent == root / CANONICAL / 'scripts' and digest(path) != digest(root / 'scripts' / path.name):
            raise ValueError('根脚本与规范脚本不一致。')
    return {'source_commit': data['source_commit'], 'managed_files': len(data['files_sha256']),
            'hashes': 'passed', 'skill_entries': 1}


def snapshot(repository, revision, staging, target):
    commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse',
        '--verify', revision + '^{commit}'], text=True).strip()
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['git', '-C', str(repository), 'archive', commit, CANONICAL.as_posix()], stdout=archive, check=True)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as source:
            for member in source:
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or '..' in relative.parts or not (member.isdir() or member.isfile()):
                    raise ValueError('提交快照包含不支持的文件类型或路径。')
                if member.isdir() and relative in PurePosixPath(CANONICAL.as_posix()).parents:
                    continue
                try:
                    portable = relative.relative_to(PurePosixPath(CANONICAL.as_posix()))
                except ValueError:
                    raise ValueError('提交快照包含 Skill 目录外的路径。')
                if not portable.parts:
                    continue
                member.name = portable.as_posix()
                source.extract(member, staging, filter='data')
    skill = staging / 'SKILL.md'
    text = skill.read_text(encoding='utf-8').replace('/absolute/skill', str(target))
    skill.write_text(text + '\n安装源码版本：' + commit + '。Skill 根目录：' + str(target) + '。\n', encoding='utf-8')
    files = {p.relative_to(staging).as_posix(): digest(p) for p in sorted(staging.rglob('*')) if p.is_file()}
    data = {'schema': 1, 'source_commit': commit, 'installed_root': str(target),
            'installed_at': datetime.now(timezone.utc).isoformat(), 'files_sha256': files}
    (staging / MANIFEST).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    verify(staging)
    return data


def unmanaged(root, managed):
    """Find movable entries using metadata only; never read their contents."""
    result = []
    def visit(directory):
        for path in directory.iterdir():
            relative = path.relative_to(root).as_posix()
            if relative in managed:
                continue
            if path.is_dir() and not path.is_symlink() and any(p.startswith(relative + '/') for p in managed):
                visit(path)
            else:
                result.append(path.relative_to(root))
    visit(root)
    return result


def publish(target, staging, backup):
    old = manifest(target) if target.exists() else None
    if old:
        verify_files(target, old)
    extras = unmanaged(target, set(old['files_sha256']) | {MANIFEST}) if old else []
    for relative in extras:
        destination = staging / relative
        if destination.exists() or destination.is_symlink():
            raise ValueError('新版本与未管理文件冲突，旧安装保持不变。')
        parent = destination.parent
        while parent != staging:
            if parent.exists() and not parent.is_dir():
                raise ValueError('新版本与未管理目录冲突，旧安装保持不变。')
            parent = parent.parent
    moved = []
    if old:
        target.rename(backup)
    try:
        for relative in extras:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            (backup / relative).rename(destination)
            moved.append(relative)
        staging.rename(target)
    except BaseException:
        try:
            for relative in reversed(moved):
                (backup / relative).parent.mkdir(parents=True, exist_ok=True)
                (staging / relative).rename(backup / relative)
            if old:
                backup.rename(target)
        except BaseException:
            # The caller must retain staging if a filesystem error also blocks
            # restoration. It may contain the user's unmanaged task directory.
            (staging / '.recovery-required').touch()
            raise
        raise


def backup_path(target):
    # Keep backups outside the host's skills directory to avoid discovery.
    directory = target.parent.parent / 'skill-backups'
    directory.mkdir(parents=True, exist_ok=True)
    local_path(directory)
    if directory.stat().st_dev != target.parent.stat().st_dev:
        raise ValueError('备份和安装必须位于同一文件系统。')
    return directory / (target.name + '-' + uuid.uuid4().hex)


def install(repository, revision, target):
    repository, target = local_path(repository), local_path(target)
    if target == repository or target.is_relative_to(repository) or repository.is_relative_to(target):
        raise ValueError('安装目标必须与源码工作区分开。')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + target.name + '-staging-', dir=target.parent))
    try:
        data = snapshot(repository, revision, staging, target)
        if target.exists():
            previous = manifest(target)
            if previous['source_commit'] == data['source_commit'] and previous['files_sha256'] == data['files_sha256']:
                return {**verify(target), 'status': 'unchanged'}
        backup = backup_path(target)
        publish(target, staging, backup)
        return {**verify(target), 'status': 'installed', 'backup': str(backup) if backup.exists() else None}
    finally:
        if staging.exists() and not (staging / '.recovery-required').exists():
            shutil.rmtree(staging)


def rollback(target, backup):
    target, backup = local_path(target), local_path(backup)
    if target == backup or target.is_relative_to(backup) or backup.is_relative_to(target):
        raise ValueError('回滚路径不能重叠。')
    verify(backup)
    if manifest(backup).get('installed_root') != str(target):
        raise ValueError('备份属于另一安装目标。')
    current_backup = backup_path(target)
    publish(target, backup, current_backup)
    return {**verify(target), 'status': 'restored', 'backup': str(current_backup)}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('install', 'verify', 'rollback'))
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--repository', type=Path, default=REPOSITORY)
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    try:
        if args.operation == 'install':
            result = install(args.repository, args.revision, args.target)
        elif args.operation == 'verify':
            result = verify(args.target)
        else:
            if args.backup is None:
                parser.error('rollback requires --backup')
            result = rollback(args.target, args.backup)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
