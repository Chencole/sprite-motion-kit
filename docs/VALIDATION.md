# Release validation

Validated on Windows with Python 3.12, Pillow/NumPy, the installed Codex CLI and a Chromium-based preview, September 2026.

- Ten offline regression tests passed, covering source preservation, alpha/keyed backgrounds, uneven cell dimensions, clipping rejection, uniform death scale, invalid timing, source repacking and settled-corpse export.
- Codex plugin manifest validator passed.
- Codex skill validator passed.
- Repository marketplace was added locally and the plugin installed successfully with the CLI.
- Existing AI-generated walk and death sheets were prepared and exported through the plugin with the original character. These private test inputs and outputs are excluded from distribution.
- Browser interaction verified pause, quarter-speed selection, reverse wrap to the last walk frame, advance from last to first, and death clamping at the final corpse even after advancing again.

These checks validate packaging, export and controls. They do **not** establish that every generated character has natural gait or that the plugin is accepted by an official directory. The plugin does not contain a generation model; a fresh installation still needs the host agent's generation capability. Additional host/OS combinations and new generated artwork require their own testing.
