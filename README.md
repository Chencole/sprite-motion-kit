# Sprite Motion Kit

**当前为实验版本，尚未证明能稳定生成自然动作。** The repository is private;
installation requires repository access. No public release or model weights are
being distributed as a finished animation solution.

## Existing image/video account connection

The plugin can now use an existing **MXAPI/MyPixelFlow** account to submit image
jobs and **Seedance / Veo** video jobs, query progress and download the actual results.
It can reuse MyPixelFlow's encrypted local account without copying secrets or
modifying that project. Other installations provide their own account. See the
[connection workflow](plugins/sprite-motion-kit/skills/sprite-motion/references/mxapi-generation.md).

The selected video route is **character still → continuous action video → local
transparent frames → playback review**. It uses existing FFmpeg for timestamp-based
frame extraction, preserves one canvas and jump height, and supports green/magenta
key backgrounds. Local source files need the user's own reachable media publisher;
the image generator's returned HTTPS output can go directly into the selected video adapter.
No quota, credentials or models are included. Successful connection/extraction tests
are not a promise of stable character motion; one real sample still needs review.

**The AI derives the animation set from the project; the user does not fill in an
action checklist.** Before generating a complete character, inspect its state
machine, movement/controls, weapons, abilities, damage reactions, falls/death and
other relevant gameplay transitions. Record the inspected sources and map every
applicable requirement to an action ID. Two different spells need their respective
casting actions; a generic `attack` does not replace them. Include idle, movement,
running, jumping, landing, reactions and other states where the project uses them,
and explain exclusions from source evidence. A fixed five-action list is not a
substitute for this analysis. The [coverage contract](plugins/sprite-motion-kit/skills/sprite-motion/references/batch-coverage.md)
tracks the AI-authored plan and exact reviewed outputs, including video-derived
actions. A walk-only model comparison remains an action study, not a finished
character or authorization to replace the roster.

Seedance **2.0 Mini** is a separate adapter, with a documented dedicated route and
defaults of 480p / 4 seconds. Model selection and resolution selection are distinct;
raising resolution does not upgrade the model. The provider's public Mini pricing
sources currently differ, so estimates are not promised bills. Preserve the task's
returned point cost, and never submit extra paid samples merely to discover pricing.

Veo **3.1 Fast** uses its own provider request and polling routes. Its adapter
accepts the documented landscape/portrait formats and keeps paid image expansion
off. The gateway does not expose duration or resolution controls for this route;
unsupported overrides fail before submission rather than pretending to change
the requested model tier. Read the current provider quote before each authorized
trial and report the actual returned video length and charge separately.

The reusable Veo route is project-bound rather than a free-form prompt wrapper.
The AI derives each action from the game's actual state and ability data, records
ordered phases and equipment states. Users can directly reuse verified existing
art with `prepare-video --existing-image-job`, without another image generation
or still review; weapon/start-pose conflicts are recorded as risks. When a new
action-specific first frame is selected, its visual review remains required. Identity images,
start-still reviews, Veo jobs and extracted MP4 frames remain hash-linked to the
same coverage requirement. See the [Veo workflow](plugins/sprite-motion-kit/skills/sprite-motion/references/veo-workflow.md).

The explicit [body-actions/runtime-VFX strategy](plugins/sprite-motion-kit/skills/sprite-motion/references/body-actions-runtime-vfx.md)
lets multiple skills share one reviewed body animation. It preserves the complete
gameplay inventory and every skill's runtime event/effect mapping, limits each
combat character to 1-3 attack/cast bodies, and forbids baked VFX in those clips.
It does not generate separate images/videos or duplicate reviews for each skill.

The reusable [whole-sheet sample workflow](plugins/sprite-motion-kit/skills/sprite-motion/references/whole-sheet-samples.md)
now packages the direct host-image approach: a complete generated character sheet,
component-aware transparent extraction, common coordinates and a browser reviewer.
The host still needs its own image-generation access. The second skeleton sample
is included under `examples/skeleton-sheet-sample`; its walk revision was blocked
by a service usage limit, so its original walk remains a review draft.

**按项目自动整理角色动作 → 用户选定的生成方式 → 透明动画与完整性验收。**

The following 3D-reference workflow is an alternative when selected. It is not a
prerequisite for the image-to-video route above.

A Codex plugin for custom game-character animation authoring. The AI designs the anatomy and key poses for the requested action; local tools render an orthographic 3D mannequin guide, package character sprites, and open a synchronized offline reviewer.

Actions are **not limited to walk, run, jump or death**. Multiple sword attacks, casting gestures, dodges, monster collapses and multi-arm motions use the same editable motion contract. The AI writes the plan; users do not need to manipulate joints or run commands manually.

## Install

```sh
codex plugin marketplace add Chencole/sprite-motion-kit
codex plugin add sprite-motion-kit@personal
```

The repository catalog is named `personal`. If that name is already configured for a different repository, use a local clone with a distinct catalog name. See the [official packaging documentation](https://developers.openai.com/plugins/build/plugins).

After installation, start a new Codex task and attach your character. Python 3.10+, Pillow and NumPy are required:

```sh
python -m pip install -r plugins/sprite-motion-kit/requirements.txt
```

No Blender, external website, account or model credits are required for the local 3D reference renderer. Generating final character artwork still needs the host AI's image-generation tool, with its applicable access and costs.

## Ask the AI

> 用 Sprite Motion Kit，给这个四臂角色做两种不同攻击和向侧面倒地。先按他的体型设计三维木头人动作，再照参考生成整套角色帧，保留四条手臂和每只手的武器，给我正常速度和逐帧检查。

The agent:

1. Reads the project's actual character states, controls and abilities, records their complete action coverage, then interprets body, view and timing. The agent writes this manifest rather than asking the user to enumerate routine actions.
2. Authors a JSON rig and whole-body key poses, including attached weapon endpoints and extra limbs as needed.
3. Validates and renders that custom motion locally; inspects and corrects its poses.
4. Reviews the reference and checks the available image tool's declared canvas controls before unlocking requests, then supplies the complete pose guide, original character and endpoint reference together.
5. Checks the generated grid, transparency and continuity, exports frames/atlases, and opens the reference/character reviewer.
6. Checks the whole batch against that coverage. Missing run/attack/etc. remains incomplete even if a death clip is finished. Current exported-art reviews are required before `batch.py finish` succeeds.

See the [batch coverage contract](plugins/sprite-motion-kit/skills/sprite-motion/references/batch-coverage.md) for the required manifest and completion commands. The AI derives action IDs from the user's project. Scope is recorded before individual jobs so a partial repair cannot silently replace a full animation-set request.

### Pose correspondence and rejected drafts

Normal humanoid walk references with permanently folded knees are rejected before image generation. Final sprite export now requires per-frame observed landmarks matching the exact source image and guide. Directed limb angles are compared in fixed anatomical order, so repeating a trailing-leg pose cannot substitute for the passing/forward-extension phase. `pose-template` creates the observation form; the host must inspect pixels and must not copy guide coordinates into it.

`pack --draft` remains available to inspect a failed generation. Drafts and older exports without correspondence evidence cannot complete a batch. All frames share one export transform; row-specific grounding and per-frame recentering are no longer used in the default legacy export path. A changed source or guide invalidates its evidence.

These are rejection checks, **not a perfect-animation guarantee**. Joint annotations are supplied by the inspecting AI; this plugin does not contain a pixel pose detector. Incorrect or invented annotations can invalidate the conclusion. Normal-speed playback, identity/weapon consistency, uncertain occlusions and user-requested approval remain required. First validate one sample; do not expand a rejected pipeline across the user's roster.

The default custom-plan scaffold contains neutral keys and is marked `needs_motion_design`. The AI must author the requested action. Familiar sample motions are explicitly opt-in examples; they are not a closed action menu or a claim of finished animation quality.

## Agent / contributor commands

```sh
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/batch.py create --spec scope.json --out jobs/batch
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/mannequin.py create --body humanoid --actions overhead_cut thrust collapse --out jobs/plan.json
# The AI edits joints, key poses, timings and descriptions, then marks the plan authored.
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/mannequin.py validate --plan jobs/plan.json
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/mannequin.py render --plan jobs/plan.json --out jobs/reference
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py prepare --character character.png --motion-plan jobs/plan.json --out jobs/character
# Inspect actual references and record matching hashes/checks before generation.
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py review-reference --job jobs/character --report reference-review.json
# Inspect the actual provider schema and record real parameters and supported sizes.
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py generation-check --job jobs/character --adapter provider.json
# The host passes the packet's tool_arguments as actual API arguments and uses all three references.
# Inspect a source-bound crop overlay and annotate actual generated joints before final packing.
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py pack --job jobs/character --action overhead_cut --image generated-cut.png --observations observations.json --crop-plan crop.json
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/batch.py attach --batch jobs/batch --character guard --job jobs/character
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/batch.py status --batch jobs/batch
# Review all exported actions, then finish; missing actions cause a nonzero exit.
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/batch.py finish --batch jobs/batch
```

See the [motion contract](plugins/sprite-motion-kit/skills/sprite-motion/references/motion-contract.md) for coordinates, joint hierarchy, arbitrary action IDs, root movement, camera, timing and loop rules. Humanoid and quadruped topologies are convenient scaffolds; the JSON can define other joint trees without editing the renderer.

`guide-review.html` shows the 3D reference. A packed job's `review.html` shows reference and character together with pause, slow motion, replay and stepping. Both work offline.

## Alignment and limits

Custom jobs use a fixed camera and shared canvas transform. Jump height, lunges and full-size fallen bodies survive export; frames are not independently floor-aligned or stretched. Loop endpoints must match. One-shot actions hold their final frame. The original CC0 side-view walk/death workflow requires an explicit `--legacy-reference-reason` when used without `--motion-plan`.

The renderer is a shaded skeletal proxy, not a physics or character-animation model. The AI must inspect support, balance, collisions and pose transitions. The image generator receives a visual guide, not guaranteed hard skeletal conditioning; it may still introduce costume or anatomical errors. Technical export never marks the art visually approved.

Use true alpha for characters with bright magenta details. Baked white/checkerboard backgrounds and clipped cells are rejected. Dark purple artwork is preserved by the narrower magenta key.

Custom schema-2 plans and imported schema-3 references use the same generation gate. Preparation defaults to `--background-mode magenta`; select `alpha` for a character containing the key color. Reference review alone does not unlock generation. The provider adapter must record actual inspected parameters and confirmed sizes; prompt-only tools are blocked for production. The script checks this declaration and writes a packet, but does not invoke the provider or verify that the host submitted those arguments. See the [adapter contract](plugins/sprite-motion-kit/skills/sprite-motion/references/imported-references.md). An explicitly requested `--diagnostic` preview remains nonproduction, and its preflight cannot be changed later to approve the same generated art.

## Development and distribution

### Experimental generation execution

The optional [sequence-conditioned backend](plugins/sprite-motion-kit/skills/sprite-motion/references/conditioned-generation.md)
passes measured 3D pose controls, character identity and the entire action
sequence to a local Diffusers pipeline. Unlike the default host-tool packet, it
contains an actual inference call. It does not include weights, download models
or run automatically. **The first actual eight-frame trial completed inference
but failed visually: the character was severely blurred and unusable. This is
not a replacement for the host image generator or a stable animation fix.** Preparing control images or passing
mocked API tests is not a successful character-generation result. All outputs
remain diagnostic until separately reviewed.

A subsequent trial corrected reference-image padding, prompt truncation and
scheduler configuration but still produced unusable blurred art. These changes
are retained as experimental code, not enabled as the default generation route.

The optional model setup script downloads the pinned files directly from their
upstream repositories and checks exact sizes and SHA-256 values. Model weights
are not included in this MIT repository; their separate licenses still apply.
Reproducible installation does not imply reproducibly good animation.

```sh
python -m unittest discover -s tests -v
python scripts/package.py
```

Code, procedural renderer and workflow: **MIT** (modify, redistribute, commercial use permitted). Bundled legacy references: **CC0**, derived from Quaternius' Universal Animation Library. User character artwork and generated outputs retain their own applicable rights.

This repository contains no private game code, saves, credentials or model weights. The explicit review examples contain generated sample artwork. See [privacy](docs/PRIVACY.md), [terms](docs/TERMS.md) and [official directory status](docs/OFFICIAL-SUBMISSION.md). GitHub distribution is independent of OpenAI's public directory; no official listing is claimed.

## 三维参考路线的生成前置检查

默认入口必须提供角色分析、动作构思和自定义三维方案。工具先生成参考，AI 实际检查并提交记录，再通过真实生成工具的尺寸能力声明检查后才解锁生成请求；自定义方案与导入参考使用相同门槛。仅支持提示词的工具只能在用户明确要求的诊断预览中使用，诊断不能转为正式素材。替换角色图、方案或参考图会使检查失效。旧模板只可通过 `--legacy-reference-reason` 显式复用，不再作为缺省流程。检查记录不等于美术质量认证。详见插件内 motion-contract。
