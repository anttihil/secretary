import { For, Show } from "solid-js";
import type { Component } from "solid-js";
import type { NoteListItem, Note } from "../types";

interface SidebarProps {
  notes: NoteListItem[];
  currentNote: Note | null;
  onOpenNote: (filename: string) => void;
  onNewNote: () => void;
  onMigrate: () => void;
  open?: boolean;
}

const Sidebar: Component<SidebarProps> = (props) => (
  <div class={`sidebar${props.open ? " open" : ""}`}>
    <div class="sidebar-header">
      <h2>Notes</h2>
      <button class="btn-new-note" onClick={props.onNewNote}>
        + New
      </button>
    </div>
    <div class="notes-list">
      <Show when={props.notes.length === 0}>
        <div class="no-notes">No notes yet</div>
      </Show>
      <For each={props.notes}>
        {(note) => (
          <div
            class={`note-item${note.filename === props.currentNote?.filename ? " active" : ""}`}
            onClick={() => props.onOpenNote(note.filename)}
          >
            <div class="note-item-title">{note.title}</div>
            <div class="note-item-date">{note.updated}</div>
          </div>
        )}
      </For>
    </div>
    <div class="sidebar-footer">
      <button class="btn-migrate" onClick={props.onMigrate}>
        Import legacy notes
      </button>
    </div>
  </div>
);

export default Sidebar;
