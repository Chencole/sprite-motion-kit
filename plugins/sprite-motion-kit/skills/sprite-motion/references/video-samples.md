# Video-first samples

Use this route when the user chooses video generation instead of whole-sheet
image generation. Keep that choice; do not silently return to image sheets or
substitute a playback of old sprite frames as a newly generated video.

The host needs an available video-generation service or a video supplied by the
user. For an existing MXAPI/MyPixelFlow account, the plugin includes a real
[image and Seedance connection](mxapi-generation.md); inspect that route before
claiming that no video tool is available. This plugin does not bundle a video
model, credentials or credits. If no service is connected, ask which existing
service to use and continue local extraction work while waiting. Do not purchase
credits, upload character art to an unrelated provider, or claim generation is
running without a real call.

Use the approved character appearance as the image-to-video input. Request a
fixed right-profile camera, full body/weapon in frame, stable scale, simple keyed
background, no camera movement or motion blur, and several complete consecutive
steps. Character appearance comes from the input; the motion description should
focus on the actual action. A video model may still change limbs, equipment or
camera: inspect its output before choosing the extraction interval.

For walk/run, choose one full two-step cycle with the same anatomical support
foot and compatible velocity at its two boundaries. Do not mistake two similar
silhouettes for a complete loop. Attack/fall/jump intervals include anticipation
and settling as required. Death holds a full-size final body. Different actions
normally use separate clips; choose the set from the game's actual requirements.

Before generating a full character, the AI follows [batch coverage](batch-coverage.md):
inspect that project's state machine, controls, all abilities and weapons,
damage/death/revival and interactions; record sources, derived requirements and
explained exclusions. The AI writes the manifest, without asking the user to
enumerate every action. Give different spells independent action IDs and reviews.
Register all applicable states; a fixed five-action set cannot replace discovery.

```sh
python scripts/video_sample.py --video character-walk.mp4 --ffmpeg /path/to/ffmpeg \
  --out NEW_OUTPUT --character "Character" --action walk --start 1.0 \
  --duration 1.0 --count 8 --loop --background magenta --origin 512 850 \
  --review-notes "Inspected one complete two-step cycle; source camera and floor stay fixed."
```

Coordinates and timing above are examples, not inferred facts about an input.
Supply the actual video-canvas origin. Source alpha or an opaque green/magenta key is
supported; opaque arbitrary scenery requires a separate matte workflow and is
rejected. The importer does not download FFmpeg or remove arbitrary backgrounds.

The command uses an existing FFmpeg executable to inspect actual source timestamps
and select the nearest unique source frame to each uniform target time.
It keeps the original canvas and source order, without frame-wise recentering,
floor alignment, body stretching or optical-flow interpolation. It records output
target and actual sampling times plus original frame indices. A short interval cannot be silently
padded. Loop playback omits the duplicate endpoint; one-shot playback holds its
last extracted frame.

This is a single-action review artifact, not completion of a character's full
action set. Importer tests prove extraction behavior, not natural animation.
Real generated video is required before claiming the new route improves quality.
Keep repository visibility private while that quality remains unverified. Fixed
chroma thresholds remove edge-connected key background without eroding the body.
Compressed video may retain slight color spill; inspect it rather than treating
a successful alpha export as proof of a clean or natural animation.

When a plain key background is trapped in a closed gap between limbs, cloak or
weapon, first check that the character itself contains none of that key color.
Then explicitly use `--key-scope all` to remove those enclosed key pixels with
the same fixed threshold. This must not silently erase matching clothes or eyes;
default `edge-connected` preserves isolated internal colors. The review records
the chosen scope and includes a local copy of the unmodified source video.

### Generated video with black sidebars

Some providers place the square reference inside a wide canvas with black
pillarboxes. Inspect the actual borders across the whole clip. Do not crop down
to the green region: a sword or limb may extend into the black area. For confirmed
fixed sidebars, `--black-sidebars LEFT RIGHT` gives their exact widths in source
pixels. The tool removes edge-connected near-black pixels only inside those
columns, keeps the same canvas, and records these widths. Nonblack extensions
and enclosed dark detail remain. This is not arbitrary background segmentation;
dark outlines merging into a black sidebar may be ambiguous and need visual review.
Leave this option off for videos without those borders.

Source clipping is still an error. A sword already outside the video cannot be
recovered by extraction. When showing the failure for review, `--draft` explicitly
allows edge-touching frames and records their original indices. It labels the
output `video_draft_sample`, displays a diagnostic banner and cannot pass batch
acceptance. Keep anticipation and all faulty frames in the diagnostic interval;
do not hide them by trimming the action. Empty frames and invalid backgrounds
remain errors even in draft mode.

## Include video actions in a complete character

Create the coverage batch first. Add `--batch BATCH --batch-character CHARACTER_ID`
to the extraction command to bind its action to the exact scope requirement and
approved character image. The importer copies and hashes that reference and the
original source video. An optional `--character-image IMAGE` must match the
batch's approved image when bound; standalone samples may also keep a reference.

```sh
python scripts/batch.py attach-video --batch BATCH --character CHARACTER_ID \
  --action ACTION_ID --sample NEW_OUTPUT
python scripts/batch.py status --batch BATCH
python scripts/batch.py review --batch BATCH --character CHARACTER_ID \
  --action ACTION_ID --report ACTUAL_REVIEW.json
python scripts/batch.py finish --batch BATCH
```

Copy current `artifact_hashes` and `coverage_binding` from status into the actual
review report, with the checks described in [batch coverage](batch-coverage.md).
Inspect both the original video and transparent animation, including identity,
equipment, the exact skill/state gesture and timing. Technical alpha/canvas checks
do not prove motion quality. Reusing one source interval or identical exported
frames under two names cannot fulfill two independent requirements.

Each extracted clip remains an `action_study`; only the batch can establish full
coverage after every registered action has a current review. Missing a second
spell or a required base state blocks finish. Old unbound clips require local
re-extraction with binding before attachment, not another paid video generation.
