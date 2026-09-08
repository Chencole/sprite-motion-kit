# Coverage and completion contract

The AI owns discovery, manifest authoring and command execution. The user supplies the project/target characters and desired outcome; do not ask them to handwrite a manifest or enumerate every animation. Inspect the selected project's actual files before planning generation. Preserve existing requested scope when the user asks to fix one action during a full-character task.

## Discover the project before generating

For each character, record the sources inspected and the requirements derived from them:

- State machine and animation transitions, including locomotion and airborne states.
- Control inputs and controller behavior (walk/run/jump or the body's applicable alternatives).
- Every distinct ability, spell and cast phase needed by the game.
- Weapon configurations and their distinct attacks, stances or interactions.
- Hit reactions, knockdown/fall, fatal transition, persistent death state and revival/recovery paths.
- Other interactions such as climbing, using objects, dialogue or idles when actually used.

These are discovery areas, not a fixed animation list. An area with no applicable behavior still needs an inspected source/search reference and an explanation. Record non-applicable discovered requirements with an explicit exclusion reason; do not silently omit them. Distinguish a recoverable knockdown from the fatal transition and settled death pose when the game distinguishes them; describe how the relevant states connect. Combine multiple source references for one actual behavior rather than inventing duplicate requirements. Different spells remain distinct gameplay inventory entries. When the user selects `body_actions_with_runtime_vfx`, they can map to a shared body animation and do not require independent media or duplicate reviews.

The script validates the AI's recorded inventory and its execution coverage. It does not infer every requirement from arbitrary game code or prove that the host inspected all files. Use real file locations, stable state/ability/weapon IDs and concrete observations. Requirements discovered later require a revised explicit batch, preserving the prior scope as history.

## AI-authored schema-2 scope

`full_character` means all applicable requirements found for that character in this project. The tool does not inject a universal animation list. `motion_strategy` selects `independent_actions` (the historical default) or [body_actions_with_runtime_vfx](body-actions-runtime-vfx.md). In the shared strategy, each requirement is one body action with `covered_game_ids`, while the full `gameplay_inventory` and `runtime_mappings` preserve all skills. `action_map` maps each body requirement once; many runtime skill mappings may reference that same action. Optional `required_actions` equals the unique body-action set. One body export and review can therefore cover multiple mapped skills without renamed copies.

The following historical independent-action example illustrates the base shape. Use the linked body/runtime strategy when the user chooses reuse. Replace sources, IDs and findings with actual project evidence:

```json
{
  "request": "Complete the selected spellcaster's animations for the inspected game",
  "scope_mode": "full_character",
  "characters": {
    "spellcaster": {
      "character": "approved-spellcaster.png",
      "discovery": {
        "project": "/actual/selected/project",
        "inspections": [
          {"area":"state_machine","status":"inspected","source":"actors/mage/state-machine.ts","notes":"Walk, running, knockdown and dead states require animation."},
          {"area":"control_inputs","status":"inspected","source":"actors/mage/controller.ts","notes":"Movement and sprint are distinct. This actor cannot jump."},
          {"area":"abilities","status":"inspected","source":"abilities/mage.json","notes":"Firebolt and frost ward have distinct cast behavior."},
          {"area":"weapons","status":"not_applicable","source":"actors/mage/loadout.json","notes":"No weapon attack is enabled for this actor."},
          {"area":"damage_death_revival","status":"inspected","source":"actors/mage/damage.ts","notes":"Knockdown can recover; fatal damage transitions to a persistent dead body."},
          {"area":"interactions","status":"not_applicable","source":"actors/mage/interactions.ts","notes":"No additional animated interaction is assigned."}
        ]
      },
      "requirements": [
        {"id":"move","kind":"action","game_id":"state.walk","purpose":"Movement gait","source":"controller.ts:move and state-machine.ts:walk","applicable":true},
        {"id":"sprint","kind":"action","game_id":"state.run","purpose":"Separate sprint gait","source":"controller.ts:sprint","applicable":true},
        {"id":"knocked_down","kind":"action","game_id":"state.knocked_down","purpose":"Recoverable fall and recovery transition","source":"damage.ts:knockdown","applicable":true},
        {"id":"dead","kind":"action","game_id":"state.dead","purpose":"Fatal transition ending in a persistent full-size body","source":"damage.ts:die","applicable":true},
        {"id":"firebolt","kind":"ability","game_id":"ability.firebolt","purpose":"Forward firebolt cast with its release and recovery","source":"abilities/mage.json:firebolt","applicable":true},
        {"id":"frost_ward","kind":"ability","game_id":"ability.frost_ward","purpose":"Distinct defensive ward casting gesture","source":"abilities/mage.json:frost_ward","applicable":true},
        {"id":"jump","kind":"action","game_id":"input.jump","purpose":"Potential airborne action checked during discovery","source":"controller.ts:canJump=false","applicable":false,"exclusion_reason":"This selected character cannot jump in the game."}
      ],
      "action_map": {
        "move":"walk", "sprint":"run", "knocked_down":"knockdown_recover",
        "dead":"fatal_fall", "firebolt":"cast_firebolt", "frost_ward":"cast_frost_ward"
      }
    }
  }
}
```

An isolated user-requested test may use `scope_mode: action_study` and a nonempty `study_reason`. It still records the inspected context and applicable requirements of that study. Do not switch a full-character request to study mode because work is unfinished. A study can finish its own scope but never reports `complete: true` or `full_character_complete: true`.

```sh
python scripts/batch.py create --spec AI_AUTHORED_SCOPE.json --out BATCH
python scripts/batch.py status --batch BATCH
```

Existing schema-1 batches are historical coverage records without this discovery inventory. They cannot pass the new full-character finish gate. Create a reviewed schema-2 scope rather than silently inventing missing mappings or rewriting its hash.

## Bind the selected generation route

For the video route, create the batch before extracting each generated action. Binding automatically supplies the approved character reference and records the exact scope, character, action and gameplay requirement in the sample. The importer does not generate video or certify that a provider used the reference; actual visual review must confirm identity and action semantics.

```sh
python scripts/video_sample.py --video CAST_FIRE.mp4 --ffmpeg /path/to/ffmpeg \
  --out NEW_FIRE_SAMPLE --character "Spellcaster" --action cast_firebolt \
  --batch BATCH --batch-character spellcaster \
  --start 0.5 --duration 1.0 --count 12 --background green --key-scope all \
  --origin 480 830 --review-notes "Actual inspected casting interval, release timing, equipment and remaining defects."
python scripts/batch.py attach-video --batch BATCH --character spellcaster \
  --action cast_firebolt --sample NEW_FIRE_SAMPLE
```

Timing, origin and key scope above are examples requiring inspection. Keep full shared canvases, actual source order and the source video. Use `--loop` only for an inspected full cycle; a cast commonly ends after its release/recovery. Default key scope protects internal key colors; `all` requires checking that those colors are not part of the character.

Repeat for every missing body action under the shared strategy, not every mapped skill. A second spell still needs its own complete runtime mapping, but can reuse the same reviewed cast body. One clip remains `scope_mode: action_study` even when bound to a larger batch. An unbound old sample cannot simply be marked accepted: re-extract the inspected source with the new binding. This is local work, not permission for another paid generation.

Custom 3D jobs continue using `batch.py attach --batch BATCH --character ID --job JOB`. Their existing pose/reference/preflight checks remain required. Both routes share the same inventory and visual-review finish gate. Separate actions cannot use the same source-video interval or identical exported pixel sequence under renamed IDs; different intervals of a long video are allowed when actually distinct. Re-encoded or perceptually similar motions still require human/AI visual judgment.

## Review each current export, then finish

After inspecting the actual source and exported frames at normal speed, slow speed and the loop seam/end pose, copy `artifact_hashes` and `coverage_binding` from that action's `status` entry into a report. All checks must be true only after the observation actually passes. Video reviews additionally require `source_video` and `ability_or_weapon_match`:

```json
{
  "artifact_hashes": {"copy exact current entries from status": "..."},
  "coverage_binding": {"copy the complete current status binding": "..."},
  "checks": {
    "appearance": true,
    "whole_body_motion": true,
    "timing_and_transition": true,
    "transparency_and_crop": true,
    "requested_action": true,
    "source_video": true,
    "ability_or_weapon_match": true
  },
  "notes": "Concrete observations of this exact ability/weapon/state, its release/contact timing, body motion, source defects and exported edges. Unresolved faults are not a pass."
}
```

```sh
python scripts/batch.py review --batch BATCH --character spellcaster --action cast_firebolt --report REVIEW.json
python scripts/batch.py finish --batch BATCH
```

`finish` fails while any required body action lacks a valid current export/review. Under the shared strategy, omitted skills, runtime events or VFX mappings fail scope validation; a shared review must also pass `body_motion_only`, `runtime_vfx_separate` and `all_gameplay_mappings_preserved`. Review each body once, never manufacture per-skill reviews of the same pixels. `status` rechecks flags, notes, bindings and artifact hashes; changed artifacts invalidate review. Pixel checks do not certify animation naturalness or prove the game runtime integration works.

`scope_complete` means this declared scope has current reviews. `complete` and `full_character_complete` are true only for a schema-2 full-character scope. `study_complete` may be true while both full-character flags remain false. `completion_current` indicates that the completion snapshot still matches current reviews and artifacts; always rerun status/finish before delivery. Technical completion is never permission to overwrite game assets or substitute for user approval explicitly requested in the conversation.
