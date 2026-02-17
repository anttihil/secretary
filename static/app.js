let ws;
let mediaRecorder;
let currentMode = "";
let currentNote = null; // { filename, title, body, ... }
let activeView = "command"; // "command" or "note"

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => setStatus("Ready");
  ws.onclose = () => {
    setStatus("Disconnected. Reconnecting...");
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
          // Re-enable recording so user can record again immediately
          document.getElementById("noteBtnRecord").style.display = "";
          document.getElementById("noteBtnStop").style.display = "none";
          document.getElementById("cmdBtnRecord").style.display = "";
          document.getElementById("cmdBtnStop").style.display = "none";
          break;

        case "complete":
          if (parsed.mode === "note" && currentNote) {
            await appendToNote(currentNote.filename, parsed.result);
            await openNote(currentNote.filename);
            addNoteResult(parsed.transcript, parsed.result);
          } else {
            addCommandResult(parsed.transcript, parsed.result);
          }
          setStatus("Ready");
          currentMode = "";
          break;

        case "error":
          setStatus("Error: " + parsed.message);
          currentMode = "";
          break;
      }
    } else if (
      typeof text === "string" &&
      text.startsWith("Recording started")
    ) {
      // Already handled in startRecording
    } else if (typeof text === "string") {
      // Legacy plain-text messages
      if (activeView === "command") {
        addCommandResult(null, text);
      }
      setStatus("Ready");
      currentMode = "";
    }
  };
}

function setStatus(text, recording) {
  const statusEl =
    activeView === "note"
      ? document.getElementById("noteStatusText")
      : document.getElementById("cmdStatusText");
  const dotEl =
    activeView === "note"
      ? document.getElementById("noteRecDot")
      : document.getElementById("cmdRecDot");
  statusEl.textContent = text;
  if (recording === true) {
    dotEl.classList.add("active");
  } else {
    dotEl.classList.remove("active");
  }
}

async function startRecording(mode) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: true,
    });
    currentMode = mode;
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

    if (mode === "note") {
      document.getElementById("noteBtnRecord").style.display = "none";
      document.getElementById("noteBtnStop").style.display = "";
    } else {
      document.getElementById("cmdBtnRecord").style.display = "none";
      document.getElementById("cmdBtnStop").style.display = "";
    }
    setStatus("Recording...", true);
  } catch (err) {
    setStatus("Microphone access denied");
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
  // Reset buttons for both views
  document.getElementById("noteBtnRecord").style.display = "";
  document.getElementById("noteBtnStop").style.display = "none";
  document.getElementById("cmdBtnRecord").style.display = "";
  document.getElementById("cmdBtnStop").style.display = "none";
  setStatus("Processing...", false);
}

// --- Notes API ---

async function fetchNotes() {
  const resp = await fetch("/api/notes");
  if (!resp.ok) return;
  const notes = await resp.json();
  renderNotesList(notes);
}

function renderNotesList(notes) {
  const container = document.getElementById("notesList");
  container.innerHTML = "";
  if (!notes || notes.length === 0) {
    container.innerHTML =
      '<div style="padding:1rem;color:#aaa;text-align:center">No notes yet</div>';
    return;
  }
  notes.forEach(({ filename, title, updated }) => {
    const div = document.createElement("div");
    div.classList.add("note-item");
    if (filename === currentNote?.filename) {
      div.classList.add("active");
    }
    div.innerHTML = `<div class=note-item-title>${escapeHtml(title)}</div><div class=note-item-date>${escapeHtml(updated)}</div>`;
    div.onclick = () => openNote(filename);
    container.append(div);
  });
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
  hideNewNoteModal();
  titleInput.value = "";
  await openNote(note.filename);
}

async function openNote(filename) {
  const resp = await fetch(`/api/notes/${filename}`);
  if (!resp.ok) return;
  currentNote = await resp.json();
  document.getElementById("noteTitle").textContent = currentNote.title;
  const bodyEl = document.getElementById("noteBody");
  if (currentNote.body && currentNote.body.trim()) {
    bodyEl.textContent = currentNote.body;
    bodyEl.classList.remove("note-body-empty");
  } else {
    bodyEl.textContent = "No content yet. Record audio to add notes.";
    bodyEl.classList.add("note-body-empty");
  }
  document.getElementById("noteResults").innerHTML = "";
  showNoteView();
  // Refresh sidebar to highlight active note
  await fetchNotes();
}

function closeNote() {
  currentNote = null;
  showCommandView();
  fetchNotes();
}

async function deleteCurrentNote() {
  if (!currentNote) return;
  if (!confirm(`Delete "${currentNote.title}"?`)) return;
  await fetch(`/api/notes/${currentNote.filename}`, { method: "DELETE" });
  currentNote = null;
  showCommandView();
  await fetchNotes();
}

async function appendToNote(filename, text) {
  await fetch(`/api/notes/${filename}/append`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

// --- Views ---

function showCommandView() {
  activeView = "command";
  document.getElementById("commandView").classList.remove("view-hidden");
  document.getElementById("noteView").classList.add("view-hidden");
}

function showNoteView() {
  activeView = "note";
  document.getElementById("noteView").classList.remove("view-hidden");
  document.getElementById("commandView").classList.add("view-hidden");
  document.getElementById("noteStatusText").textContent = "";
  document.getElementById("noteRecDot").classList.remove("active");
}

function showNewNoteModal() {
  document.getElementById("newNoteModal").classList.add("active");
  document.getElementById("newNoteTitle").focus();
}

function hideNewNoteModal() {
  document.getElementById("newNoteModal").classList.remove("active");
  document.getElementById("newNoteTitle").value = "";
}

// --- Result rendering ---

function addCommandResult(transcript, result) {
  const container = document.getElementById("cmdResults");
  container.prepend(createResultItem(transcript, result, "command"));
}

function addNoteResult(transcript, result) {
  const container = document.getElementById("noteResults");
  container.prepend(createResultItem(transcript, result, "note"));
}

function createResultItem(transcript, result, mode) {
  const item = document.createElement("div");
  item.className = "result-item";
  const now = new Date().toLocaleTimeString();
  const tag = mode ? `<span class="mode-tag ${mode}">${mode}</span>` : "";
  const resultLabel = mode === "command" ? "Response" : "Cleaned";
  let html = `<div class="timestamp">${now}${tag}</div>`;
  if (transcript) {
    html += `<div class="transcript"><span class="transcript-label">Transcript</span><br>${escapeHtml(transcript)}</div>`;
    html += `<div class="text"><span class="transcript-label">${resultLabel}</span><br>${escapeHtml(result)}</div>`;
  } else {
    html += `<div class="text">${escapeHtml(result)}</div>`;
  }
  item.innerHTML = html;
  return item;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// --- Modal keyboard handling ---
document.getElementById("newNoteTitle").addEventListener("keydown", (e) => {
  if (e.key === "Enter") createNote();
  if (e.key === "Escape") hideNewNoteModal();
});

// --- Init ---
connectWebSocket();
fetchNotes();
