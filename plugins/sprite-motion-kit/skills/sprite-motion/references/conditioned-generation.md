# Experimental sequence-conditioned backend

The original host-image route supplies a visual reference and a prompt. It does
not execute skeletal or temporal conditioning. Canvas preflight, pose review,
cropping and playback cannot change that limitation. Do not describe those
checks as a fix for incorrectly generated poses.

This optional path changes the generation call itself: measured 3D projections
become ordered OpenPose control images, an IP-Adapter receives the character
image, and an AnimateDiff motion module processes the sequence together. This
is one inference call for a complete action, not independent frame requests.
The resulting frames are placed into a fixed atlas without guessing grid cuts.

This is **experimental infrastructure, not a demonstrated quality fix**. There
are no bundled weights and no commercial-use warranty for external
models. Each selected model has its own license. A passing mocked adapter test
only proves input wiring; it is not evidence of good generated animation.

## Prepare controls without generating

Preserve the approved mesh, camera, original animation and measured phases.
Use an already reviewed imported schema-3 job. Explicitly map anatomical sides
to the source joint names; never identify left/right by whichever foot is to the
left of the current image. A right limb remains right after it passes the other.

```json
{
  "body": "humanoid",
  "anatomical_mapping_reason": "Describe how these names were verified on the source rig.",
  "joints": {
    "right_shoulder": "near_shoulder",
    "right_elbow": "near_elbow",
    "right_wrist": "near_hand",
    "right_hip": "near_hip",
    "right_knee": "near_knee",
    "right_ankle": "near_ankle",
    "left_shoulder": "far_shoulder",
    "left_elbow": "far_elbow",
    "left_wrist": "far_hand",
    "left_hip": "far_hip",
    "left_knee": "far_knee",
    "left_ankle": "far_ankle"
  }
}
```

These names are an example for the approved side-view rig, not a universal
mapping. Verify that a hand-bone origin represents the wrist before mapping it.
Measured nose/neck/eye/ear points are optional. A head-center coordinate is not
a nose coordinate. If no neck is provided, the converter records its use of the
shoulder midpoint. Missing face points stay missing.

```sh
python scripts/conditioning.py --job JOB --action walk --mapping mapping.json --out CONTROLS
```

The output contains fixed-size control frames, their hashes, a contact sheet,
the unchanged character image, and `conditioning.json`. It does not load any
model or generate character art. The pure-side source coordinates are preserved:
no recentering, floor pinning, phase interpolation or gait replacement occurs.
Review the colored controls against the original reference before inference.

## Execute only with an explicitly selected local model setup

`conditioned_backend.py` separates `check` from `run`. Check validates the local
configuration and input package without importing an inference runtime. Only
`run` loads models and calls the pipeline. Model paths are local; implicit
downloads and retries are disabled. Missing dependencies or weights stop the
operation. Do not install a new GPU stack over an unrelated user's environment.

The first environment under test is Windows x64, Python 3.12, NVIDIA CUDA 12.8
PyTorch 2.8.0 and torchvision 0.23.0. Use a separate virtual environment. Other
platforms/builds have not been validated by this experiment. On that platform:

```sh
python -m venv motion-runtime
motion-runtime/Scripts/python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
motion-runtime/Scripts/python -m pip install -r PLUGIN_ROOT/requirements-inference.txt
```

These commands install software, not model weights, and do not generate art.
The complete package versions observed in the Windows trial are recorded in
`assets/conditioned-runtime-windows-py312.txt`. That is a reproduction record,
not a cross-platform compatibility guarantee or a successful art-quality test.

### Explicit model installation

Run these from the skill directory. `plan` does not download or load models;
`fetch` explicitly downloads about 8.02 GB from the four upstream repositories:

```sh
python scripts/model_setup.py plan --lock assets/conditioned-models.lock.json
python scripts/model_setup.py fetch --lock assets/conditioned-models.lock.json --root models
```

The lock pins all 24 files to full repository commits, byte sizes and SHA-256
values. Existing matching files are reused after verification. Conflicting
files and partial downloads are preserved and reported, never silently replaced.
The inference command itself remains offline and cannot trigger these downloads.

The plugin MIT license does not cover these weights. SD1.5 and OpenPose ControlNet
declare OpenRAIL terms, IP-Adapter declares Apache-2.0, and this MotionAdapter
model card does not declare a license. No blanket commercial-use or redistribution
permission is asserted. This repository distributes the downloader and lock,
not a mirrored model bundle. Review the pinned upstream model cards listed by
`plan` before choosing the stack for a distributable product.

### Actual trial status

One eight-frame, 512-pixel-square walk sequence was generated with the locked
models, 25 denoising steps and CPU offload on a Windows RTX 5070. Inference
completed, but the raw result was severely blurred, the character and equipment
were indistinct, and the RGB background was opaque. It failed visual acceptance.
No game assets were replaced and no automatic retry was made.

The log also proved that the positive prompt exceeded the text encoder's
77-token limit and was truncated. The adapter now checks the selected local
tokenizer before loading generation models and rejects overlong prompts rather
than silently dropping constraints. This addresses a confirmed request defect;
it does **not** establish the cause of all the blur or prove a visual fix. The
guard was tested without generating another sequence.

The underlying API is Diffusers `AnimateDiffControlNetPipeline`. It consumes
`conditioning_frames`, `ip_adapter_image` and `num_frames` together. The backend
loads the motion adapter, ControlNet model(s), base model and identity adapter
from the supplied configuration. See the script's CLI help for configuration
and execution arguments.

An RGB result stays RGB. It is not labeled transparent because it has a key
color or checkerboard. Existing background extraction may subsequently produce
RGBA after inspection, but must preserve the fixed frame canvases. Outputs
remain diagnostic and cannot finish a character or replace game assets.

## Boundaries of this first adapter

- OpenPose body conditioning applies to compatible two-arm, two-leg humanoids.
  It does not silently map a dragon, quadruped or multi-arm rig into a human.
- Body joints do not encode a sword edge, shield surface, toes or fingers.
  Equipment-sensitive motion needs appropriately rendered additional controls
  and a matching control model; identity conditioning alone is not a rigid bind.
- Conditioning is statistical. It can still lose details or miss a pose.
  Loop mode does not guarantee the generated last frame joins the first.
- Pixel style and this character's occlusion patterns need a real visual test;
  ordinary-human model examples do not prove skeleton-sprite quality.
- No GPU memory or performance claim is made before testing the selected stack.
- One action is a study, not the required complete five-action character set.
  The user's review gate on replacing the full roster remains in force.

## Primary implementation references

- [Diffusers sequence ControlNet and IP-Adapter API](https://huggingface.co/docs/diffusers/api/pipelines/animatediff#animatediffcontrolnetpipeline)
- [Control-map channel format](https://github.com/huggingface/controlnet_aux/blob/master/src/controlnet_aux/open_pose/util.py)
- [IP-Adapter loading options](https://huggingface.co/docs/diffusers/api/loaders/ip_adapter)

These document interfaces, not guaranteed results on the user's artwork.
