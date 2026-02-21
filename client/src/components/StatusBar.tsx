import type { Component } from "solid-js";

interface StatusBarProps {
  status: string;
  isRecording: boolean;
}

const StatusBar: Component<StatusBarProps> = (props) => (
  <div class="status">
    <span class={`recording-dot${props.isRecording ? " active" : ""}`} />
    <span>{props.status}</span>
  </div>
);

export default StatusBar;
