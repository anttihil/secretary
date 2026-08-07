import type { Component } from "solid-js";

interface ConfirmModalProps {
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onClose: () => void;
}

const ConfirmModal: Component<ConfirmModalProps> = (props) => {
  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === "Escape") props.onClose();
    if (e.key === "Enter") props.onConfirm();
  }

  return (
    <div
      class="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && props.onClose()}
      onKeyDown={handleKeyDown}
    >
      <div class="modal">
        <div class="modal-header">Confirm</div>
        <div class="modal-body">
          <p style={{ "font-family": "var(--font-body)", "line-height": "1.6" }}>
            {props.message}
          </p>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={props.onClose}>
            Cancel
          </button>
          <button class="btn-delete" onClick={props.onConfirm}>
            {props.confirmLabel ?? "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmModal;
