# Sprite Motion Kit

**角色原图 + 完整动作参考 → AI 连续帧 → 透明图集 → 同步播放检查。**

A Codex plugin for authoring humanoid game-character walk and death animations. It gives the AI agent a reusable workflow, side-profile mannequin references, local extraction tools, and an offline visual reviewer.

This is an early **authoring toolkit**, not an animation model. The pose guide is a visual reference rather than a hard skeleton constraint. Generated anatomy and costume consistency still require inspection.

## 安装 / Install

Use a Codex release with plugin marketplace support:

```sh
codex plugin marketplace add Chencole/sprite-motion-kit
codex plugin add sprite-motion-kit@personal
```

The repository catalog currently uses the name `personal`. If you already configured a catalog with that name, use a local clone and choose a distinct catalog name before adding it. The [official packaging documentation](https://developers.openai.com/plugins/build/plugins) describes repository marketplaces and installation.

After installing, start a new Codex task and ask it to use **Sprite Motion Kit** with your character image. The agent runs the preparation, generation and export steps. It needs an available image-generation tool plus Python 3.10+, Pillow and NumPy:

```sh
python -m pip install -r plugins/sprite-motion-kit/requirements.txt
```

The plugin itself has no subscription, login, hosted API or generation credits. Your chosen image-generation provider may have its own costs and terms.

## 用法 / Usage

Attach a character and say:

> 用 Sprite Motion Kit，让这个角色按纯侧面参考生成完整行走和倒地，保留原来的外形。先给我正常速度、慢放和逐帧检查，再决定是否导入游戏。

The workflow:

1. Inspect the character and the requested camera direction.
2. Prepare an isolated job with the character, guides and generation requests.
3. The host AI generates a complete sheet for each requested action.
4. Export transparent frames, an atlas, origins, timing metadata and a contact sheet.
5. Open `review.html`: reference and character play together; pause, slow down, step across a walk loop, or hold the final death pose.

The included reference is **pure side view, facing right**. Walk has 8 key poses across a full two-step cycle; death has 12 poses. Both have a 72-frame reference preview. Extra poses and nonuniform timing are supported when repairing a loop. Other views, running, quadrupeds and flight need suitable additional references.

## Local helper commands

These are for the AI agent or contributors, not a requirement to manually operate the workflow:

```sh
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py prepare --character character.png --out jobs/example
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py pack --job jobs/example --action walk --image generated-walk.png
python plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py pack --job jobs/example --action death --image generated-death.png
```

Open `jobs/example/review.html`. Jobs preserve source sheets and default to `awaiting_visual_review`; a successful export does not mark the art approved. Packing does not invent missing walk poses or remove frame-to-frame costume changes.

Use real transparency where possible. A flat magenta background can be keyed, but this can remove magenta costume details; choose alpha for characters containing that color. Baked white/checkerboard backgrounds and frames touching cell edges are rejected. The tool uses one scale per action and retains a full-size prone body for death. Review the alignment before import, especially hats, unusual proportions and separate dropped weapons.

## Structure and contributions

```text
.agents/plugins/marketplace.json          Repository plugin catalog
plugins/sprite-motion-kit/                Installable plugin
  .codex-plugin/plugin.json
  skills/sprite-motion/SKILL.md           Agent workflow
  skills/sprite-motion/assets/            CC0 references and review template
  skills/sprite-motion/scripts/motion.py  Local preparation/export
tests/                                   Offline regression tests
docs/                                    Privacy, terms and submission notes
```

Run `python -m unittest discover -s tests -v`. Contributions to reference actions, alignment and review controls are welcome. Include motion provenance and a visual comparison; do not add artwork you lack permission to distribute.

## Licensing and distribution

Code and workflow: **MIT** — modification, redistribution and commercial use are permitted under the license. Bundled reference renders: **CC0**, derived from Quaternius' Universal Animation Library; see the included provenance and full license. User artwork and generated outputs retain their own applicable rights; the MIT license does not grant rights to third-party character designs or model services.

This repository contains no private game source, game saves, character artwork, credentials or model weights. See [privacy](docs/PRIVACY.md), [terms](docs/TERMS.md) and [official directory submission notes](docs/OFFICIAL-SUBMISSION.md). **GitHub distribution is independent of OpenAI's public directory; no official listing or endorsement is claimed.**
