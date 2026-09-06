# Release notes

## 0.2.0 — AI-authored custom motion plans

- Added schema-2 joint trees, root transforms, arbitrary action names, key-pose timing and configurable orthographic cameras.
- Added a local shaded 3D mannequin renderer and offline reference player; no Blender or hosted API required.
- The AI authors each requested motion. Scaffolds are neutral by default; familiar motion examples require an explicit flag.
- Custom frame export preserves airborne/root movement and uses one reference canvas; legacy walk/death jobs remain supported.
- Added configurable reference layouts to synchronized review, plan provenance hashes, and validation for rigs, timing and loop endpoints.
- Narrowed chroma key removal to preserve dark purple character details.

Reference rendering and data checks do not guarantee naturally animated character art. Generation remains the host image tool's responsibility, with visual review before delivery.

## 0.1.0

Initial fixed-reference walk/death workflow, transparent export, aligned atlases and synchronized review.
