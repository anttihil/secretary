import type { Note, NoteListItem } from "./types";

export async function fetchNotes(): Promise<NoteListItem[]> {
  const resp = await fetch("/api/notes");
  if (!resp.ok) throw new Error("Failed to fetch notes");
  return resp.json();
}

export async function createNote(title: string): Promise<NoteListItem> {
  const resp = await fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!resp.ok) throw new Error("Failed to create note");
  return resp.json();
}

export async function getNote(filename: string): Promise<Note> {
  const resp = await fetch(`/api/notes/${filename}`);
  if (!resp.ok) throw new Error("Note not found");
  return resp.json();
}

export async function deleteNote(filename: string): Promise<{ deleted: string }> {
  const resp = await fetch(`/api/notes/${filename}`, { method: "DELETE" });
  if (!resp.ok) throw new Error("Failed to delete note");
  return resp.json();
}

export async function appendToNote(filename: string, text: string): Promise<Note> {
  const resp = await fetch(`/api/notes/${filename}/append`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error("Failed to append to note");
  return resp.json();
}
