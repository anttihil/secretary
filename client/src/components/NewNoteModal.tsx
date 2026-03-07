import { createSignal, For } from "solid-js";
import type { Component } from "solid-js";

interface NewNoteModalProps {
  onClose: () => void;
  onCreate: (title: string, directory: string) => void;
  directories: string[];
  defaultDirectory?: string;
}

const NewNoteModal: Component<NewNoteModalProps> = (props) => {
  const [title, setTitle] = createSignal("");
  const [directory, setDirectory] = createSignal(props.defaultDirectory ?? "");

  function handleCreate(): void {
    const t = title().trim();
    if (!t) return;
    props.onCreate(t, directory());
    setTitle("");
  }

  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === "Enter") handleCreate();
    if (e.key === "Escape") props.onClose();
  }

  return (
    <div
      class="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && props.onClose()}
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
          <div class="modal-field-row">
            <span class="modal-field-label">FILED:</span>
            <select
              class="modal-select"
              value={directory()}
              onChange={(e) => setDirectory(e.currentTarget.value)}
            >
              <option value="">(root)</option>
              <For each={props.directories}>
                {(dir) => <option value={dir}>{dir}</option>}
              </For>
            </select>
          </div>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={props.onClose}>
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
