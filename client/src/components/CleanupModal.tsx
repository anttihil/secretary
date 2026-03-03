import { createSignal, createMemo, For, Show, Switch, Match } from "solid-js";
import type { Component } from "solid-js";
import { computeDiff, buildResult, type DiffToken } from "../diff";
import { addToGlossary } from "../api";

type Choice = "old" | "new";

interface CleanupModalProps {
  original: string;
  cleaned: string;
  onApply: (finalText: string) => void;
  onClose: () => void;
}

const CleanupModal: Component<CleanupModalProps> = (props) => {
  const tokens = createMemo(() => computeDiff(props.original, props.cleaned));
  // Keyed by delete token id for pairs, or token id for unpaired
  const [choices, setChoices] = createSignal<Map<number, Choice>>(new Map());
  const [contextMenu, setContextMenu] = createSignal<{
    x: number;
    y: number;
    deleteToken: DiffToken;
    insertToken: DiffToken;
  } | null>(null);

  function choose(key: number, side: Choice) {
    const next = new Map(choices());
    if (next.get(key) === side) {
      next.delete(key); // clicking again returns to "old → new" form
    } else {
      next.set(key, side);
    }
    setChoices(next);
  }

  function handleContextMenu(e: MouseEvent, deleteToken: DiffToken, insertToken: DiffToken) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, deleteToken, insertToken });
  }

  async function handleAddToGlossary() {
    const menu = contextMenu();
    if (!menu) return;
    try {
      await addToGlossary(menu.deleteToken.text, menu.insertToken.text);
    } catch (e) {
      console.error("Failed to add to glossary:", e);
    }
    setContextMenu(null);
  }

  function handleApply() {
    props.onApply(buildResult(tokens(), choices()));
  }

  /** Group tokens for rendering: equal tokens, paired tokens, unpaired tokens */
  const groups = createMemo(() => {
    const toks = tokens();
    type Group =
      | { type: "equal"; token: DiffToken }
      | { type: "pair"; del: DiffToken; ins: DiffToken }
      | { type: "unpaired"; token: DiffToken };
    const result: Group[] = [];
    const seen = new Set<number>();

    for (const t of toks) {
      if (seen.has(t.id)) continue;
      if (t.kind === "equal") {
        result.push({ type: "equal", token: t });
      } else if (t.pairId !== undefined) {
        const pair = toks.find((p) => p.id === t.pairId)!;
        seen.add(pair.id);
        const del = t.kind === "delete" ? t : pair;
        const ins = t.kind === "insert" ? t : pair;
        result.push({ type: "pair", del, ins });
      } else {
        result.push({ type: "unpaired", token: t });
      }
    }
    return result;
  });

  return (
    <div
      class="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) props.onClose();
        setContextMenu(null);
      }}
    >
      <div class="modal cleanup-modal">
        <div class="modal-header">Review Cleanup</div>
        <div class="modal-body cleanup-body">
          <p class="cleanup-hint">Click a word to choose it. Click again to undo.</p>
          <div class="cleanup-diff">
            <For each={groups()}>
              {(group) => (
                <Switch>
                  <Match when={group.type === "equal" && "token" in group}>
                    <span>{(group as any).token.text}{(group as any).token.space}</span>
                  </Match>
                  <Match when={group.type === "pair" && "del" in group}>
                    {(() => {
                      const g = group as { type: "pair"; del: DiffToken; ins: DiffToken };
                      const choice = () => choices().get(g.del.id);
                      return (
                        <Show
                          when={choice() === undefined}
                          fallback={
                            <span
                              class={`diff-token diff-resolved ${choice() === "old" ? "diff-kept-old" : "diff-kept-new"}`}
                              onClick={() => choose(g.del.id, choice()!)}
                            >
                              {choice() === "old" ? g.del.text : g.ins.text}
                            </span>
                          }
                        >
                          <span
                            class="diff-pair"
                            onContextMenu={(e) => handleContextMenu(e, g.del, g.ins)}
                          >
                            <span
                              class="diff-token diff-delete"
                              onClick={() => choose(g.del.id, "old")}
                            >{g.del.text}</span>
                            <span class="diff-arrow"> → </span>
                            <span
                              class="diff-token diff-insert"
                              onClick={() => choose(g.del.id, "new")}
                            >{g.ins.text}</span>
                          </span>
                        </Show>
                      );
                    })()}
                    {(group as any).ins.space}
                  </Match>
                  <Match when={group.type === "unpaired" && "token" in group}>
                    {(() => {
                      const t = (group as { type: "unpaired"; token: DiffToken }).token;
                      const choice = () => choices().get(t.id);
                      const isDelete = t.kind === "delete";
                      return (
                        <Show
                          when={choice() === undefined}
                          fallback={
                            <span
                              class={`diff-token diff-resolved ${choice() === "old" ? "diff-kept-old" : "diff-kept-new"}`}
                              onClick={() => choose(t.id, choice()!)}
                            >
                              {choice() === "old" ? (isDelete ? t.text : "") : (isDelete ? "" : t.text)}
                            </span>
                          }
                        >
                          <span
                            class={`diff-token ${isDelete ? "diff-delete" : "diff-insert"}`}
                            onClick={() => choose(t.id, isDelete ? "old" : "new")}
                          >
                            {t.text}
                          </span>
                        </Show>
                      );
                    })()}
                    {(group as any).token.space}
                  </Match>
                </Switch>
              )}
            </For>
          </div>
        </div>
        <div class="modal-buttons">
          <button class="btn-cancel" onClick={props.onClose}>
            Cancel
          </button>
          <button class="btn-create" onClick={handleApply}>
            Apply
          </button>
        </div>
      </div>
      <Show when={contextMenu()}>
        <div
          class="context-menu"
          style={{
            left: `${contextMenu()!.x}px`,
            top: `${contextMenu()!.y}px`,
          }}
        >
          <button onClick={handleAddToGlossary}>
            Add to glossary: {contextMenu()!.deleteToken.text} → {contextMenu()!.insertToken.text}
          </button>
        </div>
      </Show>
    </div>
  );
};

export default CleanupModal;
