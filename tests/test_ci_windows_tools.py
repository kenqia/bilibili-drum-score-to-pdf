"""CI bootstrap must reject successful installers that leave missing tools."""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "install_windows_tools", Path(__file__).resolve().parents[1] / "ci/install_windows_tools.py",
)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class WindowsToolBootstrap(unittest.TestCase):
    def test_existing_executables_need_no_install(self):
        with patch.object(bootstrap, "tools_ready", return_value=True), \
             patch.object(bootstrap.subprocess, "run") as run:
            bootstrap.install_tools()
            run.assert_not_called()

    def test_zero_exit_without_tools_retries_then_fails(self):
        with patch.object(bootstrap, "tools_ready", return_value=False), \
             patch.object(bootstrap.shutil, "which", return_value="choco.exe"), \
             patch.object(bootstrap.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
             patch.object(bootstrap.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "ffmpeg.*after 3 attempts"):
                bootstrap.install_tools()
            self.assertEqual(run.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_transient_feed_failure_recovers_and_checks_next_package(self):
        with patch.object(bootstrap, "tools_ready", side_effect=[False, False, True, False, True]), \
             patch.object(bootstrap.shutil, "which", return_value="choco.exe"), \
             patch.object(bootstrap.subprocess, "run") as run, \
             patch.object(bootstrap.time, "sleep"):
            bootstrap.install_tools()
            self.assertEqual([call.args[0][2] for call in run.call_args_list],
                             ["ffmpeg", "ffmpeg", "poppler"])

    def test_timeout_retries_with_a_bound(self):
        with patch.object(bootstrap, "tools_ready", side_effect=[False, False, True, True]), \
             patch.object(bootstrap.shutil, "which", return_value="choco.exe"), \
             patch.object(bootstrap.subprocess, "run", side_effect=[subprocess.TimeoutExpired("choco", 90), None]) as run, \
             patch.object(bootstrap.time, "sleep"):
            bootstrap.install_tools()
            self.assertTrue(all(call.kwargs["timeout"] == 90 for call in run.call_args_list))

    def test_probe_requires_every_executable_and_successful_exit(self):
        for package, commands in bootstrap.TOOLS:
            for failed in range(len(commands)):
                with self.subTest(package=package, executable=commands[failed][0]):
                    with patch.object(bootstrap.shutil, "which", return_value="tool.exe"), \
                         patch.object(bootstrap.subprocess, "run", side_effect=[
                             subprocess.CompletedProcess([], int(index == failed))
                             for index in range(len(commands))
                         ]):
                        self.assertFalse(bootstrap.tools_ready(commands))

    def test_probe_rejects_missing_or_hanging_executable(self):
        with patch.object(bootstrap.shutil, "which", return_value=None):
            self.assertFalse(bootstrap.tools_ready(bootstrap.TOOLS[0][1]))
        with patch.object(bootstrap.shutil, "which", return_value="tool.exe"), \
             patch.object(bootstrap.subprocess, "run", side_effect=subprocess.TimeoutExpired("tool", 15)):
            self.assertFalse(bootstrap.tools_ready(bootstrap.TOOLS[0][1]))


if __name__ == "__main__":
    unittest.main()
