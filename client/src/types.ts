export interface NoteListItem {
  filename: string;
  title: string;
  created: string;
  updated: string;
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
