"""Read and extend the transcription correction glossary."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import paths, worker
from backend.note_storage import ensure_notes_dir

router = APIRouter()


class AddGlossaryWordRequest(BaseModel):
    transcript_word: str
    correct_word: str


@router.get("/api/glossary")
async def get_glossary():
    path = paths.GLOSSARY_PATH
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


@router.post("/api/glossary")
async def add_glossary_word(req: AddGlossaryWordRequest):
    ensure_notes_dir()
    path = paths.GLOSSARY_PATH
    transcript = req.transcript_word.strip()
    correct = req.correct_word.strip()
    if not transcript or not correct:
        raise HTTPException(400, "Both words are required")
    existing = path.read_text() if path.exists() else ""
    if not existing.endswith("\n") and existing:
        existing += "\n"
    existing += f"{transcript} → {correct}\n"
    path.write_text(existing)
    worker.ai_client.reload_glossary()
    return {"transcript": transcript, "correct": correct}
