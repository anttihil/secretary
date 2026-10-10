import asyncio
import importlib
import os
import tempfile
import unittest
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from fastapi import HTTPException, UploadFile

from recording_jobs import RecordingStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = RecordingStore(Path(self.temporary.name))

    def test_acceptance_is_idempotent_but_rejects_different_payload(self):
        row, inserted = self.store.accept("recording", "note", "note", b"audio")
        self.assertTrue(inserted)
        duplicate, inserted = self.store.accept("recording", "note", "note", b"audio")
        self.assertFalse(inserted)
        self.assertEqual(row, duplicate)
        for note, mode, audio in [
            ("other", "note", b"audio"),
            ("note", "command", b"audio"),
            ("note", "note", b"other"),
        ]:
            with self.assertRaises(ValueError):
                self.store.accept("recording", note, mode, audio)

    def test_restart_recovers_queue_and_partial_save_in_acceptance_order(self):
        for key in ("first", "second", "third", "failed", "done"):
            self.store.accept(key, "note", "note", b"audio")
        self.store.update("first", "transcribing")
        self.store.update("second", "saving", result='{"result":"text"}')
        self.store.update("failed", "failed", error="failure")
        self.store.update("done", "succeeded", audio=None)
        restarted = RecordingStore(Path(self.temporary.name))
        self.assertEqual(restarted.recover(), ["first", "second", "third"])
        self.assertEqual((restarted.get("first") or {})["status"], "queued")
        self.assertEqual((restarted.get("second") or {})["status"], "saving")
        self.assertIsNone((restarted.get("done") or {})["audio"])

    def test_unsupported_modes_cannot_be_accepted(self):
        with self.assertRaisesRegex(ValueError, "Invalid recording mode"):
            self.store.accept("unsupported", "note", "command", b"audio")
        self.assertIsNone(self.store.get("unsupported"))


class SavingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        # Tests exercise persistence and worker logic without loading AI models.
        fake_ai = Mock()
        fake_ai.process_audio.return_value = {
            "transcript": "First paragraph",
            "result": "First paragraph",
        }
        with patch.dict(
            os.environ,
            {"AI_CLIENT": "local", "LLM_MODEL_PATH": "unused", "NOTES_DIR": str(root)},
        ):
            with patch("ai_client.LocalAIClient", return_value=fake_ai):
                self.main: Any = importlib.import_module("main")
        self.main.NOTES_DIR = root
        self.main.recording_store = RecordingStore(root / ".secretary")
        self.main.ai_client = fake_ai
        self.main.job_queue = asyncio.Queue()
        self.sync = patch.object(self.main, "schedule_git_sync")
        self.sync.start()
        self.addCleanup(self.sync.stop)
        self.note_id = uuid.uuid4()
        self.note = await self.main.create_note(
            self.main.CreateNoteRequest(title="Target", id=self.note_id)
        )
        self.recording_id = str(uuid.uuid4())
        self.main.recording_store.accept(
            self.recording_id, str(self.note_id), "note", b"audio"
        )

    async def test_crash_after_note_write_does_not_append_again(self):
        original_update = self.main.recording_store.update

        def crash_before_success(recording_id, status, **values):
            if status == "succeeded":
                raise RuntimeError("Simulated crash after note replacement")
            original_update(recording_id, status, **values)

        with patch.object(
            self.main.recording_store, "update", side_effect=crash_before_success
        ):
            with self.assertRaises(RuntimeError):
                await self.main.process_recording(self.recording_id)
        path = self.main.find_note(str(self.note_id))
        self.assertIsNotNone(path)
        self.assertEqual(self.main.read_note(path)[1], "First paragraph\n\n")
        self.assertEqual(
            self.main.recording_store.get(self.recording_id)["status"], "saving"
        )
        await self.main.process_recording(self.recording_id)
        self.assertEqual(self.main.read_note(path)[1], "First paragraph\n\n")
        self.main.ai_client.process_audio.assert_called_once()
        row = self.main.recording_store.get(self.recording_id)
        self.assertEqual(row["status"], "succeeded")
        self.assertIsNone(row["audio"])

    async def test_renamed_and_moved_note_keeps_job_target(self):
        renamed = await self.main.rename_note(
            self.note["filename"], self.main.RenameNoteRequest(title="Renamed")
        )
        await self.main.create_directory(
            self.main.CreateDirectoryRequest(path="folder")
        )
        await self.main.move_note(
            renamed["filename"], self.main.MoveNoteRequest(directory="folder")
        )
        await self.main.create_note(
            self.main.CreateNoteRequest(title="Different selected note")
        )
        await self.main.process_recording(self.recording_id)
        path = self.main.find_note(str(self.note_id))
        self.assertEqual(path.parent.name, "folder")
        self.assertEqual(self.main.read_note(path)[1], "First paragraph\n\n")

    async def test_upload_rejects_unsupported_mode_without_queuing(self):
        recording_id = uuid.uuid4()
        with self.assertRaises(HTTPException) as raised:
            await self.main.upload_recording(
                id=recording_id,
                mode="command",
                audio=UploadFile(file=BytesIO(b"audio")),
                note_id=self.note_id,
            )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIsNone(self.main.recording_store.get(str(recording_id)))
        self.assertTrue(self.main.job_queue.empty())
        self.main.ai_client.process_audio.assert_not_called()

    async def test_same_title_notes_created_in_same_second_do_not_overwrite(self):
        first = await self.main.create_note(
            self.main.CreateNoteRequest(title="Repeated")
        )
        second = await self.main.create_note(
            self.main.CreateNoteRequest(title="Repeated")
        )
        self.assertNotEqual(first["filename"], second["filename"])
        duplicate = await self.main.create_note(
            self.main.CreateNoteRequest(title="Repeated", id=uuid.UUID(first["id"]))
        )
        self.assertEqual(duplicate["filename"], first["filename"])

    async def test_failed_job_does_not_block_following_recordings(self):
        second_id = str(uuid.uuid4())
        self.main.recording_store.accept(second_id, str(self.note_id), "note", b"good")
        self.main.ai_client.process_audio.side_effect = [
            ValueError("Invalid audio"),
            {"result": "Second recording", "transcript": "Second recording"},
        ]
        await self.main.job_queue.put(self.main.RecordingJob(self.recording_id))
        await self.main.job_queue.put(self.main.RecordingJob(second_id))
        worker = asyncio.create_task(self.main.audio_worker())
        try:
            await asyncio.wait_for(self.main.job_queue.join(), timeout=5)
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
        self.assertEqual(
            self.main.recording_store.get(self.recording_id)["status"], "failed"
        )
        self.assertEqual(
            self.main.recording_store.get(second_id)["status"], "succeeded"
        )
        self.assertEqual(
            self.main.read_note(self.main.find_note(str(self.note_id)))[1],
            "Second recording\n\n",
        )


if __name__ == "__main__":
    unittest.main()
