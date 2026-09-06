# Sprite Motion Kit

**用户需求 → AI 设计三维体型与动作 → 木头人参考 → AI 角色帧 → 图集与可视化检查。**

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

1. Records the complete requested character/action coverage, then interprets body, view and timing.
2. Authors a JSON rig and whole-body key poses, including attached weapon endpoints and extra limbs as needed.
3. Validates and renders that custom motion locally; inspects and corrects its poses.
4. Feeds each actual pose guide and the original character to the available image tool.
5. Checks the generated grid, transparency and continuity, exports frames/atlases, and opens the reference/character reviewer.
6. Checks the whole batch against that coverage. Missing run/attack/etc. remains incomplete even if a death clip is finished. Current exported-art reviews are required before `batch.py finish` succeeds.

See the [batch coverage contract](plugins/sprite-motion-kit/skills/sprite-motion/references/batch-coverage.md) for the required manifest and completion commands. Action IDs are user-defined. Scope is recorded before individual jobs so a partial repair cannot silently replace a full animation-set request.

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
# The host image tool generates the action sheet from this job's guide and character.
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py pack --job jobs/character --action overhead_cut --image generated-cut.png
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

## Development and distribution

```sh
python -m unittest discover -s tests -v
python scripts/package.py
```

Code, procedural renderer and workflow: **MIT** (modify, redistribute, commercial use permitted). Bundled legacy references: **CC0**, derived from Quaternius' Universal Animation Library. User character artwork and generated outputs retain their own applicable rights.

This repository contains no private game code, saves, character artwork, credentials or model weights. See [privacy](docs/PRIVACY.md), [terms](docs/TERMS.md) and [official directory status](docs/OFFICIAL-SUBMISSION.md). GitHub distribution is independent of OpenAI's public directory; no official listing is claimed.

## 生成前置检查

默认入口必须提供角色分析、动作构思和自定义三维方案。工具先生成参考，AI 实际检查并提交记录后才解锁生成请求。替换角色图、方案或参考图会使检查失效。旧模板只可通过 `--legacy-reference-reason` 显式复用，不再作为缺省流程。检查记录不等于美术质量认证。详见插件内 motion-contract。
