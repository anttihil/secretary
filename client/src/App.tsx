import { createSignal, onMount, onCleanup, Show } from "solid-js";
import type { MigrationResult, Note, NoteListItem, WsMessage } from "./types";
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
  const [confirmLabel, setConfirmLabel] = createSignal("Delete");
  const [confirmAction, setConfirmAction] = createSignal<(() => void) | null>(
    null,
  );

  let ws: WebSocket | undefined;
  let mediaRecorder: MediaRecorder | undefined;

  function updateCurrentNoteState(updated: Note): void {
    setNotes(
      notes().map((n) =>
        n.filename === updated.filename
          ? { ...n, updated: updated.updated }
          : n,
      ),
    );
    setCurrentNote(updated);
  }

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

          case "complete": {
            setIsRecording(false);
            if (parsed.mode === "command" && parsed.command) {
              const cmd = parsed.command;
              if (cmd.action === "add_tags" && cmd.tags && cmd.tags.length > 0) {
                const formattedTags = cmd.tags
                  .map((t) => (t.startsWith("#") ? t : `#${t}`))
                  .join(" ");
                if (currentNote()) {
                  const updated = await appendToNote(currentNote()!.filename, formattedTags);
                  updateCurrentNoteState(updated);
                }
                setStatus(`Ready (Added tags: ${formattedTags})`);
              } else if (cmd.action === "add_links" && cmd.links && cmd.links.length > 0) {
                const formattedLinks = cmd.links.map((l) => `[[${l}]]`).join(" ");
                if (currentNote()) {
                  const updated = await appendToNote(currentNote()!.filename, formattedLinks);
                  updateCurrentNoteState(updated);
                }
                setStatus(`Ready (Added link: ${formattedLinks})`);
              } else if (cmd.action === "create_note" && cmd.title) {
                await handleCreateNote(cmd.title, "");
                setStatus(`Ready (Created note "${cmd.title}")`);
              } else if (cmd.text || parsed.result) {
                const textToAppend = cmd.text || parsed.result || "";
                if (currentNote() && textToAppend) {
                  const updated = await appendToNote(currentNote()!.filename, textToAppend);
                  updateCurrentNoteState(updated);
                }
                setStatus("Ready");
              } else {
                setStatus("Ready");
              }
            } else if (currentNote() && (parsed.result || parsed.transcript)) {
              const textToAppend = parsed.result || parsed.transcript || "";
              const updated = await appendToNote(currentNote()!.filename, textToAppend);
              updateCurrentNoteState(updated);
              setStatus("Ready");
            } else {
              setStatus("Ready");
            }
            break;
          }

          case "error":
            setStatus("Error: " + parsed.message);
            setIsRecording(false);
            break;
        }
      }
    };
  }

  async function startRecording(mode: "note" | "command" = "note"): Promise<void> {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (mode === "note" && !currentNote()) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (mode === "command") {
        ws.send(currentNote() ? `command:${currentNote()!.filename}` : "command");
      } else {
        ws.send(`note:${currentNote()!.filename}`);
      }
      mediaRecorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });
      mediaRecorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0 && ws!.readyState === WebSocket.OPEN)
          ws!.send(e.data);
      };
      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        if (ws && ws.readyState === WebSocket.OPEN) ws.send("stop");
      };
      mediaRecorder.start(250);
      setStatus(mode === "command" ? "Recording command..." : "Recording...");
      setIsRecording(true);
    } catch (err) {
      setStatus("Microphone access denied");
      console.error("Microphone error:", err);
    }
  }

  function stopRecording(): void {
    setStatus("Processing...");
    setIsRecording(false);
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      // "stop" is sent from onstop, not here: MediaRecorder.stop() flushes its
      // last chunk from a queued task, so a synchronous send would reach the
      // server first and that chunk would be dropped.
      mediaRecorder.stop();
      return;
    }
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("stop");
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
        onRecordCommand={() => startRecording("command")}
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
              <button class="btn-record" onClick={() => startRecording("note")}>
                Record
              </button>
              <button class="btn-record-cmd" onClick={() => startRecording("command")}>
                Cmd
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
            onRecord={() => startRecording("note")}
            onRecordCommand={() => startRecording("command")}
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
