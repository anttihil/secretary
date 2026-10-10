"""Note listing, creation, editing, cleanup, moves, and deletion."""

import asyncio
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import paths, worker
from backend.git_sync import schedule_git_sync
from backend.note_storage import (
    ensure_notes_dir,
    find_note,
    is_excluded_note,
    note_response,
    parse_frontmatter,
    read_note,
    slugify,
    validate_note_path,
    write_note,
)
from backend.paths import FILE_TIMESTAMP_FMT, FRONTMATTER_TIMESTAMP_FMT
from backend.worker import CleanupJob

router = APIRouter()


class CreateNoteRequest(BaseModel):
    title: str
    directory: str = ""
    id: uuid.UUID | None = None
    body: str = ""


class AppendNoteRequest(BaseModel):
    text: str


class ReplaceNoteBodyRequest(BaseModel):
    body: str


class MoveNoteRequest(BaseModel):
    directory: str = ""


class RenameNoteRequest(BaseModel):
    title: str


@router.get("/api/notes")
async def list_notes():
    try:
        ensure_notes_dir()
    except OSError:
        raise HTTPException(500, "No notes directory configured")
    note_files = [p for p in paths.NOTES_DIR.rglob("*.md") if not is_excluded_note(p)]
    resolved = paths.NOTES_DIR.resolve()
    note_data = [
        {
            "filename": str(path.resolve().relative_to(resolved)),
            **read_note(path)[0],
        }
        for path in note_files
    ]
    directories = sorted(
        str(d.resolve().relative_to(resolved))
        for d in paths.NOTES_DIR.rglob("*")
        if d.is_dir()
        and not any(
            part.startswith(".") for part in d.relative_to(paths.NOTES_DIR).parts
        )
    )
    notes = sorted(
        note_data,
        key=lambda n: n.get("updated") or n.get("created") or "",
        reverse=True,
    )
    return {"notes": notes, "directories": directories}


@router.post("/api/notes")
async def create_note(req: CreateNoteRequest):
    try:
        ensure_notes_dir()
    except OSError:
        raise HTTPException(500, "No notes directory configured.")
    if not req.title.strip() or "\n" in req.title or "\r" in req.title:
        raise HTTPException(400, "Invalid note title")
    if req.id:
        existing = find_note(str(req.id))
        if existing:
            return note_response(existing)
    if req.directory:
        validate_note_path(req.directory)
        target_dir = paths.NOTES_DIR / req.directory
        if not target_dir.is_dir():
            raise HTTPException(400, "Directory does not exist")
    else:
        target_dir = paths.NOTES_DIR
    timestamp = datetime.now(timezone.utc)
    frontmatter_timestamp = timestamp.strftime(FRONTMATTER_TIMESTAMP_FMT)
    file_timestamp = timestamp.strftime(FILE_TIMESTAMP_FMT)
    basename = f"{slugify(req.title)}-{file_timestamp}.md"
    metadata = {
        "id": str(req.id or uuid.uuid4()),
        "title": req.title,
        "created": frontmatter_timestamp,
        "updated": frontmatter_timestamp,
    }
    path = target_dir / basename
    # Two offline notes with the same title may sync in the same second.
    if path.exists():
        path = target_dir / (
            f"{slugify(req.title)}-{metadata['id'][:8]}-{file_timestamp}.md"
        )
    write_note(path, metadata, req.body)
    schedule_git_sync()
    filename = str(path.resolve().relative_to(paths.NOTES_DIR.resolve()))
    return {"filename": filename, **metadata}


@router.get("/api/notes/{filename:path}")
async def get_note(filename: str):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, body = read_note(path)
    return {"filename": filename, "body": body, **metadata}


@router.post("/api/notes/{filename:path}/append")
async def append_to_note(filename: str, req: AppendNoteRequest):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, body = read_note(path)
    if body and not body.endswith("\n\n"):
        body = body + "\n\n"
    body = body + req.text + "\n\n"
    timestamp = datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
    metadata["updated"] = timestamp
    write_note(path, metadata, body)
    schedule_git_sync()
    return {"filename": filename, "body": body, **metadata}


@router.post("/api/notes/{filename:path}/clean")
async def clean_note(filename: str):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    _, body = parse_frontmatter(path.read_text())
    if not body.strip():
        raise HTTPException(status_code=400, detail="Note is empty")
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    await worker.job_queue.put(
        CleanupJob(job_id=str(uuid.uuid4()), body=body, future=future)
    )
    cleaned = await future
    return {"cleaned": cleaned}


@router.post("/api/notes/{filename:path}/rename")
async def rename_note(filename: str, req: RenameNoteRequest):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, body = read_note(path)
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
    write_note(path, metadata, body)
    if new_path != path:
        path.rename(new_path)
    schedule_git_sync()
    resolved = paths.NOTES_DIR.resolve()
    new_filename = str(new_path.resolve().relative_to(resolved))
    return {"filename": new_filename, "body": body, **metadata}


@router.post("/api/notes/{filename:path}/replace")
async def replace_note_body(filename: str, req: ReplaceNoteBodyRequest):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    metadata, _ = read_note(path)
    timestamp = datetime.now(timezone.utc).strftime(FRONTMATTER_TIMESTAMP_FMT)
    metadata["updated"] = timestamp
    body = req.body if req.body.endswith("\n\n") else req.body + "\n\n"
    write_note(path, metadata, body)
    schedule_git_sync()
    return {"filename": filename, "body": body, **metadata}


@router.post("/api/notes/{filename:path}/move")
async def move_note(filename: str, req: MoveNoteRequest):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    if req.directory:
        validate_note_path(req.directory)
        target_dir = paths.NOTES_DIR / req.directory
        if not target_dir.is_dir():
            raise HTTPException(status_code=400, detail="Directory does not exist")
    else:
        target_dir = paths.NOTES_DIR
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
    resolved = paths.NOTES_DIR.resolve()
    new_filename = str(new_path.resolve().relative_to(resolved))
    metadata, body = parse_frontmatter(new_path.read_text())
    return {"filename": new_filename, "body": body, **metadata}


@router.delete("/api/notes/{filename:path}")
async def delete_note(filename: str):
    path = validate_note_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    path.unlink()
    schedule_git_sync()
    return {"deleted": filename}
