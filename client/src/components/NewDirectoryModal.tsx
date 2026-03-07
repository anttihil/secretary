import { createSignal, For } from "solid-js";
import type { Component } from "solid-js";

interface NewDirectoryModalProps {
  onClose: () => void;
  onCreate: (name: string, parentDirectory: string) => void;
  directories: string[];
}

const NewDirectoryModal: Component<NewDirectoryModalProps> = (props) => {
  const [name, setName] = createSignal("");
  const [parent, setParent] = createSignal("");

  function handleCreate(): void {
    const n = name().trim();
    if (!n) return;
    props.onCreate(n, parent());
    setName("");
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
        <div class="modal-header">New Folder</div>
        <div class="modal-body">
          <div class="modal-field-row">
            <span class="modal-field-label">NAME:</span>
            <input
              type="text"
              placeholder="Folder name..."
              value={name()}
              onInput={(e) => setName(e.currentTarget.value)}
              onKeyDown={handleKeyDown}
              autofocus
            />
          </div>
          <div class="modal-field-row">
            <span class="modal-field-label">INSIDE:</span>
            <select
              class="modal-select"
              value={parent()}
              onChange={(e) => setParent(e.currentTarget.value)}
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

export default NewDirectoryModal;
