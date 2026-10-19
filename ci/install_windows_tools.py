"""Install CI tools with bounded retries and verify the actual executables."""

import os
import shutil
import subprocess
import time


TOOLS = (
    ("ffmpeg", (("ffmpeg", "-version"), ("ffprobe", "-version"))),
    ("poppler", (("pdftoppm", "-v"), ("pdfinfo", "-v"), ("pdfimages", "-v"))),
)


def tools_ready(commands):
    for command in commands:
        executable = shutil.which(command[0])
        if executable is None:
            return False
        try:
            result = subprocess.run(
                [executable, *command[1:]], timeout=15,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
    return True


def install_tools():
    for package, commands in TOOLS:
        if tools_ready(commands):
            print(f"{package}: executables verified", flush=True)
            continue
        installer = shutil.which("choco")
        if installer is None:
            raise RuntimeError("Chocolatey is unavailable")
        for attempt in range(1, 4):
            print(f"{package}: installation attempt {attempt}/3", flush=True)
            try:
                subprocess.run(
                    [installer, "install", package, "--no-progress", "--limit-output",
                     "--execution-timeout=60", "-y"], timeout=90, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                print(f"{package}: installer failed or timed out", flush=True)
            # Chocolatey can return zero after feed errors and install nothing.
            if tools_ready(commands):
                print(f"{package}: executables verified", flush=True)
                break
            if attempt == 3:
                raise RuntimeError(f"{package}: executables unavailable after 3 attempts")
            time.sleep(10)


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This bootstrap requires Windows")
    install_tools()
