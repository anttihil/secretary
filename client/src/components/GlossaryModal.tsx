import { createSignal } from "solid-js";
import type { Component } from "solid-js";

interface GlossaryModalProps {
  transcriptWord: string;
  onClose: () => void;
  onAdd: (transcriptWord: string, correctWord: string) => void;
}

const GlossaryModal: Component<GlossaryModalProps> = ({
  transcriptWord,
  onClose,
  onAdd,
}) => {
  const [correctWord, setCorrectWord] = createSignal("");

  function handleSubmit(): void {
    const w = correctWord().trim();
    if (!w) return;
    onAdd(transcriptWord, w);
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
        <div class="modal-header">Add Correction</div>
        <div class="modal-body">
          <div class="modal-field-row">
            <span class="modal-field-label">Transcript:</span>
            <span class="modal-field-value">{transcriptWord}</span>
          </div>
          <div class="modal-field-row">
            <span class="modal-field-label">Correct:</span>
            <input
              type="text"
              placeholder="Correct spelling..."
              value={correctWord()}
              onInput={(e) => setCorrectWord(e.currentTarget.value)}
              onKeyDown={handleKeyDown}
              autofocus
            />
          </div>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button class="btn-create" onClick={handleSubmit}>
            Add
          </button>
        </div>
      </div>
    </div>
  );
};

export default GlossaryModal;
