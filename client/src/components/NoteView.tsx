import { Show, For, createSignal } from "solid-js";
import type { Component } from "solid-js";
import type { Note, Result } from "../types";
import { addToGlossary } from "../api";
import GlossaryModal from "./GlossaryModal";
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

const NoteView: Component<NoteViewProps> = (props) => {
  const [selectedWord, setSelectedWord] = createSignal<string | null>(null);

  async function handleAdd(transcriptWord: string, correctWord: string) {
    try {
      await addToGlossary(transcriptWord, correctWord);
    } catch (e) {
      console.error("Failed to add to glossary:", e);
    }
    setSelectedWord(null);
  }

  return (
    <>
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
          <Show
            when={props.note?.body?.trim()}
            fallback="No content yet. Record audio to add notes."
          >
            <For each={props.note!.body.split(/(\s+)/)}>
              {(part) =>
                part.trim() ? (
                  <span
                    class="transcript-word"
                    on:contextmenu={(e: MouseEvent) => {
                      e.preventDefault();
                      setSelectedWord(part);
                    }}
                  >
                    {part}
                  </span>
                ) : (
                  part
                )
              }
            </For>
          </Show>
        </div>
        <div style="margin-top: 1rem">
          <ResultList results={props.results} />
        </div>
      </div>
      <Show when={selectedWord()}>
        <GlossaryModal
          transcriptWord={selectedWord()!}
          onClose={() => setSelectedWord(null)}
          onAdd={handleAdd}
        />
      </Show>
    </>
  );
};

export default NoteView;
