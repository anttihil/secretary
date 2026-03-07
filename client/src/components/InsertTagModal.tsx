import { createSignal } from "solid-js";
import type { Component } from "solid-js";

interface InsertTagModalProps {
  onClose: () => void;
  onInsert: (tag: string) => void;
}

const InsertTagModal: Component<InsertTagModalProps> = ({ onClose, onInsert }) => {
  const [tagName, setTagName] = createSignal("");

  function handleSubmit(): void {
    const t = tagName().trim();
    if (!t) return;
    onInsert("#" + t);
  }

  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === "Enter") handleSubmit();
    if (e.key === "Escape") onClose();
  }

  return (
    <div
      class="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div class="modal">
        <div class="modal-header">Insert Tag</div>
        <div class="modal-body">
          <div class="modal-field-row">
            <span class="modal-field-label">Tag:</span>
            <input
              type="text"
              placeholder="tag name"
              value={tagName()}
              onInput={(e) => setTagName(e.currentTarget.value)}
              onKeyDown={handleKeyDown}
              autofocus
            />
          </div>
          <div class="modal-field-row">
            <span class="modal-field-label">Preview:</span>
            <span class="modal-field-value">#{tagName().trim() || "tag"}</span>
          </div>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={onClose}>Cancel</button>
          <button class="btn-create" onClick={handleSubmit}>Insert</button>
        </div>
      </div>
    </div>
  );
};

export default InsertTagModal;
