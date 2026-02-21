# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Secretary is a voice-powered AI assistant that accepts audio via WebSocket, transcribes it, and processes it through an LLM. It supports two modes: "note" (transcribe and clean up text) and "command" (transcribe and execute as an LLM prompt).

## Commands

- **Install dependencies:** `uv sync`
- **Run dev server:** `uv run fastapi dev main.py`
- **Lint:** `uv run ruff check .`
- **Format:** `uv run ruff format .`
- **Lint fix:** `uv run ruff check --fix .`

## Architecture

- `main.py` - FastAPI app with a WebSocket endpoint (`/ws`) that manages audio recording sessions. Clients send text commands ("note", "command", "stop", "close") and binary audio chunks.
- `ai_client.py` - Abstract `AIClient` base class with two implementations:
  - `AWSAIClient` - Uses AWS Transcribe for speech-to-text, S3 for audio storage, and Bedrock (Claude) for LLM prompts. Requires `S3_BUCKET` env var.
  - `LocalAIClient` - Uses OpenAI Whisper locally for speech-to-text. No LLM integration yet (stubs only).


## Tech Stack

- Python 3.13, managed with `uv`
- FastAPI with WebSocket support
- AWS services: Bedrock, Transcribe, S3 (via boto3)
- OpenAI Whisper for local transcription
- Ruff for linting/formatting (rules: E, F, I; line-length 88)
