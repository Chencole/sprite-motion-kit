# Coverage and completion contract

Extract the user's entire requested character/action scope before preparing individual jobs. Do not convert “fix the death animation” during an existing full-character replacement into a death-only replacement scope. Preserve earlier required actions unless the user changes the scope. This manifest tracks delivery coverage separately from per-action pose design.

For an unspecified complete ordinary humanoid action set, start with at least five action families: walk, run, attack, death and jump. Expand these from the user's needs (multiple attacks, casting, hit reactions, climbing, and so on). These are a coverage baseline, not a fixed action enum or a universal anatomical requirement. A specifically requested single-action repair stays single-action; a flying or otherwise non-humanoid creature needs appropriate substitutions explained in its scope. Never silently drop an explicitly requested family. A diagnostic walk-only job remains partial when the enclosing scope requires all five; even a visually accepted walk cannot complete that set.

Create a JSON specification (paths relative to this file):

```json
{
  "request": "The user's requested set, including retained prior scope",
  "characters": {
    "armored_guard": {
      "character": "guard.png",
      "required_actions": ["walk", "run", "thrust", "overhead_cut", "death"]
    }
  }
}
```

These names are illustrative. Do not force this list on a single-jump request, a creature without legs, or a user requesting multiple spell variants. Include all requested characters; share a single appearance entry only when they genuinely use the same appearance and approved motion design. Record that grouping in the specification. Existing approved clips may be reused when appropriate, but must be attached and reviewed; existence alone is not completion.

```sh
python scripts/batch.py create --spec SCOPE.json --out BATCH
python scripts/batch.py attach --batch BATCH --character armored_guard --job JOB
python scripts/batch.py status --batch BATCH
```

A job may contain a subset of required actions. Jobs can be combined; attaching one never removes other required actions. The source character hash must match. Prepare/render/review/generate/pack each action through the usual custom motion workflow. The batch records pending actions before those jobs exist, so a missing run cannot disappear merely because a death-only plan has no run key.

After actually inspecting exported animation at normal speed, slow speed and the loop seam/end pose, copy the action's `artifact_hashes` from `status` into a review report:

```json
{
  "artifact_hashes": {"copy exact current entries from status": "..."},
  "checks": {
    "appearance": true,
    "whole_body_motion": true,
    "timing_and_transition": true,
    "transparency_and_crop": true,
    "requested_action": true
  },
  "notes": "Concrete observations from playback and frames; unresolved faults are not a pass."
}
```

```sh
python scripts/batch.py review --batch BATCH --character armored_guard --action thrust --report REVIEW.json
python scripts/batch.py finish --batch BATCH
```

`finish` fails until every required pair has current exported files and an actual visual review recorded. Replacing an atlas, frame, generated source or reference invalidates the applicable review. A missing export or changed plan blocks completion. `completion.json` is a historical snapshot: always rerun `status`/`finish` immediately before delivery; do not use an old snapshot after changing artifacts. Requirements are hashed so accidental edits cannot silently reduce the scope. An intentional user scope change needs an explicitly revised batch; retain the old batch for traceability.

Limits: the script checks coverage, file identity and recorded prerequisites. It cannot verify what the user said, certify aesthetic quality, prove that an AI watched the animation, or prevent outside scripts from bypassing the workflow. The host AI must accurately populate the requirement list, inspect outputs, and report incomplete work truthfully. Never claim these checks alone make movement natural.
