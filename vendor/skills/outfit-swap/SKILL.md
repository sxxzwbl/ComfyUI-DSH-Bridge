---
name: outfit-swap
description: 把视频里的人换成另一套衣服，人或场景保持不变，输出 MiniMax H3 提示词。源视频只作为信息源被读成文字；服装来源可以是服装图、穿着该服装的模特图，或一句文字要求。当需要换装、服装替换、改穿搭、保留人不保留衣服、按参考图换整套造型时使用。
---

# 服装替换（源视频 + 服装图 → H3 提示词）

> **移植性**：第零～四节（人物来源路径、输入契约、服装三形态、换装映射）与目标模型无关。**第五节「六段式填充」是 MiniMax H3 专属**，换模型时替换为对应格式的 compose skill，逻辑部分不动。

前提和 `person-swap` 完全一致：**源视频只做信息源，不作为生成输入**，输出里不出现 `<Video N>`。差别只在换什么——这里是换衣服，不换人。

## 零、先定一件事：人物从哪来

这是本 skill 最容易搞错的地方。默认规则是「人物相关的一切取参考图」，但换装场景常常**只给服装图、没给人图**，这时就必须回到文字。

| 路径 | 输入 | 人物外观 | 服装 |
|---|---|---|---|
| **A · 只给服装图** | 源视频 + 服装图 | **必须文字描述**（没有人物参考图） | 指认来自服装图 |
| **B · 人图 + 服装图** | 源视频 + 人物图 + 服装图 | 指认来自人物图 | 指认来自服装图 |
| **C · 只给文字要求** | 源视频 + 「换成白衬衫」 | 必须文字描述 | 必须文字描述 |

**A 和 C 路径的硬限制，必须在 `analysis` 里告诉用户**：没有人物参考图时，只能保证「衣服对了」，不能保证「还是同一个人」——文字描述的人长什么样，取决于模型怎么理解那段字。要保住人脸一致，必须走 B，给一张人物图。

## 前置：先加载这三个 skill

1. `sequence-sheet-read` —— 读帧拼图
2. `shot-grammar` —— 动作、运镜、景别
3. `character-sheet` —— 服装维度清单、donor 降级、「只指认不复述」
4. `h3-prompt-writing` —— 六段式字段名与 retention 标记词

## 一、输入契约

| 槽 | 角色 | 只看什么 | 禁止看什么 |
|---|---|---|---|
| 帧拼图 | 源视频＝信息源 | 人物数量位置、动作、镜头、场景、光线 | 原服装（要被换掉） |
| `ref_person`（可选） | 人物身份 | 脸、发型、肤色、体型、年龄感 | 它的服装（除非用户说要一起换） |
| `ref_garment` | 服装来源 | 版型、色、面料、纹样、长度、领型、袖型、配饰、穿法 | 穿着者的脸、发型、身材、姿势、背景 |
| `cast_spec` | 规则 | 换谁的衣服、保留什么、服装图是纯服装还是穿着图 | — |

**参考图混在一组时怎么分辨**：默认位置约定是「`P1` = 人物，`P2` 起 = 服装」；用户写了 `P1=人物, P2=服装` 这类标注就按标注来。`analysis` 里回显你的理解：
`我这样理解你的图：P1=人物身份，P2=服装来源`。

## 二、服装来源的三种形态

| 形态 | 判断信号 | 处理 |
|---|---|---|
| 纯服装图（平铺、衣架、无头无脸） | 图里没有人脸 | 直接指认，`comes from <Picture 2>` |
| 穿着服装的模特图 | 图里有人脸 | **走 donor 降级**（见下） |
| 纯文字要求 | 没有图 | 写进文字，维度照 `character-sheet` 的九项，缺项写「不确定」 |

**判不准一律按「有人」处理**——宁可多排除，不可泄漏。

### 穿着图的 donor 降级（照 `character-sheet` 执行）

```text
<Picture 2> is used ONLY as a garment donor — the face, hair, skin, body and pose of the wearer are NOT referenced and must NOT appear in the output.
```

三条配套动作少一条都会泄漏：

1. `retention_analysis` 里 donor 给 `weak_reference`：`only garment shape, color and texture are read from it; the model's appearance is explicitly excluded`
2. **姿势单独绑定到人物来源**：`<Subject N>` 或文字描述，标 `fully_preserved`，并写 `NOT the pose of the wearer in <Picture 2>`
3. 褶皱写 `re-draped to fit the pose of the subject`，切断「衣服带着模特姿势走」

身份图与服装图高度相似（同为白底全身、同发色）时泄漏概率最高。实操顺序固定：**人物图放第 1 张、服装图放第 2 张，不换**；仍漂移就把服装图裁成纯服装局部（不含头部）再喂。

## 三、三步流程

**第 1 步 · 人物盘点**（`cast-inventory`）

换谁的衣服要先知道有几个人。单人直接过；多人必须按第三节的优先级定。

**第 2 步 · 动作与镜头**（`sequence-sheet-read` + `shot-grammar`）

换装不改变动作。动作、走位、镜头、场景、光线全部照原样文字化。

**第 3 步 · 合成映射**

| 情形 | 动作 |
|---|---|
| 画面只有一人 | 直接换 |
| 多人 + 用户给了序号 | 只换指定序号的人 |
| 多人 + 未给序号 | 换画面主体（`cast-inventory` 的四步量化规则），其余保留原服装 |
| 多人 + 说要换全部 | 全部换，但要说明服装数量是否够（不够就循环套用并提醒） |

**任何情况都不报错中止**，配不上就保留 + 提醒。

## 四、`analysis` 必须回显

```
换装映射：S2（主体）→ 服装来自 P2
外观归属：人物 → P1（指认）｜服装 → P2（指认，donor 降级）
保留原样：S1、S3 的服装不动
依据：S2 占画面约 38%、位于中心
限制：如果有……
```

A / C 路径（无人物图）时，第二行改成 `人物 → 文字描述（无参考图，人脸一致性不保证）`。

## 五、六段式填充

**1. `subject_definitions`**

```text
<Subject 1> is the single woman in the target video. Her face, facial features, hair, hair colour, skin tone, body build and age impression are taken from <Picture 1> and must read as the same person. Her outfit comes from <Picture 2>: the garment is read from it and re-draped onto her body in her own pose. Her expression may differ from <Picture 1>.

<Picture 1> is the identity source. Its own outfit, grey studio backdrop, pose and studio lighting are NOT referenced.

<Picture 2> is used ONLY as a garment donor — the face, hair, skin, body and pose of the wearer are NOT referenced and must NOT appear in the output.

The scene, the camera, the action and the timing are described in text below. No reference video is used for this shot.
```

**指认，不复述**：服装只写「来自 `<Picture 2>`」，不要重新描述它是什么颜色什么版型。指认可以点名单品（`the sweatshirt and the headband`），复述不行。

**2. `summary`**

一句话任务书：谁、穿哪件、在什么场景做什么。

**3. `retention_analysis`**

四条左右：

```text
<Subject 1> (appears in [Shot 1]): partially_preserved - face, hair, skin tone and build come from <Picture 1>; the outfit is replaced by the garment in <Picture 2>; pose, motion and blocking follow the description below.
<Picture 1> (identity source): fully_preserved - face, hair, skin tone and build are read from it; its own outfit, backdrop and pose are NOT referenced.
<Picture 2> (garment donor): weak_reference - only garment shape, colour and texture are read from it; the wearer's face, hair, body and pose are explicitly excluded.
<Subject 1> pose: fully_preserved - the stance, limb positions and head angle follow the description below, NOT the pose of the wearer in <Picture 2>.
```

**4. `detailed_description`**

逐镜头生成指令，和 `person-swap` 同样的硬要求：构图给硬上限、动作给硬幅度、时间戳 0.5s 精度、场景光线全文字化。

服装只在两处出现：`subject_definitions` 指认一次，`detailed_description` 里最多提一句褶皱/贴合（`the garment hangs loose over her hips`），不再重复描述款式。

**5. `overall_soundscape` / 6. `non_diegetic_music`**

与 `person-swap` 一致。没人说话就不设 `(S1)`，不编台词。

## 六、输出卫生

同 `person-swap`：`prompt` 零污染、纯文本、无 Markdown、无 `<Video N>`、无元话语、无中文说明。

额外一条：**不要出现「换了衣服」「替换后的服装」这类叙述句**。下游不需要知道这是编辑，只需要知道画面里是什么。

## 七、自检

- [ ] 人物来源路径（A / B / C）判断正确，`analysis` 里写明了
- [ ] 走 A / C 时提醒了「人脸一致性不保证」
- [ ] 服装只指认不复述；点名单品可以，描述版型不可以
- [ ] donor 降级三条配套动作齐全（声明 / 姿势单绑 / 褶皱重垂）
- [ ] 参考图顺序回显正确（P1 人物、P2 服装）
- [ ] 多人时写了换谁、保留谁
- [ ] 全文无 `<Video N>`，无「替换」「编辑」类叙述句
- [ ] 动作与镜头描述与源素材一致，没有被服装改动

## 八、边界

- **A / C 路径不保证人脸一致**：文字描述的人长得像不像，取决于模型理解；要保脸就必须给人物图
- 缩图会丢面料与纹理，精确复刻服装需要高分辨率单图
- 复杂层次服装（外套 + 内搭 + 裤装）在多张单调的参考图之间容易串味，建议一次只换一套
- 交付的是可生成提示词，不是渲染结果
