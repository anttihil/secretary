"""Shared AI job queue, durable recording processing, and worker lifecycle."""

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import WebSocket

from backend import paths
from backend.ai_factory import create_ai_client
from backend.git_sync import schedule_git_sync
from backend.note_storage import find_note, read_note, write_note
from backend.paths import FRONTMATTER_TIMESTAMP_FMT
from recording_jobs import RecordingStore

logger = logging.getLogger(__name__)


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


@dataclass
class RecordingJob:
    job_id: str


job_queue: asyncio.Queue[AudioJob | CleanupJob | RecordingJob] = asyncio.Queue()
recording_store = RecordingStore(paths.NOTES_DIR / ".secretary")
audio_executor = ThreadPoolExecutor(max_workers=1)
worker_busy = False
ai_client = create_ai_client()


async def process_recording(recording_id: str):
    row = recording_store.get(recording_id)
    if not row or row["status"] not in ("queued", "saving"):
        return
    if row["mode"] != "note":
        raise ValueError("Invalid recording mode")
    logger.info("Processing durable recording %s (mode=%s)", recording_id, row["mode"])
    result = json.loads(row["result"]) if row["result"] else None
    if result is None:
        recording_store.update(recording_id, "transcribing", error=None)
        path = find_note(row["note_id"]) if row["note_id"] else None
        if row["note_id"] and not path:
            raise ValueError("The target note was deleted")
        result = await asyncio.get_running_loop().run_in_executor(
            audio_executor, ai_client.process_audio, row["audio"]
        )
        recording_store.update(recording_id, "saving", result=json.dumps(result))

    path = find_note(row["note_id"]) if row["note_id"] else None
    if not path:
        raise ValueError("Select a target note for this recording")
    text = str(result.get("result") or result.get("transcript") or "").strip()
    if not text:
        raise ValueError("No speech was recognized. The audio is retained for retry.")
    metadata, body = read_note(path)
    receipts = metadata.get("recording_jobs", "").split(",")
    if recording_id not in receipts:
        if body and not body.endswith("\n\n"):
            body += "\n\n"
        body += text + "\n\n"
        metadata["recording_jobs"] = ",".join(
            [receipt for receipt in receipts if receipt] + [recording_id]
        )
        metadata["updated"] = datetime.now(timezone.utc).strftime(
            FRONTMATTER_TIMESTAMP_FMT
        )
        write_note(path, metadata, body)
    saved_note_id = metadata["id"]
    # If a crash occurs before this transaction, the note's receipt prevents replay.
    recording_store.update(
        recording_id, "succeeded", saved_note_id=saved_note_id, error=None, audio=None
    )
    logger.info("Saved durable recording %s to note %s", recording_id, saved_note_id)
    schedule_git_sync()


async def audio_worker():
    """Long-lived worker that processes audio and cleanup jobs from the queue."""
    global worker_busy
    while True:
        job = await job_queue.get()
        worker_busy = True
        t0 = time.perf_counter()
        try:
            loop = asyncio.get_event_loop()
            if isinstance(job, RecordingJob):
                await process_recording(job.job_id)
            elif isinstance(job, CleanupJob):
                logger.info(
                    "Processing cleanup job %s (body_len=%d)", job.job_id, len(job.body)
                )
                cleaned = await loop.run_in_executor(
                    audio_executor, ai_client.clean_note, job.body
                )
                if not job.future.done():
                    job.future.set_result(cleaned)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.info(
                    "Completed cleanup job %s in %.1fms", job.job_id, elapsed_ms
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
                job_result = await loop.run_in_executor(
                    audio_executor, ai_client.process_audio, job.audio_data
                )
                payload = {
                    "status": "complete",
                    "job_id": job.job_id,
                    "mode": job.mode,
                    "transcript": job_result.get("transcript", ""),
                    "result": job_result.get("result", ""),
                }
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
            if isinstance(job, RecordingJob):
                recording_store.update(job.job_id, "failed", error=str(e))
            elif isinstance(job, CleanupJob):
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
    for recording_id in recording_store.recover():
        await job_queue.put(RecordingJob(recording_id))
    worker_task = asyncio.create_task(audio_worker())
    yield
    logger.info("Secretary backend shutting down")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
