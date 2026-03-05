import { createSignal, createMemo, For, Show, Switch, Match } from "solid-js";
import type { Component } from "solid-js";
import { computeDiff, buildResult, type DiffToken } from "../diff";

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

  function chooseGroup(group: ChangeGroup, side: Choice) {
    const next = new Map(choices());
    // Check if toggling off (clicking same choice again)
    const toggling = next.get(group.key) === side;
    const allIds = [...group.dels.map((t) => t.id), ...group.ins.map((t) => t.id)];
    if (toggling) {
      for (const id of allIds) next.delete(id);
    } else {
      for (const id of allIds) next.set(id, side);
    }
    setChoices(next);
  }

  function handleApply() {
    props.onApply(buildResult(tokens(), choices()));
  }

  type ChangeGroup = { type: "change"; dels: DiffToken[]; ins: DiffToken[]; key: number };
  type Group =
    | { type: "equal"; tokens: DiffToken[] }
    | ChangeGroup;

  /** Group tokens: consecutive equals merge, consecutive non-equals merge */
  const groups = createMemo((): Group[] => {
    const toks = tokens();
    const result: Group[] = [];

    let i = 0;
    while (i < toks.length) {
      if (toks[i].kind === "equal") {
        const eqTokens: DiffToken[] = [];
        while (i < toks.length && toks[i].kind === "equal") {
          eqTokens.push(toks[i]);
          i++;
        }
        result.push({ type: "equal", tokens: eqTokens });
      } else {
        const dels: DiffToken[] = [];
        const ins: DiffToken[] = [];
        const firstId = toks[i].id;
        while (i < toks.length && toks[i].kind !== "equal") {
          if (toks[i].kind === "delete") dels.push(toks[i]);
          else ins.push(toks[i]);
          i++;
        }
        result.push({ type: "change", dels, ins, key: firstId });
      }
    }
    return result;
  });

  return (
    <div
      class="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) props.onClose();
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
                  <Match when={group.type === "equal"}>
                    <For each={(group as { type: "equal"; tokens: DiffToken[] }).tokens}>
                      {(t) => <span>{t.text}{t.space}</span>}
                    </For>
                  </Match>
                  <Match when={group.type === "change"}>
                    {(() => {
                      const g = group as ChangeGroup;
                      const delText = () => g.dels.map((t) => t.text).join(" ");
                      const insText = () => g.ins.map((t) => t.text).join(" ");
                      const choice = () => choices().get(g.key);
                      const trailingSpace = () => {
                        const last = g.ins.length > 0 ? g.ins[g.ins.length - 1] : g.dels[g.dels.length - 1];
                        return last.space;
                      };
                      return (
                        <>
                          <Show
                            when={choice() === undefined}
                            fallback={
                              <span
                                class={`diff-token diff-resolved ${choice() === "old" ? "diff-kept-old" : "diff-kept-new"}`}
                                onClick={() => chooseGroup(g, choice()!)}
                              >
                                {choice() === "old" ? delText() : insText()}
                              </span>
                            }
                          >
                            <Show when={g.dels.length > 0 && g.ins.length > 0}>
                              <span
                                class="diff-pair"
                              >
                                <span
                                  class="diff-token diff-delete"
                                  onClick={() => chooseGroup(g, "old")}
                                >{delText()}</span>
                                <span class="diff-arrow"> → </span>
                                <span
                                  class="diff-token diff-insert"
                                  onClick={() => chooseGroup(g, "new")}
                                >{insText()}</span>
                              </span>
                            </Show>
                            <Show when={g.dels.length > 0 && g.ins.length === 0}>
                              <span
                                class="diff-token diff-delete"
                                onClick={() => chooseGroup(g, "old")}
                              >{delText()}</span>
                            </Show>
                            <Show when={g.dels.length === 0 && g.ins.length > 0}>
                              <span
                                class="diff-token diff-insert"
                                onClick={() => chooseGroup(g, "new")}
                              >{insText()}</span>
                            </Show>
                          </Show>
                          {trailingSpace()}
                        </>
                      );
                    })()}
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
    </div>
  );
};

export default CleanupModal;
