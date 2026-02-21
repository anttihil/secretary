import { For, Show } from "solid-js";
import type { Component } from "solid-js";
import type { Result } from "../types";

interface ResultListProps {
  results: Result[];
}

const ResultList: Component<ResultListProps> = (props) => (
  <div class="results">
    <For each={props.results}>
      {(item) => (
        <div class="result-item">
          <div class="timestamp">
            <span class="result-time">{item.time}</span>
            <span class={`mode-tag ${item.mode}`}>{item.mode}</span>
          </div>
          <Show when={item.transcript}>
            <div class="transcript">
              <span class="transcript-label">Transcript</span>
              <br />
              <span class="transcript-text">{item.transcript}</span>
            </div>
          </Show>
          <div class="text">
            <span class="transcript-label result-label">
              {item.transcript
                ? item.mode === "command"
                  ? "Response"
                  : "Cleaned"
                : ""}
            </span>
            <br />
            <span class="result-text">{item.result}</span>
          </div>
        </div>
      )}
    </For>
  </div>
);

export default ResultList;
