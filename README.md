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
