"""Offline maintenance contracts; only synthetic service databases and artifacts."""

from pathlib import Path
import json
import hashlib
from unittest.mock import patch
import os
import subprocess
import sys
import tempfile
import shutil
import sqlite3
import time
import signal
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from drum_score.jobs import Jobs


@unittest.skipUnless(sys.platform == "linux", "Ubuntu offline maintenance contract")
class Maintenance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "service"
        self.jobs = Jobs(self.data)
        self.env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, operation, *args):
        defaults = () if "--min-free-mib" in args else ("--min-free-mib", "1")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "drum_score.maintenance",
                operation,
                *map(str, args),
                *defaults,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_queued_task_roundtrip_keeps_identity_and_does_not_start_work(self):
        task = self.jobs.enqueue(
            "https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.1"
        )
        before = self.jobs.view(task["id"], task["capability"])
        backup = self.root / "backup"
        for operation, args in [
            (
                "backup",
                ("--data-root", self.data, "--output", backup, "--services-stopped"),
            ),
            ("verify", ("--backup-root", backup)),
            ("restore", ("--backup-root", backup, "--output", self.root / "restored")),
        ]:
            result = self.invoke(operation, *args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "complete")
            self.assertNotIn(task["capability"], result.stdout + result.stderr)
        restored = Jobs(self.root / "restored")
        self.assertEqual(restored.view(task["id"], task["capability"]), before)
        self.assertFalse((restored.root / "worker.lock").exists())
        self.assertEqual(self.jobs.view(task["id"], task["capability"]), before)

    def test_complete_pages_and_interrupted_state_restore_with_original_expiry(self):
        from score_fixtures import score_frame, video_from_image
        from drum_score import convert
        from drum_score.worker import retain_delivery

        task = self.jobs.enqueue(
            "https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.1"
        )
        row = self.jobs.claim()
        attempt = self.jobs.register_attempt(row)
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (640, 2400), "white")
        drawing = ImageDraw.Draw(image)
        for top in range(100, 2350, 280):
            for line in range(5):
                drawing.line((25, top + 8 * line, 615, top + 8 * line), fill="black")
            drawing.ellipse((90, top + 12, 100, top + 20), fill="black")
            drawing.line((100, top - 20, 100, top + 18), fill="black", width=2)
        source = video_from_image(image, self.root)
        convert(source, attempt / "result")
        summary = retain_delivery(self.jobs, row)
        self.assertGreater(len(summary["pages"]), 1)
        self.jobs.finishing(row, summary)
        self.jobs.settle(row, "complete")
        original = self.jobs.view(task["id"], task["capability"])
        abandoned = self.jobs.enqueue(
            "https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.2"
        )
        active = self.jobs.claim()
        temporary = self.jobs.register_attempt(active)
        (temporary / "partial.mp4").write_bytes(b"not a result")
        backup = self.root / "backup"
        result = self.invoke(
            "backup", "--data-root", self.data, "--output", backup, "--services-stopped"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(list(backup.rglob("partial.mp4")))
        hooks = self.root / "directory-fault-hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "import os,errno\nreal=os.fsync\ndef sync(fd):\n path=os.readlink('/proc/self/fd/'+str(fd))\n if '.drum-maintenance-' in path and path.endswith('/result'): raise OSError(errno.EIO,'synthetic directory fault')\n return real(fd)\nos.fsync=sync\n"
        )
        for operation in ("backup", "restore"):
            output = self.root / (operation + "-directory-fault")
            args = (
                ["--data-root", str(self.data), "--services-stopped"]
                if operation == "backup"
                else ["--backup-root", str(backup)]
            )
            failure = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "drum_score.maintenance",
                    operation,
                    *args,
                    "--output",
                    str(output),
                    "--min-free-mib",
                    "1",
                ],
                env={
                    **self.env,
                    "PYTHONPATH": str(hooks) + os.pathsep + self.env["PYTHONPATH"],
                },
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(failure.returncode, 2, failure.stdout)
            self.assertFalse(output.exists())
            self.assertFalse(list(self.root.glob(".drum-maintenance-*")))
        self.assertEqual(self.invoke("verify", "--backup-root", backup).returncode, 0)
        target = self.root / "restored"
        result = self.invoke("restore", "--backup-root", backup, "--output", target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        restored = Jobs(target)
        self.assertEqual(restored.view(task["id"], task["capability"]), original)
        for page, ref in [(None, summary["pdf"]), *enumerate(summary["pages"], 1)]:
            fd, _ = restored.open_artifact(task["id"], task["capability"], page)
            with os.fdopen(fd, "rb") as stream:
                self.assertEqual(
                    hashlib.sha256(stream.read()).hexdigest(), ref["sha256"]
                )
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "drum_score.worker",
                "--data-root",
                str(target),
                "--once",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(worker.returncode, 0, worker.stderr)
        self.assertEqual(
            restored.view(abandoned["id"], abandoned["capability"])["state"],
            "interrupted",
        )
        self.assertEqual(restored.view(task["id"], task["capability"]), original)
        with patch(
            "drum_score.jobs.time.time", return_value=original["expires_at"] + 1
        ):
            restored.cleanup()
        self.assertFalse(list(target.rglob("score.pdf")))
        self.assertTrue(list(backup.rglob("score.pdf")))

    def test_verify_and_restore_refuse_extra_files_duplicate_entries_and_links(self):
        backup = self.root / "backup"
        result = self.invoke(
            "backup", "--data-root", self.data, "--output", backup, "--services-stopped"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        for variant in ("extra", "duplicate", "symlink", "hardlink", "fifo", "path"):
            with self.subTest(variant=variant):
                changed = self.root / variant
                shutil.copytree(backup, changed)
                manifest = json.loads((changed / "snapshot.json").read_text())
                if variant == "extra":
                    (changed / "unknown").write_text("synthetic user marker")
                elif variant == "duplicate":
                    manifest["files"].append(dict(manifest["files"][0]))
                elif variant == "symlink":
                    (changed / "outside").symlink_to(self.data / "tasks.sqlite3")
                elif variant == "hardlink":
                    os.link(changed / "tasks.sqlite3", changed / "outside")
                elif variant == "fifo":
                    os.mkfifo(changed / "outside")
                elif variant == "path":
                    manifest["files"][0]["path"] = "../service/tasks.sqlite3"
                (changed / "snapshot.json").write_text(json.dumps(manifest))
                for operation, args in [
                    ("verify", ()),
                    ("restore", ("--output", self.root / (variant + "-restore"))),
                ]:
                    result = self.invoke(operation, "--backup-root", changed, *args)
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertNotIn(str(self.root), result.stdout + result.stderr)
                    self.assertFalse((self.root / (variant + "-restore")).exists())

    def test_active_worker_and_database_writer_are_refused_with_bounded_wait(self):
        from drum_score.worker import worker_lock

        self.jobs.enqueue("https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.1")
        with worker_lock(self.jobs):
            inode = (self.data / "worker.lock").stat().st_ino
            began = time.monotonic()
            result = self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                self.root / "busy",
                "--services-stopped",
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertLess(time.monotonic() - began, 2)
            self.assertEqual((self.data / "worker.lock").stat().st_ino, inode)
        db = sqlite3.connect(self.data / "tasks.sqlite3", isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            began = time.monotonic()
            result = self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                self.root / "busy-db",
                "--services-stopped",
                "--timeout",
                ".1",
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertLess(time.monotonic() - began, 2)
        finally:
            db.rollback()
            db.close()
        self.assertFalse((self.root / "busy").exists())
        self.assertFalse((self.root / "busy-db").exists())

    def test_unknown_schema_and_corrupt_database_are_refused_even_with_matching_file_hash(
        self,
    ):
        backup = self.root / "backup"
        result = self.invoke(
            "backup", "--data-root", self.data, "--output", backup, "--services-stopped"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        for variant in ("schema", "view", "sqlite-prefix", "corrupt"):
            changed = self.root / variant
            shutil.copytree(backup, changed)
            database = changed / "tasks.sqlite3"
            if variant == "corrupt":
                database.write_bytes(b"not sqlite, synthetic sentinel")
            else:
                with sqlite3.connect(database) as db:
                    db.execute(
                        "PRAGMA user_version=2"
                        if variant == "schema"
                        else ("CREATE TABLE sqliteXextra(value TEXT)" if variant == "sqlite-prefix" else "CREATE VIEW unknown AS SELECT 1")
                    )
            manifest = json.loads((changed / "snapshot.json").read_text())
            entry = manifest["files"][0]
            entry["bytes"] = database.stat().st_size
            entry["sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
            (changed / "snapshot.json").write_text(json.dumps(manifest))
            result = self.invoke(
                "restore",
                "--backup-root",
                changed,
                "--output",
                self.root / (variant + "-restored"),
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertFalse((self.root / (variant + "-restored")).exists())

    def test_limits_existing_nested_outputs_and_missing_stopped_ack_do_not_publish(
        self,
    ):
        backup = self.root / "backup"
        cases = [
            ("--max-mib", ".001"),
            ("--max-files", "1"),
            ("--min-free-mib", "1000000000"),
            ("--timeout", ".000001"),
        ]
        for index, extra in enumerate(cases):
            result = self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                self.root / str(index),
                "--services-stopped",
                *extra,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertFalse((self.root / str(index)).exists())
        result = self.invoke("backup", "--data-root", self.data, "--output", backup)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertFalse(backup.exists())
        existing = self.root / "existing"
        existing.mkdir()
        (existing / "sentinel").write_text("user")
        for output in (existing, self.data / "nested"):
            result = self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                output,
                "--services-stopped",
            )
            self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual((existing / "sentinel").read_text(), "user")
        self.assertFalse((self.data / "nested").exists())
        self.assertFalse(list(self.root.glob(".drum-maintenance-*")))

    def test_http_writes_are_blocked_by_snapshot_barrier_without_mutating_source_tasks(
        self,
    ):
        from fastapi.testclient import TestClient
        from drum_score.web import create_app

        hooks = self.root / "hooks"
        hooks.mkdir()
        ready = self.root / "barrier-ready"
        release = self.root / "release"
        (hooks / "sitecustomize.py").write_text(
            "import os,time\nfrom pathlib import Path\nreal=os.fsync\n"
            + "def sync(fd):\n real(fd)\n"
            + " if os.fstat(fd).st_size>100:\n"
            + "  Path("
            + repr(str(ready))
            + ').write_text("ready")\n'
            + "  while not Path("
            + repr(str(release))
            + ").exists(): time.sleep(.01)\n"
            + "os.fsync=sync\n"
        )
        env = {
            **self.env,
            "PYTHONPATH": str(hooks) + os.pathsep + self.env["PYTHONPATH"],
        }
        backup = self.root / "backup"
        application = create_app(self.data)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "drum_score.maintenance",
                "backup",
                "--data-root",
                str(self.data),
                "--output",
                str(backup),
                "--services-stopped",
                "--min-free-mib",
                "1",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while (
                not ready.exists()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            with TestClient(application, client=("192.0.2.2", 2000)) as client:
                response = client.post(
                    "/api/tasks",
                    json={"url": "https://www.bilibili.com/video/BV1rH4y1R7Rk"},
                )
                self.assertEqual(response.status_code, 503, response.text)
            release.write_text("release")
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            created = self.jobs.enqueue(
                "https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.2"
            )
            self.assertEqual(
                self.jobs.view(created["id"], created["capability"])["state"], "queued"
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()

    def test_whole_service_sigkill_recovers_owned_staging_and_preserves_unknown_attempt_files(
        self,
    ):
        self._whole_service_kill()

    def test_staging_recovery_preserves_replaced_root_identity(self):
        self._whole_service_kill("root")

    def test_staging_recovery_preserves_replaced_marker_and_external_link(self):
        self._whole_service_kill("marker")

    def _whole_service_kill(self, mutation=None):
        from score_fixtures import score_frame, video_from_image
        from test_web_worker import BACKEND
        from drum_score.supervision import _identity, _processes

        network = self.root / "network"
        network.mkdir()
        video_from_image(score_frame(), network)
        (network / "network_fixture.py").write_text(BACKEND)
        (network / "sitecustomize.py").write_text(
            "from drum_score import anonymous_backend\nfrom network_fixture import download\nanonymous_backend.download=download\n"
        )
        (network / "mode").write_text("ready")
        tools = self.root / "tools"
        tools.mkdir()
        real = shutil.which("ffmpeg")
        wrapper = tools / "ffmpeg"
        wrapper.write_text(
            "#!"
            + sys.executable
            + "\nimport os,sys\nargs=sys.argv[1:]\n"
            + 'if "-i" in args: args=["-re",*args]\n'
            + "os.execv("
            + repr(real)
            + ",["
            + repr(real)
            + ",*args])\n"
        )
        wrapper.chmod(0o755)
        env = {
            **self.env,
            "PYTHONPATH": str(network) + os.pathsep + self.env["PYTHONPATH"],
            "SYNTHETIC_NETWORK_ROOT": str(network),
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        }
        task = self.jobs.enqueue(
            "https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.1"
        )
        worker = subprocess.Popen(
            [sys.executable, "-m", "drum_score.worker", "--data-root", str(self.data)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tracked = {}
        try:
            identity = _identity(worker.pid)
            deadline = time.monotonic() + 10
            samples = []
            while time.monotonic() < deadline:
                samples = list(
                    self.data.glob(
                        "attempts/*/*/.drum-score-job-*/.drum-score-*/result/samples/*.png"
                    )
                )
                if samples:
                    break
                self.assertIsNone(worker.poll())
                time.sleep(0.01)
            self.assertTrue(samples, "Decoder never produced a real sample")
            job = next(
                parent
                for parent in samples[0].parents
                if parent.name.startswith(".drum-score-job-")
            )
            attempt = job.parent
            (attempt / "user-sentinel").write_text("unknown user file")
            unknown = attempt / ".drum-score-job-unknown"
            unknown.mkdir()
            (unknown / "user").write_text("unknown root")
            for _ in range(3):
                observed, _ = _processes(worker.pid, identity)
                tracked.update(observed)
                for pid in reversed(list(observed)):
                    if _identity(pid) == observed[pid]:
                        os.kill(pid, signal.SIGSTOP)
            self.assertGreaterEqual(len(tracked), 4)
            for pid, start in tracked.items():
                if _identity(pid) == start:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            worker.wait(timeout=5)
            if mutation == "root":
                job.rename(attempt / "quarantined-original")
                job.mkdir()
                (job / "user").write_text("replacement root")
            elif mutation == "marker":
                marker = attempt / ".staging-ownership.json"
                marker.rename(attempt / "quarantined-marker")
                marker.write_text("{}")
                outside = self.root / "outside"
                outside.mkdir()
                (outside / "sentinel").write_text("outside")
                (job / "external-link").symlink_to(outside, target_is_directory=True)
            recovery = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "drum_score.worker",
                    "--data-root",
                    str(self.data),
                    "--once",
                ],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(recovery.returncode, 0, recovery.stderr)
            self.assertEqual(
                self.jobs.view(task["id"], task["capability"])["state"], "interrupted"
            )
            if mutation is None:
                self.assertFalse(job.exists())
            elif mutation == "root":
                self.assertEqual((job / "user").read_text(), "replacement root")
                self.assertTrue((attempt / "quarantined-original").exists())
            else:
                self.assertTrue(job.exists())
                self.assertEqual((outside / "sentinel").read_text(), "outside")
                self.assertTrue((job / "external-link").is_symlink())
            self.assertEqual(
                (attempt / "user-sentinel").read_text(), "unknown user file"
            )
            self.assertEqual((unknown / "user").read_text(), "unknown root")
        finally:
            for pid, start in tracked.items():
                if _identity(pid) == start:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if worker.poll() is None:
                worker.kill()
                worker.wait()

    def test_parent_fsync_failure_reports_published_snapshot_and_never_overwrites_it(
        self,
    ):
        hooks = self.root / "fault-hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "import os,errno\nreal=os.fsync\n"
            + "def sync(fd):\n"
            + ' if os.readlink("/proc/self/fd/"+str(fd))=='
            + repr(str(self.root))
            + ': raise OSError(errno.EIO,"synthetic")\n'
            + " return real(fd)\nos.fsync=sync\n"
        )
        env = {
            **self.env,
            "PYTHONPATH": str(hooks) + os.pathsep + self.env["PYTHONPATH"],
        }
        output = self.root / "backup"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "drum_score.maintenance",
                "backup",
                "--data-root",
                str(self.data),
                "--output",
                str(output),
                "--services-stopped",
                "--min-free-mib",
                "1",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertTrue(json.loads(result.stdout)["error"]["output_published"])
        self.assertTrue(output.is_dir())
        verified = self.invoke("verify", "--backup-root", output)
        self.assertEqual(verified.returncode, 0, verified.stdout)
        self.assertEqual(
            self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                output,
                "--services-stopped",
            ).returncode,
            2,
        )

    def test_rechecks_database_semantics_after_matching_checksum(self):
        self.jobs.enqueue("https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.1")
        backup = self.root / "backup"
        result = self.invoke(
            "backup", "--data-root", self.data, "--output", backup, "--services-stopped"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        for variant in ("literal", "source", "identity", "timestamp"):
            with self.subTest(variant=variant):
                changed = self.root / variant
                shutil.copytree(backup, changed)
                database = changed / "tasks.sqlite3"
                with sqlite3.connect(database) as db:
                    if variant == "literal":
                        db.execute("DROP INDEX unfinished_ip")
                        db.execute(
                            "CREATE UNIQUE INDEX unfinished_ip ON tasks(ip_key) WHERE state IN ('QUEUED','running','cancelling','finishing')"
                        )
                    elif variant == "source":
                        db.execute(
                            "UPDATE tasks SET source=?",
                            (json.dumps({"url": "/synthetic/private-video.mp4"}),),
                        )
                    elif variant == "identity":
                        db.execute("UPDATE tasks SET id='../outside'")
                    else:
                        db.execute("UPDATE tasks SET queued_at='unreadable'")
                manifest = json.loads((changed / "snapshot.json").read_text())
                entry = manifest["files"][0]
                entry["bytes"] = database.stat().st_size
                entry["sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
                (changed / "snapshot.json").write_text(json.dumps(manifest))
                for operation in ("verify", "restore"):
                    args = (
                        ("--output", self.root / (variant + "-restored"))
                        if operation == "restore"
                        else ()
                    )
                    result = self.invoke(operation, "--backup-root", changed, *args)
                    self.assertEqual(
                        result.returncode, 2, (variant, operation, result.stdout)
                    )
                    self.assertFalse((self.root / (variant + "-restored")).exists())

    def test_expired_metadata_is_preserved_without_reviving_source_or_deadline(self):
        task = self.jobs.enqueue(
            "https://www.bilibili.com/video/BV1rH4y1R7Rk", "192.0.2.1"
        )
        cancelled = self.jobs.cancel(task["id"], task["capability"])
        with patch(
            "drum_score.jobs.time.time", return_value=cancelled["expires_at"] + 1
        ):
            self.jobs.cleanup()
        backup = self.root / "backup"
        self.assertEqual(
            self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                backup,
                "--services-stopped",
            ).returncode,
            0,
        )
        output = self.root / "restored"
        result = self.invoke("restore", "--backup-root", backup, "--output", output)
        self.assertEqual(result.returncode, 0, result.stdout)
        with sqlite3.connect(output / "tasks.sqlite3") as db:
            row = db.execute("SELECT state,source,expires_at FROM tasks").fetchone()
        self.assertEqual(row, ("expired", "{}", cancelled["expires_at"]))

    def test_killed_maintenance_never_publishes_or_adopts_private_staging(self):
        backup = self.root / "backup"
        self.assertEqual(
            self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                backup,
                "--services-stopped",
            ).returncode,
            0,
        )
        before = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in backup.iterdir()
        }
        for phase in ("copy", "manifest", "publish"):
            with self.subTest(phase=phase):
                hooks = self.root / (phase + "-hooks")
                hooks.mkdir()
                ready = self.root / (phase + "-ready")
                script = "import os,time,ctypes\nfrom pathlib import Path\n"
                script += (
                    "def stop():\n Path("
                    + repr(str(ready))
                    + ").touch()\n while True: time.sleep(.01)\n"
                )
                if phase == "publish":
                    script += "real=ctypes.CDLL\ndef library(*a,**k):\n stop()\n return real(*a,**k)\nctypes.CDLL=library\n"
                else:
                    leaf = "tasks.sqlite3" if phase == "copy" else "snapshot.json"
                    script += "real=os.open\ndef opened(name,flags,*a,**k):\n fd=real(name,flags,*a,**k)\n"
                    script += (
                        " if name=="
                        + repr(leaf)
                        + " and flags & os.O_EXCL: stop()\n return fd\nos.open=opened\n"
                    )
                (hooks / "sitecustomize.py").write_text(script)
                output = self.root / (phase + "-output")
                args = (
                    ["restore", "--backup-root", str(backup)]
                    if phase == "copy"
                    else ["backup", "--data-root", str(self.data), "--services-stopped"]
                )
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "drum_score.maintenance",
                        *args,
                        "--output",
                        str(output),
                        "--min-free-mib",
                        "1",
                    ],
                    env={
                        **self.env,
                        "PYTHONPATH": str(hooks) + os.pathsep + self.env["PYTHONPATH"],
                    },
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    deadline = time.monotonic() + 5
                    while (
                        not ready.exists()
                        and process.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    self.assertTrue(ready.exists())
                    process.kill()
                    process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
                    if process.stdout:
                        process.stdout.close()
                    if process.stderr:
                        process.stderr.close()
                self.assertFalse(output.exists())
                staging = list(self.root.glob(".drum-maintenance-*"))
                self.assertTrue(staging)
                for abandoned in staging:
                    self.assertEqual(
                        self.invoke("verify", "--backup-root", abandoned).returncode, 2
                    )
                    self.assertEqual(
                        self.invoke(
                            "restore",
                            "--backup-root",
                            abandoned,
                            "--output",
                            self.root / "not-created",
                        ).returncode,
                        2,
                    )
                result = self.invoke(
                    "restore", "--backup-root", backup, "--output", output
                )
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertTrue(all(path.exists() for path in staging))
                self.assertEqual(
                    {
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in backup.iterdir()
                    },
                    before,
                )

    def test_enospc_during_restore_copy_is_bounded_and_cleans_only_own_staging(self):
        backup = self.root / "backup"
        self.assertEqual(
            self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                backup,
                "--services-stopped",
            ).returncode,
            0,
        )
        hooks = self.root / "no-space-hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "import os,errno\nreal=os.fsync\ndef sync(fd):\n if '.drum-maintenance-' in os.readlink('/proc/self/fd/'+str(fd)) and not os.path.isdir('/proc/self/fd/'+str(fd)): raise OSError(errno.ENOSPC,'synthetic private details')\n return real(fd)\nos.fsync=sync\n"
        )
        note = self.root / ".drum-maintenance-operator"
        note.mkdir()
        (note / "sentinel").write_text("keep")
        output = self.root / "restored"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "drum_score.maintenance",
                "restore",
                "--backup-root",
                str(backup),
                "--output",
                str(output),
                "--min-free-mib",
                "1",
            ],
            env={
                **self.env,
                "PYTHONPATH": str(hooks) + os.pathsep + self.env["PYTHONPATH"],
            },
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".drum-maintenance-*")), [note])
        self.assertEqual((note / "sentinel").read_text(), "keep")
        self.assertNotIn("synthetic private details", result.stdout + result.stderr)
        self.assertEqual(self.invoke("verify", "--backup-root", backup).returncode, 0)

    def test_source_changed_during_copy_does_not_publish(self):
        backup = self.root / "backup"
        self.assertEqual(
            self.invoke(
                "backup",
                "--data-root",
                self.data,
                "--output",
                backup,
                "--services-stopped",
            ).returncode,
            0,
        )
        ready, release = self.root / "copy-ready", self.root / "copy-release"
        hooks = self.root / "change-hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "import os,time\nfrom pathlib import Path\nreal=os.open\ndef opened(name,flags,*a,**k):\n fd=real(name,flags,*a,**k)\n if name=='tasks.sqlite3' and flags & os.O_EXCL:\n  Path("
            + repr(str(ready))
            + ").touch()\n  while not Path("
            + repr(str(release))
            + ").exists(): time.sleep(.01)\n return fd\nos.open=opened\n"
        )
        output = self.root / "restored"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "drum_score.maintenance",
                "restore",
                "--backup-root",
                str(backup),
                "--output",
                str(output),
                "--min-free-mib",
                "1",
            ],
            env={
                **self.env,
                "PYTHONPATH": str(hooks) + os.pathsep + self.env["PYTHONPATH"],
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while (
                not ready.exists()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            with (backup / "tasks.sqlite3").open("ab") as stream:
                stream.write(b"synthetic concurrent change")
            release.touch()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 2, stdout + stderr)
            self.assertEqual(json.loads(stdout)["error"]["code"], "source_changed")
            self.assertFalse(output.exists())
            self.assertFalse(list(self.root.glob(".drum-maintenance-*")))
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
