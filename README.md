# Secretary

Secretary is a self-hosted dictation tool designed for seamless note-taking. It accepts audio via WebSocket, transcribes it using Whisper, and uses a local LLM to clean up your notes. Secretary prioritizes your privacy and full ownership of your data. Everything runs entirely on your own hardware, making it completely free to use (aside from electricity costs).

I use this on Tailscale so any device connected to my tailnet can access it from anywhere with an internet connection. This way the web app can be served from my home server while the actual usage is via a mobile browser. There was some initial setup involved: downloading the model file, setting up the Linux service file and installing Tailscale. After that it has been working for months without problems. Amazingly low maintenance for a home brew project!

I find that making notes via audio transcription is relaxing and natural. Because Secretary automatically commits new notes to my private Github repo, there's no manual transfer work.

Of course, one could use many commercial tools for the same purpose but I like that there's no vendor lock-in, subscription costs or sudden terms of service changes with this.

### Desktop view
<img width="1573" height="664" alt="secretary_screenshot" src="https://github.com/user-attachments/assets/71f22242-58cd-4d5a-9827-6a1ecef139d7" />

### Mobile view
<img height="800" alt="Screen Shot 2026-08-07 at 11 11 54" src="https://github.com/user-attachments/assets/65de3175-e11a-4b3b-bbb9-d6d1a3071d88" />
<img align="right" height="800" alt="Screen Shot 2026-08-07 at 11 11 48" src="https://github.com/user-attachments/assets/967c087b-0bba-4477-9f8b-de1d8264cc38" />


## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — the only prerequisite. It installs Python 3.13 and every dependency for you, and the installer below will fetch it if you don't have it.
- `curl` and `tar`
- Roughly **4 GB of free RAM** and **3 GB of disk** for the default model pair

No GPU, no C compiler, no Node.js and no separate ffmpeg install. Releases
ship the web UI already built, and `llama-cpp-python` comes from prebuilt
wheels, so nothing is compiled on your machine.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/anttihil/secretary/main/install.sh | sh
```

This downloads the latest release into `./secretary`, installs the Python
dependencies, offers to fetch a language model, and writes a `.env`. Then:

```bash
cd secretary
uv run fastapi run main.py --port 8000
```

Set `SECRETARY_DIR` to install somewhere else, or `SECRETARY_VERSION` to pin a
release tag. The script never overwrites an existing install — it stops if the
target directory is already there.

Prefer not to pipe a script into a shell? Read it first
([install.sh](install.sh)), or grab the tarball from the
[releases page](https://github.com/anttihil/secretary/releases), unpack it and
run `uv sync --frozen --no-dev` inside.

### Prebuilt wheel coverage

The prebuilt `llama-cpp-python` wheels cover Linux x86_64 and aarch64 (glibc
and musl), macOS on Apple Silicon, and Windows x64. On anything else — an
Intel Mac, for instance — uv falls back to building from source, which needs a
C compiler and CMake.

## Install from source

For hacking on Secretary. This is the path that needs
[Node.js](https://nodejs.org/) 20+ and git, because the web UI is built
locally rather than downloaded:

```bash
git clone https://github.com/anttihil/secretary.git
cd secretary
./setup.sh
make serve
```

`./setup.sh` (also `make setup`) checks prerequisites, installs dependencies,
offers to download a model, writes `.env` and builds the frontend. It is safe
to re-run — it never overwrites an existing `.env` or a model you already have.

<details>
<summary>Manual steps, if you'd rather run them yourself</summary>

```bash
# 1. Install Python and frontend dependencies
make install

# 2. Download a GGUF model (e.g. Qwen2.5-3B-Instruct)
curl -L https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf --create-dirs -o ./models/qwen2.5-3b-instruct-q4_k_m.gguf

# 3. Configure environment
cp .env.example .env
# Edit .env and set LLM_MODEL_PATH to your downloaded model path

# 4. Build static assets
make build

# 5. Serve the app
make serve
```

Step 1 matters: `uv sync` alone installs only the Python side, and step 4
will fail without the frontend's `node_modules`.

</details>

## Setup notes

### First run

Secretary loads both models at startup, so the first launch is slow and needs
a network connection: the Whisper model is downloaded from Hugging Face
the first time it's used (a few hundred MB for the default), and the GGUF file
is read into memory. Later starts are much faster.

Once it's up, open `http://localhost:8000`, press record, say a sentence and
stop. A new `.md` file should appear in `./notes`.

### Choosing models

**Language model.** Any instruction-tuned GGUF works, not just the Qwen model
in the setup script. Smaller models are faster and use less RAM; larger ones
clean up transcripts more reliably. Point `LLM_MODEL_PATH` at whichever file
you downloaded.

**Speech-to-text.** The default `WHISPER_MODEL=base.en` is **English-only**.
For any other language, use a multilingual model — `base`, `small` or
`medium`, in increasing order of accuracy and cost. You can change this in
`.env` or from the settings dialog in the web UI, which also exposes the
device and compute type.

### Microphone access needs HTTPS

Browsers only grant microphone access on secure origins. `http://localhost`
counts as secure, so a local browser works out of the box — but reaching the
server from another machine over plain HTTP does **not**, and recording will
silently fail.

The simplest fix is [Tailscale](#tailnet-hosting), which terminates TLS for
you. Alternatively, get a certificate yourself and run uvicorn directly:

```bash
tailscale cert your-machine.tailnet-name.ts.net
uv run uvicorn main:app --host 0.0.0.0 \
    --ssl-keyfile=your-machine.tailnet-name.ts.net.key \
    --ssl-certfile=your-machine.tailnet-name.ts.net.crt
```

### Using an existing notes folder (optional)

By default Secretary reads and writes notes in `./notes`. To use markdown you
already have, point `NOTES_DIR` at that folder in your `.env`:

```
NOTES_DIR=/home/you/my-notes
```

Secretary expects each note to carry `title`, `created` and `updated`
frontmatter and to be named `title-YYYYMMDD-HHMMSS.md`. Existing files usually
match neither. The **Import existing notes** button at the bottom of the
sidebar fixes that in one pass: it fills in any missing frontmatter (inferring
timestamps from the filename, or falling back to the file's modification time)
and renames files to the expected form. Notes that already conform are left
untouched, so it is safe to run more than once.

It edits the files in place, so back up the folder first. In particular, note
that renaming breaks `[[wikilinks]]` in tools that resolve links by filename,
such as Obsidian — Secretary's own links resolve by title and survive the
rename. If your notes folder is a git repository, Secretary commits and pushes
changes automatically, which includes the import.

### Syncing notes to a git repo (optional)

If `NOTES_DIR` is inside a git repository, Secretary commits and pushes every
change automatically. There is nothing to enable — just make the folder a repo
with a remote:

```bash
cd /home/you/my-notes
git init && git add . && git commit -m "Initial notes"
git remote add origin git@github.com:you/my-notes.git
git push -u origin main
```

Two things to get right, since the push runs unattended:

- **Authentication must be non-interactive.** Use an SSH key without a
  passphrase (or one loaded into an agent the service can reach), or a
  credential helper. If git prompts, the push just fails and is logged.
- **Set `user.name` and `user.email`** in that repo, or commits will fail on
  machines without a global git identity.

Pushes are best-effort: a failure is logged and the note is still saved
locally.

### GPU acceleration (optional)

By default, `llama-cpp-python` comes from the CPU wheel index. For NVIDIA
hardware, edit the `url` of the `llama-cpp-cpu` index in `pyproject.toml` to
point at the matching CUDA build — `cu121` through `cu125` are published, so
check your version with `nvidia-smi` and pick the closest:

```toml
url = "https://abetlen.github.io/llama-cpp-python/whl/cu124/"
```

Leave the index `name` alone; `[tool.uv.sources]` refers to it. Then re-run
`uv sync`. These wheels are prebuilt too, so there's still nothing to compile.
Set `LLM_GPU_LAYERS=-1` in `.env` to actually use the GPU.

If no wheel matches your platform, build with CUDA support instead — this
takes several minutes and needs the CUDA toolkit (`nvcc --version` to verify):

```bash
CMAKE_ARGS="-DGGML_CUDA=on" uv pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir
```

To move Whisper onto the GPU as well, set `WHISPER_DEVICE=cuda` and
`LLM_GPU_LAYERS=-1` (all layers) in your `.env`.

## Usage

Open `http://localhost:8000` in your browser to use the web UI. See
[Microphone access needs HTTPS](#microphone-access-needs-https) before trying
this from another device.

## Running as a Linux service

A unit file is included in the repository. Copy it into place and edit the
placeholders:

```bash
sudo cp secretary.service /etc/systemd/system/secretary.service
sudo editor /etc/systemd/system/secretary.service   # replace YOUR_USER and /path/to/secretary
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now secretary
sudo systemctl status secretary
```

View logs with `journalctl -u secretary -f`.

The unit sets `ENVIRONMENT=production`, which tells Secretary to take its
configuration from systemd's `EnvironmentFile` rather than loading `.env`
itself. It also enables some light sandboxing; drop those lines if they
conflict with where your notes live.

## Tailnet hosting

To expose the web interface on your [Tailscale](https://tailscale.com) tailnet, use `tailscale serve`:

```bash
tailscale serve --bg 8000
```

This makes the app available at `https://<your-machine-name>.<tailnet>.ts.net` over HTTPS, accessible only to devices on your tailnet. Because it serves over HTTPS, microphone access works from your phone without any further certificate setup.

To restrict access to your own user account only:

```bash
tailscale serve --bg --set-path / http://localhost:8000
```

Check serve status with `tailscale serve status` and stop with `tailscale serve --https=443 off`.

## Troubleshooting

**`KeyError: 'LLM_MODEL_PATH'` on startup.** `LLM_MODEL_PATH` isn't set. Check
that `.env` exists and names your model file. Under systemd, check the
`EnvironmentFile` path in the unit.

**`RuntimeError: Directory '.../static' does not exist`.** The frontend hasn't
been built. Run `make install && make build`.

**Loading the model fails with a path error.** `LLM_MODEL_PATH` points at a
file that isn't there. Relative paths resolve from the working directory, so
prefer an absolute path when running as a service.

**`llama-cpp-python` fails to build during install.** You're on a platform
with no prebuilt wheel (see [Prebuilt wheel
coverage](#prebuilt-wheel-coverage)), so it compiles from source and needs a C
compiler and CMake — on Debian/Ubuntu, `sudo apt install build-essential
cmake`.

**Recording does nothing on a phone or another computer.** Almost always the
HTTPS requirement — see
[Microphone access needs HTTPS](#microphone-access-needs-https).

**`Address already in use`.** Something else is on port 8000. Pass a different
one: `uv run fastapi run main.py --port 8080`.

**Transcription and cleanup are very slow.** Expected on modest CPUs. Try a
smaller Whisper model (`tiny.en`) and a smaller or more heavily quantized
GGUF, or enable [GPU acceleration](#gpu-acceleration-optional).

## Releasing

Tagging a version builds the frontend in CI and publishes a tarball containing
the built assets, which is what `install.sh` downloads:

```bash
git tag v0.1.0
git push origin v0.1.0
```

See [.github/workflows/release.yml](.github/workflows/release.yml). The
workflow can also be run manually from the Actions tab against an existing tag.

## License

MIT — see [LICENSE](LICENSE).
