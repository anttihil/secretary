import asyncio
import logging
import os
import re
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_client import AIClient, LocalAIClient

# Load .env file for local development; in production, systemd provides env vars
if os.getenv("ENVIRONMENT") != "production":
    from dotenv import load_dotenv

    load_dotenv()

NOTES_DIR = Path(os.environ.get("NOTES_DIR", Path(__file__).parent / "notes"))
GLOSSARY_PATH = NOTES_DIR / "glossary.txt"
FRONTMATTER_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%S"
FILE_TIMESTAMP_FMT = "%Y%m%d-%H%M%S"

logger = logging.getLogger(__name__)


def ensure_notes_dir():
    NOTES_DIR.mkdir(exist_ok=True)


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    current = path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return True
        current = current.parent
    return False


def git_sync():
    """Commit and push any changes in NOTES_DIR if it's a git repo.

    Best-effort: errors are logged but never raised. Notes are already
    saved to the filesystem before this runs.
    """
    if not is_git_repo(NOTES_DIR):
        return

    try:
        subprocess.run(
            ["git", "add", "--", "."], cwd=NOTES_DIR, check=True, capture_output=True
        )

        try:
            msg = f"Update notes {
                datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
            }"
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    msg,
                ],
                cwd=NOTES_DIR,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass
        subprocess.run(["git", "push"], cwd=NOTES_DIR, check=True, capture_output=True)

    except subprocess.CalledProcessError as e:
        logger.error("Git sync failed: %s (stderr: %s)", e, e.stderr)
    except Exception as e:
        logger.error("Git sync unexpected error: %s", e)


def schedule_git_sync():
    asyncio.create_task(asyncio.to_thread(git_sync))


def slugify(text: str) -> str:
    lowercase = text.lower()
    return re.sub(r"[^a-z0-9]+", "-", lowercase).strip("-")


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    no_frontmatter = ({}, content)
    if not content.startswith("---\n"):
        return no_frontmatter
    second = content.find("---", 3)
    if second == -1:
        return no_frontmatter
    frontmatter = content[3:second]
    keys = {
        k: v
        for k, v in (
            line.split(": ", 1) for line in frontmatter.strip().splitlines() if line
        )
    }
    return (keys, content[second + 3 :].lstrip())


def format_frontmatter(metadata: dict[str, str], body: str) -> str:
    front = "---\n"
    for key, value in metadata.items():
        front += f"{key}: {value}\n"
    front += "---\n"
    return front + "\n" + body


def create_ai_client() -> AIClient:
    client = os.environ.get("AI_CLIENT", "local")
    match client:
        case "local":
            model_path = os.environ["LLM_MODEL_PATH"]
            whisper_model = os.environ.get("WHISPER_MODEL", "base.en")
            return LocalAIClient(model_path, whisper_model, GLOSSARY_PATH)
        # case "aws":
        #    bucket = os.environ["S3_BUCKET"]
        #    return AWSAIClient(local_path=".", s3_bucket=bucket)
        case _:
            raise ValueError("Unknown client type")


@dataclass
class AudioJob:
    job_id: str
    audio_data: bytes
    mode: str
    websocket: WebSocket
    note_filename: str | None = None


audio_queue: asyncio.Queue[AudioJob] = asyncio.Queue()
audio_executor = ThreadPoolExecutor(max_workers=1)

ai_client = create_ai_client()


async def audio_worker():
    """Long-lived worker that processes audio jobs from the queue."""
    while True:
        job = await audio_queue.get()
        try:
            note_context = ""
            if job.note_filename and job.mode == "note":
                note_path = NOTES_DIR / job.note_filename
                if note_path.exists():
                    _, note_context = parse_frontmatter(note_path.read_text())

            loop = asyncio.get_event_loop()
            job_result = await loop.run_in_executor(
                audio_executor,
                ai_client.process_audio,
                job.audio_data,
                job.mode,
                note_context,
            )
            await job.websocket.send_json(
                {
                    "status": "complete",
                    "job_id": job.job_id,
                    "mode": job.mode,
                    "transcript": job_result["transcript"],
                    "result": job_result["result"],
                }
            )
        except Exception as e:
            logger.error("Audio worker error (job %s): %s", job.job_id, e)
            try:
                await job.websocket.send_json(
                    {"status": "error", "job_id": job.job_id, "message": str(e)}
                )
            except Exception:
                pass
        finally:
            audio_queue.task_done()


@asynccontextmanager
async def lifespan(app):
    worker_task = asyncio.create_task(audio_worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


# --- Notes REST API ---


class CreateNoteRequest(BaseModel):
    title: str


class AppendNoteRequest(BaseModel):
    text: str


class ReplaceNoteBodyRequest(BaseModel):
    body: str


class AddGlossaryWordRequest(BaseModel):
    transcript_word: str
    correct_word: str


@app.get("/api/notes")
async def list_notes():
    try:
        ensure_notes_dir()
    except OSError:
        raise HTTPException(500, "No notes directory configured")
    note_files = NOTES_DIR.glob("*.md")

    note_data = [
        {"filename": path.name, **parse_frontmatter(path.read_text())[0]}
        for path in note_files
    ]

    return sorted(note_data, key=lambda n: n.get("updated", ""), reverse=True)


@app.post("/api/notes")
async def create_note(req: CreateNoteRequest):
    try:
        ensure_notes_dir()
    except OSError:
        raise HTTPException(500, "No notes directory configured.")
    timestamp = datetime.now(timezone.utc)
    frontmatter_timestamp = timestamp.strftime(FRONTMATTER_TIMESTAMP_FMT)
    file_timestamp = timestamp.strftime(FILE_TIMESTAMP_FMT)

    filename = f"{slugify(req.title)}-{file_timestamp}.md"

    metadata = {
        "title": req.title,
        "created": frontmatter_timestamp,
        "updated": frontmatter_timestamp,
    }

    path = NOTES_DIR / filename

    path.write_text(data=format_frontmatter(metadata, ""))
    schedule_git_sync()
    return {"filename": filename, **metadata}


@app.get("/api/notes/{filename}")
async def get_note(filename: str):
    path = NOTES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    text = path.read_text()
    metadata, body = parse_frontmatter(text)
    return {"filename": filename, "body": body, **metadata}


@app.post("/api/notes/{filename}/append")
async def append_to_note(filename: str, req: AppendNoteRequest):
    path = NOTES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, body = parse_frontmatter(path.read_text())
    if body and not body.endswith("\n\n"):
        body = body + "\n\n"
    body = body + req.text + "\n\n"

    timestamp = datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
    metadata["updated"] = timestamp
    path.write_text(format_frontmatter(metadata, body))
    schedule_git_sync()
    return {"filename": filename, "body": body, **metadata}


@app.post("/api/notes/{filename}/clean")
async def clean_note(filename: str):
    path = NOTES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    _, body = parse_frontmatter(path.read_text())
    if not body.strip():
        raise HTTPException(status_code=400, detail="Note is empty")
    loop = asyncio.get_event_loop()
    cleaned = await loop.run_in_executor(
        audio_executor, ai_client.clean_note, body
    )
    return {"cleaned": cleaned}


@app.post("/api/notes/{filename}/replace")
async def replace_note_body(filename: str, req: ReplaceNoteBodyRequest):
    path = NOTES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, _ = parse_frontmatter(path.read_text())
    timestamp = datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
    metadata["updated"] = timestamp
    body = req.body if req.body.endswith("\n\n") else req.body + "\n\n"
    path.write_text(format_frontmatter(metadata, body))
    schedule_git_sync()
    return {"filename": filename, "body": body, **metadata}


@app.delete("/api/notes/{filename}")
async def delete_note(filename: str):
    path = NOTES_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    # Prevent path traversal
    if path.resolve().parent != NOTES_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid filename")
    path.unlink()
    schedule_git_sync()
    return {"deleted": filename}


# --- Glossary API ---

@app.get("/api/glossary")
async def get_glossary():
    path = GLOSSARY_PATH
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if " → " in line:
            transcript, correct = line.split(" → ", 1)
            entries.append({"transcript": transcript, "correct": correct})
        else:
            entries.append({"transcript": line, "correct": line})
    return entries


@app.post("/api/glossary")
async def add_glossary_word(req: AddGlossaryWordRequest):
    ensure_notes_dir()
    path = GLOSSARY_PATH
    transcript = req.transcript_word.strip()
    correct = req.correct_word.strip()
    if not transcript or not correct:
        raise HTTPException(400, "Both words are required")
    existing = path.read_text() if path.exists() else ""
    if not existing.endswith("\n") and existing:
        existing += "\n"
    existing += f"{transcript} → {correct}\n"
    path.write_text(existing)
    ai_client.reload_glossary()
    return {"transcript": transcript, "correct": correct}


# --- WebSocket ---


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    recording: bool = False
    chunks: list[bytes] = []
    mode: str = ""
    note_filename: str | None = None

    try:
        while True:
            message = await websocket.receive()
            if "text" in message:
                data = message["text"]
                match data:
                    case "close":
                        await websocket.close()
                        break
                    case data if data.startswith("note:"):
                        if recording:
                            continue
                        recording = True
                        mode = "note"
                        note_filename = data[5:] or None
                        chunks = []
                        await websocket.send_text("Recording started (note mode)")
                    case "note":
                        if recording:
                            continue
                        recording = True
                        mode = "note"
                        note_filename = None
                        chunks = []
                        await websocket.send_text("Recording started (note mode)")
                    case "stop":
                        if not recording:
                            continue
                        recording = False
                        audio_data = b"".join(chunks)
                        job_id = str(uuid.uuid4())
                        job = AudioJob(
                            job_id=job_id,
                            audio_data=audio_data,
                            mode=mode,
                            websocket=websocket,
                            note_filename=note_filename,
                        )
                        await audio_queue.put(job)
                        await websocket.send_json(
                            {"status": "queued", "job_id": job_id}
                        )
                        chunks = []
                        mode = ""
                    case _:
                        await websocket.send_text(f"Unknown command: {data}")
            elif "bytes" in message:
                data = message["bytes"]
                if recording:
                    chunks.append(data)

    except WebSocketDisconnect:
        pass


app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
