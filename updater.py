"""Release installation and transactional systemd updates (Python stdlib only)."""

import argparse
import contextlib
import fcntl
import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

REPO = "anttihil/secretary"
MODEL = "qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_URL = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/" + MODEL
PAYLOAD = (
    "main.py",
    "backend",
    "ai_client.py",
    "aws_client.py",
    "config.py",
    "recording_jobs.py",
    "logging_config.py",
    "pyproject.toml",
    "uv.lock",
    ".env.example",
    "static",
)
# v0.1.0 predates the backend package, durable jobs, and logging module.
CORE_PAYLOAD = (
    "main.py",
    "config.py",
    "pyproject.toml",
    "uv.lock",
    ".env.example",
    "static",
)


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "secretary-updater"})
    with urllib.request.urlopen(request, timeout=60) as response:
        with target.open("wb") as output:
            shutil.copyfileobj(response, output)


def release_info(version: str) -> tuple[str, str, str | None]:
    suffix = "latest" if version == "latest" else "tags/" + version
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/{suffix}",
        headers={"User-Agent": "secretary-updater"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    tag = release["tag_name"]
    if not re.fullmatch(r"v[\w.+-]+", tag):
        raise ValueError(f"Unsupported release tag: {tag!r}")
    for asset in release["assets"]:
        if asset["name"] == f"secretary-{tag}.tar.gz":
            return tag, asset["browser_download_url"], asset.get("digest")
    raise ValueError(f"Release {tag} has no packaged Secretary asset")


def extract_release(archive: Path, destination: Path) -> None:
    """Accept only ordinary files/directories under the archive's secretary root."""
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if (
                not parts
                or parts[0] != "secretary"
                or ".." in parts
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError(f"Unsafe release archive entry: {member.name}")
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            source.extractall(temporary, filter="data")
            payload = Path(temporary) / "secretary"
            for name in CORE_PAYLOAD:
                if not (payload / name).exists():
                    raise ValueError(f"Release is missing {name}")
            if not (payload / "static/index.html").is_file():
                raise ValueError("Release has no built web UI")
            # Runtime state in an archive must never become installation state.
            for name in (".env", "settings.json", "notes", "models", "logs", ".venv"):
                path = payload / name
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            shutil.copytree(payload, destination)


def env_values(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        tokens = shlex.split(value, comments=True)
        result[key.strip()] = " ".join(tokens)
    return result


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def confirm_model_download() -> bool:
    try:
        with open("/dev/tty", "r+") as terminal:
            terminal.write("Download Qwen2.5-3B-Instruct (~2 GB)? [Y/n] ")
            terminal.flush()
            answer = terminal.readline()
        return bool(answer) and not answer.strip().lower().startswith("n")
    except OSError:
        return False


class Installation:
    def __init__(
        self,
        root: Path,
        service: str | None = "secretary",
        health_url: str = "http://127.0.0.1:8000/api/health",
        timeout: float = 300,
        user_service: bool = False,
    ):
        self.root = root.resolve()
        if any(char in str(self.root) for char in ("\n", "\r", '"', "\\")):
            raise ValueError(
                "Installation path contains unsupported service-path characters"
            )
        self.shared = self.root / "shared"
        self.service = service
        self.health_url = health_url
        self.timeout = timeout
        self.user_service = user_service

    @contextlib.contextmanager
    def lock(self):
        with (self.root / ".update.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "Another Secretary update is already running"
                ) from error
            yield

    def systemctl(self, *arguments: str) -> None:
        if self.service:
            prefix = [] if self.user_service or os.geteuid() == 0 else ["sudo"]
            scope = ["--user"] if self.user_service else []
            # A stopped inactive unit can be unloaded: no failure counters remain.
            reset = arguments == ("reset-failed",)
            subprocess.run(
                [*prefix, "systemctl", *scope, *arguments, self.service],
                check=not reset,
                capture_output=reset,
            )

    def validate_service(self) -> None:
        if not self.service:
            return
        # Catch a flat-install unit before it starts the wrong app after switching.
        result = subprocess.run(
            [
                "systemctl",
                *(["--user"] if self.user_service else []),
                "show",
                self.service,
                "--property=WorkingDirectory",
                "--value",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != str(self.root / "current"):
            raise RuntimeError(
                "The service WorkingDirectory must point to "
                f"{self.root / 'current'}. Install/edit the generated unit first."
            )
        for property_name, expected in (
            ("ExecStart", self.root / "current/.venv/bin/fastapi"),
            ("EnvironmentFiles", self.shared / ".env"),
        ):
            result = subprocess.run(
                [
                    "systemctl",
                    *(["--user"] if self.user_service else []),
                    "show",
                    self.service,
                    f"--property={property_name}",
                    "--value",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if str(expected) not in result.stdout:
                raise RuntimeError(
                    f"The service {property_name} must reference {expected}. "
                    "Install/edit the generated unit first."
                )

    def current(self) -> Path:
        link = self.root / "current"
        if not link.is_symlink():
            raise RuntimeError("No versioned installation; run --migrate first")
        target = link.resolve(strict=True)
        if target.parent != self.root / "releases":
            raise RuntimeError("current points outside this installation's releases")
        return target

    def switch(self, name: str, target: Path) -> None:
        temporary = self.root / (name + ".next")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target.relative_to(self.root), target_is_directory=True)
        temporary.replace(self.root / name)

    def link_shared(self, release: Path) -> None:
        for name in (".env", "settings.json", "notes", "models", "logs"):
            path = release / name
            path.unlink(missing_ok=True)
            path.symlink_to(
                self.shared / name,
                target_is_directory=name
                in (
                    "notes",
                    "models",
                    "logs",
                ),
            )

    def sync(self, release: Path) -> None:
        print(f"Installing dependencies in {release.name}", flush=True)
        result = subprocess.run(
            ["uv", "sync", "--frozen", "--no-dev"],
            cwd=release,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            print(result.stdout + result.stderr, file=sys.stderr)
            result.check_returncode()

    def prepare(self, version: str) -> Path:
        tag, url, digest = release_info(version)
        releases = self.root / "releases"
        releases.mkdir(exist_ok=True)
        destination = releases / f"{tag}-{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            archive = Path(temporary) / "release.tar.gz"
            print(f"Downloading {tag}", flush=True)
            download(url, archive)
            if digest:
                with archive.open("rb") as stream:
                    actual = (
                        "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
                    )
                if actual != digest:
                    raise ValueError(
                        "Release checksum does not match GitHub's asset digest"
                    )
            try:
                extract_release(archive, destination)
                atomic_json(
                    destination / ".secretary-release.json",
                    {
                        "tag": tag,
                        "deployment_id": destination.name,
                    },
                )
                self.link_shared(destination)
                self.sync(destination)
            except BaseException:
                if destination.exists():
                    shutil.rmtree(destination)
                raise
        return destination

    def configure_shared(self, source: Path) -> None:
        self.shared.mkdir()
        for name in ("notes", "models", "logs"):
            original = source / name
            target = self.shared / name
            if original.exists():
                shutil.copytree(original, target, symlinks=True)
            else:
                target.mkdir()
        env = source / ".env"
        text = (
            env.read_text() if env.exists() else (source / ".env.example").read_text()
        )
        (self.shared / ".env").write_text(text)
        values = env_values(self.shared / ".env")
        settings = Path(values.get("SETTINGS_FILE", "settings.json"))
        if not settings.is_absolute():
            settings = source / settings
        if settings.exists():
            shutil.copy2(settings, self.shared / "settings.json")
        overrides = {"SETTINGS_FILE": str(self.shared / "settings.json")}
        for key, default in (
            ("NOTES_DIR", "notes"),
            ("LLM_MODEL_PATH", "models/your-model.gguf"),
            ("LOG_DIR", "logs"),
            ("LOG_FILE", "logs/secretary.log"),
            ("LOCAL_AUDIO_PATH", "notes"),
        ):
            value = values.get(key, default)
            path = Path(value)
            original = (
                path.resolve() if path.is_absolute() else (source / path).resolve()
            )
            try:
                relative = original.relative_to(source.resolve())
            except ValueError:
                overrides[key] = str(original)
            else:
                if relative.parts and relative.parts[0] in ("notes", "models", "logs"):
                    overrides[key] = str(self.shared / relative)
                else:
                    overrides[key] = str(original)
        lines = [
            line
            for line in text.splitlines()
            if not ("=" in line and line.split("=", 1)[0].strip() in overrides)
        ]
        lines.extend(f"{key}={json.dumps(value)}" for key, value in overrides.items())
        (self.shared / ".env").write_text("\n".join(lines) + "\n")
        (self.shared / ".env").chmod(0o600)

    def write_controls(self) -> None:
        if Path(__file__).resolve() != self.root / "updater.py":
            shutil.copy2(Path(__file__).resolve(), self.root / "updater.py")
        (self.root / "update.sh").write_text(
            '#!/bin/sh\nset -eu\nROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'exec uv run --no-project --python 3.13 python "$ROOT/updater.py" '
            '--root "$ROOT" "$@"\n'
        )
        (self.root / "update.sh").chmod(0o755)
        root = (
            str(self.root).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
        )
        unit = (
            "[Unit]\nDescription=Secretary dictation\nAfter=network.target\n\n"
            "[Service]\nType=simple\n"
            f"User={getpass.getuser()}\n"
            f"WorkingDirectory={root}/current\n"
            f"EnvironmentFile={root}/shared/.env\n"
            "Environment=ENVIRONMENT=production\n"
            f'ExecStart="{root}/current/.venv/bin/fastapi" run main.py --port 8000\n'
            "Restart=on-failure\nRestartSec=5\nNoNewPrivileges=true\nPrivateTmp=true\n"
            "ProtectSystem=full\n\n[Install]\nWantedBy=multi-user.target\n"
        )
        (self.root / "secretary.service").write_text(unit)

    def snapshot(self) -> Path:
        backup = (
            self.root
            / "backups"
            / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        )
        backup.mkdir(parents=True)
        backup.chmod(0o700)
        for name in (".env", "settings.json"):
            if (self.shared / name).exists():
                shutil.copy2(self.shared / name, backup / name)
        notes = Path(env_values(self.shared / ".env")["NOTES_DIR"]).resolve()
        if notes == self.root or notes in self.root.parents:
            raise ValueError("NOTES_DIR must not contain the installation directory")
        shutil.copytree(notes, backup / "notes", symlinks=True)
        atomic_json(backup / "snapshot.json", {"notes_path": str(notes)})
        print(f"State backup: {backup}", flush=True)
        return backup

    def restore(self, backup: Path) -> None:
        for name in (".env", "settings.json"):
            target = self.shared / name
            if (backup / name).exists():
                shutil.copy2(backup / name, target)
            else:
                target.unlink(missing_ok=True)
        notes = Path(json.loads((backup / "snapshot.json").read_text())["notes_path"])
        if notes.exists():
            shutil.rmtree(notes)
        shutil.copytree(backup / "notes", notes, symlinks=True)

    def healthy(self, release: Path) -> None:
        if not self.service:
            return
        identity = release.name
        # Older releases have no identity endpoint; readiness still tests their API.
        modern = '"/api/health"' in (release / "main.py").read_text()
        url = (
            self.health_url
            if modern
            else self.health_url.removesuffix("/api/health") + "/api/notes"
        )
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    url, timeout=min(5, self.timeout)
                ) as response:
                    data = json.load(response)
                if modern and data.get("deployment_id") != identity:
                    raise ValueError("Health response is from a different release")
                if not modern and not isinstance(data.get("notes"), list):
                    raise ValueError("Notes API is not ready")
                return
            except (OSError, ValueError):
                time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise RuntimeError(f"Release {identity} did not become healthy at {url}")

    def activate(self, target: Path, old: Path) -> None:
        self.validate_service()
        self.systemctl("stop")
        transaction = self.root / ".update-transaction.json"
        try:
            backup = self.snapshot()
            atomic_json(
                transaction,
                {"old": str(old), "target": str(target), "backup": str(backup)},
            )
        except BaseException:
            self.systemctl("start")
            raise
        try:
            self.switch("current", target)
            self.systemctl("start")
            self.healthy(target)
        except BaseException:
            print("Activation failed; restoring previous code and state", flush=True)
            self.recover()
            raise
        self.switch("previous", old)
        transaction.unlink()
        controller = target / "updater.py"
        if controller.is_file():
            temporary = self.root / "updater.py.next"
            shutil.copy2(controller, temporary)
            temporary.replace(self.root / "updater.py")
        print(f"Now running {target.name}", flush=True)

    def recover(self) -> None:
        transaction = self.root / ".update-transaction.json"
        if not transaction.exists():
            raise RuntimeError("No interrupted activation to recover")
        state = json.loads(transaction.read_text())
        old, backup = Path(state["old"]), Path(state["backup"])
        if (
            old.parent != self.root / "releases"
            or backup.parent != self.root / "backups"
        ):
            raise ValueError("Invalid update recovery paths")
        self.systemctl("stop")
        self.switch("current", old)
        self.restore(backup)
        self.systemctl("reset-failed")
        self.systemctl("start")
        self.healthy(old)
        transaction.unlink()

    def update(self, version: str) -> None:
        old = self.current()
        self.validate_service()
        target = self.prepare(version)
        self.activate(target, old)

    def rollback(self) -> None:
        old = self.current()
        previous = self.root / "previous"
        if not previous.is_symlink():
            raise RuntimeError("No previous release to restore")
        target = previous.resolve(strict=True)
        if target.parent != self.root / "releases" or target == old:
            raise RuntimeError("Invalid previous release")
        # Manual rollback retains today's notes; failed activation restores state.
        self.activate(target, old)

    def migrate(self) -> None:
        if (self.root / "current").exists() or self.shared.exists():
            raise RuntimeError(
                "Installation already migrated (or migration needs recovery)"
            )
        if (self.root / ".git").exists():
            raise RuntimeError(
                "Migrate a release installation, not a development Git checkout"
            )
        for name in CORE_PAYLOAD:
            if not (self.root / name).exists():
                raise RuntimeError(f"Existing installation is missing {name}")
        self.systemctl("stop")
        # Preserve the original flat installation for recovery; never move its venv.
        try:
            backup = (
                self.root / "backups" / ("flat-" + uuid.uuid4().hex[:12] + ".tar.gz")
            )
            backup.parent.mkdir(exist_ok=True)
            backup.parent.chmod(0o700)
            originals = [
                p
                for p in self.root.iterdir()
                if p.name not in ("backups", ".update.lock", "releases")
            ]
            with tarfile.open(backup, "w:gz") as archive:
                for original in originals:
                    archive.add(original, arcname=original.name)
            print(f"Original installation backup: {backup}", flush=True)
            releases = self.root / "releases"
            releases.mkdir(exist_ok=True)
            legacy = releases / ("legacy-" + uuid.uuid4().hex[:12])
        except BaseException:
            self.systemctl("start")
            raise
        try:
            self.configure_shared(self.root)
            self.snapshot()  # Includes external NOTES_DIR, not just root/notes.
            legacy.mkdir()
            application_files = {
                *PAYLOAD,
                "README.md",
                "LICENSE",
                "Makefile",
                ".python-version",
                *(path.name for path in originals if path.suffix == ".py"),
            }
            application_files.discard("updater.py")
            for name in application_files:
                source = self.root / name
                if not source.exists():
                    continue
                if source.is_dir():
                    shutil.copytree(source, legacy / name)
                else:
                    shutil.copy2(source, legacy / name)
            self.link_shared(legacy)
            atomic_json(
                legacy / ".secretary-release.json",
                {"tag": "legacy", "deployment_id": legacy.name},
            )
            self.sync(legacy)
            self.switch("current", legacy)
            self.write_controls()
        except BaseException:
            (self.root / "current").unlink(missing_ok=True)
            if legacy.exists():
                shutil.rmtree(legacy)
            if self.shared.exists():
                shutil.rmtree(self.shared)
            self.systemctl("start")
            raise
        print(
            "Migration prepared; service remains stopped. Preserve custom unit "
            "settings, install the generated unit, daemon-reload, then start "
            "the service.",
            flush=True,
        )


def install(root: Path, version: str) -> None:
    if root.exists():
        raise RuntimeError(f"{root} already exists; use update.sh or --migrate")
    installation = Installation(root, service=None)
    root.mkdir(parents=True)
    try:
        install_release(installation, version)
    except BaseException:
        shutil.rmtree(root)
        raise


def install_release(installation: Installation, version: str) -> None:
    root = installation.root
    # Fetch first into a disposable layout, then use its example configuration.
    installation.shared.mkdir()
    for name in ("notes", "models", "logs"):
        (installation.shared / name).mkdir()
    with installation.lock():
        release = installation.prepare(version)
        shutil.rmtree(installation.shared)
        installation.configure_shared(release)
        if confirm_model_download():
            model = installation.shared / "models" / MODEL
            download(MODEL_URL, model)
            env = installation.shared / ".env"
            lines = [
                line
                for line in env.read_text().splitlines()
                if not line.startswith("LLM_MODEL_PATH=")
            ]
            lines.append(f"LLM_MODEL_PATH={json.dumps(str(model))}")
            env.write_text("\n".join(lines) + "\n")
        installation.switch("current", release)
        installation.write_controls()
    print(
        f"Installed in {root.resolve()}. Configure shared/.env, then:\n"
        f"  cd {root.resolve()}/current && uv run fastapi run main.py --port 8000"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version", nargs="?", default="latest", help="release tag or latest"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--migrate", action="store_true")
    actions.add_argument("--rollback", action="store_true")
    actions.add_argument("--recover", action="store_true")
    parser.add_argument("--service", default="secretary", help="systemd unit name")
    parser.add_argument(
        "--user-service", action="store_true", help="use systemctl --user"
    )
    parser.add_argument(
        "--no-service",
        action="store_true",
        help="app must already be stopped; no health check",
    )
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/api/health")
    parser.add_argument(
        "--timeout", type=float, default=300, help="startup timeout in seconds"
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.version != "latest" and not re.fullmatch(r"v[\w.+-]+", args.version):
        parser.error("version must be a v-prefixed release tag or latest")
    try:
        if args.install:
            install(args.root, args.version)
        else:
            installation = Installation(
                args.root,
                None if args.no_service else args.service,
                args.health_url,
                args.timeout,
                args.user_service,
            )
            with installation.lock():
                if args.recover:
                    installation.recover()
                elif (installation.root / ".update-transaction.json").exists():
                    raise RuntimeError(
                        "Interrupted activation; run update.sh --recover"
                    )
                elif args.migrate:
                    installation.migrate()
                elif args.rollback:
                    installation.rollback()
                else:
                    installation.update(args.version)
    except (
        OSError,
        ValueError,
        RuntimeError,
        tarfile.TarError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Update failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
