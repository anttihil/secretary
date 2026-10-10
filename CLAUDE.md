# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Secretary is a dictation app that stores recordings on the device, uploads them as durable HTTP jobs, and saves transcripts to Markdown notes. AI cleanup is a separate, explicit action.

## Commands

- **Install dependencies:** `uv sync`
- **Run dev server:** `uv run fastapi dev main.py`
- **Lint:** `uv run ruff check .`
- **Format:** `uv run ruff format .`
- **Lint fix:** `uv run ruff check --fix .`
- **Type check:** `uv run pyright`

## Architecture

- `main.py` - FastAPI app with durable recording uploads (`/api/recordings`), note APIs, an AI worker, and a WebSocket dictation endpoint (`/ws`).
- `recording_jobs.py` - SQLite job storage and restart recovery.
- `ai_client.py` - Abstract `AIClient` base class with two implementations:
  - `AWSAIClient` - Uses Amazon Lex V2 for speech transcription, dictation bot provisioning, and custom vocabulary.
  - `LocalAIClient` - Uses faster-whisper for speech-to-text and llama-cpp-python for explicit cleanup.


## Tech Stack

- Python 3.13, managed with `uv`
- FastAPI with WebSocket support
- AWS services: Amazon Lex V2 (via boto3)
- OpenAI Whisper for local transcription
- Ruff for linting/formatting (rules: E, F, I; line-length 88)
- Pyright for static type checking
