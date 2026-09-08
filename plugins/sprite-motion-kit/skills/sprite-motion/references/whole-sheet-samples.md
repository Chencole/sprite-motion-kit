# Reusable whole-sheet character samples

Use this route when the user asks to repeat the direct image-tool sample workflow.
The host AI generates artwork; this plugin supplies a repeatable export and review
step. It does **not** bundle an image model, bypass service limits, or guarantee
correct legs, weapons or costumes. No PixelLab or other animation website is needed.

## Author and generate

1. Record the character's style, anatomy, equipment and the actions the project
   actually needs. Do not silently turn a full character into a walk-only study.
   The declared action list may contain multiple attacks, casting, crawling, etc.
2. Generate complete ordered action sheets using the host image tool. Keep the
   character, camera, body scale, row floor and nominal cell origins consistent.
   Use an approved character as a style reference only when appropriate. Do not
   copy its failed poses or independently generate every frame.
3. Describe complete action phases: contact, compression, passing, lift, opposite
   contact for a two-step walk; anticipation, release and recovery for an attack;
   full-size settling for a death. Equipment remains attached to the same hand.
   A loop's last frame advances into the first; it need not duplicate the first.
4. Ask for actual alpha. If the returned background is opaque/checkerboard, do not
   call it transparent. A separately authorized background edit may produce a
   uniform magenta key, then local extraction produces RGBA. Record that extra
   generation call. Characters containing magenta require actual alpha instead.
5. Inspect the returned image before declaring its grid or source baselines.
   Prompted dimensions are not proof of actual dimensions. A service usage limit
   stops generation; export existing images honestly, without switching providers
   or automatically retrying.

## Export

The host creates a JSON spec and runs:

```sh
python scripts/sheet_sample.py --spec character.json --out NEW_OUTPUT_DIRECTORY
```

Example spec (paths resolve relative to the spec):

```json
{
  "schema": 1,
  "mode": "whole_sheet_sample",
  "character": "New character",
  "image": "generated.png",
  "background": "alpha",
  "grid": [8, 5],
  "tile": [320, 320],
  "origin": [160, 250],
  "row_ground_y": [188, 386, 574, 747, 954],
  "registration_notes": "These example coordinates must be replaced by inspected ground contacts on the actual source. Never infer jump floor from airborne feet.",
  "required_actions": ["walk", "run", "attack", "death", "jump"],
  "actions": [
    {"name": "walk", "rows": [0], "seconds": 1.0, "loop": true, "design": "Two alternating steps; sword arm counter-swings."},
    {"name": "run", "rows": [1], "seconds": 0.72, "loop": true, "design": "Forward lean, distinct flight phase and recovering leg."},
    {"name": "attack", "rows": [2], "seconds": 0.85, "loop": false, "design": "Step, wind-up, forward cut, follow-through and guard."},
    {"name": "death", "rows": [3], "seconds": 1.05, "loop": false, "design": "Knee buckles, body falls to its side, limbs settle."},
    {"name": "jump", "rows": [4], "seconds": 1.05, "loop": false, "design": "Crouch, launch, apex, descend, land and recover."}
  ],
  "notes": ["Review sample; motion quality and user acceptance are not yet established."]
}
```

Every row belongs to exactly one declared action. An action may span several
rows; all cells are retained in source order. IDs are arbitrary safe names, not
a hardcoded action menu. This sample route follows the user's actual action set;
it does not promote a sample through the separate production batch contract.

The exporter preserves original scale. It uses a shared canvas, nominal grid
centers and one ground translation per row. It does not independently resize,
floor-snap, warp, reorder or delete poses. Jump displacement remains intact.

Unlike the straight separator path, component extraction can preserve a sword
that extends across a nominal column when another row needs a different cut.
There must be exactly one opaque main body per frame. Nearby small fragments and
edge alpha are retained; uncertain body counts, distant/ambiguous fragments,
source boundary clipping or insufficient canvas space stop export. This cannot
infer the anatomical owner of every disconnected fragment: inspect the overlay
and frame-ID map before using the result. Never tune the component threshold to
conceal a merged or missing character.

Output contains transparent frame PNGs, atlases, contact sheets, original and
transparent sources, source masks/bounds, portable spec and manifest, plus a
local browser reviewer. Serve the folder with a local HTTP server; the viewer
loads PNGs directly and supports pause, speed, frame stepping and terminal holds.

## Acceptance and known evidence

The first blue-cape human sample was accepted by the user for apparent smoothness
after a separately generated walk revision. The second skeleton sample retained
its visual style, but its walk revision returned a service usage-limit error.
Its currently exported walk is the original, repetitive row. This is evidence of
reusable extraction/playback, **not** evidence that all characters generate
equally well in one attempt. Background editing was also required.

The manifest always records `review_sample`, `pose_correspondence_verified: false`
and `accepted_by_user: false`. Tests check data integrity and viewer behavior,
not artistic naturalness. Keep the user's sample approval gate before replacing
game art. Do not publish the experimental route as a solved animation generator.
