export interface NoteListItem {
  id: string;
  filename: string;
  title: string;
  created: string;
  updated: string;
  localOnly?: boolean;
  directory?: string;
}

export interface Note extends NoteListItem {
  body: string;
}

export interface NotesListResponse {
  notes: NoteListItem[];
  directories: string[];
}

export interface MigratedFile {
  original_filename: string;
  filename: string;
  actions: string[];
}

export interface MigrationResult {
  migrated: number;
  skipped: number;
  files: MigratedFile[];
}

export interface Result {
  transcript: string | null;
  result: string;
  time: string;
}

export interface Settings {
  whisper_device: string;
  whisper_compute_type: string;
  whisper_model: string;
  cuda_available: boolean;
}

export interface WsMessage {
  status: "queued" | "complete" | "error";
  job_id?: string;
  mode?: string;
  transcript?: string;
  result?: string;
  message?: string;
}

export type JobStatus = "queued" | "transcribing" | "saving" | "succeeded" | "failed";

export interface RecordingJob {
  id: string;
  note_id: string | null;
  mode: "note";
  status: JobStatus;
  saved_note_id: string | null;
  error: string | null;
  result: { transcript?: string; result?: string } | null;
}

export interface LocalRecording {
  id: string;
  note_id: string | null;
  title: string;
  mode: "note";
  created: string;
  audio?: Blob;
  status: JobStatus | "awaiting_upload" | "uploading";
  accepted: boolean;
  cacheRefreshed?: boolean;
  error?: string;
  nextAttempt?: number;
}
