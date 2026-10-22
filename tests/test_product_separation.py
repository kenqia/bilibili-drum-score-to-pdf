"""Each product runs from its own files and its own test discovery process."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from score_fixtures import score_frame, video_from_image

ROOT = Path(__file__).resolve().parents[1]


class ProductSeparation(unittest.TestCase):
    def test_program_converts_from_detached_package_without_skill_or_repository_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            package_root = base / 'library'
            shutil.copytree(ROOT / 'src/drum_score', package_root / 'drum_score',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            video = video_from_image(score_frame(), base)
            script = '''
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import drum_score
assert Path(drum_score.__file__).resolve().is_relative_to(Path(sys.argv[1]))
result = drum_score.convert(sys.argv[2], sys.argv[3])
print(json.dumps(result))
'''
            result = subprocess.run([sys.executable, '-I', '-c', script, str(package_root),
                                     str(video), str(base / 'result')], cwd=base,
                                    capture_output=True, text=True, timeout=60, check=True)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest['status'], 'complete')
            self.assertFalse(manifest['reliable'])
            self.assertEqual(manifest['staff_count'], 3)
            for reference in [manifest['pdf'], *manifest['pages']]:
                self.assertTrue((base / 'result' / reference['path']).is_file())
            self.assertFalse((base / 'skills').exists())
            self.assertFalse((base / 'tools').exists())

    def test_program_discovery_does_not_load_skill_contracts(self):
        def discover(path):
            result = subprocess.run([sys.executable, str(ROOT / 'ci/run_unittest_shard.py'),
                                     '--tests', str(path), '--index', '0', '--count', '1', '--list'],
                                    capture_output=True, text=True, check=True, timeout=30)
            return result.stdout.splitlines()

        program = discover(ROOT / 'tests')
        self.assertTrue(any('ScriptPublicContracts.' in item for item in program))
        self.assertFalse(any('SkillPackageTests.' in item for item in program))
        # Discovery of the Skill suite needs its own dependencies; don't import it
        # into the program process merely to count it. Its workflow owns that run.
        self.assertFalse((ROOT / 'tests/skill/__init__.py').exists())


if __name__ == '__main__':
    unittest.main()
