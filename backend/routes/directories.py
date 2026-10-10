"""Create, move, and delete note directories."""

import os
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import paths
from backend.git_sync import schedule_git_sync
from backend.note_storage import validate_note_path
from backend.routes.notes import MoveNoteRequest

router = APIRouter()


class CreateDirectoryRequest(BaseModel):
    path: str


@router.post("/api/directories/{path:path}/move")
async def move_directory(path: str, req: MoveNoteRequest):
    validate_note_path(path)
    src = paths.NOTES_DIR / path
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    if req.directory:
        validate_note_path(req.directory)
        target_parent = paths.NOTES_DIR / req.directory
        if not target_parent.is_dir():
            raise HTTPException(
                status_code=400, detail="Target directory does not exist"
            )
    else:
        target_parent = paths.NOTES_DIR
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
        resolved = paths.NOTES_DIR.resolve()
        return {"path": str(src_resolved.relative_to(resolved))}
    if new_path.exists():
        raise HTTPException(
            status_code=409,
            detail="A directory with that name already exists in the target",
        )
    src.rename(new_path)
    schedule_git_sync()
    resolved = paths.NOTES_DIR.resolve()
    return {"path": str(new_path.resolve().relative_to(resolved))}


@router.delete("/api/directories/{path:path}")
async def delete_directory_endpoint(path: str):
    validate_note_path(path)
    dir_path = paths.NOTES_DIR / path
    if not dir_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    shutil.rmtree(dir_path)
    schedule_git_sync()
    return {"deleted": path}


@router.post("/api/directories")
async def create_directory(req: CreateDirectoryRequest):
    validate_note_path(req.path)
    dir_path = paths.NOTES_DIR / req.path
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / ".gitkeep").touch()
    schedule_git_sync()
    return {"path": req.path}
