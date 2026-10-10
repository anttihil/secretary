import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import updater


def payload(directory: Path, *, modern: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in updater.PAYLOAD:
        target = directory / name
        if name in ("backend", "static"):
            target.mkdir(exist_ok=True)
        else:
            target.write_text("# application\n")
    (directory / "static/index.html").write_text("<h1>Secretary</h1>")
    (directory / "main.py").write_text('"/api/health"\n' if modern else "# old app\n")
    (directory / ".env.example").write_text(
        "AI_CLIENT=local\nLLM_MODEL_PATH=./models/model.gguf\n"
    )


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "installation"
        self.root.mkdir()
        self.app = updater.Installation(self.root, service=None, timeout=0.02)
        self.source = self.base / "source"
        payload(self.source)
        (self.source / ".env").write_text(
            "# keep comments\nAI_CLIENT=local\nLLM_MODEL_PATH=./models/model.gguf\n"
            "WHISPER_MODEL=tiny.en\n"
        )
        for name in ("notes", "models", "logs"):
            (self.source / name).mkdir()
        (self.source / "models/model.gguf").write_bytes(b"model")
        (self.source / "notes/note.md").write_text("original note")
        (self.source / "notes/.secretary").mkdir()
        (self.source / "notes/.secretary/jobs.sqlite3").write_bytes(b"pending audio")
        (self.source / "settings.json").write_text('{"whisper_model":"tiny.en"}')
        self.app.configure_shared(self.source)
        self.old = self.root / "releases/v1-old"
        payload(self.old)
        self.app.link_shared(self.old)
        self.app.switch("current", self.old)
        self.archive = self.base / "release.tar.gz"
        packaged = self.base / "package/secretary"
        payload(packaged)
        (packaged / "notes").mkdir()
        (packaged / "notes/unwanted.md").write_text("not user data")
        with tarfile.open(self.archive, "w:gz") as archive:
            archive.add(packaged, arcname="secretary")

    def prepare(self):
        digest = "sha256:" + hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with (
            patch(
                "updater.release_info",
                return_value=("v2", self.archive.as_uri(), digest),
            ),
            patch.object(self.app, "sync") as sync,
        ):
            result = self.app.prepare("v2")
        sync.assert_called_once_with(result)
        return result

    def test_prepare_is_clean_and_preserves_state_and_running_release(self):
        (self.old / "obsolete.py").write_text("obsolete")
        new = self.prepare()
        self.assertEqual(self.app.current(), self.old)
        self.assertFalse((new / "obsolete.py").exists())
        self.assertFalse((new / "notes/unwanted.md").exists())
        self.assertEqual((new / "notes/note.md").read_text(), "original note")
        self.assertEqual(
            (new / "settings.json").resolve(), self.app.shared / "settings.json"
        )
        self.assertTrue((new / ".env").is_symlink())
        self.assertEqual(
            json.loads((new / ".secretary-release.json").read_text())["deployment_id"],
            new.name,
        )

    def test_original_release_without_new_backend_modules_can_be_installed(self):
        original = self.base / "original-package/secretary"
        payload(original, modern=False)
        for name in ("backend", "recording_jobs.py", "logging_config.py"):
            path = original / name
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        with tarfile.open(self.archive, "w:gz") as archive:
            archive.add(original, arcname="secretary")
        release = self.prepare()
        self.assertFalse((release / "backend").exists())
        self.assertTrue((release / "main.py").is_file())

    def test_original_flat_release_without_new_backend_modules_can_be_migrated(self):
        flat = self.base / "original-flat"
        payload(flat, modern=False)
        for name in ("backend", "recording_jobs.py", "logging_config.py"):
            path = flat / name
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        (flat / ".env").write_text("LLM_MODEL_PATH=./models/model.gguf\n")
        app = updater.Installation(flat, service=None)
        with patch.object(app, "sync"):
            app.migrate()
        self.assertTrue((app.current() / "main.py").is_file())
        self.assertFalse((app.current() / "backend").exists())

    def test_absolute_paths_inside_flat_install_are_relocated(self):
        flat = self.base / "flat"
        payload(flat)
        (flat / "notes").mkdir()
        (flat / ".env").write_text(f'NOTES_DIR="{flat / "notes"}"\n')
        destination = self.base / "other"
        destination.mkdir()
        app = updater.Installation(destination, service=None)
        app.configure_shared(flat)
        self.assertEqual(
            updater.env_values(app.shared / ".env")["NOTES_DIR"],
            str(app.shared / "notes"),
        )

    def test_activation_service_order_and_manual_rollback_keep_recent_notes(self):
        new = self.prepare()
        events = []
        self.app.validate_service = Mock()
        self.app.systemctl = Mock(
            side_effect=lambda action: events.append((action, self.app.current()))
        )
        self.app.healthy = Mock()
        self.app.activate(new, self.old)
        self.assertEqual(events, [("stop", self.old), ("start", new)])
        self.assertEqual((self.root / "previous").resolve(), self.old)
        (self.app.shared / "notes/note.md").write_text("written after update")
        self.app.rollback()
        self.assertEqual(self.app.current(), self.old)
        self.assertEqual(
            (self.app.shared / "notes/note.md").read_text(), "written after update"
        )
        self.assertEqual((self.root / "previous").resolve(), new)

    def test_failed_health_restores_code_settings_notes_and_pending_audio(self):
        new = self.prepare()
        events = []
        self.app.systemctl = Mock(
            side_effect=lambda action: events.append((action, self.app.current()))
        )

        def unhealthy(release):
            if release == new:
                (self.app.shared / "notes/note.md").write_text("bad migration")
                (self.app.shared / "settings.json").write_text("bad settings")
                (self.app.shared / "notes/.secretary/jobs.sqlite3").unlink()
                raise RuntimeError("unhealthy")

        self.app.healthy = unhealthy
        with self.assertRaisesRegex(RuntimeError, "unhealthy"):
            self.app.activate(new, self.old)
        self.assertEqual(self.app.current(), self.old)
        self.assertEqual(
            (self.app.shared / "notes/note.md").read_text(), "original note"
        )
        self.assertEqual(
            (self.app.shared / "notes/.secretary/jobs.sqlite3").read_bytes(),
            b"pending audio",
        )
        self.assertEqual(
            json.loads((self.app.shared / "settings.json").read_text())[
                "whisper_model"
            ],
            "tiny.en",
        )
        self.assertEqual(
            [action for action, _ in events],
            ["stop", "start", "stop", "reset-failed", "start"],
        )
        self.assertFalse((self.root / ".update-transaction.json").exists())

    def test_failed_service_start_restores_previous_release(self):
        new = self.prepare()

        def service(action):
            if action == "start" and self.app.current() == new:
                raise subprocess.CalledProcessError(1, "systemctl")

        self.app.systemctl = Mock(side_effect=service)
        with self.assertRaises(subprocess.CalledProcessError):
            self.app.activate(new, self.old)
        self.assertEqual(self.app.current(), self.old)

    def test_backup_failure_restarts_without_switching(self):
        self.app.systemctl = Mock()
        self.app.snapshot = Mock(side_effect=OSError("disk full"))
        with self.assertRaisesRegex(OSError, "disk full"):
            self.app.activate(self.prepare(), self.old)
        self.assertEqual(self.app.current(), self.old)
        self.assertEqual(
            [call.args for call in self.app.systemctl.call_args_list],
            [("stop",), ("start",)],
        )

    def test_transaction_write_failure_restarts_without_switching(self):
        new = self.prepare()
        self.app.systemctl = Mock()
        atomic_json = updater.atomic_json

        def disk_full(path, data):
            if path.name == ".update-transaction.json":
                raise OSError("disk full")
            atomic_json(path, data)

        with patch("updater.atomic_json", side_effect=disk_full):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.app.activate(new, self.old)
        self.assertEqual(self.app.current(), self.old)
        self.assertEqual(
            [call.args for call in self.app.systemctl.call_args_list],
            [("stop",), ("start",)],
        )

    def test_checksum_failure_happens_before_service_stop(self):
        self.app.systemctl = Mock()
        with (
            patch(
                "updater.release_info",
                return_value=("v2", self.archive.as_uri(), "sha256:wrong"),
            ),
            self.assertRaisesRegex(ValueError, "checksum"),
        ):
            self.app.update("v2")
        self.app.systemctl.assert_not_called()
        self.assertEqual(self.app.current(), self.old)

    def test_dependency_failure_cleans_incomplete_release_without_stopping(self):
        self.app.systemctl = Mock()
        with (
            patch(
                "updater.release_info", return_value=("v2", self.archive.as_uri(), None)
            ),
            patch.object(
                self.app, "sync", side_effect=subprocess.CalledProcessError(1, "uv")
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.app.update("v2")
        self.assertEqual(list((self.root / "releases").iterdir()), [self.old])
        self.app.systemctl.assert_not_called()

    def test_rejects_traversal_symlinks_and_missing_ui(self):
        for name, kind in (
            ("secretary/../../escape", tarfile.REGTYPE),
            ("secretary/link", tarfile.SYMTYPE),
        ):
            with self.subTest(name=name):
                archive = self.base / "unsafe.tar.gz"
                with tarfile.open(archive, "w:gz") as target:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = "/etc/passwd"
                    target.addfile(member)
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    updater.extract_release(archive, self.base / "unsafe")
        with tarfile.open(self.archive, "w:gz") as target:
            member = tarfile.TarInfo("secretary/main.py")
            member.size = 3
            target.addfile(member, io.BytesIO(b"app"))
        with self.assertRaisesRegex(ValueError, "missing"):
            updater.extract_release(self.archive, self.base / "incomplete")

    def test_external_notes_are_backed_up_and_restored(self):
        notes = self.base / "external-notes"
        notes.mkdir()
        (notes / "external.md").write_text("external original")
        env = self.app.shared / ".env"
        env.write_text(env.read_text() + f'NOTES_DIR="{notes}"\n')
        backup = self.app.snapshot()
        (notes / "external.md").write_text("changed")
        self.app.restore(backup)
        self.assertEqual((notes / "external.md").read_text(), "external original")

    def test_lock_prevents_concurrent_updates(self):
        other = updater.Installation(self.root)
        with self.app.lock(), self.assertRaisesRegex(RuntimeError, "already running"):
            with other.lock():
                self.fail("lock acquired twice")

    def test_interrupted_activation_can_be_recovered(self):
        new = self.prepare()
        backup = self.app.snapshot()
        updater.atomic_json(
            self.root / ".update-transaction.json",
            {
                "old": str(self.old),
                "target": str(new),
                "backup": str(backup),
            },
        )
        self.app.switch("current", new)
        (self.app.shared / "notes/note.md").write_text("partial write")
        self.app.recover()
        self.assertEqual(self.app.current(), self.old)
        self.assertEqual(
            (self.app.shared / "notes/note.md").read_text(), "original note"
        )

    def test_health_requires_matching_deployment_and_supports_older_api(self):
        self.app.service = "secretary"
        wrong = Mock()
        wrong.__enter__ = Mock(return_value=io.BytesIO(b'{"deployment_id":"other"}'))
        wrong.__exit__ = Mock(return_value=False)
        with (
            patch("urllib.request.urlopen", return_value=wrong),
            self.assertRaisesRegex(RuntimeError, "healthy"),
        ):
            self.app.healthy(self.old)
        correct = Mock()
        correct.__enter__ = Mock(
            return_value=io.BytesIO(
                json.dumps({"deployment_id": self.old.name}).encode()
            )
        )
        correct.__exit__ = Mock(return_value=False)
        with patch("urllib.request.urlopen", return_value=correct):
            self.app.healthy(self.old)
        (self.old / "main.py").write_text("# legacy app")
        legacy = Mock()
        legacy.__enter__ = Mock(return_value=io.BytesIO(b'{"notes":[]}'))
        legacy.__exit__ = Mock(return_value=False)
        with patch("urllib.request.urlopen", return_value=legacy) as request:
            self.app.healthy(self.old)
        self.assertEqual(request.call_args.args[0], "http://127.0.0.1:8000/api/notes")

    def test_rejects_flat_service_before_preparing_release(self):
        self.app.service = "secretary"
        with (
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=str(self.root)),
            ),
            patch.object(self.app, "prepare") as prepare,
            self.assertRaisesRegex(RuntimeError, "WorkingDirectory"),
        ):
            self.app.update("v2")
        prepare.assert_not_called()

    def test_rejects_service_using_old_environment_file(self):
        self.app.service = "secretary"
        values = [
            str(self.root / "current"),
            str(self.root / "current/.venv/bin/fastapi"),
            str(self.root / ".env"),
        ]
        with patch(
            "subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=value) for value in values
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "EnvironmentFiles"):
                self.app.validate_service()

    def test_migration_preserves_originals_and_generates_service(self):
        flat = self.base / "flat"
        payload(flat)
        (flat / ".env").write_text("LLM_MODEL_PATH=./models/m.gguf\n")
        (flat / "notes/.secretary").mkdir(parents=True)
        (flat / "notes/.secretary/jobs.sqlite3").write_bytes(b"pending")
        (flat / "models").mkdir()
        (flat / "models/m.gguf").write_bytes(b"model")
        app = updater.Installation(flat, service=None)
        with patch.object(app, "sync"):
            app.migrate()
        self.assertEqual(
            (flat / "notes/.secretary/jobs.sqlite3").read_bytes(), b"pending"
        )
        self.assertEqual(
            (app.current() / "notes/.secretary/jobs.sqlite3").read_bytes(), b"pending"
        )
        self.assertIn(
            str(flat / "current/.venv/bin/fastapi"),
            (flat / "secretary.service").read_text(),
        )
        self.assertTrue((flat / "update.sh").stat().st_mode & 0o111)
        self.assertTrue(list((flat / "backups").glob("flat-*.tar.gz")))
        self.assertEqual(
            updater.env_values(app.shared / ".env")["LLM_MODEL_PATH"],
            str(app.shared / "models/m.gguf"),
        )

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd is unavailable")
    def test_generated_unit_is_valid_systemd_syntax_in_path_with_spaces(self):
        root = self.base / "installation with spaces"
        root.mkdir()
        app = updater.Installation(root, service=None)
        app.write_controls()
        binary = root / "current/.venv/bin/fastapi"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        (root / "shared").mkdir()
        (root / "shared/.env").touch()
        result = subprocess.run(
            ["systemd-analyze", "verify", str(root / "secretary.service")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ignoring", result.stderr)
        self.assertNotIn("not absolute", result.stderr)

    def test_fresh_install_works_with_older_release_and_rejects_existing_target(self):
        root = self.base / "fresh"
        with (
            patch(
                "updater.release_info", return_value=("v1", self.archive.as_uri(), None)
            ),
            patch.object(updater.Installation, "sync"),
            patch("updater.confirm_model_download", return_value=False),
        ):
            updater.install(root, "v1")
        app = updater.Installation(root, service=None)
        self.assertTrue(app.current().is_dir())
        self.assertEqual(
            updater.env_values(app.shared / ".env")["NOTES_DIR"],
            str(app.shared / "notes"),
        )
        self.assertFalse((app.shared / "notes/unwanted.md").exists())
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            updater.install(root, "v1")

    def test_failed_fresh_install_removes_incomplete_target_for_retry(self):
        root = self.base / "failed-install"
        with patch("updater.release_info", side_effect=OSError("offline")):
            with self.assertRaisesRegex(OSError, "offline"):
                updater.install(root, "latest")
        self.assertFalse(root.exists())

    def test_failed_migration_restarts_original_and_can_be_retried(self):
        flat = self.base / "flat-failed"
        payload(flat)
        (flat / ".env").write_text("LLM_MODEL_PATH=./models/model.gguf\n")
        app = updater.Installation(flat, service=None)
        app.systemctl = Mock()
        with patch.object(app, "sync", side_effect=OSError("dependency failure")):
            with self.assertRaisesRegex(OSError, "dependency failure"):
                app.migrate()
        self.assertFalse(app.shared.exists())
        self.assertFalse((flat / "current").exists())
        self.assertTrue((flat / "main.py").exists())
        self.assertEqual(
            [call.args for call in app.systemctl.call_args_list],
            [("stop",), ("start",)],
        )
        with patch.object(app, "sync"):
            app.migrate()
        self.assertTrue(app.current().is_dir())

    def test_migration_archive_failure_restarts_original_service(self):
        flat = self.base / "flat-backup-failed"
        payload(flat)
        app = updater.Installation(flat, service=None)
        app.systemctl = Mock()
        with patch("tarfile.open", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                app.migrate()
        self.assertFalse(app.shared.exists())
        self.assertEqual(
            [call.args for call in app.systemctl.call_args_list],
            [("stop",), ("start",)],
        )


if __name__ == "__main__":
    unittest.main()
