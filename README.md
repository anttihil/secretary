# Secretary

Voice-powered AI assistant that accepts audio via WebSocket, transcribes it, and processes it through an LLM. Supports two modes: **note** (transcribe and clean up text) and **command** (transcribe and execute as an LLM prompt).

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Download a GGUF model

Download a small GGUF model file, for example:

- [Qwen2.5-3B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF) (Q4_K_M recommended)
- [Phi-4-mini-instruct-GGUF](https://huggingface.co/microsoft/Phi-4-mini-instruct-gguf)

example:
`curl -L https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf --create-dirs -o ./models/qwen2.5-3b-instruct-q4_k_m.gguf`
Place it somewhere accessible, e.g. `./models/your-model.gguf`.

### 3. Configure environment

Copy `.env.example` to `.env` and set your model path:

```bash
cp .env.example .env
# Edit .env and set LLM_MODEL_PATH to your downloaded model
```

### 4. Run the server

```bash
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

### WebSocket API

Connect via WebSocket to `/ws` and send text commands:

- `note` - Start recording in note mode (transcribe + clean up)
- `command` - Start recording in command mode (transcribe + LLM prompt)
- `stop` - Stop recording and process audio
- `close` - Close the connection

Send binary audio chunks between `note`/`command` and `stop`.

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
