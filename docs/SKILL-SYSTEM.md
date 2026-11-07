# DSH 提示词 skill 体系

> 状态：内容层完成，接入层未开始。
> 最后更新：2026-11-07

这套体系的目标：**把「提示词怎么写」从节点代码里移出去，变成可独立演进、可实测校准的 skill**。节点只负责收素材、拼输入、调 DSH、按契约校验输出。

---

## 一、体系总览

分两层。能力层是积木，任务层是编排。

### 能力层（5 个，全部在 `~/.dsh/skills/`）

| skill | 职责 | 谁在用 |
|---|---|---|
| `sequence-sheet-read` | 帧拼图读法：固定声明模板、三步读法、帧密度表、稳定项/推断项分层 | video-replica、person-swap、outfit-swap、action-transfer、style-transfer |
| `shot-grammar` | 动作四要素与三档粒度、H3 官方运镜词表、景别锚点、切点类型 | 同上（image-edit-brief 不用） |
| `cast-inventory` | 人物盘点：计数基准、每人九项、主体四步量化 | person-swap、outfit-swap、action-transfer |
| `character-sheet` | 角色卡、服装九项、donor 降级、**只指认不复述**权威章节 | person-swap、outfit-swap、action-transfer、image-edit-brief |
| `style-dna` | 风格五维度、与内容分离、空词禁令 | style-transfer |

### 任务层（6 个）

| skill | 输入 | 输出形态 | 参考图数 | 状态 |
|---|---|---|---|---|
| `video-replica` | 源视频 | T2VA 三段式 | 0 | 已跑通 |
| `person-swap` | 源视频 + 人物图 | Ref2VA 六段 | 0–N | 已验收 |
| `outfit-swap` | 源视频 + 服装图（+ 人物图） | 六段 | 1–2 | 已跑通 |
| `action-transfer` | 动作源视频 + 人物图 | 六段 | 1 | 已跑通 |
| `style-transfer` | 内容源 + 风格图 | 六段或三段 | 1–2 | 调色级失败，媒介级待跑 |
| `image-edit-brief` | 源图（+ 参考图） | 六段 | 1–2 | 已跑通 |

### 外部依赖（已存在，不重写）

- `h3-prompt-writing` —— 六段式字段名、`[Shot N] At MM:SS.mmm`、运镜词表、对白/屏幕文字规则、媒介词表、`retention_analysis` 标记词
- `ltx-prompt-writing` —— LTX 格式（尚未接入任何任务）

---

## 二、三条贯穿全局的硬规则

这三条是全部实测里最值钱的结论，已写进每一处该写的地方。

### 1. 源视频只做信息源，不进参考

视频不作为生成输入传给下游。它的作用是「我读它，把场景、动作、镜头、风格写成文字」。**输出里永远不出现 `<Video N>`**。

只有用户另外给了参考图（首帧/尾帧）时才走 I2VA/FL2VA，那是例外不是默认。

### 2. 参考图在场时，只指认、不复述

实测验收（H3 真机，同一素材）：

| 做法 | 结果 |
|---|---|
| 只指认 + 不复述 | 脸像了、衣服也对了 |
| 指认 + 文字复述五官/服装 | 生成「气质相近的另一个人」 |

原因：文字和图片竞争同一件事时，模型优先相信文字，参考图退化成"大方向参考"。

分界：**点名单品可以**（`the rose-print sweatshirt and the oxblood velvet headband`），**描述单品不行**（`a white oversized sweatshirt covered in large pink roses`）。

### 3. `prompt` 槽零污染

`prompt` 直接进 CLIP。元话语、风险提示、映射表、精度说明一律进 `analysis`。

配套：纯文本、无 Markdown、字段名不加粗、标签不套反引号。

---

## 三、各任务的输入契约（接入时直接用）

### 默认归属

| 项 | 默认来源 | 何时改为源素材 |
|---|---|---|
| 脸 / 五官 / 肤色 / 体型 / 年龄感 | 参考图 | 永不 |
| 发型（盘/披/编、长短、发色） | 参考图 | 声明「保留原发型」 |
| 服装 | 参考图 | 声明「保留原服装」 |
| 配饰（耳环、项链、发带、帽子） | 参考图 | 声明「保留原配饰」 |
| 表情 | 文字 | — |
| 姿势、动作、走位 | 文字（从源视频提取） | 永远 |
| 场景、光线、镜头、音效 | 文字（从源视频提取） | 永远 |

### 分任务槽位

| 任务 | 槽 | 作用 |
|---|---|---|
| video-replica | `source_video` | 全部信息的来源 |
| person-swap | `source_video` + `ref_person_1..n` | 视频提供动作场景，图提供外观 |
| outfit-swap | `source_video` + `ref_garment`（+ `ref_person`） | 服装图的三种形态：纯服装图 / 穿着图（donor 降级）/ 文字要求 |
| action-transfer | `source_video`（动作源）+ `ref_person` + 场景文字 | **只取动作**，其余全剥离 |
| style-transfer | `content` + `style_ref` | 两边互相不看：内容源不看风格，风格源不看内容 |
| image-edit-brief | `content_image`（+ `ref`） | 保留清单 vs 替换清单 |

---

## 四、实测结论

### 生效的

| 项 | 证据 |
|---|---|
| 4×3 / 4×4 帧拼图逐格读取 | 12 格全对，含位置变化、连续相同帧、递增元素数量 |
| 16 帧优于 8 帧 | 同素材两次读取，8 帧时动作次数与配饰款式不一致，16 帧稳定 |
| 只指认不复述 | 验收通过（脸像了、衣服也对了） |
| `action-transfer` 的剥离 | 户外红砖墙+鸽子 → 纯白室内，没漏任何原场景元素 |
| `image-edit-brief` 换背景 | 灰棚拍 → 阴天礁石滩，人、衣、手势、表情全保留 |
| 拼图成本 | 12 帧一张 ≈ 1024 image tokens，比 12 张独立图省约 90% |

### 不生效或需前置条件的

| 项 | 结论 |
|---|---|
| 调色级风格迁移 | **提示词拉不动**。写了完整的 grade/grain/warm 描述配一张风格图，生成结果跟原片几乎一样。这是 LoRA 或颜色参考节点的活 |
| 构图保持 | 十有八九是**画幅比例不匹配**导致的缩放居中裁切。素材竖屏就必须设竖屏输出，否则任何提示词都救不回来 |
| 单张参考图的人脸一致性 | 模型能力边界。`person-swap` v3 能像（内容与参考靠近），`action-transfer` 换全新场景后脸会漂 |
| `weak_reference` | 字面「大致像」会被下游执行成「几乎不生效」。风格源改用 `fully_preserved`（有意偏离 h3 语义，退路已记在 skill 里） |

### 已修正的错误归因

- 曾把构图收缩归因到「景别术语会向上收缩」→ 实为画幅比例问题
- 曾以为「文字写不够细所以风格没生效」→ 查证后文字已写得很细，仍无效，真因在标记词

---

## 五、节点现状与差距

### 现状

`nodes/dsh_nodes.py`：

- ✅ 已迁 V3（`io.ComfyNode` + `io.Schema`）
- ✅ 媒体插槽用 `io.Autogrow`：`images`（12 槽）、`videos`（4 槽），自动增减
- ❌ 提示词仍由 `presets.py` 四个硬编码函数拼接，与 skill 体系**零连接**
- ❌ 抽帧是逐帧送独立图（`_sampled_pictures`），与 `sequence-sheet-read` 约定的「一张拼图 + 网格声明」不符

### 接入要做的五件事（按依赖顺序）

1. **任务清单** —— `MODES` 四个字符串换成六个任务，或做成 manifest 可扩展
2. **任务 → skill 映射** —— 每个任务对应的 skill 名拼进 task 首句
3. **媒体分组** —— 从 `images` / `videos` 两组，扩成按任务命名的多组 autogrow（`source_video` / `ref_person` / `ref_garment` / `style_ref` / `content_image`）
4. **抽帧拼图** —— 节点侧把帧拼成 contact sheet 并注入 `sequence-sheet-read` 要求的固定声明段落。这是最关键的一步，不做则 `sequence-sheet-read` 空转
5. **输出槽语义** —— `prompt` 与 `analysis` 分开，让映射表、复判清单、精度限制有地方落

### 待拍板

- 六个任务全上，还是先上 2–3 个常用
- 媒体槽按任务分组（每个任务显示自己的槽），还是统一保留两组、语义靠参数区分

---

## 六、遗留

- `scripts/nodetest.py`、`modes_test.py`、`multiimage_test.py` 仍是 `.run(image=...)` 旧 API
- `person-swap`、`outfit-swap`、`action-transfer` 实测产出 700–800 词，超 h3 生成任务 350–500 词建议
- `style-transfer` 媒介级迁移（真人 → 3D CG）未跑，等待验证 `fully_preserved` 是否会连带把风格源的内容带进来

---

## 七、跨模型移植性

### 三档拆分

| 层次 | 移植性 | 说明 |
|---|---|---|
| `sequence-sheet-read` | ✅ 完全通用 | 「怎么读帧拼图」属于视觉理解方法，与生成模型无关 |
| `cast-inventory` | ✅ 完全通用 | 数人、判主体、从左到右编号 |
| `style-dna` | ✅ 完全通用 | 风格五维度、空词禁令 |
| `character-sheet` | 🟡 九成通用 | 维度清单、donor 降级、只指认不复述通用；只有 donor 的写法引用了 H3 的 `retention_analysis` 标记 |
| `shot-grammar` | 🟡 一半通用 | 动作四要素、三档粒度、镜头动 vs 主体动、景别锚点、切点类型通用；**运镜词表是 H3 专属**（`Push In` / `Pedestal Up` / `Static Shot`），LTX 走自然语言 |
| 6 个任务 skill | 🟡 逻辑通用、格式绑死 | 三级优先级、两张清单、迁移强度、剥离清单通用；T2VA 三段式 / Ref2VA 六段式、`[Shot N] At MM:SS.mmm`、`retention_analysis` 标记词是 H3 专属 |

### 真正的障碍是模型能力，不是格式

| 任务 | 需要的模型能力 | H3 | LTX-2.5 | Wan 2.x | Flux / SDXL |
|---|---|---|---|---|---|
| `video-replica` | 文生视频 | ✅ T2VA | ✅ | ✅ | ❌ 不可行 |
| `person-swap` | 参考图锁身份 + 保持原片动作 | ✅ Ref2VA | ⚠️ 只有首帧图生视频，无多参考身份 | ⚠️ | ❌ |
| `outfit-swap` | 身份参考 + 服装参考 | ✅ | ⚠️ | ⚠️ | ❌ |
| `action-transfer` | 人物参考 + 动作控制 | ✅ | ⚠️ | ⚠️ 需 ControlNet | ❌ |
| `style-transfer` | 观感参考 | ✅ | ⚠️ | ⚠️ | ✅ 图像 img2img 反而更成熟 |
| `image-edit-brief` | 图像编辑 | ⚠️ 靠视频生一帧绕 | ⚠️ | ❌ | ✅ |

`person-swap` / `outfit-swap` / `action-transfer` 三个的核心价值是「参考图锁身份 + 保持原片动作」，只有支持多参考的模型才有这个能力。换到只支持「首帧图生视频」的模型，这三个任务不是改提示词能解决的，是方案本身不成立。

### 架构已经帮忙的地方

`analysis` 与 `prompt` 分离，让 `analysis` 实质上变成了一份**结构化事实包**——有几个人、谁换谁、剥离了什么、迁移强度、保留清单，全部在自然语言里。换模型时这半页可以原样保留，只需重写 `prompt` 段。

这也是「风险提示一律赶进 analysis」这条规则的额外收益。

### 换模型的正确顺序

1. **先查能力矩阵**：目标模型支不支持多参考图、支不支持保持原视频动作。不支持就换方案，不是换提示词
2. **再写 `compose-<model>` skill**：把任务 skill 里「落位」那一节抽出来单独成文
3. **任务 skill 只改一句**：`落位见 compose-<model>`

最省力的第二模型组合是 `video-replica` + `ltx-prompt-writing`：它只要把三段式换成 LTX 结构，`analysis` 那半页一个字不用动。
