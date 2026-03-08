import { createSignal, createEffect, Show } from "solid-js";
import type { Component } from "solid-js";

interface EditableTitleProps {
  title: string;
  onRename: (newTitle: string) => Promise<void>;
  displayClass?: string;
  inputClass?: string;
}

const EditableTitle: Component<EditableTitleProps> = (props) => {
  const [isEditing, setIsEditing] = createSignal(false);
  const [editValue, setEditValue] = createSignal("");

  createEffect(() => {
    props.title;
    setIsEditing(false);
  });

  function startEditing(): void {
    setEditValue(props.title);
    setIsEditing(true);
  }

  async function submit(): Promise<void> {
    const trimmed = editValue().trim();
    if (trimmed && trimmed !== props.title) {
      await props.onRename(trimmed);
    }
    setIsEditing(false);
  }

  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === "Enter") {
      e.preventDefault();
      void submit();
    } else if (e.key === "Escape") {
      setIsEditing(false);
    }
  }

  return (
    <Show
      when={isEditing()}
      fallback={
        <span class={props.displayClass} onClick={startEditing}>
          {props.title}
        </span>
      }
    >
      <input
        class={props.inputClass}
        value={editValue()}
        onInput={(e) => setEditValue(e.currentTarget.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => void submit()}
        autofocus
      />
    </Show>
  );
};

export default EditableTitle;
