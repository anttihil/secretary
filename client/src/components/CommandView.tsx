import { Show } from "solid-js";
import type { Component } from "solid-js";
import type { Result } from "../types";
import StatusBar from "./StatusBar";
import ResultList from "./ResultList";

interface CommandViewProps {
  results: Result[];
  status: string;
  isRecording: boolean;
  onRecord: () => void;
  onStop: () => void;
}

const CommandView: Component<CommandViewProps> = ({
  results,
  status,
  isRecording,
  onRecord,
  onStop,
}) => (
  <div class="command-view">
    <h1>Secretary</h1>
    <div class="controls">
      <Show
        when={!isRecording}
        fallback={
          <button class="btn-stop" onClick={onStop}>
            Stop
          </button>
        }
      >
        <button class="btn-command" onClick={onRecord}>
          Record Command
        </button>
      </Show>
    </div>
    <StatusBar status={status} isRecording={isRecording} />
    <ResultList results={results} />
  </div>
);

export default CommandView;
