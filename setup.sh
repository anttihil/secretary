#!/bin/sh
# Bootstrap a fresh clone: check prerequisites, install dependencies, fetch a
# model, write .env and build the frontend. Safe to re-run — it never
# overwrites an existing .env or an already downloaded model.
set -eu

MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_PATH="./models/qwen2.5-3b-instruct-q4_k_m.gguf"

cd "$(dirname "$0")"

say() { printf '\n==> %s\n' "$1"; }
die() { printf 'error: %s\n' "$1" >&2; exit 1; }

say "Checking prerequisites"
command -v uv >/dev/null 2>&1 || die "uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
command -v npm >/dev/null 2>&1 || die "npm not found. Install Node.js 20+: https://nodejs.org/"
command -v git >/dev/null 2>&1 || die "git not found."
command -v curl >/dev/null 2>&1 || die "curl not found."
uv --version
printf 'node %s, npm %s\n' "$(node --version)" "$(npm --version)"

say "Installing dependencies"
uv sync
(cd client && npm install)

say "Fetching a language model"
model=$(find ./models -name '*.gguf' 2>/dev/null | head -n 1)
if [ -n "$model" ]; then
    echo "Using the model already in ./models: $model"
elif [ ! -t 0 ]; then
    echo "Not running interactively — skipping the ~2 GB download."
    echo "Fetch one later with:"
    echo "  curl -L $MODEL_URL --create-dirs -o $MODEL_PATH"
else
    printf 'Download Qwen2.5-3B-Instruct (~2 GB) to %s? [Y/n] ' "$MODEL_PATH"
    read -r reply || reply=n   # treat EOF (Ctrl-D) as "no"
    case "$reply" in
        [Nn]*) echo "Skipped. Set LLM_MODEL_PATH in .env to your own GGUF model." ;;
        *) curl -fL "$MODEL_URL" --create-dirs -o "$MODEL_PATH" && model=$MODEL_PATH ;;
    esac
fi

say "Configuring .env"
if [ -f .env ]; then
    echo ".env already exists — leaving it alone."
    [ -n "$model" ] || echo "Make sure LLM_MODEL_PATH points at a GGUF model."
else
    cp .env.example .env
    if [ -n "$model" ]; then
        sed -i.bak "s|^LLM_MODEL_PATH=.*|LLM_MODEL_PATH=$model|" .env && rm -f .env.bak
        echo "Wrote .env with LLM_MODEL_PATH=$model"
    else
        echo "Wrote .env — set LLM_MODEL_PATH to your model before starting."
    fi
fi

say "Building the frontend"
(cd client && npm run build)

say "Done. Start the server with:"
echo "  make serve"
echo
echo "Then open http://localhost:8000"
