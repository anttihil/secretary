import { createSignal, For, createMemo } from "solid-js";
import type { Component } from "solid-js";
import type { NoteListItem } from "../types";

interface InsertNoteLinkModalProps {
  notes: NoteListItem[];
  onClose: () => void;
  onInsert: (link: string) => void;
}

const InsertNoteLinkModal: Component<InsertNoteLinkModalProps> = ({ notes, onClose, onInsert }) => {
  const [query, setQuery] = createSignal("");

  const filtered = createMemo(() => {
    const q = query().toLowerCase();
    return q ? notes.filter((n) => n.title.toLowerCase().includes(q)) : notes;
  });

  function handleSelect(note: NoteListItem): void {
    onInsert("[[" + note.title + "]]");
  }

  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === "Enter") {
      const first = filtered()[0];
      if (first) handleSelect(first);
    }
    if (e.key === "Escape") onClose();
  }

  return (
    <div
      class="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div class="modal">
        <div class="modal-header">Insert Note Link</div>
        <div class="modal-body">
          <div class="modal-field-row">
            <input
              type="text"
              placeholder="Search notes..."
              value={query()}
              onInput={(e) => setQuery(e.currentTarget.value)}
              onKeyDown={handleKeyDown}
              autofocus
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ "max-height": "200px", "overflow-y": "auto", "margin-top": "0.5rem" }}>
            <For each={filtered()}>
              {(note) => (
                <div
                  class="note-link-item"
                  onClick={() => handleSelect(note)}
                  style={{ padding: "0.4rem 0.5rem", cursor: "pointer" }}
                >
                  {note.title}
                </div>
              )}
            </For>
          </div>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
};

export default InsertNoteLinkModal;
