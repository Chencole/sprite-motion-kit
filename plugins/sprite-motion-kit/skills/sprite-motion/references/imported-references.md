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
Reference review leaves requests locked until generation-check passes. Prepare
all requested actions before selecting which one to run first.

## Controls before generation

Inspect the actual provider schema. Write an adapter JSON containing `name`,
`evidence` (where its available schema was inspected), `parameters` (real argument
names), `supported_sizes` (confirmed width/height pairs), and `canvas_binding`.
Binding is either `{"kind":"size_string","parameter":"size"}` or
`{"kind":"width_height","width":"width","height":"height"}`. These are
formats, not a claim that any particular provider exposes those parameters.

Run `motion.py generation-check --job JOB --adapter ADAPTER.json`. It validates
the complete action set before writing any request. Unsupported sizes, missing
dedicated controls, or passing size as prompt text are rejected without changing
existing outputs. A prompt-only adapter must record that limitation and stop;
do not invent a size parameter or repeatedly generate until one looks right.

On success each action receives a generation packet with actual tool arguments,
the full-sheet prompt, ordered references, common origin and baseline, input
hashes and no automatic retry. Pass the tool arguments to the corresponding
provider and both images to its reference input. Never convert the structured
size control back into prose. Generate one full sheet per action.

Canvas controls only constrain dimensions. Grid contents, footsteps, shield
attachment and identity are still model outputs unless the provider exposes
actual controls for them. The plugin does not manufacture those capabilities.
An adapter is a host-supplied description; record honest evidence, not a guessed
capability or a guarantee of perfect art.

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


### Explicit diagnostic sample

When the user explicitly requests a single-character preview despite unavailable structured canvas controls, `generation-check --diagnostic` creates diagnostic-only packets with no invented API arguments. This does not relax final export or batch acceptance. Show all requested actions and actual source/crop defects; do not retry automatically or replace game assets. The default production preflight still rejects prompt-only adapters.
