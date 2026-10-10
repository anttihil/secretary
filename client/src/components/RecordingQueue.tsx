import { For, Show } from "solid-js";
import type { LocalRecording } from "../types";

interface Props {
  jobs: LocalRecording[];
  connected: boolean;
  storageError: string;
  onRetry: (id: string) => void;
  onDiscard: (id: string) => void;
  onDownload: (id?: string) => void;
  onStoreCaptured: () => void;
}

const labels: Record<LocalRecording["status"], string> = {
  awaiting_upload: "Saved on device · waiting to upload",
  uploading: "Uploading",
  queued: "Queued on server",
  transcribing: "Transcribing",
  saving: "Saving note",
  succeeded: "Saved",
  failed: "Failed · audio retained",
};

export default function RecordingQueue(props: Props) {
  const pending = () => props.jobs.filter((job) => !["succeeded", "failed"].includes(job.status)).length;
  const failed = () => props.jobs.filter((job) => job.status === "failed").length;
  const description = () => `${pending()} pending recording${pending() === 1 ? "" : "s"}${failed() ? ` · ${failed()} failed` : ""}${props.storageError ? " · Local save failed" : ""} · ${props.connected ? "Online" : "Offline"}`;
  return (
    <section class="recording-queue" aria-label="Recording queue">
      <details>
        <summary
          class="recording-queue-indicator"
          classList={{ pending: pending() > 0, attention: failed() > 0 || !!props.storageError }}
          aria-label={description()}
          title={description()}
        >
          <span aria-hidden="true">{pending()}</span>
          <Show when={failed() > 0 || props.storageError}><span class="queue-alert" aria-hidden="true">!</span></Show>
        </summary>
        <div class="recording-queue-panel">
        <p class="queue-summary">{description()}</p>
        <Show when={props.jobs.length === 0}><p>No recordings queued.</p></Show>
        <ul>
          <For each={props.jobs}>{(job) => (
            <li class="recording-job" data-recording-id={job.id} data-status={job.status}>
              <div><strong>{job.title}</strong> <small>Dictation</small></div>
              <div class="job-status">{labels[job.status]}</div>
              <Show when={job.error}><div class="job-error">{job.error}</div></Show>
              <div class="job-actions">
                <Show when={job.status === "failed" || job.status === "awaiting_upload"}>
                  <button onClick={() => props.onRetry(job.id)}>Retry</button>
                </Show>
                <Show when={job.audio}><button onClick={() => props.onDownload(job.id)}>Download audio</button></Show>
                <Show when={job.status === "failed" || job.status === "succeeded" || (!job.accepted && job.status === "awaiting_upload")}>
                  <button onClick={() => props.onDiscard(job.id)}>{job.status === "succeeded" || job.accepted ? "Dismiss" : "Discard"}</button>
                </Show>
              </div>
            </li>
          )}</For>
        </ul>
      <Show when={props.storageError}>
        <div role="alert" class="job-error">{props.storageError}</div>
        <button onClick={props.onStoreCaptured}>Retry local save</button>
        <button onClick={() => props.onDownload()}>Download unsaved audio</button>
      </Show>
        </div>
      </details>
    </section>
  );
}
