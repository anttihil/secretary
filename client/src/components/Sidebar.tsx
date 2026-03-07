import { For, Show, createSignal, createMemo } from "solid-js";
import type { Component } from "solid-js";
import type { NoteListItem, Note } from "../types";

interface DirNode {
  name: string;
  path: string;
  children: DirNode[];
  notes: NoteListItem[];
}

interface SidebarProps {
  notes: NoteListItem[];
  directories: string[];
  currentNote: Note | null;
  onOpenNote: (filename: string) => void;
  onNewNote: (directory?: string) => void;
  onMigrate: () => void;
  onCreateDirectory: () => void;
  open?: boolean;
}

const COLLAPSED_KEY = "secretary-collapsed-dirs";

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function saveCollapsed(set: Set<string>): void {
  localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...set]));
}

const Sidebar: Component<SidebarProps> = (props) => {
  const [collapsed, setCollapsed] = createSignal(loadCollapsed());

  function toggleDir(path: string): void {
    const next = new Set(collapsed());
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
    }
    setCollapsed(next);
    saveCollapsed(next);
  }

  const tree = createMemo(() => {
    const root: DirNode = { name: "", path: "", children: [], notes: [] };
    const dirMap = new Map<string, DirNode>();
    dirMap.set("", root);

    // Create all directory nodes
    const sortedDirs = [...props.directories].sort();
    for (const dirPath of sortedDirs) {
      const parts = dirPath.split("/");
      let current = "";
      for (let i = 0; i < parts.length; i++) {
        const parentPath = current;
        current = current ? `${current}/${parts[i]}` : parts[i];
        if (!dirMap.has(current)) {
          const node: DirNode = { name: parts[i], path: current, children: [], notes: [] };
          dirMap.set(current, node);
          const parent = dirMap.get(parentPath)!;
          parent.children.push(node);
        }
      }
    }

    // Place notes into their directories
    for (const note of props.notes) {
      const slashIdx = note.filename.lastIndexOf("/");
      const dirPath = slashIdx === -1 ? "" : note.filename.substring(0, slashIdx);
      const dir = dirMap.get(dirPath);
      if (dir) {
        dir.notes.push(note);
      } else {
        root.notes.push(note);
      }
    }

    return root;
  });

  function renderNote(note: NoteListItem) {
    return (
      <div
        class={`note-item${note.filename === props.currentNote?.filename ? " active" : ""}`}
        onClick={() => props.onOpenNote(note.filename)}
      >
        <div class="note-item-title">{note.title}</div>
        <div class="note-item-date">{note.updated}</div>
      </div>
    );
  }

  function renderDir(dir: DirNode, depth: number) {
    const isCollapsed = () => collapsed().has(dir.path);
    return (
      <div class="dir-tree">
        <div
          class="dir-item"
          style={{ "padding-left": `${depth * 0.75}rem` }}
          onClick={() => toggleDir(dir.path)}
        >
          <span class={`dir-toggle${isCollapsed() ? " collapsed" : ""}`}>&#9662;</span>
          <span class="dir-name">{dir.name}</span>
        </div>
        <Show when={!isCollapsed()}>
          <div style={{ "padding-left": `${depth * 0.75}rem` }}>
            <For each={dir.notes}>{(note) => renderNote(note)}</For>
            <For each={dir.children}>{(child) => renderDir(child, depth + 1)}</For>
          </div>
        </Show>
      </div>
    );
  }

  return (
    <div class={`sidebar${props.open ? " open" : ""}`}>
      <div class="sidebar-header">
        <h2>Notes</h2>
        <div class="sidebar-header-buttons">
          <button class="btn-new-folder" onClick={props.onCreateDirectory}>
            + Folder
          </button>
          <button class="btn-new-note" onClick={() => props.onNewNote()}>
            + New
          </button>
        </div>
      </div>
      <div class="notes-list">
        <Show when={props.notes.length === 0 && props.directories.length === 0}>
          <div class="no-notes">No notes yet</div>
        </Show>
        <For each={tree().notes}>{(note) => renderNote(note)}</For>
        <For each={tree().children}>{(dir) => renderDir(dir, 1)}</For>
      </div>
      <div class="sidebar-footer">
        <button class="btn-migrate" onClick={props.onMigrate}>
          Import legacy notes
        </button>
      </div>
    </div>
  );
};

export default Sidebar;
