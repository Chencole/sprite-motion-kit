# Reusable body actions with runtime VFX

Use this policy when the user chooses 1-3 reusable attack/cast body animations per
combat character and separate effects in the game. It overrides per-skill media
generation. Reuse approved existing artwork through `prepare-video
--existing-image-job`; do not create new first-frame images when prohibited.

Set the schema-2 scope's top-level `motion_strategy` to
`body_actions_with_runtime_vfx`. Keep the complete gameplay inventory, including
all original skills, damage/combination dispatchers and applicable base states.
Do not shrink that inventory to the smaller animation set. Copy the previously
frozen inventory when revising an existing production scope and preserve the old
scope, paid jobs and ambiguous submissions as history.

## Exact per-character fields

- `gameplay_inventory`: all discovered entries, with `game_id`, `kind` (`action`,
  `ability`, `weapon`, `interaction`), `purpose`, `source` and boolean `applicable`.
  Nonapplicable entries require `exclusion_reason`. Applicable game IDs are unique.
- `requirements`: one entry per actual body action, using the existing requirement
  fields plus `body_action_kind` and nonempty `covered_game_ids`. Kinds are
  `attack`, `cast`, `locomotion`, `reaction`, `death`, `interaction`, `idle`, `other`.
  Attack and cast combined are limited to three; characters with applicable
  ability/weapon requirements need at least one. Ability/weapon entries map to a
  counted attack/cast body, not a disguised locomotion action.
- `action_map`: body-requirement ID to its body-action ID. Each body is registered
  once. Optional `required_actions` is exactly this unique action set.
- `runtime_mappings`: one object for each applicable inventory game ID, containing
  `game_id`, `body_action`, nonempty `game_event` and `runtime_vfx` (a list of game
  effect IDs, explicitly `[]` when no effect is used). Many skills may reference
  the same `body_action`. `game_event` identifies the existing skill/event
  dispatcher, which keeps damage and combo logic in the game rather than baking
  or deleting it. Preserve other runtime-specific mapping metadata as needed.
- `effects`: the body-only policy shown below. Use it in the action design too.

`covered_game_ids` must partition the applicable inventory exactly. The runtime
mapping must cover that same set exactly once and agree with each body's covered
IDs. Unknown IDs, missing skills, duplicate mappings and absent events/effect
lists are errors. The validator checks the recorded inventory; the agent still
has to discover every actual game skill and verify runtime integration.

## Example fragment

Keep the normal character image and all six project-discovery inspections. The
following character fields illustrate two real skills sharing one cast body:

```json
{
  "gameplay_inventory": [
    {"game_id":"ability.firebolt","kind":"ability","purpose":"Existing fire attack","source":"game/skills.json:firebolt","applicable":true},
    {"game_id":"ability.frost_wave","kind":"ability","purpose":"Existing frost attack","source":"game/skills.json:frost_wave","applicable":true}
  ],
  "requirements": [
    {"id":"cast_body","kind":"action","game_id":"body.cast_common","purpose":"Reusable cast anticipation, release and recovery","source":"game/body-map.json:cast_common","applicable":true,"body_action_kind":"cast","covered_game_ids":["ability.firebolt","ability.frost_wave"]}
  ],
  "action_map": {"cast_body":"cast_common"},
  "runtime_mappings": [
    {"game_id":"ability.firebolt","body_action":"cast_common","game_event":"skills.firebolt.release","runtime_vfx":["vfx.firebolt"]},
    {"game_id":"ability.frost_wave","body_action":"cast_common","game_event":"skills.frost_wave.release","runtime_vfx":["vfx.frost_wave"]}
  ],
  "effects": {
    "allowed": [],
    "allow_unlisted": false,
    "forbidden": ["runtime_vfx","projectiles","beams","particles","trails","impact_flashes","explosions","auras","glows","smoke","sparks","spell_symbols","magic_shields","elemental_effects","summoned_objects","screen_effects"]
  }
}
```

The mandatory forbidden categories are exported as `batch.RUNTIME_VFX_FORBIDDEN`.
Additional forbidden items are allowed; removing required categories or permitting
baked effects is rejected. `veo_workflow.py scaffold` carries the scope effects
policy into the design template. Author the actual body motion and phases before
preparing video. Physical held equipment remains part of the character, while
runtime magic, projectiles and impact effects are excluded.

## Generation, extraction and review

```sh
python scripts/batch.py create --spec BODY_SCOPE.json --out NEW_BODY_BATCH
python scripts/veo_workflow.py scaffold --batch NEW_BODY_BATCH \
  --character mage --action cast_common --out cast-common-design.json
# Author this one body design. No per-skill image or clip is required.
python scripts/veo_workflow.py prepare-video --batch NEW_BODY_BATCH \
  --character mage --action cast_common --design cast-common-design.json \
  --existing-image-job ORIGINAL_UPLOAD_JOB --job NEW_CAST_VIDEO_JOB
```

These commands spend no generation credits. Submit only missing body actions
authorized for the new scope, never every runtime skill mapping. Do not resubmit
old paid jobs or delete an unknown-submission lock. Mark only genuinely unsubmitted
old planned work as superseded in the coordinating production queue.

The normal source/identity, interval, transparency, loop/death endpoint and framing
checks remain. `coverage_binding` now includes the strategy, all covered game IDs,
their runtime mappings and the effects policy. Pass the complete binding through
generation, extraction and review. A changed scope requires a new explicit batch;
do not alter old job hashes to impersonate the new scope.

Review a shared export once. In addition to the usual video/design checks, the
review must explicitly pass `body_motion_only`, `runtime_vfx_separate` and
`all_gameplay_mappings_preserved`. These are observations of the body clip and its
runtime mapping contract, not repeated reviews pretending each skill got new
pixels. Renaming one export into several supposedly independent body actions
remains an error. `status.required` and `status.reviewed` count unique bodies;
completion requires every registered body and every inventory mapping.
