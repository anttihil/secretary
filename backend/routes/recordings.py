"""Durable recording upload, status, retry, and queue endpoints."""

import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend import worker
from backend.worker import RecordingJob

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/queue")
async def queue_status():
    return {"total": worker.job_queue.qsize() + (1 if worker.worker_busy else 0)}


@router.post("/api/recordings", status_code=202)
async def upload_recording(
    id: uuid.UUID = Form(),
    mode: str = Form(),
    audio: UploadFile = File(),
    note_id: uuid.UUID | None = Form(default=None),
):
    if mode != "note":
        raise HTTPException(400, "Invalid recording mode")
    if not note_id:
        raise HTTPException(400, "A note recording requires a target note")
    # Bound request memory; whole-recording upload is appropriate for Opus notes.
    limit = 100 * 1024 * 1024
    data = bytearray()
    while chunk := await audio.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, "Recording exceeds the 100 MiB upload limit")
    if not data:
        raise HTTPException(400, "Recording is empty")
    try:
        row, inserted = worker.recording_store.accept(
            str(id), str(note_id) if note_id else None, mode, bytes(data)
        )
    except ValueError as error:
        raise HTTPException(409, str(error))
    if inserted:
        logger.info(
            "Accepted recording %s (mode=%s, note_id=%s, audio_bytes=%d)",
            id,
            mode,
            note_id,
            len(data),
        )
        await worker.job_queue.put(RecordingJob(str(id)))
    return worker.recording_store.public(row)


@router.get("/api/recordings/{recording_id}")
async def get_recording(recording_id: uuid.UUID):
    row = worker.recording_store.get(str(recording_id))
    if not row:
        raise HTTPException(404, "Recording not found")
    return worker.recording_store.public(row)


@router.post("/api/recordings/{recording_id}/retry")
async def retry_recording(recording_id: uuid.UUID):
    row = worker.recording_store.get(str(recording_id))
    if not row:
        raise HTTPException(404, "Recording not found")
    if row["status"] == "failed":
        result = row["result"]
        if row["error"] and "No speech was recognized" in row["error"]:
            result = None
        worker.recording_store.update(
            str(recording_id),
            "saving" if result else "queued",
            result=result,
            error=None,
        )
        await worker.job_queue.put(RecordingJob(str(recording_id)))
    return worker.recording_store.public(
        worker.recording_store.get(str(recording_id)) or row
    )
