---
name: style-transfer
description: 把一份内容套上另一份素材的观感，输出 MiniMax H3 提示词。内容是视频时文字化，是图时指认；风格是图时指认，是视频时必须先抽成文字风格卡。必须显式声明迁移强度（只调色 / 加光照 / 全风格），否则下游会连构图一起改。当需要风格迁移、套调色、统一观感、把这段素材做成那种质感、风格复刻时使用。
---

# 风格迁移（内容源 + 风格源 → H3 提示词）

> **移植性**：第零～四节（输入形态、两边互不看、迁移强度、内容保持清单）与目标模型无关。**第五、六节（六段式 / T2VA 落位）是 MiniMax H3 专属**，换模型时替换为对应格式的 compose skill，逻辑部分不动。

一句判据：**内容不动，观感换掉**。

内容指的是主体、动作、构图、场景；观感指的是媒介、质感、调色、光照。分不清这两组的输出，都不是风格迁移。

## 零、两种输入各自怎么进（先定形态）

| 内容源 | 风格源 | 输出形态 | 内容 | 风格 |
|---|---|---|---|---|
| 视频 | 图 | Ref2VA | 文字化 | 指认 `<Picture N>` |
| 图 | 图 | Ref2VA | 指认 `<Picture 1>` | 指认 `<Picture 2>` |
| 视频 | 视频 | **T2VA**（全文字） | 文字化 | 文字风格卡 |

原因：**视频不作为参考素材传给下游**，所以视频里的一切（含它的风格）都必须落成文字。图可以直接指认，不用复述。

## 前置：先加载这三个 skill

1. `sequence-sheet-read` —— 内容源是视频时读它
2. `style-dna` —— 风格源是视频时，用它抽出文字风格卡
3. `h3-prompt-writing` —— 六段式或三段式字段名

**h3 里已经有三样东西，直接引用，不要自己另造：**

| 用途 | 位置 | 内容 |
|---|---|---|
| 媒介词表 | `references/base-en.txt` 4.1 节 | `Cinematic` / `live-action` / `2D-animated` / **`3D CG`** / `claymation` / `watercolor` / `vintage film`——媒介级迁移就从这张表里选词 |
| CG 风格范例 | `references/image-edit-example.txt` | `The target video uses a polished 3D animated-film style with soft warm lighting, like a modern family animation movie still.` |
| Style opening 位置 | `references/ref-en.txt` 5.2 节 | T2VA 写在 `[Shot 1]` **之后**；Ref2VA 写在 `[Shot 1]` **之前**，一到两句英文 |

h3 那三份 references 里没有「风格迁移」这个任务类别——风格怎么写、强度怎么控、什么时候该判死，是本 skill 补的部分；媒介词表和格式位置是 h3 已经定好的，照用。

## 一、输入契约：两边互相不看

| 槽 | 只看什么 | **禁止看什么** |
|---|---|---|
| 内容源 | 主体、动作、构图、场景陈设、景别 | 它的调色、质感、光照风格 |
| 风格源 | 媒介、笔触质感、调色、光照、构图倾向 | **它里面有什么内容**（人、物、场景） |

这条最容易违反。风格图里往往有人，模型会顺手把那个人写进输出——那就变成内容迁移了。必须显式排除：

```text
<Picture 2> supplies only the look. Its subject, people, objects, composition and content are NOT referenced.
```

## 二、迁移强度必须显式声明（最容易翻车的地方）

用户说「套个调色」，如果不说清取哪几项，下游会把构图也一起改。三档，选一档写死：

| 档 | 取什么 | 典型写法 |
|---|---|---|
| **轻 · 只调色** | 色相倾向、对比、饱和度、色偏 | `Match only the grade of <Picture 2>: warm highlights, cool shadows, raised contrast. Composition, lighting direction and texture stay as described below.` |
| **中 · 调色 + 光照** | 上面 + 光源数量/方向/硬度/色温 | `Match the grade and lighting quality of <Picture 2>.` |
| **重 · 全风格** | 上面 + 媒介、质感、颗粒、景深倾向 | `Apply the complete look of <Picture 2>: medium, texture, grain, grade and lighting.` |

**任何一档都要写「不取什么」**。不写就会默认全取。

用户没说强度时按「中」处理，并在 `analysis` 里提醒：`迁移强度未指定，按「调色 + 光照」处理；要全风格请说明`。

### 只有「重」档在提示词层面现实

这是必须提前告诉用户的边界，否则会反复试错：

| 想迁移的跨度 | 提示词能否可靠拉动 |
|---|---|
| 调色微调、颗粒增减、对比推一点 | ❌ 基本拉不动。实测：一份写得非常详细的调色描述 + 一张风格参考图，生成结果跟原片观感几乎一样。这类活在专业流程里是 LoRA 或专门的颜色参考节点干的 |
| 光照方向与硬度改变 | ⚠️ 有时有效，取决于内容描述有没有把原光线写死 |
| **媒介级迁移**：真人 → 3D CG / 写实 → 二次元 / 照片 → 油画 / 实拍 → 手绘 | ✅ 可靠。跨度越大越有效 |

所以接到「把这个片子的色调往暖里推一点」这类需求时，直接说明这不是提示词的活；接到「把这段真人视频做成那种 CG 质感」时，才是本 skill 的用武之地。

媒介级迁移必然改变人脸质感（真人会被 CG 化），这不算失败，是迁移本身的代价。

## 三、风格源是视频时：抽成文字卡

按 `style-dna` 的五个维度写，产出形如：

```text
[Style] 35mm film look with fine grain and slight halation; warm amber highlights against cool teal shadows, high contrast, medium saturation; single hard key light from upper left at 3200K with no fill; subject framed on the left third with a low horizon line.
```

这份卡直接进 `integrated_multimodal_description` 的开头（T2VA 要求先声明整体风格与初始构图）。

**风格卡里不能出现内容**：不写「一个人站在窗边」，只写「窗户方向来的硬光」。

## 四、内容保持清单

内容源是视频时，先列一份「不能变」的清单（进 `analysis`）：

```text
内容保持：主体（单人女性，长深棕发，taupe 细吊带）、动作（三次转头，约 2.7s）、构图（胸上中近景，人物偏中右）、场景（红砖墙 + 石板广场 + 鸽子）、镜头（Static Shot）
将被替换：调色、光照质感、颗粒、对比
```

这份清单是最后自检的依据——输出里这五项必须一致，只有观感变了。

## 五、六段式填充（Ref2VA 形态）

**1. `subject_definitions`**

```text
<Subject 1> is the single woman in the target video. Her face, facial features, hair, hair colour, skin tone, build and outfit are taken from <Picture 1> and must read as the same person. Her motion, blocking and framing follow the description below.

<Picture 1> is the content source: subject, wardrobe, pose and composition are read from it.

<Picture 2> supplies only the look: medium, texture, grain, grade and lighting quality are read from it. Its subject, people, objects, composition and content are NOT referenced and must not appear.

The scene and timing are described in text below. No reference video is used for this shot.
```

**2. `summary`**

一句话：把什么内容做成什么观感。

**3. `retention_analysis`**

```text
<Subject 1> (appears in [Shot 1]): fully_preserved - face, hair, outfit, pose, blocking and framing are unchanged from <Picture 1>.
<Picture 1> (content source): fully_preserved - subject and composition are read from it; its own grade, lighting quality and texture are replaced.
<Picture 2> (style source): fully_preserved - the grade, lighting quality, texture and grain defined for it are applied in full; its subject and content are explicitly excluded.
```

**风格源不要用 `weak_reference`。** 这是实测踩过的坑：`weak_reference` 字面意思是「只要大致像」，下游就真的弱处理它——四份测试里只有风格迁移这一项完全没生效，内容一个字没差、颜色和质感一点没变。

风格迁移要的是「观感完全一致」，`<Picture 2>` 的角色定义就是「提供观感」，所以标 `fully_preserved`。`weak_reference` 留给「大概有点像就行」的场景（比如服装 donor 只取版型轮廓）。

**这是有意偏离 h3 语义的**：`ref-en.txt` 里 `weak_reference` 的定义就是「只保留风格/类别/构图/气氛上的大致相似」，例子是 `<Video 1> (cut and pacing structure): weak_reference`——按它的原意，风格参考本该用 weak_reference。但实测下游会把「大致相似」执行成「几乎不生效」，所以这里以执行强度优先，用 `fully_preserved`。如果将来发现 fully_preserved 导致内容也被带进来，再退回 weak_reference 并靠文字承担全部风格强度。

**4. `detailed_description`**

**观感写在 `[Shot 1]` 之前，一到两句**——这是 Ref2VA 的格式要求（`ref-en.txt` 5.2 节）。写成独立的开头句，不要塞进 `[Shot 1]` 里面：

```text
The target video uses a polished 3D animated-film style with soft warm lighting and a low-saturation creamy grade.
[Shot 1] A vertical chest-up shot frames ...
```

T2VA 方向相反：风格写在 `[Shot 1]` **之后**，作为该镜头的开头描述（`[Shot 1] Live-action, cinematic, a medium-wide shot frames...`）。

**风格只描述一次**。观感靠开头定调，后面交给模型保持。

**双保险：即使有风格图，这段文字也必须写。** 只靠一张风格图加标记词，实测不可靠——下游可能完全忽略它，只按文字生成。文字负责「说什么」、图片负责「像不像」，缺一半都不稳。风格源是图时，文字里照样要有媒介、色调、光照、颗粒四项。

**5. `overall_soundscape` / 6. `non_diegetic_music`**

与内容源一致，风格迁移不动声音。

## 六、T2VA 形态的差别

内容源和风格源都是视频时，没有参考标签，走三段式：

```text
integrated_multimodal_description: [Shot 1] <风格卡> <内容描述逐镜头>
overall_soundscape: ...
non_diegetic_music: ...
```

风格卡放最前面（T2VA 规范要求开头声明整体风格），内容描述紧跟。其余规则见 `video-replica`。

## 七、输出卫生

同其他任务 skill：`prompt` 零污染、纯文本、无 Markdown、无元话语、无中文说明、无「迁移」「参考风格」这类叙述。

额外一条：**不出现 `cinematic` / `moody` / `beautiful` / `8k` 这类空词**——风格必须写成物理描述，见 `style-dna` 的空词禁令。

## 八、自检

- [ ] 输出形态判断正确（Ref2VA 还是 T2VA）
- [ ] 迁移强度写明了，并且写了「不取什么」
- [ ] 风格源里的内容（人、物、场景）一个都没进输出
- [ ] 内容保持清单五项逐条核对过
- [ ] 风格只描述一次，没有每句重复
- [ ] 没有空词
- [ ] 全文无 `<Video N>`（视频不进参考）

## 九、边界

- 缩图后颗粒、色偏、暗角会失真，精细质感需要高分辨率原图
- 无法判断拍摄设备与焦段，只描述观察到的光学现象（虚化、畸变、光晕）
- 「只迁移一部分」时下游可能不听话，把构图一起改；出现这种情况就把内容保持清单写得更硬（`framing must remain identical`, `subject must stay on the left third`）
- 交付的是可生成提示词，不是渲染结果
