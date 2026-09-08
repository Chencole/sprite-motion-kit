# Project-bound Veo action workflow

Use this route after the user selects Veo image-to-video. It prepares requests;
it never submits a paid generation by itself.

## User-selected direct reuse of existing images

When the user selects existing artwork or prohibits new image generation, prepare
the video directly. This route overrides the optional new-start-still sequence
below. It accepts a verified `upload-reference` receipt or a successful downloaded
identity image job that matches the coverage character. It never creates an image
task, demands a still review, or invents a still-review hash.

```sh
python scripts/veo_workflow.py prepare-video \
  --existing-image-job jobs/original-upload \
  --batch jobs/batch --character guard --action death \
  --design jobs/guard-death-design.json --job jobs/guard-death-veo \
  --source-risk-notes "Existing art is reused; its weapon/start pose may differ from this action."
```

Preparation is local. Use the normal explicitly authorized `mxapi.py submit`
command for each video job. The workflow stores `source_mode: existing_image`,
the source identity hashes, coverage binding, design hash and honest risk notes.
Weapon/start-pose conflicts do not block authorized direct reuse. Action-design
semantics, full-interval clearance, alpha extraction and final action review still
apply. `video_sample.py --generation-job` and batch acceptance recognize this
source mode without requiring an action-still review.

## Optional action-specific start stills

Veo treats a supplied image as the first video frame. A generic combat portrait
with a sword already in hand therefore tends to produce walking with the sword
held. Text such as “sheathe the sword” is not a reliable replacement for a
correct first frame.

Keep two separate concepts:

- **identity image**: the approved character appearance stored in the coverage
  batch;
- **action-specific start still**: the same character already in this action's
  exact start pose and equipment state.

Exploration walking may start with a sword fully sheathed and both hands free.
Combat movement may start with the sword ready. An attack may start ready, or it
may explicitly include draw, strike, recovery and re-sheath. Choose from inspected
gameplay evidence, not a universal weapon rule.

## Order when new action-specific stills are selected

1. Inspect the selected project's state machine, controls, abilities, weapons,
   death/revival and interactions. Create the schema-2 coverage batch described
   in [batch coverage](batch-coverage.md). The AI maps every applicable gameplay
   requirement to an independent action; the user does not handwrite a routine
   checklist.
2. Create one action design scaffold. The AI fills its body motion, exact equipment
   lifecycle, normalized phase times, gameplay events, loop/end behavior, effects
   and numeric safe area from project evidence. It then changes `design_status`
   to `authored`.
3. For a local game original, run `mxapi.py upload-reference --image ORIGINAL
   --job UPLOAD_JOB` with the selected account. This preserves the source bytes,
   uploads them to the same provider and downloads the result to verify SHA256.
   Prepare the action-specific still with `--identity-job UPLOAD_JOB`. A successful,
   downloaded identity image job is also supported when that is the approved
   identity. A naked HTTPS URL is rejected because it cannot prove that the
   supplied image is the batch character. Never invent a generated identity job.
4. Submit, poll and download that image through `mxapi.py` only when the current
   task authorizes the billable call.
5. Inspect the actual downloaded still. Create its hash-bound review template,
   record the observed equipment state, mark checks true only when seen, and
   submit the review. A generated image being technically successful is not a
   visual pass.
6. Prepare the Veo job. This is blocked until the current still review proves the
   identity, strict side view, true start pose, equipment state, key background
   and full action clearance.
7. Submit once, poll the same provider task and download the video. Never delete
   a submit marker or create an automatic paid retry.
8. Inspect a complete motion interval and extract it with `video_sample.py`
   using `--generation-job`. The extractor binds the local MP4 to the Veo request,
   action design and coverage requirement. Loop extraction omits a duplicate end
point; a one-shot includes its real final recovery or held pose.
9. Review the transparent frames at normal speed, slow speed and frame by frame.
   Attach and finish the coverage batch only after the action semantics, equipment
   lifecycle, gameplay event, framing and visual quality all pass. If the user
   asked to approve the first sample, do not expand to the roster before that
   approval.

## Commands

Paths are examples. Preparation and templates are local and spend no points.

```sh
python scripts/veo_workflow.py scaffold \
  --batch jobs/batch --character guard --action exploration_walk \
  --out jobs/guard-walk-design.json

# The AI authors the scaffold from the inspected project, then may inspect the
# exact prompts without making a request.
python scripts/veo_workflow.py prompts \
  --batch jobs/batch --character guard --action exploration_walk \
  --design jobs/guard-walk-design.json

python scripts/veo_workflow.py prepare-still \
  --batch jobs/batch --character guard --action exploration_walk \
  --design jobs/guard-walk-design.json \
  --identity-job jobs/guard-identity-image --job jobs/guard-walk-still

python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow \
  submit --job jobs/guard-walk-still --confirm-submit
python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow \
  poll --job jobs/guard-walk-still
python scripts/mxapi.py download --job jobs/guard-walk-still

python scripts/veo_workflow.py still-review-template \
  --batch jobs/batch --character guard --action exploration_walk \
  --design jobs/guard-walk-design.json --still-job jobs/guard-walk-still \
  --out jobs/guard-walk-still-review.json

# After inspecting the downloaded still, the AI fills the template.
python scripts/veo_workflow.py review-still \
  --batch jobs/batch --character guard --action exploration_walk \
  --design jobs/guard-walk-design.json --still-job jobs/guard-walk-still \
  --report jobs/guard-walk-still-review.json

python scripts/veo_workflow.py prepare-video \
  --batch jobs/batch --character guard --action exploration_walk \
  --design jobs/guard-walk-design.json --still-job jobs/guard-walk-still \
  --job jobs/guard-walk-veo

python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow \
  submit --job jobs/guard-walk-veo --confirm-submit
python scripts/mxapi.py --mypixelflow-root /path/to/mypixelflow \
  poll --job jobs/guard-walk-veo
python scripts/mxapi.py download --job jobs/guard-walk-veo

python scripts/video_sample.py \
  --video jobs/guard-walk-veo/result-00.mp4 \
  --generation-job jobs/guard-walk-veo \
  --ffmpeg /path/to/ffmpeg --out jobs/guard-walk-sample \
  --character "Guard" --action exploration_walk \
  --start 1.25 --duration 1.6 --count 16 --loop \
  --background green --origin 640 610 \
  --review-notes "Two complete alternating steps, inspected in the source video" \
  --batch jobs/batch --batch-character guard
```

Use the provider's normal `attach-video`, review and finish commands after
extraction. Keep job folders, signed URLs and generated media outside Git.

## Action design rules

The design uses structured equipment states: `none`, `sheathed`, `ready`,
`attack`, `casting`, `natural`, `dropped` and `recovered`. Each ordered phase has
its own state and gameplay event. Illegal jumps are rejected. Examples include:

- noncombat walk: `sheathed → sheathed` for every phase, hands free;
- ready sword strike: `ready → attack → ready`;
- draw-and-sheathe strike: `sheathed → ready → attack → ready → sheathed`;
- staff spell: `ready → casting → ready`, with the exact spell release event and
  only that spell's allowed effect;
- unarmed movement: `none → none` with no invented weapon;
- creature attack: `natural → attack → natural`, using its actual jaws, claws,
  wings or other anatomy.

Different spells and attacks remain different coverage actions even when they
share a stance. Their ordered phases, release/contact event and allowed effects
must match the actual ability. A renamed generic clip cannot satisfy both.

For loops, the design requires compatible equipment state, hand occupancy,
facing, scale and velocity at the seam, while the final exported frame remains
the frame before the repeated first endpoint. One-shot actions record a recoverable
or holdable final pose and extraction includes that endpoint.

The numeric safe rectangle and clearance apply to the complete body, equipment,
cape and allowed effects. Increasing resolution does not repair a weapon that
left the source canvas. The design must select `green` or `magenta` keying; if
the identity artwork contains that key color, preparation stops so the AI can
author the other mode instead of erasing costume pixels.

Extraction must match the design's `loop` or `one_shot` action kind. Batch
acceptance rechecks this flag, the key background, consecutive full-interval
source indices, the one-shot endpoint and exported foreground clearance. A
death action must retain its settled body instead of being exported as a loop.
Still reviews also bind the provider result URL list by hash; changing the URL
or local pixels after review blocks video preparation. These are local gates,
not provider calls or automatic visual approvals.

## Limits

These gates prevent accidental identity swaps, generic combat still reuse, missing
end poses and unbound extraction. They do not force Veo to draw correct anatomy or
guarantee temporal consistency. A failed visual review remains a failed sample;
the workflow does not automatically spend points to retry it.
