import { Show, For, createSignal, onMount, onCleanup } from "solid-js";
import type { Component } from "solid-js";
import type { Note, NoteListItem, Result } from "../types";
import { addToGlossary } from "../api";
import GlossaryModal from "./GlossaryModal";
import InsertTagModal from "./InsertTagModal";
import InsertNoteLinkModal from "./InsertNoteLinkModal";
import StatusBar from "./StatusBar";
import ResultList from "./ResultList";

interface NoteViewProps {
  note: Note | null;
  results: Result[];
  status: string;
  isRecording: boolean;
  isCleaning: boolean;
  notes: NoteListItem[];
  onRecord: () => void;
  onStop: () => void;
  onBack: () => void;
  onDelete: () => void;
  onClean: () => void;
  onUpdateBody: (newBody: string) => Promise<void>;
  onOpenNote: (filename: string) => void;
}

type Token =
  | { type: "word"; text: string }
  | { type: "space"; text: string }
  | { type: "notelink"; text: string; title: string };

function tokenizeBody(body: string): Token[] {
  const tokens: Token[] = [];
  const regex = /(\[\[.*?\]\])|(\s+)|(\S+)/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(body)) !== null) {
    if (match[1]) {
      tokens.push({ type: "notelink", text: match[1], title: match[1].slice(2, -2) });
    } else if (match[2]) {
      tokens.push({ type: "space", text: match[2] });
    } else {
      tokens.push({ type: "word", text: match[3] });
    }
  }
  return tokens;
}

const NoteView: Component<NoteViewProps> = (props) => {
  const [selectedWord, setSelectedWord] = createSignal<string | null>(null);
  const [clickedPartIndex, setClickedPartIndex] = createSignal<number>(0);
  const [contextMenuPos, setContextMenuPos] = createSignal<{ x: number; y: number } | null>(null);
  const [insertMode, setInsertMode] = createSignal<"tag" | "notelink" | null>(null);
  const [contextMenuHasWord, setContextMenuHasWord] = createSignal(false);

  function closeContextMenu(): void {
    setContextMenuPos(null);
  }

  onMount(() => document.addEventListener("click", closeContextMenu));
  onCleanup(() => document.removeEventListener("click", closeContextMenu));

  async function handleAdd(transcriptWord: string, correctWord: string) {
    try {
      await addToGlossary(transcriptWord, correctWord);
    } catch (e) {
      console.error("Failed to add to glossary:", e);
    }
    setSelectedWord(null);
  }

  async function handleInsert(text: string): Promise<void> {
    const idx = clickedPartIndex();
    let newBody: string;
    if (idx === -1) {
      const trimmed = props.note!.body.trimEnd();
      newBody = trimmed ? trimmed + " " + text : text;
    } else {
      const tokens = tokenizeBody(props.note!.body);
      tokens.splice(idx + 1, 0, { type: "space", text: " " }, { type: "word", text });
      newBody = tokens.map((t) => t.text).join("");
    }
    await props.onUpdateBody(newBody);
    setInsertMode(null);
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
        <div
          class={`note-body${!props.note?.body?.trim() ? " note-body-empty" : ""}`}
          on:contextmenu={(e: MouseEvent) => {
            e.preventDefault();
            setClickedPartIndex(-1);
            setContextMenuHasWord(false);
            setContextMenuPos({ x: e.clientX, y: e.clientY });
          }}
        >
          <Show
            when={props.note?.body?.trim()}
            fallback="No content yet. Record audio to add notes."
          >
            <For each={tokenizeBody(props.note!.body)}>
              {(token, index) => {
                if (token.type === "space") return <>{token.text}</>;
                if (token.type === "notelink") {
                  const notelink = token;
                  const filename = () => props.notes.find((n) => n.title === notelink.title)?.filename;
                  return (
                    <span
                      class="note-link"
                      onClick={() => { const f = filename(); if (f) props.onOpenNote(f); }}
                      on:contextmenu={(e: MouseEvent) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setClickedPartIndex(index());
                        setContextMenuHasWord(false);
                        setContextMenuPos({ x: e.clientX, y: e.clientY });
                      }}
                    >
                      {notelink.title}
                    </span>
                  );
                }
                return (
                  <span
                    class="transcript-word"
                    on:contextmenu={(e: MouseEvent) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setClickedPartIndex(index());
                      setContextMenuHasWord(true);
                      setContextMenuPos({ x: e.clientX, y: e.clientY });
                    }}
                  >
                    {token.text}
                  </span>
                );
              }}
            </For>
          </Show>
        </div>
        <div style="margin-top: 1rem">
          <ResultList results={props.results} />
        </div>
      </div>
      <Show when={contextMenuPos() !== null}>
        <div
          class="context-menu"
          style={{ left: `${contextMenuPos()!.x}px`, top: `${contextMenuPos()!.y}px` }}
          onClick={(e) => e.stopPropagation()}
        >
          <Show when={contextMenuHasWord()}>
            <button
              onClick={() => {
                const tokens = tokenizeBody(props.note!.body);
                setSelectedWord(tokens[clickedPartIndex()]?.text ?? null);
                setContextMenuPos(null);
              }}
            >
              Add to Glossary
            </button>
          </Show>
          <button onClick={() => { setInsertMode("tag"); setContextMenuPos(null); }}>
            Insert Tag
          </button>
          <button onClick={() => { setInsertMode("notelink"); setContextMenuPos(null); }}>
            Insert Note Link
          </button>
        </div>
      </Show>
      <Show when={selectedWord()}>
        <GlossaryModal
          transcriptWord={selectedWord()!}
          onClose={() => setSelectedWord(null)}
          onAdd={handleAdd}
        />
      </Show>
      <Show when={insertMode() === "tag"}>
        <InsertTagModal onClose={() => setInsertMode(null)} onInsert={handleInsert} />
      </Show>
      <Show when={insertMode() === "notelink"}>
        <InsertNoteLinkModal notes={props.notes} onClose={() => setInsertMode(null)} onInsert={handleInsert} />
      </Show>
    </>
  );
};

export default NoteView;
