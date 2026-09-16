# Current three-action production queue

UI version 5.5. Root URL: http://127.0.0.1:8805/

Only the authoritative current scope is displayed. Every current character has
visible body_attack (attack preparation), walk and death columns, not an action
list hidden behind an original-art thumbnail. No other action or historical
navigation is served. Existing jobs, bills, source media and deduplication records
remain untouched on disk; this is presentation cleanup, never deletion.

## Select the current frozen source

Retain the production root and allowed original/output media directories. Use:

```text
--port 8805 --scope-policy current-three-actions --scope-spec ABSOLUTE_CURRENT_SPEC_JSON
```

The exact spec's parent becomes an allowed coverage directory, and its sibling
PREFIX-batch directory is watched automatically for scope.json and batch.json.
The separate PREFIX-scope.json frozen production-intent format is also supported;
its existence never implies that provider inputs or a provider batch are prepared.
Alternatively use the author's precise revision name as scope-policy and pass
the matching PREFIX-batch as a root. The server accepts simple lowercase revision
names so an author handoff does not require another code change.

The source contract is schema-2 characters with required_actions containing only
body_attack, walk and death. Job, sample and queue bindings must match the current
scope SHA256. queue.json, fullqueue.json and *-fullqueue.json are supported, using
scope-bound items with character/action, state, character_png and optional job paths.
Driver ledger.json and production-status.json can bind directly with scope_sha256,
or indirectly with queue plus a verified queue_sha256. They update local preparation
and reuse states independently of actual provider job receipts. Explicit job paths
and provider_coverage_binding bridge intent and later prepared-batch bindings.
Current placeholders come from the actual scope even before job files exist.

Before the new source arrives, the page shows the requested 37 x 3 = 111 plan as
awaiting scope, with zero evidenced targets. It never invents prepared/submitted
jobs or substitutes a retired range. The retired v3, r2, initial v4-three-actions
and six-pilot policies show no current items unless an explicit new spec is supplied.
Old human walk and front-facing pilot media cannot bypass scope fingerprint checks.
An explicit current queue reuse entry may reference a sample_json plus SHA256.
Only hash-matching samples become current previews; review_json and its SHA256,
status and sample hash must match before showing an approved reuse. This does not
rewrite the source job or revive an archive listing. Integration remains separate.
Top-level driver sample/review/decision fields are also supported. A technical
approved_for_reuse decision must match its declared hash, sample, review, frame
count and positive criteria. It is not per-frame user approval or game integration.
For reused material, the provider column says no new submission rather than
suggesting no prior generation occurred. New receipt totals remain job-derived.

Integration_json plus integration_sha256 can reference a canonical per-character
receipt. Per-action sample/review hashes and frame counts must match. Sibling
validation.json and validation-v5-map.json may advance the reported engine/map
validation; mapping check totals come from the validated report, never constants.
Blocked/hold/keycollision states and explicit blocked_reason/hold_reason fields
are consumed from the driver. Missing references alone are not inferred as holds.

## Evidence and visible media

Provider state, local video download, transparent extraction, review and game
integration are independent. Submitted is never complete. A local sample must
contain real, permitted frames before a frame sequence appears. Optional preview_gif
or gif fields in clip/sample metadata expose only registered local media. Reference
upload receipts and local design readiness never imply video submission.

Actual current video/GIF/frame outputs appear directly in the matrix and latest
output preview. If sample source_times_seconds are present for every frame, the
review control synchronizes original-video seeking with transparent frame stepping.
Prices and provider models come from current job records; budgets are not billing.
Missing safe failure reasons are labelled missing rather than exposing provider
error bodies or remote URLs. Existing-image workflows never trigger new stills.

The API and media registry contain only current rows/handles. No historical media
navigation, attempt list, or archived completion section is included. This affects
visibility only; no source or accounting file is moved or removed.

## HTTP and lifecycle

The source directory's seedance-v5/registry-links.json supplements integration
for already matched current clips. Sample, review, integration and validation
hashes, current video hash, frame count and atlas receipt must agree. Technical
approval is not per-frame user approval. Missing entries do not become completed.
Only registered local GIFs are exposed, not raw review HTML or game config.

- `/`: version-5.5 current-only HTML, without a query requirement.
- `/api/progress`: schema_version 1, ui_version, scope_revision, evidence-derived
  current counts, sources, warnings, rows and opaque media handles.
- `/media/<opaque-id>`: permitted local PNG/JPEG/WebP/GIF/MP4/WebM with byte ranges.

Responses are no-store/no-cache and include X-Progress-Process-Id,
X-Progress-Scope and X-Progress-View-Version. The page refuses API downgrades to an
old process. Windows uses exclusive socket binding; an occupied port fails instead
of silently sharing an endpoint. Compare the actual HTTP PID with the listening PID.

The UI maintenance task owns only this progress_server.py listener on port 8805.
Before stopping it, verify the listening PID and exact repository script plus
port in its command line. Unknown owners remain untouched. Use a tool-managed
exec session; never stop the independent 8804 service or generation workers.
No paid/provider calls occur here.

Execution ledger/status job paths take precedence over copied preparation records,
even when those copies retain valid bindings and newer directory timestamps.
The compact first section shows only current jobs with actual external receipts,
with provider, download and extraction states separately. Verified reuse does not
increase these receipt counts or become the default hero. A canonical global halt
is displayed separately from completed paid jobs and unsubmitted pending items.

Python 3.10+ standard library only. Loopback-only binding, Host/Origin checks and
restrictive CSP remain in force. No raw jobs, requests, signed URLs, credentials,
config/database files, arbitrary paths or directory listings are served. Media
must resolve within explicitly allowed roots. Windows JSON reads share READ,
WRITE and DELETE, avoiding producer rename locks. Scans are bounded and retry
incomplete records every three seconds without writing any production state.
