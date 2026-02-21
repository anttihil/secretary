import { createSignal, onMount, onCleanup, Show } from "solid-js";
import type { Note, NoteListItem, Result, WsMessage } from "./types";
import Sidebar from "./components/Sidebar";
import CommandView from "./components/CommandView";
import NoteView from "./components/NoteView";
import NewNoteModal from "./components/NewNoteModal";
import {
  fetchNotes,
  createNote,
  getNote,
  deleteNote,
  appendToNote,
} from "./api";

export default function App() {
  const [notes, setNotes] = createSignal<NoteListItem[]>([]);
  const [currentNote, setCurrentNote] = createSignal<Note | null>(null);
  const [view, setView] = createSignal<"command" | "note">("command");
  const [commandResults, setCommandResults] = createSignal<Result[]>([]);
  const [noteResults, setNoteResults] = createSignal<Result[]>([]);
  const [status, setStatus] = createSignal("Connecting...");
  const [isRecording, setIsRecording] = createSignal(false);
  const [showModal, setShowModal] = createSignal(false);
  const [sidebarOpen, setSidebarOpen] = createSignal(false);

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
            if (parsed.mode === "note" && currentNote()) {
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
                  transcript: parsed.transcript ?? null,
                  result: parsed.result ?? "",
                  mode: "note",
                  time: new Date().toLocaleTimeString(),
                },
                ...noteResults(),
              ]);
            } else {
              setCommandResults([
                {
                  transcript: parsed.transcript ?? null,
                  result: parsed.result ?? "",
                  mode: "command",
                  time: new Date().toLocaleTimeString(),
                },
                ...commandResults(),
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
      } else if (
        typeof text === "string" &&
        !text.startsWith("Recording started")
      ) {
        setCommandResults([
          {
            transcript: null,
            result: text,
            mode: "command",
            time: new Date().toLocaleTimeString(),
          },
          ...commandResults(),
        ]);
        setStatus("Ready");
        setIsRecording(false);
      }
    };
  }

  async function startRecording(mode: "command" | "note"): Promise<void> {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      ws.send(mode);
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
      setView("note");
    } catch {}
  }

  async function handleCreateNote(title: string): Promise<void> {
    try {
      const note = await createNote(title);
      const newNote: Note = { ...note, body: "" };
      setNotes([newNote, ...notes()]);
      setCurrentNote(newNote);
      setNoteResults([]);
      setView("note");
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
      setView("command");
    } catch {}
  }

  function showCommandView(): void {
    setCurrentNote(null);
    setNoteResults([]);
    setView("command");
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
        onCommandMode={() => { showCommandView(); setSidebarOpen(false); }}
        open={sidebarOpen()}
      />
      <Show when={sidebarOpen()}>
        <div class="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      </Show>
      <div class="main-panel">
        <div class="mobile-topbar">
          <button class="btn-menu" onClick={() => setSidebarOpen(true)}>≡</button>
        </div>
        <Show when={view() === "command"}>
          <CommandView
            results={commandResults()}
            status={status()}
            isRecording={isRecording()}
            onRecord={() => startRecording("command")}
            onStop={stopRecording}
          />
        </Show>
        <Show when={view() === "note"}>
          <NoteView
            note={currentNote()}
            results={noteResults()}
            status={status()}
            isRecording={isRecording()}
            onRecord={() => startRecording("note")}
            onStop={stopRecording}
            onBack={showCommandView}
            onDelete={handleDeleteNote}
          />
        </Show>
      </div>
      <Show when={showModal()}>
        <NewNoteModal
          onClose={() => setShowModal(false)}
          onCreate={handleCreateNote}
        />
      </Show>
    </>
  );
}
