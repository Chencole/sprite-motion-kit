# Reference motion provenance

The bundled naked mannequin pose sheets and preview atlases were rendered from
Quaternius' Universal Animation Library, standard distribution, using Walk_Loop
and Death01. Camera: level orthographic side view, character facing screen right.
The walk uses a 1.333333 second full cycle. Death lasts 2.375 seconds.

- Official source: https://quaternius.com/packs/universalanimationlibrary.html
- Official distribution: https://quaternius.itch.io/universal-animation-library
- Source GLTF mirror used during authoring: https://github.com/J-Ponzo/gltf-universal-animation-library
- Original reference license: CC0 1.0, reproduced in `../assets/QUATERNIUS-CC0.txt`.

The near and far walking legs were recolored to help maintain anatomical identity
during pose transfer. The reference previews contain 72 samples in 12 columns by
6 rows, each tile 256x320. The walk guide selects 8 evenly spaced phases; the
death guide selects 12 ordered poses. The renderings are provided under CC0.

No game code, game save, private character artwork, model weights, API credentials
or third-party paid tool output is bundled. The plugin requires the host agent's
own image-generation capability for new character images.
