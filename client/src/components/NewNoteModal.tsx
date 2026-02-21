import { createSignal } from "solid-js";
import type { Component } from "solid-js";

interface NewNoteModalProps {
  onClose: () => void;
  onCreate: (title: string) => void;
}

const NewNoteModal: Component<NewNoteModalProps> = ({ onClose, onCreate }) => {
  const [title, setTitle] = createSignal("");

  function handleCreate(): void {
    const t = title().trim();
    if (!t) return;
    onCreate(t);
    setTitle("");
  }

  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === "Enter") handleCreate();
    if (e.key === "Escape") onClose();
  }

  return (
    <div
      class="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div class="modal">
        <div class="modal-header">Memorandum</div>
        <div class="modal-body">
          <div class="modal-field-row">
            <span class="modal-field-label">RE:</span>
            <input
              type="text"
              placeholder="Note title..."
              value={title()}
              onInput={(e) => setTitle(e.currentTarget.value)}
              onKeyDown={handleKeyDown}
              autofocus
            />
          </div>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button class="btn-create" onClick={handleCreate}>
            Create
          </button>
        </div>
      </div>
    </div>
  );
};

export default NewNoteModal;
