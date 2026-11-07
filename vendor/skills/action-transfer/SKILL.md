---
name: action-transfer
description: 把一段视频里的动作搬到参考图的人物身上，场景另行指定，输出 MiniMax H3 提示词。只从动作源提取动作序列与节奏，剥离原人物、原服装、原场景、原镜头。当需要动作迁移、让这个人做那个动作、照搬动作、动作复刻、把舞蹈/走路/转身搬到新人物身上时使用。
---

# 动作迁移（动作源视频 + 人物图 → H3 提示词）

> **移植性**：第零～四节与第六节（界限、输入契约、只取三样、剥离清单、回显格式）与目标模型无关。**第五节「六段式填充」是 MiniMax H3 专属**，换模型时替换为对应格式的 compose skill，逻辑部分不动。

只搬动作，其他全换。这是它和 `person-swap` 的根本区别。

## 零、先和 person-swap 划清界限

| 需求长相 | 走哪个 |
|---|---|
| 原视频**原地**把里面的人换掉，场景镜头动作全保留 | `person-swap` |
| 把那个动作**搬到别的场景**，让参考图里的人做 | `action-transfer`（本 skill） |
| 换成另一个人**并且**换衣服，场景动作不变 | `outfit-swap` |

判断口诀：**动作之外的东西要不要跟过来？** 要 → person-swap；不要 → action-transfer。

## 前置：先加载这三个 skill

1. `sequence-sheet-read` —— 读帧拼图（按它的帧密度表，短素材给到 16 帧）
2. `shot-grammar` —— 动作四要素（动词 + 部位 + 方向 + 幅度）与三档粒度
3. `h3-prompt-writing` —— Ref2VA 六段式字段名与 retention 标记词

## 一、输入契约

| 槽 | 角色 | 只看什么 | **禁止看什么** |
|---|---|---|---|
| 动作源视频 | 动作提取 | 身体部位怎么动、方向、幅度、速度、起止姿势 | **长相、服装、场景、镜头、光线、音效——全部不看** |
| `ref_person` | 外观来源 | 脸、发型、肤色、体型、年龄感 | 它的姿势与背景 |
| `ref_scene`（可选） | 场景来源 | 空间、陈设、光线条件 | 里面有没有人 |
| `cast_spec` | 规则 | 用哪个人的动作、场景用什么、节奏要不要改 | — |

**「禁止看什么」这一栏是本 skill 的执行核心。** 动作源视频里的人穿什么、站在哪、镜头怎么动，一律不带入输出。看多了就会漏出来——实测中模型很容易顺手写「她穿着浅色吊带站在红砖墙前」，那已经不是迁移了。

## 二、从动作源里只取三样

**1. 动作序列**

按 `shot-grammar` 的三要素写：动词 + 身体部位 + 方向（+ 幅度、速度）。逐段推进，不要概括成「在跳舞」「在走路」。

```text
lifts the right hand to shoulder height → turns the palm outward → shifts weight onto the left leg → pivots the torso thirty degrees to screen-right
```

**2. 节奏**

起止时间、快慢变化、有没有停顿。写成相对时间，精度 0.5 秒：

```text
the arm lift takes about one second; the torso pivot is quicker, around half a second; there is a short hold before the weight shift
```

**3. 起止姿势**

这两个必须单独写清楚，它们是整段动作的锚点：

```text
Start: standing upright, feet shoulder-width apart, arms relaxed at the sides, head level.
End: torso rotated thirty degrees to screen-right, right palm facing outward at shoulder height, weight on the left leg, head turned to follow the right hand.
```

## 三、动作粒度（按帧密度选）

| 帧密度 | 粒度 | 写法 |
|---|---|---|
| ≤8 帧 或 >8s | 状态迁移 | 只写起止姿势 + 「中间连续完成」，不虚构中间路径 |
| 12–16 帧 / 4–8s | 分段 | 按约数时间分段描述 |
| >16 帧 / <4s | 动词序列 | 逐动作串联，用 `→` 在心里串，落成自然英语 |

帧数按 `sequence-sheet-read` 的新表：2–10s 用 16 帧（4×4），动作类任务尤其需要密——动作细节全靠帧。

## 四、场景从哪来

| 情形 | 写法 |
|---|---|
| 用户用文字描述场景 | 把描述展开成：空间类型、可见陈设、光线方向与性质、地面材质 |
| 用户给了场景图 | **只指认不复述**：`the environment comes from <Picture 2>`，同时否定图里的人（`any people in <Picture 2> are not referenced`） |
| 用户什么都没说 | 必须给一个中性可用的场景并提醒：`场景未指定，按中性室内环境处理`。不要留空 |

场景里如果要放人，只能放 `<Subject 1>`；场景图里的人不算。

## 五、六段式填充

**1. `subject_definitions`**

```text
<Subject 1> is the single person in the target video. Her face, facial features, hair, hairstyle, hair colour, skin tone, body build and age impression are taken from <Picture 1> and must read as the same person. Her complete outfit also comes from <Picture 1>. Her motion follows the action description below and is unrelated to the performer in the reference footage.

<Picture 1> is the identity and wardrobe source. Its own pose, background and lighting are NOT referenced.

The environment, the camera and the timing are described in text below. No reference video is used for this shot.
```

**2. `summary`**

一句话：谁、在什么场景、做什么动作。

**3. `retention_analysis`**

```text
<Subject 1> (appears in [Shot 1]): partially_preserved - appearance and outfit come from <Picture 1>; the motion is newly specified in the description below and is not tied to any reference footage.
<Picture 1> (identity and wardrobe source): fully_preserved - face, hair, build and outfit are read from it; its own pose, background and lighting are NOT referenced and must not appear.
<Subject 1> motion: fully_preserved - the sequence, timing and start/end poses follow the description below exactly.
```

**不要出现 `<Video 1>` 条目**——动作源不是参考素材，只是我们读过的信息。

**4. `detailed_description`**

- 开头：场景 + 光线 + 景别 + 构图锚点
- 主体动作：按第三节粒度写，起止姿势必须露出来
- 镜头：默认新写一个（`Static Shot` 或按用户要求），**不要照搬动作源的镜头语言**；用户明确说要照搬时才照搬
- 服装只提一句动态（褶皱、飘动），不重复描述款式

**5. `overall_soundscape`**

按**新场景**推断，不是按动作源。原片是户外有鸽子，新场景在室内就写室内环境音。

**6. `non_diegetic_music`**

未指定写 `N/A`；用户要节奏感可以写乐器 + 速度 + 动态，不写情绪词。

## 六、`analysis` 必须回显

```
动作来源：3 段动作，总时长约 2.5 秒（抽样 16 帧）
已剥离：原人物外观 / 原服装 / 原场景 / 原镜头 / 原音效
外观归属：脸、发型、服装 → P1（指认）
场景：文字指定 / 来自 P2（指认）
起止姿势：已单列
提醒：帧间中间过程无证据（如适用）
```

「已剥离」这一行是质量自检的抓手——用户一眼就能看出我有没有把不该带的东西带过来。

## 七、输出卫生

同其他任务 skill：`prompt` 零污染、纯文本、无 Markdown、无 `<Video N>`、无元话语、无中文说明。

额外两条：

- **不出现「原视频」「动作源」「迁移」这类叙述**
- **不出现动作源里的任何具体物件**：如果它写了「红砖墙」，输出里就不该有墙；除非新场景恰好也是砖墙（那是场景描述带来的，不是漏出来的）

## 八、自检

- [ ] 输出里没有任何来自动作源的场景、服装、光线、镜头描述
- [ ] 动作有四要素（动词 + 部位 + 方向 + 幅度），不是「在动」
- [ ] 起止姿势单独写清
- [ ] 节奏用相对时间，精度 0.5 秒
- [ ] 场景有明确来源（文字 / 指认图片 / 中性默认 + 提醒）
- [ ] 服装与外观只指认不复述
- [ ] `overall_soundscape` 是按新场景写的
- [ ] 全文无 `<Video N>`

## 九、边界

- 抽样帧数决定动作精细度；<4 秒的快动作即使 16 帧也可能丢中间过程，必须声明
- 无法判断动作的力度与重量感（画面看不出肌肉发力），只能写幅度和速度
- 手部细节（手指姿态）在缩图后基本不可读，需要时要求高分辨率单帧
- 动作迁移不保证物理合理性：新场景的地面高度、障碍物与原片不同，模型可能生成穿模
