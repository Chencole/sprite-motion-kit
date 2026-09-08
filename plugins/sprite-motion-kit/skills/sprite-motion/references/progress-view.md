# Live production evidence view

Current UI revision: **3.1**, at `http://127.0.0.1:8805/?v=3.1`.
Version-2 pages automatically detect this API version and reload. The top live
task strip counts actual batch video jobs with `external_job_id`, completed jobs,
`submit.lock` files awaiting receipts, prepared jobs and unknown submission receipts
separately. It does not trust queue summary state. Recursive scanning includes
`batch-01/*-veo/job.json`. A dedicated playable-results panel surfaces bound
transparent samples such as `human-0-walk-transparent/sample.json` even while a
different submitted task is selected. Windows JSON reads use
`FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` to avoid preventing
producer atomic renames. No locks, jobs or queue records are modified.
The already completed baseline walk is displayed in playable results, separately
from the batch-01 totals. A lock is evidence of a lock, not proof that a live API
call still exists. Unknown receipts are distinct and never imply safe retry.

`scripts/progress_server.py` is a standalone Python 3.10+ standard-library server.
It binds only `127.0.0.1`, observes existing files, and makes no generation, polling,
credential, database, integration, or provider calls. It never writes job state.

```powershell
& 'C:/Users/cheny/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/progress_server.py --port 8805 --root E:/Dev/sprite-motion-kit/work/mxapi-connection-trial-20260908 --root E:/Dev/Duskbone/work/veo-production-20260908 --coverage C:/Users/cheny/Documents/Codex/2026-09-08/sprite-motion-finish-game-assets/outputs/motion-coverage.json
```

Prefer a tool-managed `exec_command` session: launch Python directly and let the
tool yield its session ID. This keeps the server alive without a visible native
window. Record the session ID and complete launch command in the coordinating
chat's `work` directory. Poll that session with `write_stdin`; to reload changed
Python send Ctrl+C only to that owned session and relaunch the recorded command.
`Start-Process -WindowStyle Hidden` was rejected by automatic execution policy in
the coordinating session; do not repeat that launch mode there. An occupied port
fails without stopping its owner. Never stop the independent 8804 review service.

Open `http://127.0.0.1:8805/?v=2`. Version 2 places the current task's real images
and video above its compact status strip, including in a narrow sidebar. Below
it, one existing-art thumbnail per character opens that character's full action
list, with 24-action expansion and search across the complete inventory.
Search spans all registered characters and actions. Historical connection
trials are an explicitly labelled alternate filter and never count as this run.
Filters distinguish production coverage, unbound studies, failures and pending
work. Original art, action start still, original video and transparent frames are
separate players; frame playback supports pause, frame stepping, scrubbing and
speed. Videos support byte ranges and native seeking. Playback is opt-in.

## Evidence and semantics

- Refresh every three seconds; missing configured roots and coverage files are
  watched and explicitly shown as not yet present.
- `production-status.json` contributes the current action, explicit preparation
  phase and `new_generation_submitted=false`. A character ID is preferred; the
  named reference directory supplies a fallback when no ID is present.
- `reference_upload` job receipts have a separate interpretation: `verified`,
  matching source/remote SHA256 and a matching local verification file indicate
  uploaded identity art. Matching original-image bytes associate the receipt with
  that character's actions. Uploading identity art never implies new generation,
  action-specific first-frame submission, or review. No remote receipt URL is
  exposed. Add the original reference directory with `--media-root` when needed.
- `scope.json` and `motion-coverage.json` inventory `characters` as a mapping or
  list, and each character's `required_actions`, `action_map` or `actions`.
  Inventory is never treated as evidence of submission.
- Duskbone coverage exports with `profiles` and `requirements` are also supported:
  `batch_character` plus `action_id` groups shared character tasks while preserving
  searchable profile display names. Existing published coverage is labelled as
  existing publication, not a new production run or visual acceptance. All rows
  remain searchable; character galleries replace the old long default action-card
  list. The selected character's actions expand 24 at a time.
- `queue.json` can contain `items`, `jobs`, `tasks` or `queue` entries, using
  character/action IDs and optional job-directory and existing-image references.
  Queue entries are preparation evidence only; real job state proves submission.
  `existing_image` mode displays original art directly followed by Veo and the
  extracted transparent animation, without introducing a first-frame request.
  Production inventory without a historical still attempt defaults to this mode;
  original still attempts remain inspectable as actual historical evidence.
  The viewer never submits, resubmits, purchases or generates anything.
- `job.json` supplies state and local results. Only selected fields of its known
  sibling `request.json` are consumed: model, kind and workflow binding. Raw
  requests, prompts, supplier responses, remote URLs and credentials are not sent
  to the browser. `action-design.json` binds character/action and proves only that
  a design record exists. The `action_still` phase separates start stills from art.
- `still-review.json` plus `workflow_review` indicates a recorded first-frame
  review. Recorded review passes are labelled as requiring workflow freshness
  checks; the viewer does not certify current hashes or visual quality.
- Root-level `CHARACTER-ACTION-still-review.json` reports are associated by
  result hash or their exact character/action name. Explicit false checks mark
  first-frame review failed and show sanitized concrete notes. A positive report
  outside the job never becomes an approved workflow review. The production
  status phase `first_frame_review_failed` also displays failure. Generated images
  stay visible on failure; image `succeeded` never means approved. Standalone
  `*-design.json` records contribute authored design status without rewriting jobs.
- Multiple bound attempts are ordered by job-directory creation time. Current
  stage and media follow the newest still/video attempt. Prior image attempts and
  their rejected reports remain under Attempt History, with safe image links.
  A historical rejection never marks the next submitted attempt failed. Reports
  carrying result hashes must match an actual local image; an old report cannot
  be attached to another attempt merely by its character/action name.
- `sample.json` provides original video, character reference, exact frame list,
  duration, source timestamps, loop flag, draft, user acceptance and integration
  flags. All listed local frames must exist before the sequence is exposed.
  Duplicate sample copies are collapsed by source hash, action and interval.
  Unbound studies can be associated with a video job using the actual video hash,
  never by guessing an action from a file name.
- `batch.json` review checks are displayed as recorded reviews, not a fresh
  production acceptance. `game_assets_replaced` is a recorded integration claim,
  never inferred from a completed video or export. No full-character completion
  is asserted by this viewer.
- Evidence modification time is separate from dashboard refresh time. A waiting
  supplier job stays waiting until another process persists its updated state.
  Failure bodies are not exposed, since supplier errors can contain credentials.

## Local media boundary

Only known referenced PNG/JPEG/WebP/GIF/MP4/WebM files within configured roots,
coverage-file parents, or explicit `--media-root` directories can be served.
Media outside those roots remains unavailable; add the smallest intended media
directory explicitly if a character reference lives elsewhere. Symlink targets
must remain inside allowed roots. UNC/remote references, SVG, HTML, arbitrary
files, directory browsing, raw JSON endpoints and query-supplied paths are not
supported. Browser media URLs contain opaque registered identifiers.

Responses use no-store, no-referrer, nosniff and a restrictive same-origin CSP.
Host and Origin validation blocks foreign browser origins and DNS rebinding.
The only data API is `/api/progress`, a deliberately reduced public projection.
Its `schema_version` is 1 and `ui_version` is "2", with `updated_at`, `poll_seconds`, `sources`, `warnings`,
`coverage_summary`, `counts`, `labels` and `items`. Each item contains safe IDs,
character/action, group, seven independent stages, opaque local media handles,
evidence file labels and optional upload receipt. `counts.production` counts all
inventory actions, not completed actions. The source batch remains schema 2.
Do not reverse proxy or expose this server publicly.
The page and all API/media responses are `no-store` and carry
`X-Progress-View-Version: 2`. Version-2 clients detect future `ui_version` changes
and reload once with the new version query. An already open pre-versioned client
must be navigated once to `/?v=2`; old JavaScript cannot gain reload logic without
loading the new page.

For the coordinating full roster, additionally pass
`--root C:/Users/cheny/Documents/Codex/2026-09-08/sprite-motion-finish-game-assets/outputs/motion-coverage-batch`
to pick up the schema-2 scope and subsequent batch reviews. Missing directories
can be configured before their producer creates them.

Scans are bounded to ten directory levels, 6,000 directories per root, 4,000
evidence documents and 12 MB per JSON. Config/database/secret directories are
excluded. Partial JSON is retried on the next scan; a failed scan preserves the
last snapshot with a visible warning. Use atomic JSON replacement in producers.
For very large batches supply narrow roots; the page reports scan-limit warnings.
