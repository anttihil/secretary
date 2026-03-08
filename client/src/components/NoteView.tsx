import { Show, For, createSignal, createEffect, onMount, onCleanup } from "solid-js";
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
  onRenameNote: (newTitle: string) => Promise<void>;
  onOpenNote: (filename: string) => void;
}

type Token =
  | { type: "word"; text: string }
  | { type: "space"; text: string }
  | { type: "tag"; text: string; name: string }
  | { type: "notelink"; text: string; title: string };

function tokenizeBody(body: string): Token[] {
  const tokens: Token[] = [];
  const regex = /(\[\[.*?\]\])|(#\S+)|(\s+)|(\S+)/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(body)) !== null) {
    if (match[1]) {
      tokens.push({ type: "notelink", text: match[1], title: match[1].slice(2, -2) });
    } else if (match[2]) {
      tokens.push({ type: "tag", text: match[2], name: match[2].slice(1) });
    } else if (match[3]) {
      tokens.push({ type: "space", text: match[3] });
    } else {
      tokens.push({ type: "word", text: match[4] });
    }
  }
  return tokens;
}

const NoteView: Component<NoteViewProps> = (props) => {
  const [isEditingTitle, setIsEditingTitle] = createSignal(false);
  const [editTitle, setEditTitle] = createSignal("");
  const [selectedWord, setSelectedWord] = createSignal<string | null>(null);
  const [clickedPartIndex, setClickedPartIndex] = createSignal<number>(0);
  const [contextMenuPos, setContextMenuPos] = createSignal<{ x: number; y: number } | null>(null);
  const [insertMode, setInsertMode] = createSignal<"tag" | "notelink" | null>(null);
  const [contextMenuTokenType, setContextMenuTokenType] = createSignal<Token["type"] | "empty">("empty");

  createEffect(() => {
    props.note;
    setIsEditingTitle(false);
  });

  function startEditing(): void {
    setEditTitle(props.note?.title ?? "");
    setIsEditingTitle(true);
  }

  async function submitTitle(): Promise<void> {
    const trimmed = editTitle().trim();
    if (trimmed && trimmed !== props.note?.title) {
      await props.onRenameNote(trimmed);
    }
    setIsEditingTitle(false);
  }

  function handleTitleKeyDown(e: KeyboardEvent): void {
    if (e.key === "Enter") {
      e.preventDefault();
      void submitTitle();
    } else if (e.key === "Escape") {
      setIsEditingTitle(false);
    }
  }

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

  async function handleDelete(): Promise<void> {
    const tokens = tokenizeBody(props.note!.body);
    const idx = clickedPartIndex();
    const newTokens = [...tokens];
    newTokens.splice(idx, 1);
    if (newTokens[idx]?.type === "space") {
      newTokens.splice(idx, 1);
    } else if (idx > 0 && newTokens[idx - 1]?.type === "space") {
      newTokens.splice(idx - 1, 1);
    }
    await props.onUpdateBody(newTokens.map((t) => t.text).join(""));
    setContextMenuPos(null);
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
          <Show
            when={isEditingTitle()}
            fallback={
              <h1 class="note-title" onClick={startEditing}>{props.note?.title}</h1>
            }
          >
            <input
              class="note-title-input"
              value={editTitle()}
              onInput={(e) => setEditTitle(e.currentTarget.value)}
              onKeyDown={handleTitleKeyDown}
              onBlur={() => void submitTitle()}
              autofocus
            />
          </Show>
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
            setContextMenuTokenType("empty");
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
                        setContextMenuTokenType("notelink");
                        setContextMenuPos({ x: e.clientX, y: e.clientY });
                      }}
                    >
                      {notelink.title}
                    </span>
                  );
                }
                if (token.type === "tag") {
                  const tag = token;
                  return (
                    <span
                      class="tag-token"
                      on:contextmenu={(e: MouseEvent) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setClickedPartIndex(index());
                        setContextMenuTokenType("tag");
                        setContextMenuPos({ x: e.clientX, y: e.clientY });
                      }}
                    >
                      {tag.text}
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
                      setContextMenuTokenType("word");
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
          <Show when={contextMenuTokenType() === "tag" || contextMenuTokenType() === "notelink"}>
            <button onClick={handleDelete}>Delete</button>
          </Show>
          <Show when={contextMenuTokenType() !== "tag" && contextMenuTokenType() !== "notelink"}>
            <Show when={contextMenuTokenType() === "word"}>
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
          </Show>
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
