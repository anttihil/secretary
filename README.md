# Secretary

## Why Secretary?

Dictating a note should be as natural as saying it out loud. Secretary records
in your browser, transcribes with Whisper, and can clean up the text with a local
LLM. Your recordings and Markdown notes stay on your own hardware: no
subscription, vendor lock-in, or third-party AI service required. Optional Git
sync keeps your notes in a repository you control.

I run it on a home server and use it from my phone over Tailscale. Once set up,
it needs little attention.

## Install

Choose **a release** for everyday use, or **a Git checkout** to develop or run
unreleased changes. Either can run as a Linux service.

### From a GitHub release (recommended)

You need `curl` and roughly **4 GB RAM / 3 GB disk** for the default
models. The installer installs [uv](https://docs.astral.sh/uv/getting-started/installation/)
if needed (to manage Python 3.13 and dependencies) and offers a model download.

```bash
curl -LsSf https://raw.githubusercontent.com/anttihil/secretary/main/install.sh | sh
cd secretary/current
uv run fastapi run main.py --port 8000
```

The installer downloads the latest release into `./secretary/releases/`, creates
`shared/.env`, and points `current` at the installed release.

Set `SECRETARY_DIR` to choose another location or `SECRETARY_VERSION` to choose
a release tag (pass these to `sh` when using the pipeline). **It is a fresh-install
script, not an updater:** it refuses an existing target directory.

The installer uses the **`secretary-v….tar.gz` release asset** from
[GitHub Releases](https://github.com/anttihil/secretary/releases). GitHub's
automatic “Source code” archives do not include the built web UI. If you skip
the model download, set `LLM_MODEL_PATH` in `shared/.env` before starting.

Release assets need no Node.js or separate ffmpeg installation. Prebuilt CPU
wheels cover Linux x86_64/aarch64 (glibc and musl), Apple Silicon macOS, and
Windows x64. Other platforms may need a C compiler and CMake.

### From a Git checkout

Install uv, Git, `curl`, Node.js 20+, and `make`, then:

```bash
git clone https://github.com/anttihil/secretary.git
cd secretary
./setup.sh
make serve
```

Setup installs dependencies, offers a model download, creates `.env`, and builds
the UI. Re-running it preserves an existing `.env` and downloaded models.

### First start

Open `http://localhost:8000`, create a note with **+ New**, record, and stop.
The first start needs internet access to download Whisper and takes longer while
the models load. Release installs keep notes in `shared/notes`; Git checkouts
use `./notes`. Below, “`.env`” means `shared/.env` for a release installation.

For another language, change `WHISPER_MODEL=base.en` (English-only) to `base`,
`small`, or `medium` in `.env` or the web settings. Set `LLM_MODEL_PATH` to your
instruction-tuned GGUF model; smaller models use less RAM and run faster.

## Run as a Linux service

After installing and checking that the app starts:

```bash
cd /path/to/secretary
sudo cp secretary.service /etc/systemd/system/secretary.service
sudo editor /etc/systemd/system/secretary.service
# Release installs generate the user and paths; review before installing.
sudo systemctl daemon-reload
sudo systemctl enable --now secretary
sudo systemctl status secretary
```

For release installs, the generated unit runs `current/.venv/bin/fastapi` from
`current` and reads `shared/.env`. These paths stay fixed across updates.
For a Git checkout, replace `YOUR_USER`, use the checkout as `WorkingDirectory`,
and point `EnvironmentFile` / `ExecStart` at its `.env` / `.venv/bin/fastapi`.
Restart the service after editing `.env`. Prefer absolute model and notes paths.

### Access from a phone or another computer

Microphone access requires **HTTPS**, except on `http://localhost`. With
[Tailscale](https://tailscale.com) installed and HTTPS enabled for your tailnet:

```bash
tailscale serve --bg 8000
tailscale serve status
```

Open `https://<machine>.<tailnet>.ts.net` from a device on your tailnet. Access is
controlled by your Tailscale policy. Stop serving with
`tailscale serve --https=443 off`. You can also use your own HTTPS reverse proxy.

## Update and maintain

**Updates are user-triggered.** Release installs have a one-command updater;
Git checkouts use Git and a frontend build. Nothing updates on a schedule.

### Update a release installation

Run as the installation owner (not with `sudo`):

```bash
cd /path/to/secretary
./update.sh                 # Latest GitHub release
./update.sh vX.Y.Z          # A specific release tag
./update.sh --rollback      # Switch back, retaining current notes/settings
```

The updater downloads and validates the package (including GitHub's SHA-256
digest when provided), then installs dependencies in a fresh release directory
while the service keeps running. It uses `sudo` only to stop/start the service,
backs up settings and notes while stopped, switches `current`, and waits for
the running app's health check. Failed activation restores the previous code
and pre-update state. After a killed/interrupted activation, run
`./update.sh --recover` to restore that same snapshot.

Models and other persistent files live in `shared/`; application files and
virtual environments live in `releases/`. Obsolete application files cannot
leak into a new version. Backups are retained in `backups/`. Old release
directories are retained too; remove only ones not referenced by `current` or
`previous`. Allow disk space for two releases and a notes backup.

Read release notes before updating: manual rollback keeps today's data and
cannot undo incompatible data migrations. The new `.env.example` is available
under `current`; add any required new settings to `shared/.env`.

For a different service/port, use `--service NAME` and
`--health-url http://127.0.0.1:PORT/api/health`. Startup waits up to 300 seconds;
increase with `--timeout SECONDS` for slow model loading. User-level systemd
units use `--user-service`. Older releases without `/api/health` are checked
through `/api/notes`, without deployment identity verification.

For a terminal-run installation, stop the app yourself, run
`./update.sh --no-service`, and start from `current` again. This mode does not
control a service or perform a startup health check.

### Migrate an existing release/service installation (once)

For an older flat installation, download the new updater into that directory
and run it as the installation owner:

```bash
cd /path/to/secretary
curl -fL https://raw.githubusercontent.com/anttihil/secretary/main/updater.py -o updater.py
uv run --no-project --python 3.13 python updater.py --migrate
sudo editor /etc/systemd/system/secretary.service
# Use the generated secretary.service paths; preserve custom service settings.
sudo systemctl daemon-reload
sudo systemctl start secretary
sudo systemctl status secretary
./update.sh
```

Migration stops the service, backs up the original installation and notes,
copies persistent files into `shared/`, and prepares a `legacy` release with a
new virtual environment. It leaves the service stopped for the one-time unit
edit. Allow extra disk space for the backup and copied models/data. Original
flat files remain for recovery; use `current` / `shared` afterward.
For a terminal install, pass `--no-service` after stopping it yourself. Git
checkouts keep using the separate instructions below.

### Update a Git checkout

Commit or stash local code changes first and make a backup with the service
stopped (see below). Run each step only if the previous one succeeds:

```bash
cd /path/to/secretary
sudo systemctl stop secretary
git pull --ff-only
uv sync --frozen --no-dev
cd client
npm ci
cd ..
make build
sudo systemctl start secretary
sudo systemctl status secretary
journalctl -u secretary -n 50 --no-pager
```

This updates the current branch, usually `main`; GitHub releases do not update
your checkout automatically. To run a particular release instead, use
`git fetch --tags` and `git switch --detach vX.Y.Z` in place of `git pull`, then
sync dependencies and rebuild as above. For development, use `uv sync` to also
install development dependencies.

### Backups and recovery

- Stop the service for a consistent backup. Keep `.env`, `settings.json`, and
  your entire notes directory, **including `NOTES_DIR/.secretary/jobs.sqlite3`**
  (pending recordings and job state). Back up custom systemd configuration too.
- The updater snapshots `.env`, `settings.json`, and the entire configured
  `NOTES_DIR`, including external folders. Keep a separate backup outside the
  installation/machine too. Models can be backed up or downloaded again.
- Automatic Git sync covers notes, **not** the hidden job database. Keep note
  `id` and `recording_jobs` frontmatter when editing externally; these prevent
  recordings from being appended twice after recovery.
- `--rollback` switches application versions while retaining current data.
  If a release changed the data format, stop the app and restore compatible
  notes/settings from a backup too. Restoring old data discards later edits.
- Run **one backend process** for the recording queue. After an update, reload
  the browser and check that a short recording saves successfully.

### Everyday commands

```bash
sudo systemctl restart secretary       # Apply .env changes
sudo systemctl status secretary        # Check service health
journalctl -u secretary -f             # Follow logs
```

Logs also rotate daily in `./logs/secretary.log`, with 30 rotated files retained.
Use `LOG_DIR` / `LOG_FILE` to change the location and `LOG_LEVEL=DEBUG` for more
detail. Cleanup requests and model outputs are logged; debug logging also
includes full prompts.

## Notes and daily use

### Using an existing notes folder

Set `NOTES_DIR=/home/you/my-notes` in `.env`. Back up that folder, then use
**Import existing notes** at the bottom of the sidebar to add missing frontmatter
and rename files to Secretary's format. Import edits files in place; renaming
can break filename-based `[[wikilinks]]` in other tools such as Obsidian.

### Syncing notes to Git (optional)

If the notes folder is in a Git repository, Secretary automatically commits and
pushes changes, including imports. For a new repository:

```bash
cd /home/you/my-notes
git init -b main
git config user.name "Your Name"
git config user.email "you@example.com"
git add .
git commit -m "Initial notes"
git remote add origin git@github.com:you/my-notes.git
git push -u origin main
```

Authentication must work without prompts **as the service user** (SSH key/agent
or credential helper). Failed pushes are logged; notes remain saved locally.

### Recording offline

Open Secretary online once to cache the app. You can then create notes and
record offline. Press **Stop** and wait for **Saved on device** before closing
the page. The recording queue shows upload, processing, and save progress;
failed recordings can be retried or downloaded.

Pending uploads resume when you reopen the app online; supported browsers can
also upload via Background Sync. Once uploaded, processing continues even with
the browser closed. Clearing browser site data deletes unuploaded recordings.
Each upload is limited to 100 MiB. Use **Clean up** to edit a transcript with AI.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Missing `LLM_MODEL_PATH` or model path error | Check `.env`, the model file, and the service's `EnvironmentFile` / `WorkingDirectory`. Prefer absolute paths. |
| Missing `static/` | Release install: use the packaged release asset, not a source archive. Git checkout: run `make install && make build`. |
| Recording fails on a phone | Use HTTPS; plain HTTP only works for microphone access on localhost. |
| Port 8000 is in use | Stop the other server or use `--port 8080` (update the service/proxy too). |
| Slow transcription or cleanup | Try `WHISPER_MODEL=tiny.en` for English or a smaller GGUF model. |
| `llama-cpp-python` needs compiling | A wheel may not cover your platform. On Debian/Ubuntu install `build-essential cmake`. |

<details>
<summary>Optional NVIDIA GPU setup</summary>

In `pyproject.toml`, change the `llama-cpp-cpu` index URL to a matching published
CUDA wheel index, such as `https://abetlen.github.io/llama-cpp-python/whl/cu124/`.
Keep the index name unchanged and run `uv sync`. Set `LLM_GPU_LAYERS=-1` and,
for Whisper, `WHISPER_DEVICE=cuda` in `.env`, then restart. This is a local
dependency customization: preserve/reapply it when updating.

</details>

## Screenshots

<details>
<summary>Desktop and mobile views</summary>

<img width="1573" height="664" alt="Secretary desktop view" src="https://github.com/user-attachments/assets/71f22242-58cd-4d5a-9827-6a1ecef139d7" />
<img height="800" alt="Secretary mobile notes view" src="https://github.com/user-attachments/assets/65de3175-e11a-4b3b-bbb9-d6d1a3071d88" />
<img height="800" alt="Secretary mobile recording view" src="https://github.com/user-attachments/assets/967c087b-0bba-4477-9f8b-de1d8264cc38" />

</details>

## Development and releases

From a Git checkout, `make dev` runs backend and frontend development servers.
Checks:

```bash
uv run python -m unittest discover -s tests -v
make check
make build
cd client
npm exec tsc -- --noEmit
```

User-facing code changes also require browser verification; see [AGENTS.md](AGENTS.md).
Pushing a `v*` tag runs [the release workflow](.github/workflows/release.yml),
which builds the UI and publishes `secretary-<tag>.tar.gz`. It can also be run
manually for an existing tag from GitHub Actions.

## License

MIT — see [LICENSE](LICENSE).
