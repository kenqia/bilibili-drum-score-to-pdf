#!/usr/bin/env python3
"""Report local Skill discovery and runtime prerequisites without loading host config."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys


SKILL_NAME = 'bilibili-drum-score-to-pdf'


def check(roots):
    script_dir = Path(__file__).resolve().parent
    repository = script_dir.parent
    if not (repository / 'docs/agents/stage-recovery-layout.md').is_file():
        repository = script_dir.parents[2]
    discoveries = []
    for root in roots:
        root = Path(root).expanduser().absolute()
        matches = []
        if root.is_dir():
            for entry in sorted(root.iterdir()):
                skill = entry / 'SKILL.md'
                if skill.is_file():
                    # Inspect only the public Skill entry, never host config or credentials.
                    name = next((line.split(':', 1)[1].strip().strip('\'"')
                                 for line in skill.read_text().splitlines()
                                 if line.startswith('name:')), None)
                    if name == SKILL_NAME:
                        matches.append(str(skill))
        discoveries.append({'root': str(root), 'entries': matches, 'duplicate': len(matches) > 1})
    dependencies = []
    for line in (script_dir / 'requirements.txt').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, expected = line.strip().split('==')
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        dependencies.append({'name': name, 'expected': expected, 'actual': actual,
                             'status': 'passed' if actual == expected else 'missing_or_mismatch'})
    tools = {name: shutil.which(name) for name in ('uv', 'git', 'ffmpeg', 'ffprobe', 'pdftoppm')}
    protocol = ((script_dir.parent / 'references/stage-recovery-layout.md').is_file() or
                (repository / 'docs/agents/stage-recovery-layout.md').is_file())
    ready = sys.version_info >= (3, 12) and all(tools.values()) and protocol and all(
        item['status'] == 'passed' for item in dependencies)
    return {'runtime_ready': ready, 'python': sys.version.split()[0],
            'python_executable': sys.executable, 'tools': tools, 'dependencies': dependencies,
            'protocol_present': protocol, 'discovery': discoveries,
            'host_image_view': 'unverified', 'host_imagegen': 'unverified',
            'scope': 'local filesystem discovery; host inventory and visual capabilities require host confirmation'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-root', action='append', type=Path,
                        help='Host Skill discovery root; repeat for multiple roots')
    args = parser.parse_args()
    roots = args.skills_root or [Path.home() / directory / 'skills'
                                for directory in ('.agents', '.codex', '.claude')]
    print(json.dumps(check(roots), ensure_ascii=False))


if __name__ == '__main__':
    main()
