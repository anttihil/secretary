"""Legacy streaming audio WebSocket protocol."""

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend import worker
from backend.note_storage import validate_note_path
from backend.worker import AudioJob

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    recording: bool = False
    chunks: list[bytes] = []
    mode: str = ""
    note_filename: str | None = None
    try:
        while True:
            message = await websocket.receive()
            # receive() returns disconnect rather than raising; do not call it again.
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
                        await worker.job_queue.put(job)
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
