# Validation

The 0.3.0 automated suite contains 25 tests, all passing. It exercises arbitrary custom action IDs, neutral scaffolds, extra-arm topology and attached weapons, fixed segment lengths through interpolation, distinct attack trajectories, quadruped roll anatomy, invalid plans, loop seams, preserved jump height, custom render/export roundtrip and legacy export compatibility.

The roundtrip test uses rendered mannequin images as engineering fixtures, not as claimed AI character output. Structural validation is distinct from visual approval; exported clips retain visual_review_passed=false.

The local reference player is additionally inspected with authored overhead-cut, lunge and hop plans and a quadruped collapse example. This release does not claim an external image model followed every custom guide or that a new character roster was completed.

New boundary tests cover no-plan fallback rejection, missing analysis/design, falsely authored static poses, reference-review gating and modified character/plan/guide rejection. Review checks are agent attestations, not automated semantic/art-quality proof.
