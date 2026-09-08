# MXAPI image and Seedance connection

Use this connection when the user chooses their existing MXAPI account, including
the encrypted account stored by MyPixelFlow. The host AI executes the CLI; the user
does not need to write requests. This is a provider connection, not a bundled model
or an assertion that generated motion will always be correct.

## Account selection and read-only connection check

Requires Python 3.10+. Existing MyPixelFlow credentials additionally need Node.js
with its built-in crypto module. No Node packages are installed. The SQLite database
and encryption configuration are read locally; the decrypted key stays in process
memory. Never print or copy its value into commands, reports, job files or Git.
The old project is not modified or launched. A nonempty WAL stops the read rather
than using stale data. If several active accounts exist, select the intended
credential explicitly with `--credential-id`.

All paths below are examples. Resolve the user's actual project and runtime.
Global account options precede the subcommand:

```sh
python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow --node /path/to/node check
python scripts/mxapi.py models
```

`check` calls only the quota endpoint and reports available points without creating
a generation. `models` lists implemented request profiles; it is not a live account
entitlement or pricing lookup.

Other installations can supply both `MXAPI_API_KEY` and `MXAPI_BASE_URL` through
their existing secret/environment setup. Do not mix an environment key with a
database endpoint or assume a default account. API and media URLs must use HTTPS.
API redirects are refused. Media downloads never carry the provider credentials.

## Prepare, submit once, poll, download

Image profiles: `gpt-image-2`, `seedream-4.5`, `seedream-5.0`, `nano2`.
Video profiles: `seedance-2.0`, `seedance-2.0-fast`, `seedance-2.0-mini`, `seedance-1.0-fast`,
`seedance-1.0-lite-i2v`. Use the user's selected model. Do not silently change model,
drop references, increase duration, buy credits, or retry a paid generation.

If the user prioritizes the cheapest trial, compare their current account pricing
first. MyPixelFlow's existing price table lists the 1.0 Fast 480p profile below
the 2.0 profiles; do not assume the newest Fast model is the cheapest. The CLI
defaults to the selected model's smallest resolution and shortest duration.
Explicitly record the selected model/size/seconds before submission. A request
already submitted cannot be made cheaper by changing its local request file.

1. Write the requested character appearance or action description to a UTF-8 prompt
   file in a private work directory. Prepare a new job; preparation makes no network
   request and consumes no quota.

   ```sh
   python scripts/mxapi.py prepare --model gpt-image-2 --prompt-file character.txt --ratio 1:1 --resolution 1K --job NEW_IMAGE_JOB
   ```

2. Submit only within the user's existing authorization. `--confirm-submit` records
   the caller's decision to make one billable request; it does not demand another
   user confirmation when the current task already authorized this generation.

   ```sh
   python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow submit --job NEW_IMAGE_JOB --confirm-submit
   python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow poll --job NEW_IMAGE_JOB
   python scripts/mxapi.py download --job NEW_IMAGE_JOB
   ```

   Poll existing tasks at bounded intervals (normally 10–30 seconds); do not create
   another job when a response is slow. If submission times out or lacks a task ID,
   state becomes `submission_unknown`; reconcile with provider history. Never
   delete `submit.lock` or create a duplicate to bypass that state. Each job stores
   its request hash, task ID, status and results without the credential.

3. Inspect the downloaded still. Use its returned **HTTPS image result URL** as
   the video's `--reference`. Preserve the requested profile view, style, complete
   body and weapon margins. This reuses the same account's image output directly.

   ```sh
   python scripts/mxapi.py prepare --model seedance-1.0-fast --reference HTTPS_IMAGE_RESULT_URL --prompt-file walk.txt --duration 2 --resolution 480p --ratio 1:1 --job NEW_VIDEO_JOB
   python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow submit --job NEW_VIDEO_JOB --confirm-submit
   python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow poll --job NEW_VIDEO_JOB
   python scripts/mxapi.py download --job NEW_VIDEO_JOB
   ```

   The verified MyPixelFlow transport supplies publicly reachable image URLs.
   Local files/base64 are rejected before job creation: no unverified inline
   transport and no silent text-only fallback. For existing local artwork, use the
   user's existing media publisher with authorization, or another documented host
   image tool that returns a reachable URL. Do not publish art on an unrelated host.

4. Inspect the real video and use [video extraction](video-samples.md). Select a
   complete cycle from observed timestamps, not an assumed interval. MP4 normally
   has an opaque background; request solid green/magenta and explicitly key it
   locally. Arbitrary scenery is not automatically made transparent.

## Endpoint roles and limits

The current Seedance 2 standard/Fast adapters send image roles as `reference_image`.
Seedance 1.0 Fast uses `first_frame` for its single image; using `reference_image`
incorrectly selects unsupported r2v and was rejected by the live provider. Refunded
tasks record both the provider's original point amount and the net zero cost.
Do not claim it locks first/last frames. The Lite I2V adapter supports explicit
`--first-last` with exactly two image URLs, in first then last order. Unsupported
combinations are rejected before a billable call. Model names alone do not prove
the gateway implements every upstream capability.

The CLI keeps explicit model resolution and duration ranges and rejects unsupported
combinations. Even matching start/end pictures do not guarantee two complete steps,
anatomical identity or a seamless loop. Preserve user review before batch replacement.

### Seedance 2.0 Mini

Mini is a separate model profile, selected with `--model seedance-2.0-mini`;
changing `--resolution` does not select or upgrade a model. Its route is
`POST /api/v2/video/seedance2-mini`, fixed by MXAPI to
`doubao-seedance-2-0-mini-260615`. The request omits `model` and uses top-level
`resolution`, `ratio` and `duration`; old text flags such as `--rs`, `--ratio`
and `--dur` are rejected. Poll with the existing `/api/v2/video/task` route.
These fields are sourced from the [Mini API documentation](https://open.mxapi.org/api/docs?id=v2-video-seedance2-mini),
checked 2026-09-08, rather than copied from the Fast profile.

The CLI defaults to **480p and 4 seconds** for a small trial. Supported explicit
resolutions are 480p/720p and durations are integer 4–15 seconds; 1080p/4K are
rejected. The provider's automatic `duration=-1` is deliberately not exposed,
so the requested duration stays explicit. Ratios are 16:9, 9:16, 1:1, 4:3, 3:4, 21:9 and adaptive.
Audio generation is disabled. This image-reference adapter currently supports
at most two images; that is an implementation limit, not a claim about the
provider's complete multimodal capacity.

- No image: text-to-video.
- One `--reference HTTPS_IMAGE_URL`: image-to-video with `role=first_frame`.
- Two references plus `--first-last`: explicit `first_frame`, then `last_frame`.
- One or two references plus `--reference-role reference_image`: explicit image
  conditioning, without claiming an exact first frame. Do not combine this flag
  with `--first-last`.

```sh
python scripts/mxapi.py prepare --model seedance-2.0-mini --reference HTTPS_IMAGE_RESULT_URL --prompt-file walk.txt --resolution 480p --duration 4 --ratio 1:1 --job NEW_MINI_JOB
python scripts/mxapi.py prepare --model seedance-2.0-mini --reference HTTPS_FIRST_FRAME_URL --reference HTTPS_LAST_FRAME_URL --first-last --prompt-file walk.txt --job NEW_MINI_ENDPOINT_JOB
```

Preparation remains local; the normal authorized submit/poll/download commands
above operate on either new Mini job. Do not report a real Mini round trip based
only on request-fixture tests.

Pricing is not hardcoded as a settled bill. On 2026-09-08 the
[public Mini page](https://open.mxapi.org/api-test?id=v2-video-seedance2-mini)
listed T2V/I2V at RMB 0.000023/token (about 249 points for 720p, 16:9, 5 seconds),
V2V at RMB 0.000014/token, and a separate Mini promotion at 55% of list price (5.5折) through
October 7. Its detailed Markdown still listed RMB 0.000028/0.000017 per token.
These public descriptions conflict, so do not promise a final price or assume
how the promotion combines with either table. Report the completed task's actual
`points_cost`, including any refund; a channel's placeholder `points: 0` does
not mean generation is free.

### Veo 3.1 Fast

Select the independent profile `--model veo-3.1-fast`, which sends the exact
MXAPI model name `veo31-fast` to `POST /api/v2/veo/generate`. The
[generation documentation](https://open.mxapi.org/api/docs?id=v2-veo-generate),
checked 2026-09-08, specifies `prompt`, `aspectRatio`, `images`,
`enableExtendImg` and `enableTranslation`. The adapter keeps both switches false;
paid image expansion is not enabled. It does not substitute a higher model tier.

The default ratio is **16:9**, with 9:16 also supported. No controllable resolution
or duration is published for this endpoint, so `--resolution` and `--duration`
are rejected instead of guessing or forwarding Seedance parameters. Record the
actual duration and dimensions after download. One image in `images` is the first
frame; two references require explicit `--first-last` and preserve first/last
order. No references select text-to-video. This profile does not select the
separate multi-image ingredients model. A supplied reference must be a reachable
HTTPS URL, using the same validation as the other adapters.

```sh
python scripts/mxapi.py prepare --model veo-3.1-fast --reference HTTPS_IMAGE_RESULT_URL --prompt-file walk.txt --ratio 16:9 --job NEW_VEO_JOB
```

Preparation is local. Use the existing authorized submit/poll/download workflow.
The [task documentation](https://open.mxapi.org/api/docs?id=v2-veo-task) specifies
`GET /api/v2/veo/task?task_id=...`; `data.status` progresses through
pending/processing/completed/failed, and `data.video_url` holds the completed media.
Submission returns `data.task_id`. Preserve the no-repeat submission marker even
on a timeout or failure; do not automatically create another paid request.

On 2026-09-08 the [public live channel table](https://open.mxapi.org/api/v2/api-channels/ai.veo)
listed **40 points per request** for default-channel `veo31-fast`. This is a dated
price observation, not a promised settled bill. Report each completed task's
`points_cost` and `points_refunded`; the generic query example's 60 points is not
this profile's price. The documented optional image expansion costs an additional
RMB 0.20 and remains disabled by this adapter.

## Distribution and verification

Keep runtime jobs, prompt/reference uploads, signed media URLs and credentials out
of the repository. Do not bundle another project's database, configuration or model
weights. Each installer uses their own selected account and credits.

Provider tests use response fixtures; importer tests use local synthetic videos.
They prove request handling and extraction behavior, not current provider availability,
model quality or natural movement. Report separately: connected, submitted, rendered,
extracted, visually reviewed and user-approved. A real image/video round trip is needed
before claiming that generation itself was tested.
