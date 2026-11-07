---
name: character-sheet
description: 把一个人（含其服装）描述成可跨镜头复用的固定设定卡，或从一张"穿着某件衣服的人"的图里自动拆出服装要素并排除模特本体。当需要角色一致性、跨镜头同一人、服装替换的服装来源、或把模特照降级成 donor 时使用。
---

# 角色设定卡与服装拆解

两个用途共用一份维度清单：**让同一个人（或同一件衣服）在不同画面里长得一样**。

## 零、参考图在场时：只指认，不复述

这是实测对比得出的硬规则（2026-11，H3 真机跑同一素材）：

| 做法 | 结果 |
|---|---|
| 只指认 + 不复述 | 脸像了、衣服也对了 |
| 指认 + 文字复述五官/服装 | 生成的是「气质相近的另一个人」 |

原因：文字和图片在竞争同一件事时，模型优先相信文字，参考图退化成"大方向参考"。

| 内容 | 有参考图时怎么写 |
|---|---|
| 脸 / 五官 / 肤色 / 体型 / 年龄感 | 只写 `taken from <Picture 1> and must read as the same person`，五官一个字不写 |
| 服装 / 配饰 | 只写 `outfit, including the rose-print sweatshirt and the oxblood velvet headband, also comes from <Picture 1>` |
| 表情 | 允许文字：`her expression may differ from <Picture 1>: here she is calm` |
| 姿势 / 动作 / 场景 / 光线 / 镜头 | 必须文字，参考图里没有 |
| 需要保留的源素材部分 | 必须文字（没有图片承载）+ 显式否定参考图的对应项 |

**点名单品 ≠ 描述单品**，这条分界最容易踩错：

- 点名单品（对）：`the rose-print sweatshirt and the oxblood velvet headband`——告诉模型取哪几件
- 描述单品（错）：`a white oversized sweatshirt covered in large pink roses with green leaves`——替图片重新描述一遍

多张参考图分工时必须写清谁管什么：`face from <Picture 1>, wardrobe from <Picture 2>; the wearer of <Picture 2> is not referenced.`

只有在**完全没有参考图**、必须靠文字建人物时，才使用下面第一、二节的维度清单。

## 一、外貌维度（逐项写，缺项写「不确定」）

| 维度 | 英文锚点 | 备注 |
|---|---|---|
| 年龄段感 | `early twenties` / `mid-forties` | 不写具体岁数 |
| 脸型 | `oval face` / `square jawline` / `heart-shaped face` | |
| 眉眼 | `thick straight brows` / `hooded eyes` | |
| 鼻唇 | `straight nose` / `full lower lip` | |
| 发型发色发长 | `shoulder-length wavy black hair, parted on the left` | 三项都要 |
| 肤色 | `light warm skin` / `deep brown skin` | |
| 体型 | `slim build` / `broad-shouldered` | |
| 显著特征 | `a small mole under the left eye` | 痣/疤/纹身/眼镜/耳饰，没有就写 `none visible` |
| 手部 | 可选，特写镜头才需要 | |

**只写视觉事实，不写性格、职业、性格化形容词。** `kind-looking`、`confident` 这种无法复现。

## 二、服装维度（九项，缺项写「不确定」）

`版型` / `主色` / `面料` / `纹样` / `长度` / `领型` / `袖型` / `配饰` / `穿法`

示例：`a loose-fitting white cotton shirt with a camp collar and rolled-up sleeves, tucked into high-waisted navy trousers, worn with a thin leather belt`

## 三、一致性锚定（IdentityLock）

同一角色跨镜头、跨任务时，**用完全相同的字符串**，不许换近义词：

- 允许：`shoulder-length wavy black hair, parted on the left`（每次都一模一样）
- 禁止：这一次 `black wavy hair`，下一次 `dark wavy hair`，再下一次 `raven hair`

原因：下游模型换一个词就换一张脸。要改就全局一起改。

设定卡输出格式（一段可直接黏进提示词的英文串）：

```text
<Subject 1>: a woman in her late twenties, oval face, thick straight brows, shoulder-length wavy black hair parted on the left, light warm skin, slim build, a small mole under the left eye; wearing a loose-fitting white cotton shirt with a camp collar and rolled-up sleeves, tucked into high-waisted navy trousers, a thin leather belt.
```

## 四、服装 donor 模式

当参考图是「一个穿着某件衣服的模特」，而我们要的只是那件衣服时：

```text
<Picture 2> is used ONLY as a garment donor — the face, hair, skin, body and pose of the wearer are NOT referenced and must NOT appear in the output.
```

三条配套动作（少一条就会泄漏）：

1. `retention_analysis` 里给 donor 一条 `weak_reference`：`only garment shape, color and texture are read from it; the model's appearance is explicitly excluded`
2. **姿势单独绑定到身份源**：新开一个 `<Subject N>` 专指姿势，标 `fully_preserved`，并写 `NOT the pose of the person in <Picture 2>`
3. 服装褶皱写 `re-draped to fit the pose of <Subject N>`，切断「衣服带着原模特姿势走」的路径

如果身份图与服装图高度相似（同为白底全身、同发色），泄漏概率最高。这时实操顺序固定：**身份图放第 1 张、服装图放第 2 张，顺序不换**；仍漂移就把服装图裁成纯服装局部（不含头部）再喂。

## 五、自动拆分：一张图里既有人又有衣服

判不准时**一律按「有人」处理**（宁可多排除，不可泄漏）。拆分产出两份：

```text
[服装要素] 版型：oversized / 主色：燕麦米 / 面料：粗针织 / 纹样：竖罗纹 / 长度：过臀 / 领型：圆领 /
          袖型：落肩长袖 / 配饰：无 / 穿法：敞开穿着
[排除项] 模特的脸、发型、肤色、身材、姿势、背景 —— 全部不引用
```

## 六、边界

- 缩图会丢面料微观纹理。需要精确复刻时，让用户单独补一张高分辨率服装图。
- 看不到的部分写「不确定」，不要按品类惯例脑补（看不到裤脚就别断言裤长）。
- 多人同款服装时，每个人单独出一张卡，不要合并成「大家都穿白衬衫」。

## 七、自检

- [ ] 外貌九项、服装九项都有内容或明确写「不确定」
- [ ] 没有性格化、职业化形容词
- [ ] 跨镜头使用时字符串完全一致，没有换近义词
- [ ] 走 donor 模式时，三条配套动作（donor 声明 / 姿势单绑 / 褶皱重垂）齐全
- [ ] 自动拆分时排除项写全了脸/发型/肤色/身材/姿势/背景
- [ ] 相同来源的图，顺序固定为「身份在前、服装在后」
