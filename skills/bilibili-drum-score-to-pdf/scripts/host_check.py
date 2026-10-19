#!/usr/bin/env python3
"""Report local Skill discovery and runtime prerequisites without loading host config."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile


SKILL_NAME = 'bilibili-drum-score-to-pdf'


def check(roots, probe=False):
    script_dir = Path(__file__).resolve().parent
    repository = script_dir.parent
    if not (repository / 'docs/agents/stage-recovery-layout.md').is_file():
        repository = script_dir.parents[2]
    discoveries, warnings = [], []
    for root in roots:
        root = Path(root).expanduser().absolute()
        matches = []
        try:
            entries = sorted(root.iterdir()) if root.is_dir() else []
        except OSError:
            entries = []
            warnings.append({'code': 'skill_root_unreadable', 'root_index': len(discoveries)})
        for entry in entries:
            skill = entry / 'SKILL.md'
            try:
                if not skill.is_file():
                    continue
                # Read only public Skill entries, never host config or credentials.
                name = next((line.split(':', 1)[1].strip().strip('\'"')
                             for line in skill.read_text(encoding='utf-8').splitlines()
                             if line.startswith('name:')), None)
                if name == SKILL_NAME:
                    matches.append(str(skill))
            except (OSError, UnicodeError):
                warnings.append({'code': 'skill_entry_unreadable', 'root_index': len(discoveries),
                                 'entry': entry.name})
        discoveries.append({'root': str(root), 'entries': matches, 'duplicate': len(matches) > 1})
    dependencies = []
    for line in (script_dir / 'requirements.txt').read_text(encoding='utf-8').splitlines():
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
    python_supported = sys.version_info[:2] == (3, 12)
    ready = python_supported and all(tools.values()) and protocol and all(
        item['status'] == 'passed' for item in dependencies)
    return {'runtime_ready': ready, 'prerequisites_ready': ready,
            'runtime_ready_semantics': 'prerequisites only; see decode_probe for functional evidence',
            'decode_probe': decode_probe() if probe else {'status': 'not_run'}, 'warnings': warnings, 'python': sys.version.split()[0],
            'python_supported': python_supported, 'python_requirement': '3.12',
            'python_executable': sys.executable, 'tools': tools, 'dependencies': dependencies,
            'protocol_present': protocol, 'discovery': discoveries,
            'host_image_view': 'unverified', 'host_imagegen': 'unverified',
            'scope': 'local filesystem discovery; host inventory and visual capabilities require host confirmation'}


def decode_probe():
    """Bounded synthetic local encode/probe/decode, with no network or host auth."""
    from video_seek import VideoReader, ConversionError
    try:
        with tempfile.TemporaryDirectory(prefix='score-host-check-') as temporary:
            source = Path(temporary) / 'probe.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                'color=c=white:s=32x32:r=2', '-frames:v', '2', '-c:v', 'ffv1', str(source)],
                capture_output=True, check=True, timeout=5)
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'json', str(source)], capture_output=True, check=True, timeout=5)
            duration = float(json.loads(result.stdout)['format']['duration'])
            metrics = dict(seek_count=0, decode_elapsed=590, decoded_reported_frames=0, peak_temp_disk=0)
            reader = VideoReader(source, dict(width=32, height=32, duration=duration, frame_duration=.5), metrics)
            try:
                position, image = reader.read_record(0)
                image.close()
            finally:
                reader.close()
            return {'status': 'passed', 'pts': position['pts'], 'time_base': position['time_base'],
                    'scope': 'synthetic local video; no host vision or real source validation'}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, ConversionError):
        return {'status': 'failed', 'code': 'decode_probe_failed',
                'action': 'check ffmpeg and ffprobe; rerun host_check --probe-decode'}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-root', action='append', type=Path,
                        help='Host Skill discovery root; repeat for multiple roots')
    parser.add_argument('--probe-decode', action='store_true', help='Run a bounded synthetic local decoder probe')
    args = parser.parse_args()
    roots = args.skills_root or [Path.home() / directory / 'skills'
                                for directory in ('.agents', '.codex', '.claude')]
    print(json.dumps(check(roots, probe=args.probe_decode), ensure_ascii=False))


if __name__ == '__main__':
    main()
