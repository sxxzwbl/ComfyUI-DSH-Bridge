---
name: shot-grammar
description: 把视频画面读成可以复刻的镜头语言——动作、运镜、景别、切点，全部落到 H3/LTX 能接受的英文表述。当需要描述人在做什么、镜头怎么动、几个镜头怎么切、以及为复刻或迁移生成逐镜头描述时使用。
---

# 镜头与动作语法

视频提示词里最常写废的两块：动作写成「在动」，运镜写成「画面在变」。这份 skill 解决这两件事。

## 一、动作描述三档粒度

按帧密度选档，选完就按该档的句式写，不许混用：

| 帧密度 | 档位 | 句式 |
|---|---|---|
| ≤8 帧 或 时长 >8s | **状态迁移** | `starts at <起始状态>, ends at <结束状态>; the intermediate motion is not observed` |
| 12–16 帧 / 4–8s | **分段** | `approximately 0–2s: <动作>; 2–4s: <动作>; 4–5s: <动作>` |
| >16 帧 / <4s | **动词序列** | `lifts the right foot → plants it forward → shifts weight onto it → the left arm swings back` |

三档共同的硬要求：**必须有起点和终点**。只写中间过程等于没写。

## 二、动作 = 动词 + 部位 + 方向 + 幅度

| 要素 | 必填 | 示例 |
|---|---|---|
| 动词 | 是 | `turns`, `raises`, `steps`, `leans`, `reaches`, `lifts`, `places`, `crouches` |
| 身体部位 | 是 | `the right hand`, `both shoulders`, `the torso`, `the head` |
| 方向 | 是 | `toward the camera`, `to screen-left`, `upward`, `away from the window` |
| 幅度 | 强烈建议 | `slightly`, `a full step`, `a wide arc`, `about a quarter turn` |
| 速度 | 建议 | `slowly`, `steadily`, `abruptly`, `in a single continuous motion` |

合格：`raises the right hand to shoulder height and holds it there`
不合格：`moves gracefully`、`does a gesture`、`interacts with the environment`

## 三、运镜：优先用 H3 官方词表

H3 有固定词表（首字母大写），写这些词命中率最高。不要自创 `dolly in`、`crane up`、`handheld` 这类说法——H3 词表里没有它们。

| 中文 | H3 官方写法 | 判断特征 |
|---|---|---|
| 固定镜头 | `Static Shot` | 背景完全不动 |
| 推 | `Push In` | 镜头前进，透视变化 |
| 拉 | `Pull Out` | 镜头后退，环境越来越多 |
| 摇（水平） | `Pan Left` / `Pan Right` | 机位不动，镜头水平转 |
| 移 | `Truck Left` / `Truck Right` | 机位水平平移，前景视差明显 |
| 俯仰 | `Tilt Up` / `Tilt Down` | 机位不动，镜头垂直转 |
| 升降 | `Pedestal Up` / `Pedestal Down` | 整个机位上下移动 |
| 环绕 | `Arc Shot` | 绕主体画弧，背景旋转 |
| 跟拍 | `Tracking Shot` | 跟着移动主体，主体位置稳定 |
| 手持 | `Shake Slightly` / `Shake Strongly` | 高频不规则抖动 |
| 变焦 | `Zoom In` / `Zoom Out` | 内容变大但透视不变（与 Push In 的区别） |
| 主观视点 | `POV` | 第一人称 |
| 滚转 | `Roll Clockwise` / `Roll Counterclockwise` | 绕光轴旋转 |

**幅度**：`with small amplitude` / `with large amplitude`
**速度**：`at slow speed` / `at fast speed`

三项齐全才完整，但要写成自然英语动作句，不要堆标签：

```text
The camera pushes in with small amplitude at slow speed toward the folded letter in her hands.
The camera pans right with large amplitude at fast speed, revealing the open doorway.
The camera holds a static shot as the runner exits the frame.
```

**先用词表，再用自然语言补细节。** 词表覆盖得到的（推、拉、摇、移、升降、环绕、跟拍、手持、变焦）一律写词表；词表表达不了的细微特性（缓慢漂移、极小幅度手抖）才补一句自然语言。

实测教训：只写自然语言（`the camera holds near-static with a slow micro-sway and slight handheld drift at slow speed`）H3 也能正确执行，所以很容易顺手就这么写——但词表命中更稳。不要因为"自然语言也行"就跳过词表，能写 `Static Shot` 就别写 `near-static camera`。

**LTX 不用这套词表**，它走自然语言，见 `ltx-prompt-writing`。

## 四、区分「镜头动」和「主体动」——最高频的错

| 看到的现象 | 结论 |
|---|---|
| 主体变大，背景也变大，透视变 | 镜头推进（dolly in） |
| 主体变大，背景不变 | 主体走近镜头 |
| 主体位置不变，背景横向流走 | 摇镜或移镜 |
| 主体和背景一起横向流走 | 跟拍（follow） |
| 背景轻微旋转，主体居中稳定 | 环绕 |

两者可以叠加，叠加就都写：`the camera tracks right while the subject walks toward screen-left`。

## 五、景别：光写术语会向上收缩

实测教训（四份生成任务全部中招）：只写 `medium close-up`，生成结果会明显比预期更紧——本该「胸上」的变成了「头肩特写」，抬起的手和衣服下摆都被裁掉。景别术语在生成模型那里会向上收缩。

**必须配一个可验证的可见范围锚点**，锚点要具体到「画面里必须看得见什么」：

| 写法 | 结果 |
|---|---|
| `medium close-up` | 收缩成头肩特写 |
| `medium close-up framed from the chest up, with the entire raised right hand and the sweatshirt hem both visible` | 稳定 |

锚点三件套：

1. **上边界**：`little headroom above the hair`
2. **下边界**：`framed from the chest up` / `framed from the waist up`
3. **必须出现在画面里的具体物件**：抬起的手、衣服下摆、桌沿、脚下的地面

第 3 条最关键——**用具体物件锁住画幅，比任何景别术语都硬**。做编辑/替换类任务时尤其要写，因为那类任务最怕构图跑掉。

**构图收缩先排查画幅比例，别急着改提示词。**

实测踩过的坑：连续四份任务生成出来都比预期紧（胸上变头肩特写），我一开始归因到景别术语，后来确认真正原因是**素材与输出的画幅比例不一致**——素材是竖屏，输出按 16:9 出，模型会缩放后居中裁切，裁掉的正是上下两端。这种情况任何提示词都救不回来。

正确顺序：

1. **先对齐画幅**：输出比例必须等于素材比例。竖屏素材就设竖屏输出（720×1280 / 480×864）。这一步没做，后面全是白忙
2. 画幅对上了仍然偏紧，再加锚点三件套（上边界 / 下边界 / 画面里必须出现的具体物件）
3. 术语与锚点保持一致：腰上的画幅写 `medium shot`，不要用 `medium close-up` 去描述腰上

占比上限是个有用的补充：`her head occupies no more than one third of the frame height`。

## 六、切点

| 类型 | 英文 | 判断 |
|---|---|---|
| 硬切 | `hard cut` | 场景/景别瞬间突变，无过渡 |
| 叠化 | `dissolve` | 两画面重叠渐变 |
| 淡入淡出 | `fade in from black` / `fade to black` | 亮度渐变到全黑/从全黑 |
| 跳切 | `jump cut` | 同场景同主体，时间跳跃 |
| 匹配剪辑 | `match cut` | 前后镜头有形状/动作呼应 |

### 先证明，再切

**默认单镜头**。景别在多格内渐进变化（特写→中景→全景，或反向）不是切点，是主体位移或推拉镜头。判定硬切需要第 `sequence-sheet-read` 第 3.5 节表格里的证据（空间断裂 / 主体瞬移 / 光线断裂 / 单帧内景别跳变），拿不到证据就只写一个镜头段落。

写错方向的代价不对称：把一镜到底写成四段硬切，下游生成四段互不相干的画面，人物动作全丢；漏判一个切点，只是画面多连贯几秒。

单镜头时的正确写法是把景别变化写成运动的一部分：

```text
[Shot 1] ... The camera holds a Static Shot. She steps back from a collarbone-up
close-up into a full-length frame by 00:04.000 and stays there to the end.
```

而不是：

```text
[Shot 1] A close-up ... [Shot 2] At 00:00.500, hard cut to a medium close-up ...
```

写进 `detailed_description` 的格式：

```text
[Shot 1] ...
[Shot 2] At 00:02.500, hard cut to a medium shot of ...
```

`[Shot 1]` 不带时间戳，其余镜头都带。**只有确定是多镜头时才出现 `[Shot 2]` 及之后的段落。**

## 七、时间戳精度

我们只有秒级观测（帧间隔 = 时长/(帧数-1)）。

- 允许：`00:02.000`、`00:02.500`、`00:03.000`
- 禁止：`00:02.340`、`00:02.167`

伪精度会让下游以为我们知道得比实际多。

## 八、常见错误清单

1. 把推镜写成「人物变大」→ 应写 `the camera dollies in`
2. 把摇镜写成「背景移动」→ 背景横移就是镜头在动
3. 动作没有终点 → 必须写停在什么状态
4. 一个 `[Shot N]` 里塞了两个切点 → 拆成两个镜头
5. 用 `cinematic`、`beautiful`、`dynamic` 这类空词 → 全部换成具体名词和动词
6. 主体运动与镜头运动写在同一句里又不区分 → 分开写
7. 抽帧之间的过程被写实 → 写 `the intermediate motion is not observed`
8. **景别渐进变化被切成多个镜头** → 一镜到底就只写一段，景别变化融进运动描述

## 九、自检

- [ ] 每个动作都有动词 + 部位 + 方向，主要动作有幅度
- [ ] 每个镜头段都写了镜头是固定还是在动；在动就写了类型 + 幅度 + 速度
- [ ] 主体运动和镜头运动分开表述
- [ ] 切点写了类型，且有 `[Shot N]` 与时间戳
- [ ] 时间戳只有 0.5s 精度
- [ ] 没有 `cinematic` 类空词
- [ ] **若素材是一镜到底：全文只有一个镜头段，景别变化写在运动里，没有 `hard cut`**
- [ ] **若素材多镜头：每个切点都能指出具体证据（场景/位置/光线/景别突变）**
