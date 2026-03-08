import { For, Show, createSignal, createMemo, onMount, onCleanup } from "solid-js";
import type { Component } from "solid-js";
import type { NoteListItem, Note } from "../types";

interface DirNode {
  name: string;
  path: string;
  children: DirNode[];
  notes: NoteListItem[];
}

interface ContextMenuState {
  x: number;
  y: number;
  type: "note" | "dir";
  path: string;
}

interface SidebarProps {
  notes: NoteListItem[];
  directories: string[];
  currentNote: Note | null;
  onOpenNote: (filename: string) => void;
  onNewNote: (directory?: string) => void;
  onMigrate: () => void;
  onSettings: () => void;
  onCreateDirectory: () => void;
  onMoveNote: (filename: string, directory: string) => void;
  onMoveDir: (path: string, directory: string) => void;
  onDeleteNote: (filename: string) => void;
  onDeleteDir: (path: string) => void;
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

function formatNoteDate(updated: string, created: string): string {
  const raw = updated || created;
  if (!raw) return "";
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw;
  const now = new Date();
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const day = d.getDate();
  const month = months[d.getMonth()];
  const year = d.getFullYear();
  if (year === now.getFullYear()) {
    return `${day} ${month}`;
  }
  return `${day} ${month} ${year}`;
}

const Sidebar: Component<SidebarProps> = (props) => {
  const [collapsed, setCollapsed] = createSignal(loadCollapsed());
  const [isDragging, setIsDragging] = createSignal(false);
  const [dragOverDir, setDragOverDir] = createSignal<string | null>(null);
  const [draggingItem, setDraggingItem] = createSignal<{ type: "note" | "dir"; path: string } | null>(null);
  const [contextMenu, setContextMenu] = createSignal<ContextMenuState | null>(null);

  function clearDragState() {
    setIsDragging(false);
    setDragOverDir(null);
    setDraggingItem(null);
  }

  function handleDrop(e: DragEvent, targetDir: string) {
    e.preventDefault();
    const data = e.dataTransfer!.getData("text/plain");
    clearDragState();
    if (data.startsWith("note:")) {
      props.onMoveNote(data.slice(5), targetDir);
    } else if (data.startsWith("dir:")) {
      props.onMoveDir(data.slice(4), targetDir);
    }
  }

  function canDrop(targetDirPath: string): boolean {
    const item = draggingItem();
    if (!item) return false;
    if (item.type === "dir") {
      // Cannot drop a dir into itself or a descendant of itself
      if (targetDirPath === item.path || targetDirPath.startsWith(item.path + "/")) return false;
    }
    return true;
  }

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

  function openContextMenu(e: MouseEvent, type: "note" | "dir", path: string): void {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, type, path });
  }

  function closeContextMenu(): void {
    setContextMenu(null);
  }

  function handleContextMenuDelete(): void {
    const menu = contextMenu();
    if (!menu) return;
    closeContextMenu();
    if (menu.type === "note") {
      props.onDeleteNote(menu.path);
    } else {
      props.onDeleteDir(menu.path);
    }
  }

  onMount(() => {
    function handleDocClick() {
      closeContextMenu();
    }
    document.addEventListener("click", handleDocClick);
    onCleanup(() => document.removeEventListener("click", handleDocClick));
  });

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
        onContextMenu={(e) => openContextMenu(e, "note", note.filename)}
        draggable={true}
        onDragStart={(e) => {
          e.dataTransfer!.setData("text/plain", "note:" + note.filename);
          e.dataTransfer!.effectAllowed = "move";
          setIsDragging(true);
          setDraggingItem({ type: "note", path: note.filename });
        }}
        onDragEnd={clearDragState}
      >
        <div class="note-item-title">{note.title || "Untitled"}</div>
        <div class="note-item-date">{formatNoteDate(note.updated, note.created)}</div>
      </div>
    );
  }

  function renderDir(dir: DirNode, depth: number) {
    const isCollapsed = () => collapsed().has(dir.path);
    const isDragOver = () => dragOverDir() === dir.path;
    return (
      <div class="dir-tree">
        <div
          class={`dir-drop-zone${isDragOver() ? " drag-over" : ""}`}
          onDragOver={(e) => {
            if (!canDrop(dir.path)) return;
            e.preventDefault();
            e.dataTransfer!.dropEffect = "move";
            setDragOverDir(dir.path);
          }}
          onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOverDir(null); }}
          onDrop={(e) => handleDrop(e, dir.path)}
        >
          <div
            class="dir-item"
            style={{ "padding-left": `${depth * 0.75}rem` }}
            onClick={() => toggleDir(dir.path)}
            onContextMenu={(e) => openContextMenu(e, "dir", dir.path)}
            draggable={true}
            onDragStart={(e) => {
              e.stopPropagation();
              e.dataTransfer!.setData("text/plain", "dir:" + dir.path);
              e.dataTransfer!.effectAllowed = "move";
              setIsDragging(true);
              setDraggingItem({ type: "dir", path: dir.path });
            }}
            onDragEnd={clearDragState}
          >
            <span class={`dir-toggle${isCollapsed() ? " collapsed" : ""}`}>&#9662;</span>
            <span class="dir-name">{dir.name}</span>
          </div>
          <Show when={!isCollapsed()}>
            <div style={{ "padding-left": `${depth * 0.75}rem` }}>
              <For each={dir.notes}>{(note) => renderNote(note)}</For>
            </div>
          </Show>
        </div>
        <Show when={!isCollapsed()}>
          <For each={dir.children}>{(child) => renderDir(child, depth + 1)}</For>
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
        <div
          class={`root-drop-zone${isDragging() ? " dragging" : ""}${dragOverDir() === "" ? " drag-over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); e.dataTransfer!.dropEffect = "move"; setDragOverDir(""); }}
          onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOverDir(null); }}
          onDrop={(e) => handleDrop(e, "")}
        >
          <For each={tree().notes}>{(note) => renderNote(note)}</For>
        </div>
        <For each={tree().children}>{(dir) => renderDir(dir, 1)}</For>
      </div>
      <div class="sidebar-footer">
        <button class="btn-migrate" onClick={props.onMigrate}>
          Import legacy notes
        </button>
        <button class="btn-settings" onClick={props.onSettings}>
          Settings
        </button>
      </div>
      <Show when={contextMenu() !== null}>
        <div
          class="context-menu"
          style={{ left: `${contextMenu()!.x}px`, top: `${contextMenu()!.y}px` }}
          onClick={(e) => e.stopPropagation()}
        >
          <button style={{ color: "var(--ink-red)" }} onClick={handleContextMenuDelete}>
            Delete
          </button>
        </div>
      </Show>
    </div>
  );
};

export default Sidebar;
