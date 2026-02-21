import type { Component } from "solid-js";

interface StatusBarProps {
  status: string;
  isRecording: boolean;
}

const StatusBar: Component<StatusBarProps> = ({ status, isRecording }) => (
  <div class="status">
    <span class={`recording-dot${isRecording ? " active" : ""}`} />
    <span>{status}</span>
  </div>
);

export default StatusBar;
