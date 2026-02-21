import { Show } from "solid-js";
import type { Component } from "solid-js";
import type { Note, Result } from "../types";
import StatusBar from "./StatusBar";
import ResultList from "./ResultList";

interface NoteViewProps {
  note: Note | null;
  results: Result[];
  status: string;
  isRecording: boolean;
  onRecord: () => void;
  onStop: () => void;
  onBack: () => void;
  onDelete: () => void;
}

const NoteView: Component<NoteViewProps> = ({
  note,
  results,
  status,
  isRecording,
  onRecord,
  onStop,
  onBack,
  onDelete,
}) => (
  <div class="note-view">
    <div class="note-header">
      <button class="btn-back" onClick={onBack}>
        ←
      </button>
      <h1>{note?.title}</h1>
      <button class="btn-delete" onClick={onDelete}>
        Delete
      </button>
    </div>
    <div class="note-controls">
      <Show
        when={!isRecording}
        fallback={
          <button class="btn-stop" onClick={onStop}>
            Stop
          </button>
        }
      >
        <button class="btn-record" onClick={onRecord}>
          Record
        </button>
      </Show>
    </div>
    <StatusBar status={status} isRecording={isRecording} />
    <div class={`note-body${!note?.body?.trim() ? " note-body-empty" : ""}`}>
      {note?.body?.trim()
        ? note.body
        : "No content yet. Record audio to add notes."}
    </div>
    <div style="margin-top: 1rem">
      <ResultList results={results} />
    </div>
  </div>
);

export default NoteView;
