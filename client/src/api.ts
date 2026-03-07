import type { Note, NotesListResponse, Settings } from "./types";

function encodeNotePath(filename: string): string {
  return filename
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
}

export async function fetchNotes(): Promise<NotesListResponse> {
  const resp = await fetch("/api/notes");
  if (!resp.ok) throw new Error("Failed to fetch notes");
  return resp.json();
}

export async function createNote(
  title: string,
  directory?: string,
): Promise<{ filename: string; title: string; created: string; updated: string }> {
  const resp = await fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, directory: directory || "" }),
  });
  if (!resp.ok) throw new Error("Failed to create note");
  return resp.json();
}

export async function getNote(filename: string): Promise<Note> {
  const resp = await fetch(`/api/notes/${encodeNotePath(filename)}`);
  if (!resp.ok) throw new Error("Note not found");
  return resp.json();
}

export async function deleteNote(filename: string): Promise<{ deleted: string }> {
  const resp = await fetch(`/api/notes/${encodeNotePath(filename)}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error("Failed to delete note");
  return resp.json();
}

export async function addToGlossary(
  transcriptWord: string,
  correctWord: string,
): Promise<{ transcript: string; correct: string }> {
  const resp = await fetch("/api/glossary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transcript_word: transcriptWord,
      correct_word: correctWord,
    }),
  });
  if (!resp.ok) throw new Error("Failed to add to glossary");
  return resp.json();
}

export async function cleanNote(
  filename: string,
): Promise<{ cleaned: string }> {
  const resp = await fetch(`/api/notes/${encodeNotePath(filename)}/clean`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error("Failed to clean note");
  return resp.json();
}

export async function replaceNoteBody(
  filename: string,
  body: string,
): Promise<Note> {
  const resp = await fetch(`/api/notes/${encodeNotePath(filename)}/replace`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!resp.ok) throw new Error("Failed to replace note body");
  return resp.json();
}

export async function migrateNotes(): Promise<{
  migrated: number;
  skipped: number;
  files: { original_filename: string; filename: string; actions: string[] }[];
}> {
  const resp = await fetch("/api/migrate", { method: "POST" });
  if (!resp.ok) throw new Error("Migration failed");
  return resp.json();
}

export async function fetchSettings(): Promise<Settings> {
  const resp = await fetch("/api/settings");
  if (!resp.ok) throw new Error("Failed to fetch settings");
  return resp.json();
}

export async function saveSettings(
  settings: Omit<Settings, "cuda_available">,
): Promise<Settings> {
  const resp = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || "Failed to save settings");
  }
  return resp.json();
}

export async function appendToNote(filename: string, text: string): Promise<Note> {
  const resp = await fetch(`/api/notes/${encodeNotePath(filename)}/append`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error("Failed to append to note");
  return resp.json();
}

export async function moveDirectory(path: string, directory: string): Promise<{ path: string }> {
  const resp = await fetch(`/api/directories/${encodeNotePath(path)}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory }),
  });
  if (!resp.ok) throw new Error("Failed to move directory");
  return resp.json();
}

export async function moveNote(filename: string, directory: string): Promise<Note> {
  const resp = await fetch(`/api/notes/${encodeNotePath(filename)}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory }),
  });
  if (!resp.ok) throw new Error("Failed to move note");
  return resp.json();
}

export async function createDirectory(
  path: string,
): Promise<{ path: string }> {
  const resp = await fetch("/api/directories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!resp.ok) throw new Error("Failed to create directory");
  return resp.json();
}
