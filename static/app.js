// --- Module-level variables ---

let ws;
let mediaRecorder;
let currentNote = null;
let notes = [];
let commandResults = [];
let noteResults = [];

// --- Template helper ---

function cloneTemplate(id) {
  const tmpl = document.getElementById(id);
  return tmpl.content.firstElementChild.cloneNode(true);
}

// --- DOM update helpers ---

function renderNotesList() {
  const notesList = document.getElementById("notesList");
  if (!notesList) return;
  notesList.innerHTML = "";
  if (notes.length === 0) {
    const emptyNotice = document.createElement("div");
    emptyNotice.classList.add("no-notes");
    emptyNotice.textContent = "No notes yet";
    notesList.appendChild(emptyNotice);
  } else {
    notes.forEach((note) => {
      const noteItem = cloneTemplate("tmpl-note-item");
      noteItem.querySelector(".note-item-title").textContent = note.title;
      noteItem.querySelector(".note-item-date").textContent = note.updated;
      if (note.filename === currentNote?.filename)
        noteItem.classList.add("active");
      noteItem.onclick = () => openNote(note.filename);
      notesList.appendChild(noteItem);
    });
  }
}

function renderResults(containerId, results) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  results.forEach(({ transcript, result, mode, time }) => {
    const el = cloneTemplate("tmpl-result-item");
    el.querySelector(".result-time").textContent = time;
    const tag = el.querySelector(".mode-tag");
    tag.textContent = mode;
    tag.className = "mode-tag " + mode;

    if (transcript) {
      el.querySelector(".transcript-text").textContent = transcript;
      const label = mode === "command" ? "Response" : "Cleaned";
      el.querySelector(".result-label").textContent = label;
      el.querySelector(".result-text").textContent = result;
    } else {
      el.querySelector(".transcript").remove();
      el.querySelector(".result-label").textContent = "";
      el.querySelector(".result-text").textContent = result;
    }
    container.appendChild(el);
  });
}

function setStatus(text, recording) {
  const noteView = document.querySelector("#noteView");
  const isCommandView = noteView.classList.contains("view-hidden");

  const statusElement = document.querySelector(
    isCommandView ? "#cmdStatusText" : "#noteStatusText",
  );
  statusElement.textContent = text;

  const recordingEl = document.querySelector(
    isCommandView ? "#cmdRecDot" : "#noteRecDot",
  );
  if (recording) {
    recordingEl.classList.add("active");
  } else {
    recordingEl.classList.remove("active");
  }
}

function showNoteView(note) {
  currentNote = note;
  document.getElementById("commandView").classList.add("view-hidden");
  const noteView = document.getElementById("noteView");
  noteView.classList.remove("view-hidden");

  document.getElementById("noteTitle").textContent = note.title;
  updateNoteBody(note.body);
  noteResults = [];
  renderResults("noteResults", noteResults);
  setStatus("Ready", false);
  renderNotesList();
}

function showCommandView() {
  currentNote = null;
  noteResults = [];
  document.getElementById("noteView").classList.add("view-hidden");
  document.getElementById("commandView").classList.remove("view-hidden");
  setStatus("Ready", false);
  renderNotesList();
}

function updateNoteBody(body) {
  const bodyEl = document.getElementById("noteBody");
  if (body && body.trim()) {
    bodyEl.textContent = body;
    bodyEl.classList.remove("note-body-empty");
  } else {
    bodyEl.textContent = "No content yet. Record audio to add notes.";
    bodyEl.classList.add("note-body-empty");
  }
}

function setRecordingButtons(mode, recording) {
  const noteRecord = document.getElementById("noteBtnRecord");
  const noteStop = document.getElementById("noteBtnStop");
  const cmdRecord = document.getElementById("cmdBtnRecord");
  const cmdStop = document.getElementById("cmdBtnStop");

  if (recording && mode === "note") {
    noteRecord.style.display = "none";
    noteStop.style.display = "";
  } else {
    noteRecord.style.display = "";
    noteStop.style.display = "none";
  }

  if (recording && mode === "command") {
    cmdRecord.style.display = "none";
    cmdStop.style.display = "";
  } else {
    cmdRecord.style.display = "";
    cmdStop.style.display = "none";
  }
}

function showNewNoteModal() {
  document.getElementById("newNoteModal").classList.add("active");
  document.getElementById("newNoteTitle").focus();
}

function hideNewNoteModal() {
  document.getElementById("newNoteModal").classList.remove("active");
  document.getElementById("newNoteTitle").value = "";
}

// --- WebSocket ---

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => setStatus("Ready", false);
  ws.onclose = () => {
    setStatus("Disconnected. Reconnecting...", false);
    setTimeout(connectWebSocket, 2000);
  };
  ws.onmessage = async (event) => {
    const text = event.data;
    let parsed = null;
    try {
      parsed = JSON.parse(text);
    } catch {}

    if (parsed && parsed.status) {
      switch (parsed.status) {
        case "queued":
          setStatus("Processing audio...", false);
          setRecordingButtons("", false);
          break;

        case "complete":
          if (parsed.mode === "note" && currentNote) {
            await appendToNote(currentNote.filename, parsed.result);
            addNoteResult(parsed.transcript, parsed.result);
          } else {
            addCommandResult(parsed.transcript, parsed.result);
          }
          setStatus("Ready", false);
          setRecordingButtons("", false);
          break;

        case "error":
          setStatus("Error: " + parsed.message, false);
          setRecordingButtons("", false);
          break;
      }
    } else if (
      typeof text === "string" &&
      text.startsWith("Recording started")
    ) {
      // Already handled in startRecording
    } else if (typeof text === "string") {
      addCommandResult(null, text);
      setStatus("Ready", false);
      setRecordingButtons("", false);
    }
  };
}

// --- Recording ---

async function startRecording(mode) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    ws.send(mode);

    mediaRecorder = new MediaRecorder(stream, {
      mimeType: "audio/webm;codecs=opus",
    });
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
        ws.send(e.data);
      }
    };
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
    };
    mediaRecorder.start(250);

    setStatus("Recording...", true);
    setRecordingButtons(mode, true);
  } catch (err) {
    setStatus("Microphone access denied", false);
    console.error("Microphone error:", err);
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send("stop");
  }
  setStatus("Processing...", false);
}

// --- Notes API ---

async function fetchNotes() {
  const resp = await fetch("/api/notes");
  if (!resp.ok) return;
  notes = await resp.json();
  renderNotesList();
}

async function createNote() {
  const titleInput = document.getElementById("newNoteTitle");
  const title = titleInput.value.trim();
  if (!title) return;

  const resp = await fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!resp.ok) return;
  const note = await resp.json();
  titleInput.value = "";

  hideNewNoteModal();
  const newNote = { ...note, body: "" };
  notes.unshift(newNote);
  showNoteView(newNote);
}

async function openNote(filename) {
  const resp = await fetch(`/api/notes/${filename}`);
  if (!resp.ok) return;
  const note = await resp.json();
  showNoteView(note);
}

async function deleteCurrentNote() {
  if (!currentNote) return;
  if (!confirm(`Delete "${currentNote.title}"?`)) return;

  const filename = currentNote.filename;
  const resp = await fetch(`/api/notes/${filename}`, { method: "DELETE" });
  if (!resp.ok) return;

  notes = notes.filter((n) => n.filename !== filename);
  showCommandView();
}

async function appendToNote(filename, text) {
  const resp = await fetch(`/api/notes/${filename}/append`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) return;

  const updated = await resp.json();
  notes = notes.map((n) =>
    n.filename === filename ? { ...n, updated: updated.updated } : n,
  );
  currentNote = updated;
  updateNoteBody(updated.body);
  renderNotesList();
}

// --- Result helpers ---

function addCommandResult(transcript, result) {
  const time = new Date().toLocaleTimeString();
  commandResults = [
    { transcript, result, mode: "command", time },
    ...commandResults,
  ];
  renderResults("cmdResults", commandResults);
}

function addNoteResult(transcript, result) {
  const time = new Date().toLocaleTimeString();
  noteResults = [{ transcript, result, mode: "note", time }, ...noteResults];
  renderResults("noteResults", noteResults);
}

// --- Event listeners ---

document
  .getElementById("btnNewNote")
  .addEventListener("click", showNewNoteModal);

document
  .getElementById("btnCommandMode")
  .addEventListener("click", showCommandView);

document.getElementById("btnBack").addEventListener("click", showCommandView);
document
  .getElementById("btnDelete")
  .addEventListener("click", deleteCurrentNote);

document
  .getElementById("cmdBtnRecord")
  .addEventListener("click", () => startRecording("command"));
document.getElementById("cmdBtnStop").addEventListener("click", stopRecording);

document
  .getElementById("noteBtnRecord")
  .addEventListener("click", () => startRecording("note"));
document.getElementById("noteBtnStop").addEventListener("click", stopRecording);

document
  .getElementById("btnModalCancel")
  .addEventListener("click", hideNewNoteModal);

document.getElementById("btnModalCreate").addEventListener("click", createNote);

document.getElementById("newNoteTitle").addEventListener("keydown", (e) => {
  if (e.key === "Enter") createNote();
  if (e.key === "Escape") hideNewNoteModal();
});

// --- Init ---
connectWebSocket();
fetchNotes();
