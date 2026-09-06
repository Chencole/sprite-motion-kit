---
name: sprite-motion
description: Design custom game-character actions and body rigs from a user's request, render 3D mannequin key-pose references, generate matching character sprite frames with the host image tool, and export transparent atlases with synchronized visual review. Use for attacks, combos, locomotion, jumps, falls, monster actions or sprite-loop repairs; not generic video generation.
---

# Sprite Motion

The AI authors the motion; the local tool renders the reference and packages the resulting art. Do not restrict users to a menu of predefined actions. Infer the requested body, camera, action phases and timing, then create or modify that job's 3D rig and keyframes. A sword combo, six-arm attack, monster collapse and short hop should have different plans when their requirements differ. Do not randomize an approved animation merely to create variation.

Python 3.10+, Pillow and NumPy are required. Paths below are relative to this skill directory. No account, hosted model or paid credits are bundled. The host agent runs commands and uses its available image tool; the user should not have to write joint data or operate the CLI.

## Default workflow: request to custom motion to character

Before posing, the AI must reason about this character's anatomy, apparent mass, balance, mobility, equipment and personality. Record that reasoning briefly in each action's description and turn it into actual keys. Walking and falling are families of motions, not universal clips: a nimble humanoid may have a lighter stride, an armored giant a wider weight transfer, and a heavy creature may buckle, brace, tip onto its flank and settle its tail. Decide which supports fail first and where the body ends up. Keep a full-size settled body for death. These are examples, not prescribed outcomes; infer suitable motions from the user's character and request.

Variations are authored by the AI, not randomly supplied by the renderer. Different characters or requested variants may have different strides, timing and falls; preserve an already approved design unless a change is requested or anatomy requires adaptation. Never call a walk smooth merely because the renderer interpolates it: inspect alternating support, foot contact, weight transfer and the loop seam before applying the character art.

1. Inspect the character and interpret the requested actions. Preserve its style, proportions, limbs, weapons and requested direction. Derive action names and frame counts from the request; multiple attacks can coexist. Ask only when a material choice cannot be inferred. **Before generating, create the required coverage manifest using [batch coverage](references/batch-coverage.md).** Record every requested character/action pair, not merely the action currently being repaired. If the task requests walk, run, attacks/casting and death, list all of those applicable actions per character. Actions remain arbitrary, not a fixed menu; infer appropriate flying, crawling or other actions from the request and anatomy. Run requires its own designed gait when requested, not a faster playback of walk.
2. Read [the motion contract](references/motion-contract.md). Author schema-2 JSON: joint hierarchy, local rotations, root transforms, key times, camera and loop behavior. The AI designs whole-body poses, including anticipation, release/contact, follow-through and recovery as appropriate. Add joints for extra arms, wings, tails and weapon endpoints. Humanoid/quadruped scaffolds are starting topologies, not body restrictions.

   Optional scaffold: `python scripts/mannequin.py create --body humanoid --actions overhead_cut thrust stagger --out PLAN.json`

   This creates neutral keys marked `needs_motion_design`. Edit them into the requested motion. `--example-motion` is opt-in illustrative motion for a few actions, not the default authoring pipeline or a quality guarantee.
3. Validate and render into a new isolated directory:

   `python scripts/mannequin.py validate --plan PLAN.json`

   `python scripts/mannequin.py render --plan PLAN.json --out REFERENCE_DIR`

   Inspect `guide-review.html` and the pose sheets. Check direction, anatomy, support, trajectories and timing. Fix the plan if the mannequin is wrong; do not ask the image model to conceal faulty motion. This is agent inspection, not an automatic user approval request. Set `design_status` to `authored` once the plan has been authored.
4. Prepare a character job using that plan:

   `python scripts/motion.py prepare --character CHARACTER.png --motion-plan PLAN.json --out JOB --name CHARACTER_NAME`

   Preparation requires `character_analysis` and each action's `design` fields from the motion contract, and rejects static scaffolds even if labeled authored. It renders references but withholds generation-request files. Inspect the actual reference playback, then save an observation report using the exact `input_hashes` from `job.json`, per-action checks and concrete notes. Run `python scripts/motion.py review-reference --job JOB --report REPORT.json` to unlock requests. This is the agent's visual inspection, not a user permission step; never fill pass flags without inspecting. A changed plan, character or guide requires a new job and review.

   Read each unlocked request. Pass its custom guide first and character image second to the host image tool. Generate a coherent complete action sheet matching the poses, rather than unrelated standing images. Save the returned original in the job. The plan is a visual guide, not a guaranteed hard constraint on the image model. Tools enforce recorded prerequisites and input identity; they cannot prove the AI reasoned well or that the art looks natural.
5. Inspect actual grid, alpha, anatomy and continuity; pack:

   `python scripts/motion.py pack --job JOB --action overhead_cut --image GENERATED.png`

   Any action ID in the plan is accepted. Grid/count/timing can be overridden after inspection. Custom jobs preserve a fixed reference canvas and origin: do not floor-align jump frames or separately resize a falling body. Repair missing poses or a wrong canvas before import. `--hold-from` holds an inspected settled pose in a non-looping action.
6. Open `JOB/review.html`. Reference and character share timing, with pause, slow playback, frame stepping and replay. Inspect motion and the loop seam, not just successful export. Report remaining visual defects. Attach each job to the batch, record actual exported-art review with current artifact hashes, and run `batch.py status` after each batch of work. Successful generation, reference review or packing is partial progress. **Run `batch.py finish` before claiming the requested set is complete or delivering it as a complete replacement.** It must reject missing or unreviewed actions. Partial previews are allowed when clearly labeled with missing actions; they do not shrink the requirement list. Integrate or publish generated assets only within the requested scope.

## Reuse and compatibility

- Reuse an approved reference when it actually matches the request. Bundled CC0 pure-right-profile walk and backward fall require an explicit `--legacy-reference-reason "why this approved motion fits this character"` instead of `--motion-plan`; omitting both is an error. This compatibility mode only supports walk/death. Do not use it for a request for newly conceived, character-specific motion.
- New attacks, bodies and death directions use custom plans. Do not edit Python to add each action name or feed a human fall to a quadruped just because an old preset is convenient.
- Loop endpoints match; the renderer omits the duplicated endpoint. One-shot actions stop at their last pose. Death keeps a full-size corpse. Blue/orange identify near/far limbs, not costume colors.
- Technical validation does not certify natural movement. Keep one scale, inspect support and transitions, and distinguish generated poses from interpolation or duplicates.
- If image generation is unavailable, reference rendering and export still work locally. Report the missing capability without inventing success or purchasing services.

Procedural renderer/code: MIT. Bundled legacy renders: Quaternius CC0; see [sources](references/sources.md). Supplied character art retains its own rights.
