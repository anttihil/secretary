import { createSignal, onMount, onCleanup, Show } from "solid-js";
import type { Note, NoteListItem, Result, WsMessage } from "./types";
import Sidebar from "./components/Sidebar";
import NoteView from "./components/NoteView";
import NewNoteModal from "./components/NewNoteModal";
import CleanupModal from "./components/CleanupModal";
import {
  fetchNotes,
  createNote,
  getNote,
  deleteNote,
  appendToNote,
  cleanNote,
  replaceNoteBody,
  migrateNotes,
} from "./api";

export default function App() {
  const [notes, setNotes] = createSignal<NoteListItem[]>([]);
  const [currentNote, setCurrentNote] = createSignal<Note | null>(null);
  const [noteResults, setNoteResults] = createSignal<Result[]>([]);
  const [status, setStatus] = createSignal("Connecting...");
  const [isRecording, setIsRecording] = createSignal(false);
  const [showModal, setShowModal] = createSignal(false);
  const [sidebarOpen, setSidebarOpen] = createSignal(false);
  const [isCleaning, setIsCleaning] = createSignal(false);
  const [showCleanupModal, setShowCleanupModal] = createSignal(false);
  const [cleanedText, setCleanedText] = createSignal("");

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
              setNoteResults([
                {
                  transcript: null,
                  result: parsed.result ?? "",
                  time: new Date().toLocaleTimeString(),
                },
                ...noteResults(),
              ]);
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
      setNotes(await fetchNotes());
    } catch {}
  }

  async function handleOpenNote(filename: string): Promise<void> {
    try {
      const note = await getNote(filename);
      setCurrentNote(note);
      setNoteResults([]);
    } catch {}
  }

  async function handleCreateNote(title: string): Promise<void> {
    try {
      const note = await createNote(title);
      const newNote: Note = { ...note, body: "" };
      setNotes([newNote, ...notes()]);
      setCurrentNote(newNote);
      setNoteResults([]);
      setShowModal(false);
    } catch {}
  }

  async function handleDeleteNote(): Promise<void> {
    const note = currentNote();
    if (!note) return;
    if (!confirm(`Delete "${note.title}"?`)) return;
    try {
      await deleteNote(note.filename);
      setNotes(notes().filter((n) => n.filename !== note.filename));
      setCurrentNote(null);
    } catch {}
  }

  function handleBack(): void {
    setCurrentNote(null);
    setNoteResults([]);
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
        currentNote={currentNote()}
        onOpenNote={(f) => { handleOpenNote(f); setSidebarOpen(false); }}
        onNewNote={() => { setShowModal(true); setSidebarOpen(false); }}
        onMigrate={handleMigrate}
        open={sidebarOpen()}
      />
      <Show when={sidebarOpen()}>
        <div class="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      </Show>
      <div class="main-panel">
        <div class="mobile-topbar">
          <button class="btn-menu" onClick={() => setSidebarOpen(true)}>≡</button>
        </div>
        <Show
          when={currentNote()}
          fallback={
            <div class="welcome-view">
              <h1>Secretary</h1>
              <p class="letterhead-subtitle">Voice-Powered Correspondence System</p>
              <p class="welcome-hint">Select a note or create a new one to get started.</p>
            </div>
          }
        >
          <NoteView
            note={currentNote()}
            results={noteResults()}
            status={status()}
            isRecording={isRecording()}
            isCleaning={isCleaning()}
            onRecord={() => startRecording()}
            onStop={stopRecording}
            onBack={handleBack}
            onDelete={handleDeleteNote}
            onClean={handleCleanNote}
          />
        </Show>
      </div>
      <Show when={showModal()}>
        <NewNoteModal
          onClose={() => setShowModal(false)}
          onCreate={handleCreateNote}
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
    </>
  );
}
