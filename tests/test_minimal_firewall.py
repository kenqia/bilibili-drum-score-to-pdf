"""Keep the spatial core small and dependencies free of removed recovery engines."""
import ast
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/bilibili-drum-score-to-pdf/scripts'
REMOVED = {'ordered_score', 'central_obstruction', 'local_recovery', 'viewport_decisions',
           'resume_score', 'row_tracker', 'viewport_score', 'drum_score', 'quality_score'}


class FirewallTests(unittest.TestCase):
    def test_removed_engines_are_absent_and_no_production_module_imports_them(self):
        for name in REMOVED:
            self.assertFalse((SCRIPTS / f'{name}.py').exists(), name)
        for path in SCRIPTS.glob('*.py'):
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text())
                modules = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules.extend(alias.name.split('.')[0] for alias in node.names)
                    if isinstance(node, ast.ImportFrom) and node.module:
                        modules.append(node.module.split('.')[0])
                self.assertFalse(REMOVED.intersection(modules))

    def test_core_size_and_no_model_or_continuation_options(self):
        paths = [SCRIPTS / f'{name}.py' for name in ('viewport_sampler', 'viewport_tracker', 'candidate_selector')]
        self.assertLessEqual(sum(len(path.read_text().splitlines()) for path in paths), 500)
        text = (SCRIPTS / 'convert.py').read_text()
        for option in ('--model', '--resume', '--answers'):
            self.assertNotIn(option, text)
