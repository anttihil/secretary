import { createSignal } from "solid-js";
import { ApiError, createNote, getRecording, retryRecording, uploadRecording } from "./api";
import { deleteRecording, getCachedNotes, getRecordings, saveCachedNote, saveRecording } from "./offlineStore";
import type { LocalRecording, Note, RecordingJob } from "./types";

export type CaptureState =
  | { phase: "idle" }
  | { phase: "requesting_microphone" }
  | { phase: "recording"; title: string; mode: "note" | "command" }
  | { phase: "finalizing" }
  | { phase: "failed"; message: string };

/** Capture and delivery have independent lifetimes: uploading never blocks capture. */
export function createRecordingController(onNotesChanged: (savedNoteId?: string) => Promise<void>) {
  const [capture, setCapture] = createSignal<CaptureState>({ phase: "idle" });
  const [jobs, setJobs] = createSignal<LocalRecording[]>([]);
  const [connected, setConnected] = createSignal(navigator.onLine);
  const [storageError, setStorageError] = createSignal("");
  let recorder: MediaRecorder | undefined;
  let stream: MediaStream | undefined;
  let unsaved: LocalRecording | undefined;
  let timer: ReturnType<typeof setInterval> | undefined;
  let running = false;
  let disposed = false;
  let cancelled = false;

  async function refresh(): Promise<void> {
    const stored = await getRecordings();
    setJobs(stored.sort((a, b) => a.created.localeCompare(b.created)));
  }

  async function applyStatus(local: LocalRecording, remote: RecordingJob): Promise<void> {
    if (remote.status === "succeeded") await onNotesChanged(remote.saved_note_id || undefined);
    await saveRecording({
      ...local, status: remote.status, accepted: true,
      error: remote.error || undefined, nextAttempt: undefined,
      audio: remote.status === "succeeded" ? undefined : local.audio,
      cacheRefreshed: remote.status === "succeeded",
    });
  }

  async function syncUnlocked(): Promise<void> {
    if (disposed || !navigator.onLine) { setConnected(false); return; }
    // Draft creation is idempotent too: a lost response cannot create two notes.
    for (const note of await getCachedNotes()) {
      if (!note.localOnly) continue;
      try {
        const remote = await createNote(note.title, note.directory, note.id, note.body);
        await saveCachedNote({ ...note, ...remote, localOnly: false });
        setConnected(true);
        await onNotesChanged();
      } catch (error) {
        setConnected(false);
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          setConnected(true);
          for (const job of await getRecordings()) {
            if (job.note_id === note.id && !job.accepted && job.status !== "succeeded") {
              await saveRecording({ ...job, status: "failed", error: `Cannot create target note: ${error.message}` });
            }
          }
        }
      }
    }
    const blockedTargets = new Set<string>();
    for (const local of (await getRecordings()).sort((a, b) => a.created.localeCompare(b.created))) {
      if (disposed) return;
      if ((local.status === "succeeded" && local.cacheRefreshed) || local.status === "failed") continue;
      const targetKey = local.note_id || local.id;
      if (blockedTargets.has(targetKey) && !local.accepted) continue;
      if (local.nextAttempt && local.nextAttempt > Date.now()) {
        if (!local.accepted) blockedTargets.add(targetKey);
        continue;
      }
      // A failed draft sync must not upload jobs before their target exists.
      const target = (await getCachedNotes()).find((n) => n.id === local.note_id);
      if (target?.localOnly) continue;
      try {
        let remote: RecordingJob;
        if (local.accepted) {
          try { remote = await getRecording(local.id); }
          catch (error) {
            if (!(error instanceof ApiError) || error.status !== 404) throw error;
            remote = await uploadRecording(local);
          }
        } else {
          await saveRecording({ ...local, status: "uploading" });
          await refresh();
          remote = await uploadRecording(local);
        }
        setConnected(true);
        await applyStatus(local, remote);
      } catch (error) {
        const permanent = error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429;
        setConnected(permanent);
        if (!local.accepted && !permanent) blockedTargets.add(targetKey);
        await saveRecording({
          ...local, status: permanent ? "failed" : local.accepted ? local.status : "awaiting_upload",
          error: error instanceof Error ? error.message : "Connection unavailable",
          nextAttempt: Date.now() + 5000,
        });
      }
    }
    await refresh();
  }

  async function sync(): Promise<void> {
    if (running || disposed) return;
    running = true;
    try {
      // Coordinate tabs; stable IDs still protect uploads if Web Locks is unavailable.
      if (navigator.locks) {
        await navigator.locks.request("secretary-recording-sync", { ifAvailable: true }, async (lock) => {
          if (lock) await syncUnlocked(); else await refresh();
        });
      } else await syncUnlocked();
    } catch (error) {
      setStorageError(error instanceof Error ? error.message : "Offline storage unavailable");
    } finally { running = false; }
  }

  async function start(mode: "note" | "command", note: Note | null): Promise<void> {
    if (!["idle", "failed"].includes(capture().phase) || unsaved) return;
    if (mode === "note" && !note) return;
    const id = crypto.randomUUID();
    const target = note ? { id: note.id, title: note.title } : null;
    setCapture({ phase: "requesting_microphone" });
    cancelled = false;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (disposed) { stream.getTracks().forEach((t) => t.stop()); return; }
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      const recordingStream = stream;
      const recordingRecorder = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        recordingStream.getTracks().forEach((t) => t.stop());
        if (recorder === recordingRecorder) recorder = undefined;
        if (stream === recordingStream) stream = undefined;
        if (cancelled || disposed) { setCapture({ phase: "idle" }); return; }
        const audio = new Blob(chunks, { type: recordingRecorder.mimeType });
        chunks.length = 0;
        if (!audio.size) { setCapture({ phase: "failed", message: "Recording was empty" }); return; }
        unsaved = {
          id, note_id: target?.id || null, title: target?.title || "Voice command",
          mode, audio, created: new Date().toISOString(), status: "awaiting_upload", accepted: false,
        };
        await storeCaptured();
      };
      recorder.onerror = () => {
        setCapture({ phase: "failed", message: "Microphone recording failed" });
        if (recorder?.state === "recording") recorder.stop();
      };
      recorder.start(1000);
      setCapture({ phase: "recording", title: target?.title || "Voice command", mode });
    } catch (error) {
      stream?.getTracks().forEach((t) => t.stop());
      setCapture({ phase: "failed", message: error instanceof DOMException && error.name === "NotAllowedError" ? "Microphone access denied" : "Unable to start microphone recording" });
    }
  }

  async function storeCaptured(): Promise<void> {
    if (!unsaved) return;
    try {
      await saveRecording(unsaved);
      unsaved = undefined;
      setStorageError("");
      setCapture({ phase: "idle" });
      await refresh();
      if ("serviceWorker" in navigator) {
        void navigator.serviceWorker.ready.then((registration) => {
          const manager = (registration as ServiceWorkerRegistration & { sync?: { register: (tag: string) => Promise<void> } }).sync;
          return manager?.register("secretary-recordings");
        }).catch(() => {});
      }
      void sync();
    } catch {
      setStorageError("Could not store audio on this device. Retry saving or download it.");
      setCapture({ phase: "failed", message: "Recording is not yet saved locally" });
    }
  }

  function stop(): void {
    if (capture().phase !== "recording" || !recorder) return;
    setCapture({ phase: "finalizing" });
    recorder.stop(); // onstop runs only after the final dataavailable event.
  }

  const canStart = () => ["idle", "failed"].includes(capture().phase) && !unsaved;

  function cancel(): void { cancelled = true; stop(); }

  async function retry(id: string): Promise<void> {
    try {
      const local = (await getRecordings()).find((j) => j.id === id);
      if (!local) return;
      if (local.accepted) await applyStatus(local, await retryRecording(id));
      else await saveRecording({ ...local, status: "awaiting_upload", error: undefined, nextAttempt: undefined });
      await refresh();
      void sync();
    } catch (error) { setStorageError(error instanceof Error ? error.message : "Retry failed"); }
  }

  async function discard(id: string): Promise<void> {
    const remove = async () => {
      const job = (await getRecordings()).find((j) => j.id === id);
      if (job && (job.status === "succeeded" || job.status === "failed" || (!job.accepted && job.status === "awaiting_upload"))) {
        await deleteRecording(id);
        await refresh();
      }
    };
    if (navigator.locks) await navigator.locks.request("secretary-recording-sync", remove);
    else await remove();
  }

  async function download(id?: string): Promise<void> {
    const job = id ? (await getRecordings()).find((j) => j.id === id) : unsaved;
    if (!job?.audio) return;
    const url = URL.createObjectURL(job.audio);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${job.title}-${job.id}.${job.audio.type.includes("mp4") ? "m4a" : "webm"}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const online = () => { setConnected(true); void sync(); void onNotesChanged(); };
  const offline = () => setConnected(false);
  const workerMessage = (event: MessageEvent) => {
    if (event.data?.type === "recording-sync") { void refresh(); void sync(); void onNotesChanged(); }
  };

  async function initialize(): Promise<void> {
    try {
      await refresh();
      window.addEventListener("online", online);
      window.addEventListener("offline", offline);
      navigator.serviceWorker?.addEventListener("message", workerMessage);
      timer = setInterval(() => { void refresh().catch(() => {}); void sync(); }, 3000);
      void sync();
      void navigator.storage?.persist?.();
    } catch (error) { setStorageError(error instanceof Error ? error.message : "Offline storage unavailable"); }
  }

  function dispose(): void {
    disposed = true;
    if (timer) clearInterval(timer);
    window.removeEventListener("online", online);
    window.removeEventListener("offline", offline);
    navigator.serviceWorker?.removeEventListener("message", workerMessage);
    stream?.getTracks().forEach((t) => t.stop());
    if (recorder?.state === "recording") recorder.stop();
  }

  return { capture, canStart, jobs, connected, storageError, start, stop, cancel, retry, discard, download, storeCaptured, initialize, dispose, sync };
}
