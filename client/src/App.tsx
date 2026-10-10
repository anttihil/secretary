import { createSignal, createMemo, onMount, onCleanup, Show } from "solid-js";
import type { MigrationResult, Note, NoteListItem } from "./types";
import { createRecordingController } from "./recordingController";
import { cacheNoteList, deleteCachedNote, getCachedNotes, getCachedDirectories, saveCachedNote } from "./offlineStore";
import RecordingQueue from "./components/RecordingQueue";
import Sidebar from "./components/Sidebar";
import NoteView from "./components/NoteView";
import NewNoteModal from "./components/NewNoteModal";
import CleanupModal from "./components/CleanupModal";
import SettingsModal from "./components/SettingsModal";
import ConfirmModal from "./components/ConfirmModal";
import NewDirectoryModal from "./components/NewDirectoryModal";
import EditableTitle from "./components/EditableTitle";
import {
  fetchNotes,
  getNote,
  deleteNote,
  deleteDirectory,
  cleanNote,
  replaceNoteBody,
  renameNote,
  migrateNotes,
  createDirectory,
  moveNote,
  moveDirectory,
} from "./api";

function describeMigration(result: MigrationResult): string {
  const total = result.migrated + result.skipped;
  if (result.migrated === 0) {
    return total === 0
      ? "No markdown files found in your notes folder."
      : `Nothing to import — all ${total} notes already use Secretary's format.`;
  }
  const renamed = result.files.filter((f) =>
    f.actions.some((a) => a.startsWith("renamed")),
  ).length;
  const parts = [`Imported ${result.migrated} of ${total} notes.`];
  if (renamed > 0) parts.push(`${renamed} renamed.`);
  if (result.skipped > 0) parts.push(`${result.skipped} already up to date.`);
  return parts.join(" ");
}

export default function App() {
  const [notes, setNotes] = createSignal<NoteListItem[]>([]);
  const [directories, setDirectories] = createSignal<string[]>([]);
  const [currentNote, setCurrentNote] = createSignal<Note | null>(null);
  const [message, setStatus] = createSignal("");
  const recording = createRecordingController(async (savedNoteId) => {
    await loadNotes();
    const selected = currentNote();
    const selectionVersion = openRequest;
    if (savedNoteId) {
      const saved = notes().find((n) => n.id === savedNoteId);
      if (saved) {
        const updated = await getNote(saved.filename);
        await saveCachedNote(updated);
        if (currentNote()?.id === savedNoteId && openRequest === selectionVersion) {
          setCurrentNote(updated);
        }
      }
    }
    if (selected?.localOnly) {
      const latest = notes().find((n) => n.id === selected.id);
      if (latest && !latest.localOnly) {
        const updated = await getNote(latest.filename);
        await saveCachedNote(updated);
        if (currentNote()?.id === selected.id && openRequest === selectionVersion) {
          setCurrentNote(updated);
        }
      }
    }
  });
  const isRecording = () => recording.capture().phase === "recording";
  const captureBusy = () => !isRecording() && !recording.canStart();
  const status = createMemo(() => {
    const state = recording.capture();
    if (state.phase === "recording") return `Recording note: ${state.title}`;
    if (state.phase === "requesting_microphone") return "Opening microphone...";
    if (state.phase === "finalizing") return "Saving recording on device...";
    if (state.phase === "failed") return state.message;
    if (message()) return message();
    return recording.connected() ? "Ready" : "Offline · recordings saved on device";
  });
  const [showModal, setShowModal] = createSignal(false);
  const [newNoteDir, setNewNoteDir] = createSignal<string | undefined>(
    undefined,
  );
  const [sidebarOpen, setSidebarOpen] = createSignal(false);
  const [isCleaning, setIsCleaning] = createSignal(false);
  const [showCleanupModal, setShowCleanupModal] = createSignal(false);
  const [cleanedText, setCleanedText] = createSignal("");
  const [showSettingsModal, setShowSettingsModal] = createSignal(false);
  const [showDirectoryModal, setShowDirectoryModal] = createSignal(false);
  const [showConfirmModal, setShowConfirmModal] = createSignal(false);
  const [confirmMessage, setConfirmMessage] = createSignal("");
  const [confirmLabel, setConfirmLabel] = createSignal("Delete");
  const [confirmAction, setConfirmAction] = createSignal<(() => void) | null>(
    null,
  );

  function startRecording(): void {
    setStatus("");
    void recording.start(currentNote());
  }

  const stopRecording = () => recording.stop();
  let openRequest = 0;

  async function loadNotes(): Promise<void> {
    try {
      const resp = await fetchNotes();
      await cacheNoteList(resp.notes, resp.directories);
      const drafts = (await getCachedNotes()).filter((n) => n.localOnly);
      setNotes([...drafts, ...resp.notes]);
      setDirectories(resp.directories);
    } catch {
      setNotes(await getCachedNotes());
      setDirectories(await getCachedDirectories());
    }
  }

  async function handleOpenNote(filename: string): Promise<void> {
    const request = ++openRequest;
    try {
      const cached = (await getCachedNotes()).find((n) => n.filename === filename);
      if (cached?.localOnly || !navigator.onLine) {
        if (cached && request === openRequest) setCurrentNote(cached);
        return;
      }
      const note = await getNote(filename);
      await saveCachedNote(note);
      if (request === openRequest) setCurrentNote(note);
    } catch {
      const cached = (await getCachedNotes()).find((n) => n.filename === filename);
      if (cached && request === openRequest) setCurrentNote(cached);
    }
  }

  async function handleCreateNote(
    title: string,
    directory: string,
  ): Promise<void> {
    try {
      const id = crypto.randomUUID();
      const timestamp = new Date().toISOString();
      const newNote: Note = {
        id, filename: `${directory ? directory + "/" : ""}offline-${id}.md`,
        title, directory, localOnly: true, body: "", created: timestamp, updated: timestamp,
      };
      await saveCachedNote(newNote);
      setNotes([newNote, ...notes()]);
      ++openRequest;
      setCurrentNote(newNote);
      setShowModal(false);
      void recording.sync();
    } catch (error) { setStatus(error instanceof Error ? error.message : "Failed to store new note"); }
  }

  function openConfirmModal(
    message: string,
    action: () => void,
    label = "Delete",
  ): void {
    setConfirmMessage(message);
    setConfirmLabel(label);
    setConfirmAction(() => action);
    setShowConfirmModal(true);
  }

  async function handleDeleteNote(): Promise<void> {
    const note = currentNote();
    if (!note) return;
    openConfirmModal(`Delete "${note.title}"?`, async () => {
      setShowConfirmModal(false);
      try {
        if (!note.localOnly) await deleteNote(note.filename);
        await deleteCachedNote(note.id);
        setNotes(notes().filter((n) => n.filename !== note.filename));
        setCurrentNote(null);
      } catch {}
    });
  }

  async function handleDeleteNoteFromSidebar(filename: string): Promise<void> {
    const note = notes().find((n) => n.filename === filename);
    const title = note?.title ?? filename;
    openConfirmModal(`Delete "${title}"?`, async () => {
      setShowConfirmModal(false);
      try {
        if (!note?.localOnly) await deleteNote(filename);
        if (note) await deleteCachedNote(note.id);
        setNotes(notes().filter((n) => n.filename !== filename));
        if (currentNote()?.filename === filename) setCurrentNote(null);
      } catch {}
    });
  }

  async function handleDeleteDir(path: string): Promise<void> {
    openConfirmModal(
      `Delete folder "${path}" and all its contents?`,
      async () => {
        setShowConfirmModal(false);
        try {
          await deleteDirectory(path);
          await loadNotes();
        } catch {}
      },
    );
  }

  function handleBack(): void {
    ++openRequest;
    setCurrentNote(null);
  }

  async function handleCleanNote(): Promise<void> {
    const note = currentNote();
    if (!note) return;
    setIsCleaning(true);
    try {
      const { cleaned } = await cleanNote(note.filename);
      setCleanedText(cleaned);
      setShowCleanupModal(true);
    } catch (e) {
      console.error("Cleanup failed:", e);
      setStatus("Cleanup failed");
    } finally {
      setIsCleaning(false);
    }
  }

  async function handleMigrate(): Promise<void> {
    openConfirmModal(
      "Import every markdown file in your notes folder into Secretary's " +
        "format? Files missing a title, created or updated field get one " +
        "added, and files not already named title-YYYYMMDD-HHMMSS.md are " +
        "renamed to match. Notes already in that format are left alone. " +
        "This edits the files in place.",
      async () => {
        setShowConfirmModal(false);
        try {
          const result = await migrateNotes();
          await loadNotes();
          alert(describeMigration(result));
        } catch (e) {
          console.error("Import failed:", e);
          alert("Import failed.");
        }
      },
      "Import",
    );
  }

  async function handleCreateDirectory(
    name: string,
    parentDirectory: string,
  ): Promise<void> {
    const path = parentDirectory ? `${parentDirectory}/${name}` : name;
    try {
      await createDirectory(path);
      await loadNotes();
      setShowDirectoryModal(false);
    } catch (e) {
      console.error("Failed to create directory:", e);
    }
  }

  async function handleMoveDir(
    path: string,
    targetDirectory: string,
  ): Promise<void> {
    const currentParent = path.includes("/")
      ? path.substring(0, path.lastIndexOf("/"))
      : "";
    if (currentParent === targetDirectory) return;
    try {
      await moveDirectory(path, targetDirectory);
      await loadNotes();
    } catch (e) {
      console.error("Failed to move directory:", e);
    }
  }

  async function handleMoveNote(
    filename: string,
    directory: string,
  ): Promise<void> {
    const note = notes().find((n) => n.filename === filename);
    if (!note) return;
    const currentDir = filename.includes("/")
      ? filename.substring(0, filename.lastIndexOf("/"))
      : "";
    if (currentDir === directory) return;
    try {
      if (note.localOnly) {
        const cached = (await getCachedNotes()).find((n) => n.id === note.id);
        if (!cached) return;
        const basename = filename.slice(filename.lastIndexOf("/") + 1);
        const moved = { ...cached, directory, filename: `${directory ? directory + "/" : ""}${basename}` };
        await saveCachedNote(moved);
        setNotes(notes().map((n) => n.id === moved.id ? moved : n));
        if (currentNote()?.id === moved.id) setCurrentNote(moved);
        void recording.sync();
        return;
      }
      const moved = await moveNote(filename, directory);
      setNotes(
        notes().map((n) =>
          n.filename === filename
            ? { ...n, filename: moved.filename, updated: moved.updated }
            : n,
        ),
      );
      if (currentNote()?.filename === filename) {
        setCurrentNote({ ...currentNote()!, filename: moved.filename });
      }
    } catch (e) {
      console.error("Failed to move note:", e);
    }
  }

  function openNewNoteModal(directory?: string): void {
    setNewNoteDir(directory);
    setShowModal(true);
    setSidebarOpen(false);
  }

  async function handleUpdateNoteBody(newBody: string): Promise<void> {
    const note = currentNote();
    if (!note) return;
    try {
      const updated = note.localOnly ? { ...note, body: newBody } : await replaceNoteBody(note.filename, newBody);
      await saveCachedNote(updated);
      setCurrentNote(updated);
      setNotes(
        notes().map((n) =>
          n.filename === updated.filename
            ? { ...n, updated: updated.updated }
            : n,
        ),
      );
    } catch (e) {
      console.error("Failed to update note body:", e);
    }
  }

  async function handleRenameNote(newTitle: string): Promise<void> {
    const note = currentNote();
    if (!note) return;
    try {
      const updated = note.localOnly ? { ...note, title: newTitle } : await renameNote(note.filename, newTitle);
      await saveCachedNote(updated);
      setCurrentNote(updated);
      setNotes(
        notes().map((n) =>
          n.filename === note.filename
            ? {
                ...n,
                filename: updated.filename,
                title: updated.title,
                updated: updated.updated,
              }
            : n,
        ),
      );
    } catch (e) {
      console.error("Failed to rename note:", e);
    }
  }

  async function applyCleanup(finalText: string): Promise<void> {
    const note = currentNote();
    if (!note) return;
    try {
      const updated = await replaceNoteBody(note.filename, finalText);
      await saveCachedNote(updated);
      setCurrentNote(updated);
      setNotes(
        notes().map((n) =>
          n.filename === updated.filename
            ? { ...n, updated: updated.updated }
            : n,
        ),
      );
      setShowCleanupModal(false);
    } catch (e) {
      console.error("Failed to apply cleanup:", e);
    }
  }

  onMount(() => {
    void loadNotes();
    void recording.initialize();
    if ("serviceWorker" in navigator) {
      void navigator.serviceWorker.register("/sw.js").catch((error) => console.error("Offline app cache failed:", error));
    }
  });

  onCleanup(() => {
    recording.dispose();
  });

  return (
    <>
      <Sidebar
        notes={notes()}
        directories={directories()}
        currentNote={currentNote()}
        onOpenNote={(f) => {
          handleOpenNote(f);
          setSidebarOpen(false);
        }}
        onNewNote={openNewNoteModal}
        onMigrate={handleMigrate}
        onSettings={() => {
          setShowSettingsModal(true);
          setSidebarOpen(false);
        }}
        onCreateDirectory={() => setShowDirectoryModal(true)}
        onMoveNote={handleMoveNote}
        onMoveDir={handleMoveDir}
        onDeleteNote={handleDeleteNoteFromSidebar}
        onDeleteDir={handleDeleteDir}
        open={sidebarOpen()}
        recordingQueue={
          <RecordingQueue
            jobs={recording.jobs()} connected={recording.connected()}
            storageError={recording.storageError()}
            onRetry={(id) => void recording.retry(id)}
            onDiscard={(id) => void recording.discard(id)}
            onDownload={(id) => void recording.download(id)}
            onStoreCaptured={() => void recording.storeCaptured()}
          />
        }
      />
      <Show when={sidebarOpen()}>
        <div class="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      </Show>
      <div class="main-panel">
        <Show when={isRecording()}>
          <div class="capture-controls">
            <span>{status()}</span>
            <button class="btn-stop" onClick={stopRecording}>Stop recording</button>
            <button onClick={() => recording.cancel()}>Cancel recording</button>
          </div>
        </Show>
        <div class="mobile-topbar">
          <button class="btn-menu" onClick={() => setSidebarOpen(true)}>
            ≡
          </button>
          <Show when={currentNote()}>
            <EditableTitle
              title={currentNote()!.title}
              onRename={handleRenameNote}
              displayClass="mobile-topbar-title"
              inputClass="mobile-topbar-title-input"
            />
          </Show>
        </div>
        <Show when={currentNote()}>
          <div class="mobile-status-strip">
            <Show
              when={!isRecording()}
              fallback={
                <button class="btn-stop" onClick={stopRecording}>
                  Stop
                </button>
              }
            >
              <button class="btn-record" disabled={captureBusy()} onClick={startRecording}>
                Record
              </button>
            </Show>
            <button
              class="btn-clean"
              onClick={handleCleanNote}
              disabled={isRecording() || isCleaning() || !currentNote()?.body?.trim()}
            >
              {isCleaning() ? "..." : "Clean"}
            </button>
            <span class={`recording-dot${isRecording() ? " active" : ""}`} />
            <span class="mobile-status-text">{status()}</span>
          </div>
        </Show>
        <Show
          when={currentNote()}
          fallback={
            <div class="welcome-view">
              <h1>Secretary</h1>
              <p class="letterhead-subtitle">
                Voice-Powered Correspondence System
              </p>
              <p class="welcome-hint">
                Select a note or create a new one to get started.
              </p>
            </div>
          }
        >
          <NoteView
            note={currentNote()}
            status={status()}
            isRecording={isRecording()}
            captureBusy={captureBusy()}
            isCleaning={isCleaning()}
            notes={notes()}
            onRecord={startRecording}
            onStop={stopRecording}
            onBack={handleBack}
            onDelete={handleDeleteNote}
            onClean={handleCleanNote}
            onUpdateBody={handleUpdateNoteBody}
            onRenameNote={handleRenameNote}
            onOpenNote={handleOpenNote}
          />
        </Show>
      </div>
      <Show when={showModal()}>
        <NewNoteModal
          onClose={() => setShowModal(false)}
          onCreate={handleCreateNote}
          directories={directories()}
          defaultDirectory={newNoteDir()}
        />
      </Show>
      <Show when={showCleanupModal()}>
        <CleanupModal
          original={currentNote()?.body ?? ""}
          cleaned={cleanedText()}
          onApply={applyCleanup}
          onClose={() => setShowCleanupModal(false)}
        />
      </Show>
      <Show when={showSettingsModal()}>
        <SettingsModal onClose={() => setShowSettingsModal(false)} />
      </Show>
      <Show when={showDirectoryModal()}>
        <NewDirectoryModal
          onClose={() => setShowDirectoryModal(false)}
          onCreate={handleCreateDirectory}
          directories={directories()}
        />
      </Show>
      <Show when={showConfirmModal()}>
        <ConfirmModal
          message={confirmMessage()}
          confirmLabel={confirmLabel()}
          onConfirm={() => {
            confirmAction()?.();
          }}
          onClose={() => setShowConfirmModal(false)}
        />
      </Show>
    </>
  );
}
