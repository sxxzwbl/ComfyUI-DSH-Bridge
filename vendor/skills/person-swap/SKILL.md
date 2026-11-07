---
name: person-swap
description: 把源视频里的人换成参考图中的人，输出 MiniMax H3 提示词。帧阵列图（源视频抽帧拼图）与人物参考图都作为图片输入，帧图是动作/构图/运镜的参考（<Picture 1>），参考图是身份与服装来源；人物相关的一切默认全部取参考图，只有显式声明"保留原服装/发型/耳环"时才保留源那一部分。当需要人物替换、换人、只换人不换动作、多人按从左到右序号替换、未指定时男换男女换女、多人时替换画面主体时使用。
---

# 人物替换（帧阵列图 + 人物参考图）

> **移植性**：第零～五节（默认归属、输入契约、三级优先级、保留声明、回显格式）与目标模型无关。**第六节「六段式填充」是 MiniMax H3 专属**，换模型时替换为对应格式的 compose skill，逻辑部分不动。

## 零、默认形态（先看这条，它决定了整个输出长什么样）

**两类素材都是图片，编号必须照节点给的写。** 帧阵列图是 `<Picture 1>`（多张时依次往后），人物参考图接在它后面。物理顺序 = 附件顺序，不许重排。

**帧阵列图是动作参考，不是"读过的资料"。** 它已经在 `<Picture N>` 序列里，所以提示词里要明确引用它作为动作、构图、景别、运镜的来源（`the action ... follow <Picture 1> frame by frame`）。只在心里读成文字却不引用，等于把最强的动作约束丢掉——这正是"人物换了、动作全变了"的主要原因。

**但它的人物属性一律不继承。** 帧图里的表演者、发型、服装、配饰全部被换掉，换成人参参考图那位。这在 `retention_analysis` 里写 `partially_preserved`：动作继承、外观不继承。

**输出里永远不出现 `<Video 1>`。** 本次没有任何视频输入，帧阵列图是静态图片，指认它用 `<Picture N>`。

**人物相关的一切默认取参考图**：人物本体、发型、服装、配饰（耳环、项链、发带、帽子、手套、包）。参考图里的像素比任何文字都准，没有理由放着不用。

**只有显式声明才保留源视频的部分。** 用户说「换人但保留原服装」「发型不要换」「耳环保留」这类话时，才把那一项文字化并否定参考图的对应部分。没说的部分一律取参考图。

| 项 | 默认来源 | 何时改为源 |
|---|---|---|
| 脸 / 五官 / 肤色 / 体型 / 年龄感 | 参考图 | 永不（这就是"替换"本身） |
| 发型（盘/披/编、长短、发色） | 参考图 | 声明「保留原发型」时 |
| 服装（上衣、裤装、外套、鞋） | 参考图 | 声明「保留原服装」时 |
| 配饰（耳环、项链、发带、帽子、包） | 参考图 | 声明「保留原配饰 / 保留耳环」时 |
| 表情 | 文字指定 | — |
| 姿势、动作、走位 | `<Picture 1>` 的动作 + 文字 | 永远是 |
| 场景、光线、镜头、音效 | 文字（从帧阵列图提取） | 永远是 |

## 前置：先加载这三个 skill

1. `sequence-sheet-read` —— 把帧拼图读成「谁在哪、在做什么、镜头怎么动」
2. `shot-grammar` —— 动作、运镜、景别、切点的英文写法
3. `h3-prompt-writing` —— 六段式字段名与 `retention_analysis` 标记词表

标记词只有这四个（可见内容）：`fully_preserved` / `partially_preserved` / `attribute_transfer` / `weak_reference`；音频是 `fully_copy` / `partially_copy` / `reference` / `weak_reference`。用错词等于没写。

## 一、输入契约

| 槽 | 编号 | 角色 | 只看什么 | 禁止看什么 |
|---|---|---|---|---|
| 帧阵列图 | `<Picture 1>` | 动作 / 构图 / 运镜参考 | 人物数量与位置、动作、走位、镜头、背景、光线、音效线索 | 原人物的长相（要被替换掉） |
| `ref_person_1..n` | `<Picture 2>` 起 | 替换用人物＝**外观全来源** | 脸、发型、肤色、体型、年龄感、服装、配饰 | 他们的姿势与背景 |
| `cast_spec`（可选） | — | 替换规则与保留声明 | 序号、性别、保留原 X | — |

`cast_spec` 的三种写法都要认：

- 序号式：`左1换A 左3换B`、`1=female; 3=male`、`把左边第 2 个人换成这张`
- 位置约定式：`P1=身份A, P2=身份B`（参考图顺序有歧义时用）
- **保留声明式**：`换人，保留原服装`、`脸换成她，发型保持原样`、`耳环别动`

## 二、三步流程（顺序不可换）

**第 1 步 · 人物盘点**（只看 1–2 格就够）

按 `cast-inventory` 出盘点表：序号（从左到右）、位置、占比、外观性别与依据、年龄感、体型、是否主体。主体判定用它规定的四步量化规则（面积 → 中心 → 景深 → 从左到右），不要凭感觉。

```
序号 | 位置 | 判定依据 | 外观性别 | 是否主体
S1 | 左约 20% | 站姿、短发 | 男 | 否
S2 | 中约 50% | 长裙、长发、占画面约 40%、位于中心 | 女 | 是
```

**第 2 步 · 动作与镜头**（读完整拼图）

按 `sequence-sheet-read` 逐格读，按帧密度选粒度：

| 帧密度 | 粒度 | 写法 |
|---|---|---|
| ≤8 帧或 >8s | 状态迁移 | `starts at ..., ends at ...`，中间用 `the motion between these points is continuous` 兜住 |
| 12–16 帧 / 4–8s | 分段 | `in the first half ...; toward the end ...` |
| >16 帧 / <4s | 动词序列 | `lifts the right foot → plants it forward → shifts weight` |

写进提示词时**不要出现「未观察」「抽样」**这类分析语言，那是 `analysis` 里的事。生成提示词要的是连续动作。

**第 3 步 · 合成映射并落位**

按第三节定换谁、按第三节定哪些保留原样，然后填六段式。

## 三、替换优先级（三级，逐级降级）

**第一级 · 显式序号**

| 情形 | 动作 |
|---|---|
| 给了序号/位置 | 严格按序号替换，不管性别是否匹配 |
| 序号超出实际人数 | 跳过该条，其余照做，`analysis` 记一行 |

**第二级 · 性别配对**（无序号时）

| 源 / 参考 | 动作 |
|---|---|
| 参考数 = 人数，性别能一一配上 | 同性一一配对 |
| 参考数 < 人数 | 只换能配上的同性，其余保留原样 |
| 参考数 > 人数 | 多余参考忽略 |
| 同性数量不匹配 | 男图配男、女图配女，剩下的走第三级 |

**第三级 · 主体优先**

性别线索不足以决定时，替换画面主体，其余保持原样。

**任何情况都不许报错中止。** 配不上就保留原样 + 提醒，照样输出完整可用提示词。

## 四、保留原样时要怎么写

用户声明保留某一项时，那一项**没有图片承载**，必须写成具体文字，并在 `retention_analysis` 里否定参考图的对应部分。

`subject_definitions` 里：

```text
<Subject 1> takes her face, hair colour and body build from <Picture 1>.
She keeps the pale taupe thin-strap camisole top, the long silver beaded tassel earrings and the thin black cord necklace with a small gold pendant from the original source footage.
```

`retention_analysis` 里：

```text
<Subject 1> (appears in [Shot 1]): partially_preserved - face, hair and build come from <Picture 1>; the pale taupe camisole top, silver tassel earrings and black cord necklace are carried over as described in text; pose and motion follow the description below.
<Picture 1> (identity source): fully_preserved - face, hair, hair colour, skin tone and build are read from it; its rose-print sweatshirt, oxblood velvet headband, grey studio backdrop, raised hand and studio lighting are NOT referenced and must not enter the frame.
```

没声明保留的部分，不要写「来自源视频」，也不要写它的文字描述——它就来自参考图。

## 五、必须回显的映射表

放在 `analysis` 第一段，格式固定：

```
替换映射：S1→P1（同性/女），S2→保留原样
外观归属：脸/发型/服装/配饰 → P1（默认全取参考图）
保留原样：无（或：服装与耳环保留源视频）
依据：P1 盘发+玫瑰卫衣，判定女性；S2 男性无匹配
提醒：S3 无可用参考，保持原样
```

第二行「外观归属」是这次默认反转之后必须有的，用户扫一眼就知道我按哪种理解在做。

## 六、六段式填充（不含 `<Video N>`）

### 先画编号表

编号**不是固定的**，由输入声明给定，而输入声明来自用户描述的顺序。开工前把声明里的对照表抄下来，之后每一段都按它写。

| 用户怎么说 | `<Picture 1>` | `<Picture 2>` |
|---|---|---|
| 什么都没说 / 只说「参考图」 | 参考图 | 帧图若不编号则不被引用 |
| 「输入帧图和参考图」 | 帧阵列图 | 参考图 |
| 「输入参考图和帧图」 | 参考图 | 帧阵列图 |

多张参考图按输入序号依次往后排。**照抄声明，不要按自己的习惯重排。**

如果声明里说帧阵列图「不参与编号」，那它只用来给你读动作，提示词里一个 `<Picture N>` 都不能指向它——动作只能靠 `detailed_description` 的文字承载。这种情况下 `retention_analysis` 里也不要出现帧图条目。

### 帧阵列图是动作参考，不是"读过的资料"

**前提：它被编号了。** 如果声明里它不参与编号，跳到本节末尾的替代写法。

一旦它在 `<Picture N>` 序列里，就该在提示词里被明确引用为动作来源。只在心里读完、再写成文字、却不引用它，等于把最强的动作约束丢掉了。`detailed_description` 里要有一句把它钉在运动上（编号按声明替换，下面的 `1`/`2` 只是示例）：

```text
The action, the shot scale progression and the camera movement follow <Picture 1> frame by frame.
```

同时否定它的人物属性：

```text
The person, hair, outfit and accessories visible inside <Picture 1> are NOT carried into the target video; the identity comes from <Picture 2>.
```

**它没被编号时**（用户只说「参考图」或什么都没说）：动作全部靠 `detailed_description` 的文字承载，写清每个动作的动词、部位、方向、幅度和终点，不许留任何图片引用。这种形态本质上退化成 `video-replica` 的纯文字复刻 + 身份替换。

**1. `subject_definitions`**

```text
<Subject 1> is the single woman in the target video. Her face, facial features, hair, hairstyle, hair colour, skin tone, body build and age impression are taken from <Picture 2> and must read as the same person. Her complete outfit — including the rose-print sweatshirt and the oxblood velvet headband — also comes from <Picture 2>. Her expression may differ from <Picture 2>: here she is calm with her lips closed.

<Picture 2> is the identity and wardrobe source. Its grey studio backdrop, raised gesturing hand, studio lighting and frontal studio pose are NOT referenced and must not enter the frame.

<Picture 1> is the frame sheet of the target video: it supplies the action, the framing and the camera movement only. Everything visible inside it — the performer, her hair, her outfit, her accessories — is replaced by <Subject 1> as defined above.

The scene, the camera, the action and the timing are described in text below. No reference video is used for this shot.
```

**指认，不要复述。** 说「服装来自 `<Picture 2>`」是对的；把服装重新描述成 "a white oversized sweatshirt covered in large pink roses" 是错的。实测对比：只指认 → 脸像了、服装也对了；指认 + 文字复述 → 生成「气质相近的另一个人」。完整规则见 `character-sheet` 的「参考图在场时：只指认，不复述」。

**五官一个字都不写。** 同理，`oval face`、`defined upper eyelids` 这类词一旦出现，参考图就退化成"大方向参考"。

**2. `summary`**

一句话任务书，只用已定义的标签。不要出现「复刻」「跟随源视频」字样，但要写清动作来自 `<Picture 1>`：

```text
[reference generation] A single continuous vertical take with no cuts: <Subject 1>, exactly as she appears in <Picture 2>, repeats the action and framing of <Picture 1> in front of a matte black studio curtain.
```

**3. `retention_analysis`**

三条固定 + 可选一条保留项：

- `<Subject 1>`：外观来自 `<Picture 2>`，姿势/动作按 `<Picture 1>` 与下面的文字描述
- `<Picture 2>`：身份 + 服装来源，逐一否定它的背景、姿势、棚灯
- `<Picture 1>`：`partially_preserved` —— 动作、构图、景别、运镜继承；其中的人物外观一律不继承
- 若有保留项：单开一条写清「保留什么 + 来自源素材 + 文字已给描述」

```text
<Picture 1> (frame sheet of the target video): partially_preserved - the action, the shot scale progression and the camera movement are carried over; the performer, her hair, her outfit and her accessories inside it are NOT carried into the frame.
```

**4. `detailed_description`**

逐镜头的生成指令：
- `[Shot 1]` 不带时间戳，后续镜头 `[Shot 2] At 00:02.500, ...`
- **默认单镜头**：源素材是一镜到底时，全文只有 `[Shot 1]` 一段，景别变化写进运动描述，不许写 `hard cut`。判据见 `sequence-sheet-read` 第 3.5 节。一镜到底被切成多段，下游会生成几段动作互不相干的画面，人物替换就白做了
- 开头就把动作锚在帧阵列图上：`<Subject 1> performs the action shown across the frames of <Picture 1>.` 然后再展开具体动作
- 时间精度到 0.5s，不许伪精度
- 构图要**跟随源素材**：写清主体占画幅的大致比例（`occupies roughly two thirds of the frame width, matching the source framing`），**不要套用固定数值**。不同素材的主体占比差别极大——近景人像能占到七成，中景只占三成——套一个固定上限会让复刻走形
- 动作给**硬幅度**（`a clear thirty degrees`、`well past the left edge of the frame`、`a full forty degrees back`），别写 `approximately`
- 场景、光线、镜头、音效全部文字化；**唯一允许的图片引用是动作来源那两句**，其余不留引用

**5. `overall_soundscape`**

从画面推断环境音与动作音。有人张嘴但没给台词时写 `She speaks briefly near the end of the clip, but no dialogue content is specified.`——不要编台词。

**6. `non_diegetic_music`**

未指定写 `N/A`。

## 七、输出卫生（`prompt` 槽零污染）

`prompt` 会直接进 CLIP，任何非画面描述都是污染：

- `Note:` / `Risk:` / `注意` / `建议` / `不确定` → 删掉，移到 `analysis`
- 「我」「根据分析」「抽样」「未观察」 → 删掉
- 中文说明 → 删掉（正文英文，只有对白/歌词/画面文字保留原语言）
- **纯文本，不要 Markdown**：字段名不加粗、标签不套反引号、不用 `###` 标题。`**summary**` 和 `` `<Subject 1>` `` 会把符号带进 CLIP
- 不出现 `<Video N>`——本次输出没有任何视频参考

## 八、自检

- [ ] 全文没有 `<Video 1>` 或任何「来自源视频」的引用
- [ ] 盘点表人数与实际一致，映射表在 `analysis` 第一段
- [ ] 「外观归属」一行写明了脸/发型/服装/配饰各自跟着谁
- [ ] 默认情况下，服装与配饰**没有**被写成文字描述，只是指认来自 `<Picture 1>`
- [ ] 有保留声明时，那一项写了具体文字 + 否定了参考图的对应部分
- [ ] 五官没有任何文字复述
- [ ] 动作有硬幅度词，构图有硬上限，没有 `approximately`
- [ ] 时间戳 0.5s 精度，`[Shot 1]` 无时间戳
- [ ] `prompt` 里没有元话语、中文、Markdown 符号

## 九、边界

- 只看过 N 帧抽样，帧间过程无证据；这一点写在 `analysis`，不写进 prompt
- 缩图会丢面料与配饰细节，要精确复刻服装请让用户补高分辨率单图
- 交付的是可生成提示词，不是渲染结果

## 附：通过验收的样例

`references/accepted-example.txt` 是一版**实拍验收通过**的完整输出（人物/发型/服装/配饰全取参考图 + 场景动作文字化 + 全文无 `<Video N>`）。结构可以照抄；**只继承句式，不要继承数值**——占幅比例、转身角度、时间点、景别都是那一版素材专属的，换素材必须按源素材重写。

实测踩过这个坑：模型把样例里的 `occupies no more than one third of the frame width` 原样搬到了一段主体占七成的近景素材上，复刻直接走形。
