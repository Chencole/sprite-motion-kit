# 0.5.3

Move imported-reference generation safeguards before the provider call.
Reference review now leaves requests locked. The new generation-check command
requires inspected provider capabilities, dedicated canvas controls and confirmed
size support for the whole action set before emitting requests. A prompt-only
interface is blocked instead of silently treating prose as a size setting.

Packets separate real tool arguments from visual instructions, retain the fixed
cell origin and baseline, preserve reference camera priority over character-art
camera, and explicitly disable automatic retries. Existing source images can
still be inspected as drafts; old requests cannot be retroactively certified.

Sixty regression checks cover supported controls, unsupported sizes, prompt-only
providers, unchanged outputs after rejection, and earlier export invariants.
These safeguards do not guarantee perfect model-generated poses or appearance.
