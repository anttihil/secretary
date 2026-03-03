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
  isCleaning: boolean;
  onRecord: () => void;
  onStop: () => void;
  onBack: () => void;
  onDelete: () => void;
  onClean: () => void;
}

const NoteView: Component<NoteViewProps> = (props) => (
  <div class="note-view">
    <div class="note-header">
      <button class="btn-back" onClick={props.onBack}>
        ←
      </button>
      <h1>{props.note?.title}</h1>
      <button class="btn-delete" onClick={props.onDelete}>
        Delete
      </button>
    </div>
    <div class="note-controls">
      <Show
        when={!props.isRecording}
        fallback={
          <button class="btn-stop" onClick={props.onStop}>
            Stop
          </button>
        }
      >
        <button class="btn-record" onClick={props.onRecord}>
          Record
        </button>
      </Show>
      <button
        class="btn-clean"
        onClick={props.onClean}
        disabled={props.isRecording || props.isCleaning || !props.note?.body?.trim()}
      >
        {props.isCleaning ? "Cleaning..." : "Clean up"}
      </button>
    </div>
    <StatusBar status={props.status} isRecording={props.isRecording} />
    <div class={`note-body${!props.note?.body?.trim() ? " note-body-empty" : ""}`}>
      {props.note?.body?.trim()
        ? props.note.body
        : "No content yet. Record audio to add notes."}
    </div>
    <div style="margin-top: 1rem">
      <ResultList results={props.results} />
    </div>
  </div>
);

export default NoteView;
