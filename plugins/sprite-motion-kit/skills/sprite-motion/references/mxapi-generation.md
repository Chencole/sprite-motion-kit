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
Video profiles: `seedance-2.0`, `seedance-2.0-fast`, `seedance-1.0-fast`,
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

The current verified Seedance 2 adapter sends image roles as `reference_image`.
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

## Distribution and verification

Keep runtime jobs, prompt/reference uploads, signed media URLs and credentials out
of the repository. Do not bundle another project's database, configuration or model
weights. Each installer uses their own selected account and credits.

Provider tests use response fixtures; importer tests use local synthetic videos.
They prove request handling and extraction behavior, not current provider availability,
model quality or natural movement. Report separately: connected, submitted, rendered,
extracted, visually reviewed and user-approved. A real image/video round trip is needed
before claiming that generation itself was tested.
