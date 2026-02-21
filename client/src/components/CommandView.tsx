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

const CommandView: Component<CommandViewProps> = (props) => (
  <div class="command-view">
    <h1>Secretary</h1>
    <div class="controls">
      <Show
        when={!props.isRecording}
        fallback={
          <button class="btn-stop" onClick={props.onStop}>
            Stop
          </button>
        }
      >
        <button class="btn-command" onClick={props.onRecord}>
          Record Command
        </button>
      </Show>
    </div>
    <StatusBar status={props.status} isRecording={props.isRecording} />
    <ResultList results={props.results} />
  </div>
);

export default CommandView;
