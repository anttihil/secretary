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

export interface Result {
  transcript: string | null;
  result: string;
  time: string;
}

export interface WsMessage {
  status: "queued" | "complete" | "error";
  job_id?: string;
  mode?: string;
  transcript?: string;
  result?: string;
  message?: string;
}
