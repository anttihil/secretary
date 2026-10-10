"""Durable recording acceptance and job state, independent of client connections."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RecordingStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "jobs.sqlite3"

    @contextmanager
    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        # Runtime audio/job data must never be committed by notes git_sync.
        ignore_file = self.directory / ".gitignore"
        if not ignore_file.exists():
            ignore_file.write_text("*\n")
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY, note_id TEXT, mode TEXT NOT NULL,
                    created TEXT NOT NULL, status TEXT NOT NULL,
                    digest TEXT NOT NULL, audio BLOB, result TEXT,
                    saved_note_id TEXT, error TEXT
                )"""
            )
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, recording_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            return dict(row) if row else None

    def accept(
        self, recording_id: str, note_id: str | None, mode: str, audio: bytes
    ) -> tuple[dict[str, Any], bool]:
        if mode != "note":
            raise ValueError("Invalid recording mode")
        digest = hashlib.sha256(audio).hexdigest()
        with self.connect() as db:
            inserted = (
                db.execute(
                    """INSERT OR IGNORE INTO recordings
                   (id, note_id, mode, created, status, digest, audio)
                   VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
                    (
                        recording_id,
                        note_id,
                        mode,
                        datetime.now(timezone.utc).isoformat(),
                        digest,
                        audio,
                    ),
                ).rowcount
                == 1
            )
            row = dict(
                db.execute(
                    "SELECT * FROM recordings WHERE id = ?", (recording_id,)
                ).fetchone()
            )
            if (row["note_id"], row["mode"], row["digest"]) != (
                note_id,
                mode,
                digest,
            ):
                raise ValueError("Recording ID is already used for different audio")
            return row, inserted

    def update(self, recording_id: str, status: str, **values: Any) -> None:
        allowed = {"result", "saved_note_id", "error", "audio"}
        if not values.keys() <= allowed:
            raise ValueError("Unknown recording field")
        fields = {"status": status, **values}
        with self.connect() as db:
            db.execute(
                "UPDATE recordings SET "
                + ", ".join(f"{field} = ?" for field in fields)
                + " WHERE id = ?",
                (*fields.values(), recording_id),
            )

    def recover(self) -> list[str]:
        """Resume interrupted inference or saving in acceptance order on startup."""
        with self.connect() as db:
            db.execute(
                "UPDATE recordings SET status = 'queued' WHERE status = 'transcribing'"
            )
            return [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM recordings WHERE status IN ('queued', 'saving') "
                    "ORDER BY created, rowid"
                )
            ]

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "note_id": row["note_id"],
            "mode": row["mode"],
            "created": row["created"],
            "status": row["status"],
            "saved_note_id": row["saved_note_id"],
            "error": row["error"],
            "result": json.loads(row["result"]) if row["result"] else None,
        }
