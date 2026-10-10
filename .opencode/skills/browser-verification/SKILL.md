---
name: browser-verification
description: Verify Secretary features end to end in a real browser and check for regressions after changes to its SolidJS UI, notes APIs, recording, WebSocket processing, or local AI integration. Use when implementing user-facing features, fixing browser bugs, or asked to smoke test or validate the app.
---

# Secretary browser verification

Validate the user's workflow through the actual browser, running frontend, and
backend. A successful build, an API response, or a screenshot alone does not
prove a feature works. Finish with observable assertions and a coverage report.

## 1. Establish scope and tooling

1. Read the requested behavior and the working diff, including uncommitted
   changes. Identify the changed workflow, adjacent workflows, and likely failure
   modes. Do not treat current implementation behavior as the specification when
   it conflicts with the user's request.
2. Re-read relevant source before testing; this skill is a baseline, not a frozen
   specification. Start with `client/src/App.tsx`, relevant components,
   `client/src/api.ts`, `main.py`, `config.py`, and `client/vite.config.ts`.
3. Use an available browser automation tool (such as Playwright MCP). If none is
   available, use a temporary Playwright script through the shell. Browser tools
   are not supplied by this skill. Do not claim to have used unavailable tools.
4. For a Python Playwright fallback, run these from the repository root:

   ```bash
   uv run --with playwright python -m playwright install chromium
   uv run --with playwright python /tmp/opencode/secretary-verification/verify.py
   ```

   Create the script with file-editing tools first, implementing the selected
   scenarios with `playwright.sync_api` or `playwright.async_api`. Use the existing
   browser if possible. If installation or browser launch is blocked, report the
   blocker rather than replacing browser verification with HTTP checks.
5. Record acceptance criteria before exercising the feature: initial state,
   user actions, visible result, persisted result, and cancellation/error result.
   Use `references/regression-matrix.md` to select adjacent coverage.

## 2. Run current code against isolated data

Use a new absolute temporary directory outside any Git repository for notes.
`main.py` automatically runs Git add/commit/push when `NOTES_DIR` is inside a
repository; even the default project `notes/` can trigger this. Keep all test
notes, folders, imports, and glossary entries in the temporary directory.

Example setup (verify `/tmp/opencode` exists before creating directories):

```bash
ls /tmp/opencode
mkdir -p /tmp/opencode/secretary-verification
mktemp -d /tmp/opencode/secretary-notes.XXXXXX
```

Use the actual path returned by `mktemp`, not a literal placeholder. Reuse it
throughout the run and record it in the report. It must not have a Git ancestor.
Use unique titles such as `E2E <run-id> source` to avoid timestamp-name collisions.

For production-like verification, build the latest UI and start the backend:

```bash
make build
NOTES_DIR=/tmp/opencode/secretary-notes.ACTUAL uv run fastapi run main.py --host 127.0.0.1 --port 8000
```

Start long-running processes using the harness's background-process facility or
a shell background process with captured logs and PID. Wait for readiness; do
not let a foreground server block the verification session. Choose another port
if needed, and use that port consistently in the browser. Do not stop an existing
user-owned service. Confirm `/api/notes`, `/api/settings`, and the browser's
WebSocket are reachable before testing.

For iterative frontend development, start `npm run dev` with `workdir=client`
and open the actual Vite URL. Its `/api` and `/ws` proxies currently target
backend port 8000. A backend on another port requires a matching proxy setup;
simply changing the browser URL does not fix the proxy. Finish with the built
UI served by FastAPI for changes involving builds, asset caching, or deployment.

Prerequisites:

- Python dependencies: `uv sync`; frontend dependencies: `npm ci` in `client/`
  when missing or out of sync with its lockfile.
- Local startup requires `LLM_MODEL_PATH` and loads Whisper plus the GGUF model
  during import. Check prerequisites without printing `.env` secrets. Model
  downloads/startup may take time; retain server logs for diagnosis.
- `settings.json` is stored at the repository root, independently of
  `NOTES_DIR`, and overrides Whisper environment settings. If testing settings
  writes, preserve its original content (or original absence) and restore it
  afterward. Do not silently change the user's models or production settings.
- Microphone capture requires a secure origin: localhost HTTP or HTTPS.
  Chromium needs support for `audio/webm;codecs=opus`.

There is currently no built-in mock backend or E2E runner. Do not invent commands
such as `npm test` or an `AI_CLIENT=mock` option. If real AI cannot run, explicitly
mark dependent checks blocked. For frontend-only checks, a temporary test-only
mock can be used, but report exactly which HTTP/WebSocket boundaries were mocked.

## 3. Execute and assert browser workflows

Use a fresh browser context. Run the changed feature's full happy path and an
appropriate cancellation/error path, plus the baseline and adjacent scenarios
from the regression matrix.

- Prefer roles, labels, and visible text. The current app also has clickable
  `div`/`span` elements and unlabeled icon controls; use narrow, source-backed
  selectors where necessary. Desktop and mobile controls can share labels, so
  scope to visible containers rather than using an arbitrary first match.
- Perform the action under test through the UI. API calls/file fixtures may
  arrange starting data or inspect results, but do not substitute an API call
  for creating, renaming, moving, or deleting through the UI when verifying it.
- The note body is token-rendered, not a textarea or contenteditable editor.
  Seed text via fixtures or `/api/notes/{filename}/append` when arranging a
  non-audio test. Exercise actual context menus for tag/link/glossary operations.
- Wait for specific visible states and matching responses; use bounded assertion
  retries instead of arbitrary sleeps. Use longer, explicitly bounded timeouts
  for AI jobs. Readiness, recording, queued processing, completion, and saving
  are distinct states.
- For each mutation, assert the UI result and an independent persisted result
  using a backend read or the temporary note file. Reload the page, reopen the
  note from the sidebar, and verify it again. Current selection does not persist
  across reload, so don't expect the note to reopen automatically.
- Capture browser console errors, uncaught page exceptions, failed network
  requests, unexpected HTTP errors, and relevant server errors. Several handlers
  swallow failures; a closed modal does not prove the mutation succeeded.
- Inspect screenshots for layout/interaction issues at approximately 1440×900
  and 390×844. Check scrolling, sidebar overlays, dialog visibility, clipped
  context menus near viewport edges, and access to record/stop controls.
  Wait for CSS transitions to finish (check element bounds or animations);
  removing an overlay does not mean the sidebar has finished sliding away.
- A mobile viewport verifies responsive layout, not actual mobile microphone,
  codec, or long-press support. State when those require a physical device.

## 4. Verify audio without bypassing the pipeline

For recording-related changes, exercise:

`UI Record → getUserMedia → MediaRecorder → Stop → IndexedDB → multipart POST
/api/recordings → queued → AI processing → server save → succeeded → reload`.

For Chromium automation, launch with a known spoken WAV fixture:

```python
browser = playwright.chromium.launch(args=[
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--use-file-for-fake-audio-capture=/absolute/path/to/spoken-fixture.wav",
])
context = browser.new_context(permissions=["microphone"])
```

The fixture must contain intelligible speech with a documented expected phrase;
fake microphone silence alone cannot verify transcription. Allow enough capture
time for the phrase before clicking Stop. Assert nonempty audio transfer,
eventual completion, expected semantic content, no duplicate append, and saved
content after reload. Do not require byte-exact probabilistic AI output.

Important implementation details:

- Create/select a note before normal dictation; the current frontend does not
  automatically create a note from note-mode recording.
- `MediaRecorder.stop()` flushes its final chunk asynchronously; the frontend
  stores the Blob from `onstop`. Short recordings are especially important for
  detecting dropped final chunks.
- Correlate HTTP jobs by recording ID; assert `succeeded` and persisted content.
  Recordings are dictation-only; unsupported modes must be rejected.
- Chromium loops fake audio files. Pad speech with silence beyond the capture
  duration before asserting one occurrence; repeated fixture speech is not a
  duplicate save.
- Playwright may return `None` for multipart `request.post_data_buffer`. Observe
  FormData mode and Blob size with a pass-through `fetch` wrapper, or inspect
  backend job/log evidence; do not assume the raw request body is available.
- Test permission denial in a separate browser without
  `--use-fake-ui-for-media-stream` (it can override context permissions). CDP
  `Browser.setPermission` uses descriptor name `microphone`, not `audioCapture`.
  Inspect the actual exception: headless Chromium may return `NotSupportedError`
  rather than `NotAllowedError`; report the error path actually exercised.
  Assert usable controls and no unexpected note mutation.
- Test disconnect/reconnect and failed processing when relevant. Do not mistake
  an expected injected error for an unrelated application exception.

Injecting a WebSocket completion or mocking AI only checks behavior downstream of
that boundary. Report it as mocked UI/integration coverage, not real audio E2E.

## 5. Diagnose, reverify, and report

When a check fails, retain its reproduction steps and evidence, identify the
first failing boundary, and fix within the requested scope. Rerun the failed
workflow and its affected adjacent regressions after the fix. Do not weaken an
assertion just to make it pass. Distinguish pre-existing defects from regressions
using a baseline run when needed; preserve the user's work when comparing code.

Use source checks appropriate to changed code alongside browser verification:

- Python: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`.
- Frontend: `npm exec tsc -- --noEmit` in `client/`, and `make build`.

Keep evidence in `/tmp/opencode/secretary-verification/` (use per-run subfolders
for repeated runs): screenshots, Playwright trace if supported, browser/server
logs, and the temporary script. Avoid putting real notes or secrets in evidence.
Stop only processes started by this run and restore any modified settings.
For repeatable high-value cases, follow an existing E2E setup if one is added
later; add durable tests when requested or warranted by the implementation task.

Final report:

| Scenario | Environment / data | Result | Evidence |
| --- | --- | --- | --- |
| Changed workflow | Real backend, desktop | PASS / FAIL / BLOCKED | Assertions and artifact paths |
| Adjacent regression | Real backend, mobile viewport | PASS / FAIL / BLOCKED | Assertions and artifact paths |
| Audio pipeline | Real AI or explicitly named mocks | PASS / FAIL / BLOCKED | Persisted result / blocker |

Include URLs, executed commands, selected scenarios, defects, and untested areas.
State whether the backend and AI were real or mocked. Never describe unexecuted
checks as passing, or claim that a finite smoke test guarantees no regressions.
