# OpenAI directory submission draft

Status: **not submitted or listed**. The GitHub package is independently distributable.

Official source checked: https://developers.openai.com/plugins/deploy/submission

The official process accepts skills-only plugins. It requires a verified developer identity and the submitting organization's Apps Management Write permission, plus review and publication. This release does not establish either account requirement.

## Listing materials

- Name: Sprite Motion Kit
- Publisher: Chencole (GitHub publisher; must be matched to the verified identity before submission)
- Category: Productivity
- Short description: Turn character artwork and pose references into inspectable game animation sheets.
- Description: A Codex authoring workflow for side-profile humanoid walk and death animations. Includes CC0 mannequin references, local frame extraction, transparent atlases, timing metadata and an offline synchronized reviewer. Requires the host's image-generation capability; no model or generation credits included.
- Website: https://github.com/Chencole/sprite-motion-kit
- Support: https://github.com/Chencole/sprite-motion-kit/issues
- Privacy: https://github.com/Chencole/sprite-motion-kit/blob/main/docs/PRIVACY.md
- Terms: https://github.com/Chencole/sprite-motion-kit/blob/main/docs/TERMS.md
- Bundle: the installable `plugins/sprite-motion-kit` directory in the release ZIP.
- Starter prompts: make a side-profile walk from a character; make a fall ending in a full-size corpse; inspect an existing walk loop against its reference.

## Reviewer scenarios (expected behavior, not recorded evaluations)

| Type | User scenario | Expected behavior |
| --- | --- | --- |
| Positive | Supply a pixel humanoid and ask for a right-facing walk | Inspect references, generate a full action, pack it, show synchronized playback |
| Positive | Ask for death from the same character | Generate a full-size fall and hold the settled final pose |
| Positive | Supply a generated sheet with real transparency | Export frames, atlas and metadata without background removal damage |
| Positive | Supply a known grid and uneven phase times for a repaired loop | Respect actual grid and timing, keep the cycle duration, step across the seam |
| Positive | Ask for walking and death on multiple compatible humanoids | Track each appearance separately, preserve identities, report visual review state |
| Negative | No image-generation capability is available | Explain the missing capability; never claim newly generated poses or buy credits |
| Negative | Request a dragon flight using the biped reference | Identify the incompatible reference instead of silently producing biped movement |
| Negative | Supply an opaque checkerboard or a cropped cell | Reject the technical export and request/correct the source before calling it ready |

Before submission the publisher must supply a suitable final listing logo, select verified identity and availability, run and record these agent-level scenarios with a supported generation tool, and upload the final bundle. Local unit tests do not replace these end-to-end evaluations. Account verification and reviewer approval cannot be represented as completed by this document.
