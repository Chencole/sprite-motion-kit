# Custom motion contract (schema 2)

The host AI writes what the body does; the renderer produces a 3D mannequin guide. Action IDs are arbitrary safe names, not an enum. Multiple attacks, gestures, dodges, jumps, falls and monster motions use the same contract. Plans contain data, not executable code.

## Coordinates and skeleton

- Units are consistent (stock rigs use roughly metres). +X is forward/right in a side image, +Y up, +Z near. Camera `azimuth: 0, elevation: 0` is strict right-facing orthographic profile. Follow the requested view; do not substitute diagonal views.
- `joints` are parent-first. Exactly one has `parent: null`. Each has `id`, `parent`, fixed local `offset: [x,y,z]`, positive `radius`, optional `color` (`body`, `near`, `far`, `head`, `extra`). Add branches for extra limbs and weapon tips. The body label does not restrict topology.
- Key `rotations` are local Euler angles `[x,y,z]` in degrees, composed Rz × Ry × Rx. Omitted joints have zero rotation. Rotating a shoulder moves its elbow/hand; rotating a hand aims an attached weapon.
- `root` is world translation added to the root's rest offset. `root_rotation` rotates the rig around that pivot. This preserves jumping, lunging and falling displacement.
- Interpolation uses shortest local angular paths and fixed segment lengths. Add intermediate keys for turns exceeding 180 degrees. `smooth` eases between keys; use `linear` or denser keys for constant motion and sharp impacts.

## Structure

```json
{
  "schema": 2,
  "name": "Custom action study",
  "design_status": "authored",
  "body": "custom",
  "camera": {"azimuth": 0, "elevation": 0},
  "frame_size": [384, 384],
  "joints": [
    {"id": "pelvis", "parent": null, "offset": [0, 1, 0], "radius": 0.12, "color": "body"},
    {"id": "chest", "parent": "pelvis", "offset": [0, 0.4, 0], "radius": 0.15, "color": "body"}
  ],
  "actions": {
    "overhead_cut": {
      "description": "Raise weapon, commit a downward cut, recover balance",
      "seconds": 1.2,
      "loop": false,
      "frame_count": 12,
      "columns": 4,
      "interpolation": "smooth",
      "keys": [
        {"time": 0, "root": [0, 0, 0], "rotations": {}},
        {"time": 0.4, "root": [0, 0, 0], "rotations": {"chest": [0, 0, 12]}},
        {"time": 0.65, "root": [0.15, -0.04, 0], "rotations": {"chest": [0, 0, -20]}},
        {"time": 1.2, "root": [0.15, 0, 0], "rotations": {}}
      ]
    }
  }
}
```

This minimal example demonstrates the format, not a complete rig or usable sword attack. Build the actual anatomy and poses. A scaffold provides full starting anatomy, but neutral keys are not an authored action.

Keys start at zero, end at `seconds`, and strictly increase. A looping action needs matching start/end poses; the closing key is omitted from exported samples. One-shot actions include the ending pose. `frame_count` sets AI guide density (2–64); use enough authored keys to describe the motion independently of output frame count. Split large rosters into jobs rather than exceeding renderer resource limits.

## Agent's authoring responsibilities

### Required generation prerequisites

Draft plans can still be rendered before they are complete. Character preparation additionally requires nonempty `character_analysis.anatomy`, `character_analysis.mass_and_balance` and `character_analysis.equipment` (describe the absence of equipment when appropriate). Each action needs `design.intent`, `design.support_and_contact`, `design.phases` and `design.end_state`. These are explanatory strings authored for the actual character and requested action, not generic placeholders. Preparation rejects motion with fewer than three keys or no changing joint positions.

Preparation does not emit ready-to-use request files. After inspecting the reference, the agent submits `review-reference --job JOB --report REPORT.json`. The report contains `input_hashes` copied from the job and `actions` keyed by action ID. Each action records true checks for `anatomy`, `support_and_contact`, `timing`, `camera`, `end_state`, plus nonempty `notes` describing observed motion. A failed check means repair the plan and prepare again. No automatic user approval is required. This report is an accountable agent observation, not an automated certificate of natural movement.

The tool checks hashes of the character, plan and every guide before accepting the report or exporting. Changed inputs invalidate the job; prepare and review a new one. Legacy jobs need an explicit reference-reuse reason; default preparation never silently chooses the bundled backward fall.

Before choosing key poses, describe the character-specific motion intent in each action's `description`: apparent weight, supporting limbs, balance/centre-of-mass shift, equipment constraints and the desired end state. For a large creature's death, reason about the sequence of lost support, any bracing, the fall direction, ground contact and settling of secondary parts. For walking, reason about footfall order, stride, stance width and the return into the next step. Express those decisions through joint/root keys and timings; changing an action label alone is not a variant. Examples such as a giant's braced collapse or a nimble humanoid's lighter stride are not mandatory templates. The AI chooses a suitable motion for the request, while reusing approved motion when appropriate.

1. Translate the request into named actions and descriptions, anatomy, attached objects, view and timing.
2. Author whole-body key poses. Distinguish support and swing feet; keep weapons attached. Creature mass, extra limbs and silhouette influence action design, not just its label. Different fall directions need different root rotations and folding.
3. Validate, render and inspect. Rendering is deterministic and needs no model credits. It does not simulate balance, collisions, muscles or foot IK; check penetration, intersections, support and transitions and correct the plan.
4. Mark an authored design `authored`, prepare the character job, and use the host image tool with the actual custom guide and original character. No fixed legacy guide is substituted.

The custom renderer and packer have no action-name dispatch. Familiar illustrative motions are opt-in under `create --example-motion`; all names otherwise begin as neutral keys for the AI to author. Reuse an approved plan when it fits; do not force random variation every run.

## Outputs and alignment

The renderer saves the exact plan and its hash, pose guides, individual PNGs, world-joint samples, animation atlases, metadata and offline `guide-review.html`. One shared orthographic camera/scale spans the actions; jumping or collapsing does not change framing.

Character export uses `reference_canvas`: one fixed canvas transform retains the guide origin and airborne height. A wrong cell aspect ratio is rejected instead of stretching the character. Correct the actual generated grid or recreate matching references for a deliberate framing change.

The image model can deviate from a guide. Inspect its output independently. `visual_review_passed` stays false after technical export; no JSON status proves art quality.
