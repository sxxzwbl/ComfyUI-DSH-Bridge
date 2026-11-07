---
name: video-replica
description: 把一段视频读成能让下游复刻同款的 MiniMax H3 提示词。默认 T2VA 三段式纯文字；当下游同时收到帧阵列图作为参考图时，改为在提示词里引用 <Picture 1> 作为动作与构图来源。当需要"照着这个视频写一版提示词"、"视频转提示词"、"复刻同款"、"把这个镜头语言文字化"时使用。
---

# 视频复刻（源视频 → H3 提示词）

> **移植性**：第零～二节与第四节（默认形态、复刻清单、三步流程、时长密度）与目标模型无关。**第三节「输出结构」是 MiniMax H3 的 T2VA 三段式专属**，换模型时替换为对应格式的 compose skill，逻辑部分不动。

目标只有一个：**别人只读这段字，就能生成出同款的片子**。

判断标准也很硬——把提示词发给一个从没见过原片的人，问他"要做的是不是这个画面"，他点头，就成了。

## 零、先定形态：下游收不收到帧阵列图

这一步决定输出里能不能出现 `<Picture 1>`，先看清楚再动笔。

| 下游形态 | 判据 | 输出 |
|---|---|---|
| **纯 T2VA**（默认） | 只有文本进生成模型，没有图 | 三段式纯文字，**不出现**任何 `<Picture N>` / `<Video N>` / `<Subject N>` |
| **帧阵列图也在参考图里**（Ref2VA） | 节点把帧阵列图当图片一起送进去了 | 允许并**要求**在提示词里把 `<Picture 1>` 引为动作、构图、景别、运镜的来源 |

判断方法：看输入声明里有没有给帧阵列图编号。**编号来自用户描述的顺序**——他说了「输入帧图和参考图」或「输入参考图和帧图」，帧图才有编号；什么都没说、只说参考图，帧图就只用来读动作，不编号也不引用。

给了编号，说明它物理上是一张图、进了参考图序列，那就必须引用——模型看得到它，提示词却不提，等于把最强的动作约束丢掉。

引用方式（放在 `integrated_multimodal_description` 开头）：

```text
[Shot 1] Live-action, cinematic. The action, the shot scale progression and the
camera movement follow <Picture 1> frame by frame. ...
```

如果用的是 Ref2VA 六段式而非三段式，结构改按 `person-swap` / `h3-prompt-writing` 的六段式走。

其余情况：

- 源视频**只作为信息源**时，它的作用是「我读它，把看到的东西写成文字」，不传给下游
- 全文**不出现** `<Video N>` —— 本次没有任何视频输入，帧阵列图是静态图片
- 只有用户另外给了首帧、尾帧参考图时才走 I2VA / FL2VA，见最后一节

## 前置：先加载这三个 skill

1. `sequence-sheet-read` —— 逐格读帧拼图
2. `shot-grammar` —— 动作、运镜、景别、切点的写法与判断
3. `h3-prompt-writing` 的 `references/base-en.txt` —— T2VA 字段名、运镜词表、对白与屏幕文字规范

运镜必须用 H3 官方词表（`Push In`、`Pan Left`、`Truck Left`、`Tilt Up`、`Pedestal Up`、`Arc Shot`、`Tracking Shot`、`Static Shot`、`Shake Slightly`、`Roll Clockwise`…），不要自创 `dolly in` 这类说法。

## 一、复刻清单：按辨识度排序（本 skill 的核心方法）

不是所有细节都值得写。按下面顺序分配笔墨，**越靠前越是"删掉就不像了"**：

| 优先级 | 要素 | 判据 |
|---|---|---|
| 1 | **场景地标与关键道具** | 删掉它，还认得出这是同一个地方吗？ |
| 2 | **主体外观与穿着**（有参考图时只指认） | 删掉它，还认得出是同一个人吗？ |
| 3 | **动作时序**（谁在什么时候做什么） | 删掉它，还认得出是同一个事件吗？ |
| 4 | **镜头语言**（景别、运动、切点节奏） | 删掉它，观感还是同一支片子吗？ |
| 5 | **光线与调色** | 删掉它，气氛还对吗？ |
| 6 | **音效与音乐** | 删掉它，还是同一支片子吗？（复刻时常被忽略但权重很高） |

写作时先把这六项各写一句「清单草稿」（放在 `analysis` 里），再决定哪几项要展开。展开给前四项，后两项一句带过即可。

**不要**平铺直叙地把每帧都描述一遍。复刻靠锚点，不靠流水账。

## 二、三步流程

**第 1 步 · 读**（`sequence-sheet-read`）

逐格读，产出跨格归纳：主体运动、镜头运动、切点、连续性、不可见区间。

**第 2 步 · 判**（复刻清单）

按上表填六项，每项一句。这一步的产物进 `analysis`，让你自己能核对"我是不是抓住了重点"。

**第 3 步 · 落位**（T2VA 三段式）

把清单展开成 `integrated_multimodal_description`。开头先给风格 + 初始构图，再逐镜头推进。

## 三、输出结构

```text
integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium close-up frames ... The camera holds a static shot as ...
[Shot 2] At 00:03.500, the camera cuts to ...

overall_soundscape: ...

non_diegetic_music: ...
```

规则（来自 base-en.txt，不要改）：

- `[Shot 1]` **不带时间戳**，开头先声明整体风格与初始构图（`Live-action, cinematic, a medium close-up frames...`）
- 后续镜头 `[Shot 2] At 00:03.500, the camera cuts to ...`，切点时间严格递增且落在时长内
- 切点用 `the camera cuts to` / `the shot transitions to`；单纯改变距离或轻微角度**不要切**，用镜头运动
- **默认单镜头**：拿不到切点证据时，全文只有 `[Shot 1]` 一段，景别变化写进运动（`she steps back from a collarbone-up close-up into a full-length frame by 00:04.000`）。判据见 `sequence-sheet-read` 第 3.5 节
- 镜头运动写成自然英语动作句：`The camera pushes in with small amplitude at slow speed toward the folded letter in her hands.`
- `overall_soundscape` 一段 1–4 句，只写环境音、动作音、非语言人声；对白与可见音乐**不重复写**；全片静音才写 `N/A`
- `non_diegetic_music` 1–3 句，只写乐器/速度/节奏/动态变化，不写情绪；没有就 `N/A`

## 四、时长与信息密度

| 时长 | `integrated_multimodal_description` 大致词数 | 镜头数上限 |
|---|---|---|
| 2–4s | 100–160 | 1 |
| 5–8s | 180–280 | 2 |
| 9–12s | 280–380 | 3 |
| 13–15s | 350–450 | 4 |

「上限」不是「目标」。**默认就是 1 个镜头**，多出来的镜头必须各自有切点证据（场景换、主体瞬移、光线断裂、单帧内景别跳变）。短视频绝大多数是一镜到底，为了凑镜头数去编切点，会让下游生成几段互不相干的画面。

写超了说明在记流水账，回头砍第 5、6 项。写不够说明锚点没抓全。

## 五、对白与屏幕文字

- 有人说话**且我们知道台词** → 设 `(S1)`，写 `<d>[语言] 原文</d>`，原文逐字保留
- 有人说话**但我们没有台词** → **不要设 speaker，不要编台词**。只写嘴部动作：`her lips part slightly and close again`。编一句假台词比不写更糟
- 屏幕上的招牌、字幕、霓虹字 → 用英文双引号包住原文：`A red neon sign reading "营业中" glows above the doorway.`
- 画外音 → 固定短语 `says in an off-screen voiceover`，并紧跟一句说明画面里那人嘴唇闭合

## 六、不要写进 `prompt` 的东西

- 「复刻」「原片」「参考视频」这类元描述
- 抽样说明、「帧与帧之间未观察」
- 猜的机型、镜头焦段、滤镜名
- `cinematic` 之外的空词：`beautiful`、`stunning`、`masterpiece`、`moody`——要写就写具体的物理现象
- 中文说明（正文英文，只有对白/歌词/屏幕文字保留原语言）

## 七、输出卫生

- 纯文本，字段名不加粗、不加反引号、不用 Markdown 标题
- 三个字段名顶格写，`字段名: 内容`
- 时间要写时用 `At 00:03.500`，精度到 0.5s，不许伪精度

## 八、自检

- [ ] 全文没有 `<Video N>` / `<Picture N>` / 任何"跟随源视频"的引用
- [ ] `[Shot 1]` 无时间戳，开头有风格 + 初始构图
- [ ] 运镜用的是 H3 官方词表，不是自创说法
- [ ] 切点时间严格递增且在时长内
- [ ] **一镜到底的素材：全文只有一个镜头段，没有 `cut` 类动词**
- [ ] 复刻清单六项都过了一遍，前四项展开、后两项简短
- [ ] 没有编造台词；无台词的说话者没有设 `(S1)`
- [ ] `overall_soundscape` 没有重复对白
- [ ] 词数落在时长对应的区间里
- [ ] `prompt` 里没有元话语、空词、中文

## 九、变体：用户额外给了参考图

| 情形 | 走哪种 | 变化 |
|---|---|---|
| 给了首帧图 | I2VA | 首行加固定句 `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`，正文从首帧起步向前推进 |
| 给了首帧 + 尾帧 | FL2VA | 首行换成 `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark...`，正文描写从首帧到尾帧的连续路径，通常单镜头 |
| 只给尾帧 | L2VA | 首行说明 `<Picture 1>` 对齐末尾时刻，正文推演一个合理的前置状态收敛到尾帧 |

给了参考图时，图里的外观遵守 `character-sheet` 的「只指认，不复述」——图里有的一律只写 `from <Picture N>`，不要用文字重描。
