# Secretary regression matrix

Always run the baseline, the changed workflow, and its relevant neighbors. Run
the broader matrix for cross-cutting UI, API, state-management, or release changes.
Record anything selected but blocked as BLOCKED rather than silently omitting it.
Use only isolated test data. Check current source for exact labels and behaviors.

| Area | Browser actions and assertions | Important adjacent checks |
| --- | --- | --- |
| Baseline (every run) | Open current UI; confirm notes list and WebSocket Ready; create a uniquely titled note with `+ New`; open it; insert a tag via body context menu; reload and reopen to confirm persistence. | Empty-note hint; cleanup disabled for empty body; no unexpected console/network errors; desktop and mobile navigation. |
| Titles | Click title, rename and commit; verify title in header/sidebar, new filename from backend, preserved body and created metadata; reload/reopen. Test cancel without mutation. | Both desktop and mobile title controls; note links resolve by title, so check behavior of links to renamed notes against requirements. |
| Folders and moves | Create root/nested folders; create a note in a selected folder; expand/collapse; drag note to a folder and back to root; drag folder to another parent; verify paths and bodies after reload. | Active note remains usable after a move; nested contents move together; collapse state persists; self/descendant drops rejected; conflict handling where affected. |
| Deletion | Right-click sidebar note/folder; cancel confirmation and confirm no mutation; then confirm deletion on fixtures and verify absence after reload. | Active-note state after deletion; folder deletion with open descendant note; no stale selection or subsequent writes to removed files. |
| Tags | Right-click word or empty body, Insert Tag, submit; verify rendering and saved `#tag`; delete via tag context menu and reload. | Insertion position, spacing, modal cancellation, menus near viewport edges; ordinary note text preserved. |
| Note links | Create source and target fixtures; Insert Note Link, search/select target, save; verify `[[Title]]` persisted and click navigates to target; delete link token. | Whitespace, duplicate/missing target titles, target rename/delete behavior according to requested requirements; reload source and target. |
| Glossary | Right-click word, Add to Glossary, enter correction, save; inspect `/api/glossary` or temporary `glossary.txt`; reopen/reload to confirm stored entry. | Cancel, blank input, no unwanted note-body mutation; actual transcription impact only counts when tested with real speech/AI. |
| Cleanup | Start with a nonempty note; Clean up / Clean; wait for preview; cancel and verify original body unchanged; run again, use available diff/edit controls, apply and reload. | Empty-body disabled state, repeated cleanup, error recovery, no duplicate content; correct note receives the result. |
| Dictation | Selected note, spoken microphone fixture, Record then Stop; observe processing, eventual persisted text, reload/reopen; repeat for a second append. | Short capture/final chunk, no duplicate append, permission denied, controls after failure, changing selection during processing when affected. |
| Connection and queue | Observe `/ws` connection and Ready; interrupt the test-owned connection/server and restore; verify reconnect and successful subsequent operation. Observe processing queue during an AI job. | No duplicate saves/listeners after reconnect; pending-job behavior according to requirements; queue polling errors and eventual idle state. |
| Settings | Open Settings; verify real `/api/settings` capabilities and selected values; cancel; if relevant, save a supported configuration, reopen and verify persistence. Restore original settings. | Incompatible values, unsupported backend, 409 while busy, reinitialization failure and usable error state; no accidental model downloads. |
| Import | Seed a legacy markdown fixture plus a compliant note and excluded README/hidden files in temporary notes; Import existing notes, cancel first, then confirm; handle native alert and verify bodies/metadata/renames. | Second run is idempotent; nested paths preserved; excluded files untouched; already-compliant note unchanged. |
| Responsive/layout | Repeat changed workflow at desktop and 390×844; open/close mobile sidebar and overlay; scroll long body/list; inspect dialogs and context menus at edges. | Visible controls receive clicks; overlay does not trap navigation; actual touch/long-press and microphone behavior need separate device coverage. |
| Built assets/cache | `make build`; load UI from FastAPI, reload an existing browser context after a rebuild and assert changed behavior. | Index revalidation, hashed assets load without 404, API/WS same-origin routing; no stale frontend evidence. |

## Fixture strategy

- Prefer UI-created baseline data. For arranging specialized scenarios, APIs or
  file fixtures are fine; label them as setup and still perform tested actions
  in the browser.
- For text-dependent checks, append a recognizable body containing ordinary
  words, a tag, and a link to a uniquely titled target. The UI has no general
  text editor; do not assume the rendered body can be filled.
- For import, create plain markdown files in the isolated notes directory before
  opening the page. Include one nested legacy file, a compliant frontmatter
  fixture, `README.md`, and a hidden-directory file.
- For speech, document fixture phrase, duration, language, and expected semantic
  result. Use supported Whisper language/model settings. Synthesized silence is
  useful for capture failures but is not a positive transcription fixture.
- Before reload, capture the current filename from the response or backend.
  Reopen by title/path afterward; verify old paths disappear after rename/move.
- Screenshots provide visual evidence. Persistence assertions and recorded
  network/console outcomes establish functional evidence.
