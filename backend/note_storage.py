"""Note path validation, frontmatter, and atomic filesystem persistence."""

import os
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import HTTPException

from backend import paths


def validate_note_path(filename: str) -> Path:
    """Validate and resolve a note path, preventing directory traversal."""
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = (paths.NOTES_DIR / filename).resolve()
    if not path.is_relative_to(paths.NOTES_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return path


def ensure_notes_dir():
    paths.NOTES_DIR.mkdir(exist_ok=True)


def is_excluded_note(path: Path) -> bool:
    """Return True if path is excluded: README.md or inside a hidden directory."""
    if path.name == "README.md":
        return True
    rel = path.relative_to(paths.NOTES_DIR)
    return any(part.startswith(".") for part in rel.parts)


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


def write_note(path: Path, metadata: dict[str, str], body: str) -> None:
    """Atomically persist body and recording receipts in the same file replacement."""
    fd, temporary = tempfile.mkstemp(prefix=".secretary-", dir=path.parent)
    try:
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w") as output:
            output.write(format_frontmatter(metadata, body))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_note(path: Path) -> tuple[dict[str, str], str]:
    metadata, body = parse_frontmatter(path.read_text())
    if "id" not in metadata:
        metadata["id"] = str(uuid.uuid4())
        write_note(path, metadata, body)
    return metadata, body


def find_note(note_id: str) -> Path | None:
    if paths.NOTES_DIR.exists():
        for path in paths.NOTES_DIR.rglob("*.md"):
            if not is_excluded_note(path) and read_note(path)[0]["id"] == note_id:
                return path
    return None


def note_response(path: Path) -> dict[str, str]:
    metadata, body = read_note(path)
    return {
        **metadata,
        "filename": str(path.resolve().relative_to(paths.NOTES_DIR.resolve())),
        "body": body,
    }
