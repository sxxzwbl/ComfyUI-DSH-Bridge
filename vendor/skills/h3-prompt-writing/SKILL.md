---
name: h3-prompt-writing
description: Write MiniMax H3 video generation prompts for T2VA, I2VA, FL2VA, L2VA, and Ref2VA, and adapt the six-section Ref2VA structure to image editing and modification. Use when rewriting multimodal or image-modification requests into H3 prompt structures, composing integrated_multimodal_description, overall_soundscape, and non_diegetic_music, aligning keyframes, or defining reference labels for images, videos, and audio.
compatibility: Portable to any agent that can read local files — no external API calls, MiniMax Hub tools, or proprietary runtime required. The agents/openai.yaml file only adds optional ChatGPT/Codex UI metadata; it does not restrict the skill to OpenAI agents.
---

# H3 Prompt Writing

## Workflow

1. Identify the input mode: T2VA, I2VA, FL2VA, L2VA, or full-reference Ref2VA.
2. For base text/keyframe modes, read `references/base-en.txt` and follow its final prompt structure.
3. For full-reference mode, read `references/ref-en.txt` and follow its six-section rewrite format.
4. Preserve the exact field names, section order, labels, and timing notation from the selected guide.
5. For image editing / modification requests, apply the 六段式速查（用于图片修改）section below and fill both audio sections with N/A.

## Base Modes

- T2VA: build the full audiovisual timeline from text.
- I2VA: start from the first frame and develop forward from it.
- FL2VA: describe the continuous path between the first and last frames.
- L2VA: infer a plausible opening and converge to the supplied last frame.

Use `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music` in the order shown in `references/base-en.txt`.

## Full-Reference Mode

Ref2VA rewrites use `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, and `non_diegetic_music` in that order. Reference labels stay consistent across all sections.

Read `references/ref-en.txt` for label rules, retention analysis, and complete examples.

### 编号纪律（先定表再写）

`<Picture N>` 的编号**由输入声明给定**，而输入声明来自用户描述的顺序，不是自由命名，也不等于我们的 socket 顺序。开工前先把表抄下来，之后每一段都按这张表写：

| 用户怎么说 | `<Picture 1>` | `<Picture 2>` |
|---|---|---|
| 什么都没说 / 只说参考图 | 参考图 | 帧图不编号、不引用 |
| 「输入帧图和参考图」 | 帧阵列图 | 参考图 |
| 「输入参考图和帧图」 | 参考图 | 帧阵列图 |

三条硬约束：

1. **被编号的帧阵列图必须被引用。** 它物理上进了模型输入，提示词却不提，等于丢掉最强的动作约束。`subject_definitions` 里单独一条说明它只提供动作，`detailed_description` 里写 `the action ... follow <Picture N> frame by frame`。
2. **同时否定它的人物属性。** 帧图里的表演者、发型、服装、配饰不继承，在 `retention_analysis` 里写 `partially_preserved`：动作继承、外观不继承。
3. **绝不写 `<Video N>`。** 本次没有视频输入。任何「跟随源视频」「参考视频」的说法都要换成 `<Picture N>` 或纯文字。

编号写错是不可恢复的：`<Picture 1>` 被当成身份源而它实际是帧阵列图，生成出来的就是「气质相近的另一个人」。

## 六段式速查（用于图片修改）

将 Ref2VA 六段式结构用于图片修改任务时，按以下速查执行。`retention_analysis` 是编辑指令核心。

- `subject_definitions` — `<Subject N>` 绑定 `<Picture N>`，特征点写清
- `summary` — 一句话任务书
- `retention_analysis` ★ — 保留什么 / 改什么：
  - `partially_preserved` = 主力：逐项列"保留清单"（face, hair, eyes, pose retained exactly）+ "替换指令"（X replaced by Y），越具体越听话
  - `attribute_transfer` = 跨角色迁移（Subject 1 = 身份来自图A，Subject 2 = 服装来自图B）
  - 3D/动漫转真人（cosplayer 重构）：保留清单只放可穿戴件（假发/美瞳/服装），脸写 NOT retained，替换成真人
- `detailed_description` — 静态镜头 + 构图锚点（"entire body from head to toes visible, headroom above, floor space below" 防裁切）+ 目标细节
- `overall_soundscape` / `non_diegetic_music` — 图像任务填 `N/A` 即可

完整黄金示例见 `references/image-edit-example.txt`（涂鸦狐狸→3D 渲染）。注意示例中的关键惯例：summary 用 `[reference generation]` 前缀；`detailed_description` 保留单镜头静态视频骨架（"The target video uses ... [Shot 1] ... The camera holds completely still."）；构图锚点写法为 "entire body visible from ears to feet with space above and below"；`overall_soundscape` 也可只填一句轻环境音。

### 相似图防泄漏：donor 降级法

当身份图与服装图高度相似（同为白底全身、同发色、同色系服装）时，模型易把服装图整张复制（身份泄漏）。按以下方式修复：

- **服装图降级为 donor**：`<Picture 2>` 单独一条定义，写死 "used ONLY as a garment donor — the face, hair, skin, body and pose of the wearer are NOT referenced and must NOT appear in the output"
- **retention_analysis 显式否定 donor**：donor 条目用 `weak_reference - only garment shape, color and texture are read from it; the model's appearance is explicitly excluded`；服装迁移条目补一句 "her face, hair, hairstyle, body and pose are NOT transferred and must not replace <Subject 1>"
- **姿势单独绑定**：新增 `<Subject N>` = 姿势身份（来自 `<Picture 1>`，逐项写清：直立面向镜头、双臂垂放、肩头水平、双腿并拢等），标 `fully_preserved`，并写 "NOT the pose of the woman in <Picture 2>"
- **detailed_description 双向锚定**：开头声明 "The output is an edited version of <Picture 1>"；中段补 "identical to <Picture 1>, NOT the silver-white hair or the face of the woman in <Picture 2>"；服装褶皱写 "re-draped to fit the pose of <Subject N>"，切断服装带着 donor 姿势走的泄漏路径
- **实操**：图1 永远放第一张、服装图放第二张，顺序不换；若仍向服装图漂移，把服装图裁剪成纯服装局部（不含头部）再喂，效果最稳

## Output Rules

- Write rewrite sections in English; preserve dialogue, lyrics, and visible scene text in their original language.
- Describe each shot by composition, subjects, environment, actions, camera, sound, and the exact point where referenced content appears.
- Avoid plot summaries, unresolved reference labels, and timing that does not match the requested duration.
## Tips for Better Results
- Always match the total duration of the description to the requested video length (4–15 seconds).
- Keep reference labels consistent (e.g. `<Picture 1>`, `<Video 1>`, `<Audio 1>`) across every section.
- Prefer concrete visual and audio details over abstract words like "cinematic" or "beautiful".
- When using keyframes (I2VA / FL2VA / L2VA), clearly state how the first and/or last frame connects to the timeline.
