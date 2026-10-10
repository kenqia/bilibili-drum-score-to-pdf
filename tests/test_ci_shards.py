import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CLI = Path(__file__).resolve().parents[1] / 'ci' / 'run_unittest_shard.py'


class CiShardTests(unittest.TestCase):
    def invoke(self, root, index, *extra):
        return subprocess.run(
            [sys.executable, str(CLI), '--tests', str(root), '--index', str(index),
             '--count', '2', *extra], capture_output=True, text=True,
        )

    def test_shard_lists_partition_discovery_and_reject_invalid_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'test_sample.py').write_text(
                'import unittest\nclass Sample(unittest.TestCase):\n'
                ' def test_a(self): pass\n def test_b(self): pass\n'
                ' def test_c(self): pass\n', encoding='utf-8')
            first = self.invoke(root, 0, '--list')
            second = self.invoke(root, 1, '--list')
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            a, b = set(first.stdout.splitlines()), set(second.stdout.splitlines())
            self.assertFalse(a & b)
            self.assertEqual(a | b, {'test_sample.Sample.test_a',
                                    'test_sample.Sample.test_b',
                                    'test_sample.Sample.test_c'})
            self.assertNotEqual(self.invoke(root, 2, '--list').returncode, 0)

    def test_import_error_fails_every_shard_including_listing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'test_broken.py').write_text('raise RuntimeError("broken discovery")\n', encoding='utf-8')
            (root / 'test_good.py').write_text(
                'import unittest\nclass Good(unittest.TestCase):\n def test_ok(self): pass\n',
                encoding='utf-8')
            for index in range(2):
                for extra in [(), ('--list',)]:
                    result = self.invoke(root, index, *extra)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('broken discovery', result.stderr)

    def test_selected_failure_returns_nonzero_and_empty_shard_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'test_result.py').write_text(
                'import unittest\nclass Result(unittest.TestCase):\n'
                ' def test_fail(self): self.fail("expected failure")\n'
                ' def test_pass(self): pass\n', encoding='utf-8')
            failed = self.invoke(root, 0)
            self.assertEqual(failed.returncode, 1)
            self.assertIn('expected failure', failed.stderr)
            passed = self.invoke(root, 1)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            (root / 'test_result.py').unlink()
            self.assertNotEqual(self.invoke(root, 0, '--list').returncode, 0)


if __name__ == '__main__':
    unittest.main()
