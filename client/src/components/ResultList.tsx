import { For, Show, createSignal } from "solid-js";
import type { Component } from "solid-js";
import type { Result } from "../types";
import { addToGlossary } from "../api";
import GlossaryModal from "./GlossaryModal";

interface ResultListProps {
  results: Result[];
}

const TranscriptWord: Component<{
  word: string;
  onClick: (word: string) => void;
}> = (props) => {
  const [added, setAdded] = createSignal(false);

  return (
    <span
      class={`transcript-word${added() ? " added" : ""}`}
      onClick={() => props.onClick(props.word)}
      ref={(el) => {
        // expose setAdded via data attribute for parent to trigger animation
        (el as any).__setAdded = setAdded;
      }}
    >
      {props.word}
    </span>
  );
};

const ResultList: Component<ResultListProps> = (props) => {
  const [selectedWord, setSelectedWord] = createSignal<string | null>(null);
  let clickedEl: HTMLElement | null = null;

  function handleWordClick(word: string) {
    setSelectedWord(word);
  }

  async function handleAdd(transcriptWord: string, correctWord: string) {
    try {
      await addToGlossary(transcriptWord, correctWord);
      setSelectedWord(null);
      // Trigger added animation on the clicked element
      if (clickedEl && (clickedEl as any).__setAdded) {
        (clickedEl as any).__setAdded(true);
        setTimeout(() => (clickedEl as any).__setAdded?.(false), 1500);
      }
    } catch (e) {
      console.error("Failed to add to glossary:", e);
    }
  }

  return (
    <>
      <div class="results">
        <For each={props.results}>
          {(item) => (
            <div class="result-item">
              <div class="timestamp">
                <span class="result-time">{item.time}</span>
              </div>
              <Show when={item.transcript}>
                <div class="transcript">
                  <span class="transcript-label">Transcript</span>
                  <br />
                  <span class="transcript-text">
                    <For each={item.transcript!.split(/(\s+)/)}>
                      {(part) =>
                        part.trim() ? (
                          <TranscriptWord
                            word={part}
                            onClick={(word) => {
                              clickedEl = document.querySelector(
                                `.transcript-word:hover`,
                              );
                              handleWordClick(word);
                            }}
                          />
                        ) : (
                          part
                        )
                      }
                    </For>
                  </span>
                </div>
              </Show>
              <div class="text">
                <span class="transcript-label result-label">
                  {item.transcript ? "Cleaned" : ""}
                </span>
                <br />
                <span class="result-text">{item.result}</span>
              </div>
            </div>
          )}
        </For>
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

export default ResultList;
