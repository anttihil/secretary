import { createSignal, onMount, onCleanup, Show } from "solid-js";
import type { Note, NoteListItem, WsMessage } from "./types";
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
  createNote,
  getNote,
  deleteNote,
  deleteDirectory,
  appendToNote,
  cleanNote,
  replaceNoteBody,
  renameNote,
  migrateNotes,
  createDirectory,
  moveNote,
  moveDirectory,
} from "./api";

export default function App() {
  const [notes, setNotes] = createSignal<NoteListItem[]>([]);
  const [directories, setDirectories] = createSignal<string[]>([]);
  const [currentNote, setCurrentNote] = createSignal<Note | null>(null);
  const [status, setStatus] = createSignal("Connecting...");
  const [isRecording, setIsRecording] = createSignal(false);
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
  const [confirmAction, setConfirmAction] = createSignal<(() => void) | null>(
    null,
  );

  let ws: WebSocket | undefined;
  let mediaRecorder: MediaRecorder | undefined;

  function connectWebSocket(): void {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => setStatus("Ready");
    ws.onclose = () => {
      setStatus("Disconnected. Reconnecting...");
      setTimeout(connectWebSocket, 2000);
    };
    ws.onmessage = async (event: MessageEvent<string>) => {
      const text = event.data;
      let parsed: WsMessage | null = null;
      try {
        parsed = JSON.parse(text) as WsMessage;
      } catch {}

      if (parsed && parsed.status) {
        switch (parsed.status) {
          case "queued":
            setStatus("Processing audio...");
            setIsRecording(false);
            break;

          case "complete":
            if (currentNote()) {
              const updated = await appendToNote(
                currentNote()!.filename,
                parsed.result ?? "",
              );
              setNotes(
                notes().map((n) =>
                  n.filename === updated.filename
                    ? { ...n, updated: updated.updated }
                    : n,
                ),
              );
              setCurrentNote(updated);
            }
            setStatus("Ready");
            setIsRecording(false);
            break;

          case "error":
            setStatus("Error: " + parsed.message);
            setIsRecording(false);
            break;
        }
      }
    };
  }

  async function startRecording(): Promise<void> {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!currentNote()) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      ws.send(`note:${currentNote()!.filename}`);
      mediaRecorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });
      mediaRecorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0 && ws!.readyState === WebSocket.OPEN)
          ws!.send(e.data);
      };
      mediaRecorder.onstop = () => stream.getTracks().forEach((t) => t.stop());
      mediaRecorder.start(250);
      setStatus("Recording...");
      setIsRecording(true);
    } catch (err) {
      setStatus("Microphone access denied");
      console.error("Microphone error:", err);
    }
  }

  function stopRecording(): void {
    if (mediaRecorder && mediaRecorder.state !== "inactive")
      mediaRecorder.stop();
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("stop");
    setStatus("Processing...");
    setIsRecording(false);
  }

  async function loadNotes(): Promise<void> {
    try {
      const resp = await fetchNotes();
      setNotes(resp.notes);
      setDirectories(resp.directories);
    } catch {}
  }

  async function handleOpenNote(filename: string): Promise<void> {
    try {
      const note = await getNote(filename);
      setCurrentNote(note);
    } catch {}
  }

  async function handleCreateNote(
    title: string,
    directory: string,
  ): Promise<void> {
    try {
      const note = await createNote(title, directory || undefined);
      const newNote: Note = { ...note, body: "" };
      setNotes([newNote, ...notes()]);
      setCurrentNote(newNote);
      setShowModal(false);
    } catch {}
  }

  function openConfirmModal(message: string, action: () => void): void {
    setConfirmMessage(message);
    setConfirmAction(() => action);
    setShowConfirmModal(true);
  }

  async function handleDeleteNote(): Promise<void> {
    const note = currentNote();
    if (!note) return;
    openConfirmModal(`Delete "${note.title}"?`, async () => {
      setShowConfirmModal(false);
      try {
        await deleteNote(note.filename);
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
        await deleteNote(filename);
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
    try {
      const result = await migrateNotes();
      await loadNotes();
      alert(`Migrated ${result.migrated} notes.`);
    } catch (e) {
      console.error("Migration failed:", e);
      alert("Migration failed.");
    }
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
      const updated = await replaceNoteBody(note.filename, newBody);
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
      const updated = await renameNote(note.filename, newTitle);
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
    connectWebSocket();
    loadNotes();
  });

  onCleanup(() => {
    ws?.close();
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
      />
      <Show when={sidebarOpen()}>
        <div class="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      </Show>
      <div class="main-panel">
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
              <button class="btn-record" onClick={() => startRecording()}>
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
            isCleaning={isCleaning()}
            notes={notes()}
            onRecord={() => startRecording()}
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
          onConfirm={() => {
            confirmAction()?.();
          }}
          onClose={() => setShowConfirmModal(false)}
        />
      </Show>
    </>
  );
}
