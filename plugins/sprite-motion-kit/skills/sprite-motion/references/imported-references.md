# Preserve an existing 3D reference

Use this when the user has approved an actual rig/animation rendered in Blender,
Godot or another 3D tool. The host authors or adapts the requested five actions
on that rig, renders them, and exports projected landmarks. Do not replace its
walk with a newly computed simplified skeleton merely to fit schema 2.

Prepare with `motion.py prepare --character CHARACTER.png --reference-bundle bundle.json --out JOB --background-mode magenta`.

The bundle is JSON with schema 1, source_description, reuse_reason,
source_asset_sha256 (the original 3D asset hash), character_analysis
(anatomy, mass_and_balance, equipment) and an actions mapping. Each action has:

- guide, reference, landmarks: files relative to the bundle directory.
- columns, rows, count, tile: fixed guide grid and cell size.
- seconds, loop, phases: exact ordered sampling. Loop samples omit phase 1;
  non-looping actions may include phase 1 so the final corpse/landing is held.
- origin: fixed cell-local x/y; floor_y: the projected ground coordinate.
- reference_layout: tile, columns, count for the full playback atlas.
- design: intent, support_and_contact, phases, end_state, describing this character.

Landmarks JSON contains `frames` (one dictionary of named x/y joint positions per
guide cell) and `edges` (pairs of names forming directed limb segments). Obtain
these positions by projecting the actual animated 3D joints through the same
camera used to render the images. Do not invent them or infer them from a
different rig. Character pose observations are separately measured on the
generated pixels, never copied from these reference coordinates.

Review the reference through its rendered playback; `review-reference` accepts
the same five observations as custom-plan jobs. Its input hashes cover bundle,
character, guide, full playback and landmarks. A change invalidates the job.
Only then read the emitted action request, pass the full guide and character to
the image tool, and generate ONE complete sheet for that action. Prepare all
requested actions before selecting which one to run first.

Magenta mode deliberately requests RGB solid-key images and extracts the key
to alpha during pack. Alpha mode expects genuine transparency. No white or
checkerboard removal is guessed from brightness; that could erase ivory bones,
silver weapons or clothing. Neither mode can guarantee that a model follows its
request. Rejected source art remains a draft, not a finished character.

The registration gate fits one scale over the whole sequence and removes only
constant landmark offsets for differing body proportions. Changing frame
translations are rejected; output packing uses a single canvas transform.
This is a diagnostic constraint, not automatic anatomy recognition or a promise
that all generated poses will be natural.
