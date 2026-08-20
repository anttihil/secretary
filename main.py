import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.types import Scope

from ai_client import AIClient, LocalAIClient, get_whisper_capabilities
from config import get_settings, save_settings
from logging_config import setup_logging

# Load .env file for local development; in production, systemd provides env vars
if os.getenv("ENVIRONMENT") != "production":
    from dotenv import load_dotenv

    load_dotenv()

setup_logging()
logger = logging.getLogger("secretary.main")

NOTES_DIR = Path(os.environ.get("NOTES_DIR", Path(__file__).parent / "notes"))
GLOSSARY_PATH = NOTES_DIR / "glossary.txt"
FRONTMATTER_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%S"
FILE_TIMESTAMP_FMT = "%Y%m%d-%H%M%S"
FILENAME_RE = re.compile(r"^.+-\d{8}-\d{6}\.md$")


def validate_note_path(filename: str) -> Path:
    """Validate and resolve a note path, preventing directory traversal."""
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = (NOTES_DIR / filename).resolve()
    if not path.is_relative_to(NOTES_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return path


def ensure_notes_dir():
    NOTES_DIR.mkdir(exist_ok=True)


def is_excluded_note(path: Path) -> bool:
    """Return True if path is excluded: README.md or inside a hidden directory."""
    if path.name == "README.md":
        return True
    rel = path.relative_to(NOTES_DIR)
    return any(part.startswith(".") for part in rel.parts)


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
        except subprocess.CalledProcessError as commit_err:
            if b"nothing to commit" not in commit_err.stdout:
                logger.error(
                    "Git commit failed: %s (stderr: %s)",
                    commit_err,
                    commit_err.stderr,
                )
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
    settings = get_settings()
    match client:
        case "local":
            model_path = os.environ["LLM_MODEL_PATH"]
            os.environ["WHISPER_DEVICE"] = settings["whisper_device"]
            os.environ["WHISPER_COMPUTE_TYPE"] = settings["whisper_compute_type"]
            return LocalAIClient(model_path, settings["whisper_model"], GLOSSARY_PATH)
        case _:
            raise ValueError("Unknown client type")


@dataclass
class AudioJob:
    job_id: str
    audio_data: bytes
    mode: str
    websocket: WebSocket
    note_filename: str | None = None


@dataclass
class CleanupJob:
    job_id: str
    body: str
    future: asyncio.Future


job_queue: asyncio.Queue[AudioJob | CleanupJob] = asyncio.Queue()
audio_executor = ThreadPoolExecutor(max_workers=1)
worker_busy = False

ai_client = create_ai_client()


async def audio_worker():
    """Long-lived worker that processes audio and cleanup jobs from the queue."""
    global worker_busy
    while True:
        job = await job_queue.get()
        worker_busy = True
        t0 = time.perf_counter()
        try:
            loop = asyncio.get_event_loop()
            if isinstance(job, CleanupJob):
                logger.info(
                    "Processing cleanup job %s (body_len=%d)",
                    job.job_id,
                    len(job.body),
                )
                cleaned = await loop.run_in_executor(
                    audio_executor, ai_client.clean_note, job.body
                )
                job.future.set_result(cleaned)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.info(
                    "Completed cleanup job %s in %.1fms",
                    job.job_id,
                    elapsed_ms,
                )
            else:
                logger.info(
                    "Processing audio job %s (mode=%s, audio_bytes=%d, "
                    "note_filename=%s)",
                    job.job_id,
                    job.mode,
                    len(job.audio_data),
                    job.note_filename,
                )
                note_context = ""
                existing_titles: list[str] = []
                if NOTES_DIR.exists():
                    for p in NOTES_DIR.rglob("*.md"):
                        if not is_excluded_note(p):
                            try:
                                meta, _ = parse_frontmatter(p.read_text())
                                if "title" in meta:
                                    existing_titles.append(meta["title"])
                            except Exception:
                                pass

                if job.note_filename:
                    note_path = NOTES_DIR / job.note_filename
                    if note_path.exists():
                        _, note_context = parse_frontmatter(note_path.read_text())

                job_result = await loop.run_in_executor(
                    audio_executor,
                    ai_client.process_audio,
                    job.audio_data,
                    job.mode,
                    note_context,
                    existing_titles,
                )

                payload = {
                    "status": "complete",
                    "job_id": job.job_id,
                    "mode": job.mode,
                    "transcript": job_result.get("transcript", ""),
                    "result": job_result.get("result", ""),
                }
                if "action" in job_result:
                    payload["action"] = job_result["action"]
                if "command" in job_result:
                    payload["command"] = job_result["command"]

                await job.websocket.send_json(payload)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.info(
                    "Completed audio job %s (mode=%s) in %.1fms",
                    job.job_id,
                    job.mode,
                    elapsed_ms,
                )
        except Exception as e:
            if isinstance(job, AudioJob):
                logger.error(
                    "Worker error (job %s, %d bytes, head %s): %s",
                    job.job_id,
                    len(job.audio_data),
                    job.audio_data[:8].hex(),
                    e,
                )
            else:
                logger.error("Worker error (job %s): %s", job.job_id, e)
            if isinstance(job, CleanupJob):
                if not job.future.done():
                    job.future.set_exception(e)
            else:
                try:
                    await job.websocket.send_json(
                        {"status": "error", "job_id": job.job_id, "message": str(e)}
                    )
                except Exception:
                    pass
        finally:
            worker_busy = False
            job_queue.task_done()


@asynccontextmanager
async def lifespan(app):
    logger.info("Secretary backend starting up")
    worker_task = asyncio.create_task(audio_worker())
    yield
    logger.info("Secretary backend shutting down")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


# --- Queue status ---


@app.get("/api/queue")
async def queue_status():
    return {"total": job_queue.qsize() + (1 if worker_busy else 0)}


# --- Settings API ---


class UpdateSettingsRequest(BaseModel):
    whisper_device: str
    whisper_compute_type: str
    whisper_model: str


@app.get("/api/settings")
async def get_settings_endpoint():
    capabilities = get_whisper_capabilities()
    if isinstance(ai_client, LocalAIClient):
        current = ai_client.get_current_whisper_settings()
    else:
        current = get_settings()
    return {**current, **capabilities}


@app.post("/api/settings")
async def update_settings_endpoint(req: UpdateSettingsRequest):
    if worker_busy:
        raise HTTPException(
            status_code=409, detail="Cannot update settings while processing audio"
        )
    if not isinstance(ai_client, LocalAIClient):
        raise HTTPException(status_code=400, detail="Settings only for local client")
    try:
        ai_client.update_whisper(
            req.whisper_device, req.whisper_compute_type, req.whisper_model
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to reinit whisper: {e}")
    new_settings = {
        "whisper_device": req.whisper_device,
        "whisper_compute_type": req.whisper_compute_type,
        "whisper_model": req.whisper_model,
    }
    save_settings(new_settings)
    capabilities = get_whisper_capabilities()
    return {**new_settings, **capabilities}


# --- Notes REST API ---


class CreateNoteRequest(BaseModel):
    title: str
    directory: str = ""


class CreateDirectoryRequest(BaseModel):
    path: str


class AppendNoteRequest(BaseModel):
    text: str


class ReplaceNoteBodyRequest(BaseModel):
    body: str


class AddGlossaryWordRequest(BaseModel):
    transcript_word: str
    correct_word: str


class MoveNoteRequest(BaseModel):
    directory: str = ""


@app.get("/api/notes")
async def list_notes():
    try:
        ensure_notes_dir()
    except OSError:
        raise HTTPException(500, "No notes directory configured")
    note_files = [p for p in NOTES_DIR.rglob("*.md") if not is_excluded_note(p)]
    resolved = NOTES_DIR.resolve()

    note_data = [
        {
            "filename": str(path.resolve().relative_to(resolved)),
            **parse_frontmatter(path.read_text())[0],
        }
        for path in note_files
    ]

    directories = sorted(
        str(d.resolve().relative_to(resolved))
        for d in NOTES_DIR.rglob("*")
        if d.is_dir()
        and not any(part.startswith(".") for part in d.relative_to(NOTES_DIR).parts)
    )

    notes = sorted(
        note_data,
        key=lambda n: n.get("updated") or n.get("created") or "",
        reverse=True,
    )
    return {"notes": notes, "directories": directories}


@app.post("/api/notes")
async def create_note(req: CreateNoteRequest):
    try:
        ensure_notes_dir()
    except OSError:
        raise HTTPException(500, "No notes directory configured.")

    if req.directory:
        validate_note_path(req.directory)
        target_dir = NOTES_DIR / req.directory
        if not target_dir.is_dir():
            raise HTTPException(400, "Directory does not exist")
    else:
        target_dir = NOTES_DIR

    timestamp = datetime.now(timezone.utc)
    frontmatter_timestamp = timestamp.strftime(FRONTMATTER_TIMESTAMP_FMT)
    file_timestamp = timestamp.strftime(FILE_TIMESTAMP_FMT)

    basename = f"{slugify(req.title)}-{file_timestamp}.md"

    metadata = {
        "title": req.title,
        "created": frontmatter_timestamp,
        "updated": frontmatter_timestamp,
    }

    path = target_dir / basename
    path.write_text(data=format_frontmatter(metadata, ""))
    schedule_git_sync()

    filename = str(path.resolve().relative_to(NOTES_DIR.resolve()))
    return {"filename": filename, **metadata}


@app.get("/api/notes/{filename:path}")
async def get_note(filename: str):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    text = path.read_text()
    metadata, body = parse_frontmatter(text)
    return {"filename": filename, "body": body, **metadata}


@app.post("/api/notes/{filename:path}/append")
async def append_to_note(filename: str, req: AppendNoteRequest):
    path = validate_note_path(filename)
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


@app.post("/api/notes/{filename:path}/clean")
async def clean_note(filename: str):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    _, body = parse_frontmatter(path.read_text())
    if not body.strip():
        raise HTTPException(status_code=400, detail="Note is empty")
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    await job_queue.put(CleanupJob(job_id=str(uuid.uuid4()), body=body, future=future))
    cleaned = await future
    return {"cleaned": cleaned}


class RenameNoteRequest(BaseModel):
    title: str


@app.post("/api/notes/{filename:path}/rename")
async def rename_note(filename: str, req: RenameNoteRequest):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, body = parse_frontmatter(path.read_text())
    m = re.match(r"^(.+)-(\d{8}-\d{6})$", path.stem)
    timestamp_part = (
        m.group(2) if m else datetime.now(timezone.utc).strftime(FILE_TIMESTAMP_FMT)
    )
    new_basename = f"{slugify(req.title)}-{timestamp_part}.md"
    new_path = path.parent / new_basename
    if new_path != path and new_path.exists():
        raise HTTPException(
            status_code=409, detail="A note with that name already exists"
        )
    metadata["title"] = req.title
    metadata["updated"] = datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
    path.write_text(format_frontmatter(metadata, body))
    if new_path != path:
        path.rename(new_path)
    schedule_git_sync()
    resolved = NOTES_DIR.resolve()
    new_filename = str(new_path.resolve().relative_to(resolved))
    return {"filename": new_filename, "body": body, **metadata}


@app.post("/api/notes/{filename:path}/replace")
async def replace_note_body(filename: str, req: ReplaceNoteBodyRequest):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, _ = parse_frontmatter(path.read_text())
    timestamp = datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
    metadata["updated"] = timestamp
    body = req.body if req.body.endswith("\n\n") else req.body + "\n\n"
    path.write_text(format_frontmatter(metadata, body))
    schedule_git_sync()
    return {"filename": filename, "body": body, **metadata}


@app.post("/api/migrate")
async def migrate_notes():
    ensure_notes_dir()
    resolved = NOTES_DIR.resolve()
    migrated = 0
    skipped = 0
    files = []

    for path in sorted(p for p in NOTES_DIR.rglob("*.md") if not is_excluded_note(p)):
        metadata, body = parse_frontmatter(path.read_text())
        actions = []

        m = re.match(r"^(.+)-(\d{8}-\d{6})$", path.stem)
        if m:
            slug = m.group(1)
            file_dt = datetime.strptime(m.group(2), FILE_TIMESTAMP_FMT).replace(
                tzinfo=timezone.utc
            )
        else:
            slug = path.stem
            file_dt = None

        filename_compliant = FILENAME_RE.match(path.name) is not None
        all_keys_present = all(k in metadata for k in ("title", "created", "updated"))

        if all_keys_present and filename_compliant:
            skipped += 1
            continue

        if "title" not in metadata:
            s = slug.replace("-", " ")
            metadata["title"] = s[0].upper() + s[1:]
            actions.append("added title")

        if "created" not in metadata:
            if file_dt:
                metadata["created"] = file_dt.strftime(FRONTMATTER_TIMESTAMP_FMT)
            else:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                metadata["created"] = mtime.strftime(FRONTMATTER_TIMESTAMP_FMT)
            actions.append("added created")

        if "updated" not in metadata:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            metadata["updated"] = mtime.strftime(FRONTMATTER_TIMESTAMP_FMT)
            actions.append("added updated")

        path.write_text(format_frontmatter(metadata, body))

        original_filename = str(path.resolve().relative_to(resolved))
        new_filename = original_filename

        if not filename_compliant:
            created_dt = datetime.strptime(
                metadata["created"], FRONTMATTER_TIMESTAMP_FMT
            )
            created_ts = created_dt.strftime(FILE_TIMESTAMP_FMT)
            new_basename = f"{slugify(metadata['title'])}-{created_ts}.md"
            new_path = path.parent / new_basename
            path.rename(new_path)
            new_filename = str(new_path.resolve().relative_to(resolved))
            actions.append(f"renamed to {new_basename}")

        migrated += 1
        files.append(
            {
                "original_filename": original_filename,
                "filename": new_filename,
                "actions": actions,
            }
        )

    if migrated > 0:
        schedule_git_sync()

    return {"migrated": migrated, "skipped": skipped, "files": files}


@app.post("/api/directories/{path:path}/move")
async def move_directory(path: str, req: MoveNoteRequest):
    validate_note_path(path)
    src = NOTES_DIR / path
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    if req.directory:
        validate_note_path(req.directory)
        target_parent = NOTES_DIR / req.directory
        if not target_parent.is_dir():
            raise HTTPException(
                status_code=400, detail="Target directory does not exist"
            )
    else:
        target_parent = NOTES_DIR

    src_resolved = src.resolve()
    target_parent_resolved = target_parent.resolve()
    is_self_or_descendant = target_parent_resolved == src_resolved or str(
        target_parent_resolved
    ).startswith(str(src_resolved) + os.sep)
    if is_self_or_descendant:
        raise HTTPException(
            status_code=400,
            detail="Cannot move directory into itself or a descendant",
        )

    new_path = target_parent / src.name
    if new_path.resolve() == src_resolved:
        resolved = NOTES_DIR.resolve()
        return {"path": str(src_resolved.relative_to(resolved))}

    if new_path.exists():
        raise HTTPException(
            status_code=409,
            detail="A directory with that name already exists in the target",
        )

    src.rename(new_path)
    schedule_git_sync()

    resolved = NOTES_DIR.resolve()
    return {"path": str(new_path.resolve().relative_to(resolved))}


@app.delete("/api/directories/{path:path}")
async def delete_directory_endpoint(path: str):
    validate_note_path(path)
    dir_path = NOTES_DIR / path
    if not dir_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    shutil.rmtree(dir_path)
    schedule_git_sync()
    return {"deleted": path}


@app.post("/api/directories")
async def create_directory(req: CreateDirectoryRequest):
    validate_note_path(req.path)
    dir_path = NOTES_DIR / req.path
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / ".gitkeep").touch()
    schedule_git_sync()
    return {"path": req.path}


@app.post("/api/notes/{filename:path}/move")
async def move_note(filename: str, req: MoveNoteRequest):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")

    if req.directory:
        validate_note_path(req.directory)
        target_dir = NOTES_DIR / req.directory
        if not target_dir.is_dir():
            raise HTTPException(status_code=400, detail="Directory does not exist")
    else:
        target_dir = NOTES_DIR

    new_path = target_dir / path.name
    if new_path == path:
        metadata, body = parse_frontmatter(path.read_text())
        return {"filename": filename, "body": body, **metadata}

    if new_path.exists():
        raise HTTPException(
            status_code=409,
            detail="A note with that name already exists in the target directory",
        )

    path.rename(new_path)
    schedule_git_sync()

    resolved = NOTES_DIR.resolve()
    new_filename = str(new_path.resolve().relative_to(resolved))
    metadata, body = parse_frontmatter(new_path.read_text())
    return {"filename": new_filename, "body": body, **metadata}


@app.delete("/api/notes/{filename:path}")
async def delete_note(filename: str):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
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
            # The low-level receive() returns the disconnect message rather than
            # raising; calling it again afterwards is a RuntimeError.
            if message["type"] == "websocket.disconnect":
                break
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
                        nf = data[5:]
                        if nf:
                            validate_note_path(nf)
                        note_filename = nf or None
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
                    case data if data.startswith("command:"):
                        if recording:
                            continue
                        recording = True
                        mode = "command"
                        nf = data[8:]
                        if nf:
                            validate_note_path(nf)
                        note_filename = nf or None
                        chunks = []
                        await websocket.send_text("Recording started (command mode)")
                    case "command":
                        if recording:
                            continue
                        recording = True
                        mode = "command"
                        note_filename = None
                        chunks = []
                        await websocket.send_text("Recording started (command mode)")
                    case "stop":
                        if not recording:
                            continue
                        recording = False
                        audio_data = b"".join(chunks)
                        chunks = []
                        if not audio_data:
                            mode = ""
                            await websocket.send_json(
                                {
                                    "status": "error",
                                    "message": "Recording was too short",
                                }
                            )
                            continue
                        job_id = str(uuid.uuid4())
                        job = AudioJob(
                            job_id=job_id,
                            audio_data=audio_data,
                            mode=mode,
                            websocket=websocket,
                            note_filename=note_filename,
                        )
                        await job_queue.put(job)
                        await websocket.send_json(
                            {"status": "queued", "job_id": job_id}
                        )
                        mode = ""
                    case _:
                        await websocket.send_text(f"Unknown command: {data}")
            elif "bytes" in message:
                data = message["bytes"]
                if recording:
                    chunks.append(data)

    except WebSocketDisconnect:
        pass


class CacheControlledStaticFiles(StaticFiles):
    """Cache hashed build assets forever; always revalidate everything else.

    Starlette sets etag/last-modified but no Cache-Control, which lets browsers
    apply heuristic freshness and serve a stale index.html (and the old asset
    hashes it points at) long after a deploy.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if scope["path"].startswith("/assets/"):
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["cache-control"] = "no-cache"
        return response


app.mount(
    "/",
    CacheControlledStaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
