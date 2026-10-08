import type { LocalRecording, Note, NoteListItem } from "./types";

let database: Promise<IDBDatabase> | undefined;

function openDatabase(): Promise<IDBDatabase> {
  database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open("secretary-offline", 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("recordings", { keyPath: "id" });
      request.result.createObjectStore("notes", { keyPath: "id" });
      request.result.createObjectStore("meta");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Close other Secretary tabs to open offline storage"));
  });
  return database;
}

async function read<T>(store: string, key?: IDBValidKey): Promise<T> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(store, "readonly");
    const request = key === undefined
      ? transaction.objectStore(store).getAll()
      : transaction.objectStore(store).get(key);
    request.onsuccess = () => resolve(request.result as T);
    request.onerror = () => reject(request.error);
  });
}

async function write(store: string, value: unknown, key?: IDBValidKey): Promise<void> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(store, "readwrite");
    transaction.objectStore(store).put(value, key);
    // Request success precedes transaction commit. Only commit means saved locally.
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error || new Error("Offline storage failed"));
    transaction.onerror = () => reject(transaction.error);
  });
}

async function remove(store: string, key: string): Promise<void> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(store, "readwrite");
    transaction.objectStore(store).delete(key);
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error);
  });
}

export const saveRecording = (recording: LocalRecording) => write("recordings", recording);
export const deleteRecording = (id: string) => remove("recordings", id);
export const getRecordings = () => read<LocalRecording[]>("recordings");
export const saveCachedNote = (note: Note) => write("notes", note);
export const deleteCachedNote = (id: string) => remove("notes", id);
export const getCachedNotes = () => read<Note[]>("notes");
export const getCachedNote = (id: string) => read<Note | undefined>("notes", id);
export const getCachedDirectories = async () => (await read<string[] | undefined>("meta", "directories")) || [];

export async function cacheNoteList(notes: NoteListItem[], directories: string[]): Promise<void> {
  const cached = await getCachedNotes();
  for (const note of notes) {
    const previous = cached.find((n) => n.id === note.id);
    await saveCachedNote({ ...previous, ...note, body: previous?.body || "", localOnly: false });
  }
  for (const note of cached) {
    if (!note.localOnly && !notes.some((n) => n.id === note.id)) await deleteCachedNote(note.id);
  }
  await write("meta", directories, "directories");
}
