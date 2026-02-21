import { For, Show } from "solid-js";
import type { Component } from "solid-js";
import type { NoteListItem, Note } from "../types";

interface SidebarProps {
  notes: NoteListItem[];
  currentNote: Note | null;
  onOpenNote: (filename: string) => void;
  onNewNote: () => void;
  onCommandMode: () => void;
}

const Sidebar: Component<SidebarProps> = ({
  notes,
  currentNote,
  onOpenNote,
  onNewNote,
  onCommandMode,
}) => (
  <div class="sidebar">
    <div class="sidebar-header">
      <h2>Notes</h2>
      <button class="btn-new-note" onClick={onNewNote}>
        + New
      </button>
    </div>
    <div class="notes-list">
      <Show when={notes.length === 0}>
        <div class="no-notes">No notes yet</div>
      </Show>
      <For each={notes}>
        {(note) => (
          <div
            class={`note-item${note.filename === currentNote?.filename ? " active" : ""}`}
            onClick={() => onOpenNote(note.filename)}
          >
            <div class="note-item-title">{note.title}</div>
            <div class="note-item-date">{note.updated}</div>
          </div>
        )}
      </For>
    </div>
    <div class="sidebar-footer">
      <button class="btn-command-mode" onClick={onCommandMode}>
        Command Mode
      </button>
    </div>
  </div>
);

export default Sidebar;
