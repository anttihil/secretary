# Secretary

Secretary is a self-hosted dictation tool designed for seamless note-taking. It accepts audio via WebSocket, transcribes it using Whisper, and uses a local LLM to clean up your notes. Secretary prioritizes your privacy and full ownership of your data—everything runs entirely on your own hardware, making it completely free to use (aside from electricity costs).

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Download a GGUF model (e.g. Qwen2.5-3B-Instruct)
curl -L https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf --create-dirs -o ./models/qwen2.5-3b-instruct-q4_k_m.gguf

# 3. Configure environment
cp .env.example .env
# Edit .env and set LLM_MODEL_PATH to your downloaded model path

# 4. Run the server
uv run fastapi dev main.py
```

### GPU acceleration (optional)

By default, `llama-cpp-python` is installed as CPU-only. To enable GPU acceleration on NVIDIA hardware, reinstall it with CUDA support:

```bash
CMAKE_ARGS="-DGGML_CUDA=on" uv pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir
```

This compiles from source and takes several minutes. Requires the CUDA toolkit (`nvcc --version` to verify). Check your CUDA version with `nvidia-smi`.

### AWS mode

To use AWS services (Transcribe, Bedrock, S3) instead of local models:

```bash
uv sync --group aws
```

Set `AI_CLIENT=aws` and `S3_BUCKET=your-bucket` in your `.env` file.

## Usage

Open `http://localhost:8000` in your browser to use the web UI.

## Running as a Linux service

Create a systemd unit file at `/etc/systemd/system/secretary.service`:

```ini
[Unit]
Description=Secretary voice assistant
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/secretary
EnvironmentFile=/path/to/secretary/.env
ExecStart=/path/to/secretary/.venv/bin/fastapi run main.py --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Replace `YOUR_USER` and the paths as appropriate. Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now secretary
sudo systemctl status secretary
```

View logs with `journalctl -u secretary -f`.

## Tailnet hosting

To expose the web interface on your [Tailscale](https://tailscale.com) tailnet, use `tailscale serve`:

```bash
tailscale serve --bg 8000
```

This makes the app available at `https://<your-machine-name>.<tailnet>.ts.net` over HTTPS, accessible only to devices on your tailnet.

To restrict access to your own user account only:

```bash
tailscale serve --bg --set-path / http://localhost:8000
```

Check serve status with `tailscale serve status` and stop with `tailscale serve --https=443 off`.
