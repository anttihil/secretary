"""Whisper capability discovery and settings updates."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_client import LocalAIClient, get_whisper_capabilities
from backend import worker
from config import get_settings, save_settings

router = APIRouter()


class UpdateSettingsRequest(BaseModel):
    whisper_device: str
    whisper_compute_type: str
    whisper_model: str


@router.get("/api/settings")
async def get_settings_endpoint():
    capabilities = get_whisper_capabilities()
    if isinstance(worker.ai_client, LocalAIClient):
        current = worker.ai_client.get_current_whisper_settings()
    else:
        current = get_settings()
    return {**current, **capabilities}


@router.post("/api/settings")
async def update_settings_endpoint(req: UpdateSettingsRequest):
    if worker.worker_busy:
        raise HTTPException(
            status_code=409, detail="Cannot update settings while processing audio"
        )
    if not isinstance(worker.ai_client, LocalAIClient):
        raise HTTPException(status_code=400, detail="Settings only for local client")
    try:
        worker.ai_client.update_whisper(
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
