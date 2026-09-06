---
name: sprite-motion
description: Create game-character walk and death sprite sequences from an existing character image and full-body pose references, then export aligned transparent atlases and an interactive visual review. Use for humanoid pixel-character animation or fixing a walking loop; not for generic video, dragon flight, or automatic art replacement.
---

# Sprite Motion

Turn an existing character into an inspectable sprite-animation job. The bundled mannequin references are strict side profile facing right: one complete alternating walk and one backward fall. This plugin is an authoring workflow, not an animation model or a paid-generation entitlement.

## Run the workflow

Paths below are relative to this skill directory. Use a Python 3.10+ interpreter with Pillow and NumPy. The host agent runs commands; the user need not operate the CLI.

1. Inspect the supplied character. Keep its style, outfit, weapons and anatomy. Match the user's requested direction. The included guide is side view; do not pass it off as front/back or three-quarter animation. Use a compatible reference for other directions or bodies.
2. Create a separate output job:

   `python scripts/motion.py prepare --character CHARACTER.png --out NEW_JOB --name CHARACTER_NAME`

   This copies the character and reference images and writes a request for each action. Add `--actions walk` or `--actions death` for only one action.
3. Inspect both reference images, read the generated request, and use the host's available image-generation/editing tool. Pass the pose guide first and the character image second. Generate an entire action sheet coherently. Built-in image generation is preferred when available. Save the returned original in the job before extraction. No network or model call is hidden in the Python script. If generation is unavailable, report that specific missing capability; do not substitute a video site, purchase credits, or claim generation succeeded.
4. Pack the actual returned sheet, checking its actual grid and transparency:

   `python scripts/motion.py pack --job NEW_JOB --action walk --image GENERATED.png`

   Repeat for death when requested. Actual grid can be specified using `--columns`, `--rows`, `--count`. `--seconds` controls cycle duration. `--phases` accepts normalized frame start times when a loop repair adds poses at uneven intervals. `--hold-from` is a zero-based settled death pose; use only after visual inspection identifies it.
5. Open the job's `review.html` for the user. It is self-contained and works offline. Reference and character share a phase clock. Normal speed, pause, quarter speed, frame stepping across the seam, and one-shot death are available. Inspect the actual moving result and contact sheet before judging quality.

## Animation decisions

- Blue reference leg means near/right; orange means far/left. The first and second halves must use opposite support legs. Their colors are only reference labels. Preserve extra arms, tails and attached equipment on humanoids instead of changing them into an ordinary human.
- Diagnose a loop seam against adjacent phases and the same ground origin. A continuous walk does not stop with both feet together. Do not double-hold the first frame at the end. New in-between drawings must fill the original time interval, not lengthen the final step.
- Do not call crossfading, cutout warping, or duplicate frames a newly generated full walking pose. A pose guide is a visual reference, not a guaranteed hard skeleton constraint. Report rejected frames and remaining visual defects honestly.
- Keep a single scale throughout each action. Death should fall into the character's own full-size corpse and stop; no shrinking, generic corpse substitution, automatic looping or premature fading.
- A technical export never certifies anatomical quality. Check support/swing leg identity, heel/toe movement, head jitter, stable costume/weapon size, transparent gaps and cell cropping. Repair a specific defect and recheck; don't silently batch a failed seed across many characters.
- When the user accepts the seed and requests a roster, reuse reference timing and processing, while generating each distinct appearance. Track pending/generated/packed/reviewed per role. Preserve previous assets until the requested integration is verified. Skip incompatible bodies only with an explicit report.

## Outputs and boundaries

Each job contains the supplied character, pose guides, generation requests, original generated sheets, transparent per-frame PNGs, atlases, clip JSON, contact sheets, and `review.html`. Integration into a game is a separate user-authorized step. The script does not write into game directories or upload assets.

The bundled reference renders derive from Quaternius' CC0 Universal Animation Library. See `assets/QUATERNIUS-CC0.txt` and `references/sources.md`. The source code is MIT; user-supplied artwork retains its own rights.
