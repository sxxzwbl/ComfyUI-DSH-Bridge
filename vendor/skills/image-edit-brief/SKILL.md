---
name: image-edit-brief
description: 把一句图片修改要求写成 MiniMax H3 六段式编辑指令，核心是「保留清单 vs 替换清单」逐项写死。当需要局部重绘、换背景、换光、换材质、风格化、角色一致性、把这张图改成那样、图片编辑提示词时使用。
---

# 图像编辑指令（源图 + 文字要求 → H3 六段式）

> **移植性**：第一～三节（编辑类型、两张清单、多图分工）与目标模型无关。**第四节「六段式填充」是 MiniMax H3 专属**，换模型时替换为对应格式的 compose skill，逻辑部分不动。

图片编辑的成败几乎全压在一处：**你有没有把「什么不能变」逐项写死**。

只写「把背景换成海边」，模型会把脸、发型、光线、构图一起重画一遍。写清「脸/发型/眼睛/姿势/身体/构图/焦距全部保留，只换背景」，它才听话。

## 前置

- `character-sheet` —— 外观维度、donor 降级、「只指认不复述」
- `h3-prompt-writing` 的 `references/ref-en.txt` 与 `references/image-edit-example.txt` —— 六段式字段与编辑范例
- `style-dna` —— 涉及风格化时用

音频两段固定填 `N/A`（除极少数需要环境音的情况）。

## 一、编辑类型识别（先归类，再写）

| 类型 | 用户话术 | retention 主标记 | 保留重点 |
|---|---|---|---|
| 局部改动 | 「把杯子换成花瓶」 | `partially_preserved` | 全图除目标物件全保留 |
| 换背景 / 换场景 | 「背景换成海边」 | `partially_preserved` | 人物本体 + 姿势 + 光向 |
| 换光 / 换时间 | 「改成黄昏」 | `partially_preserved` | 几何、材质、颜色关系全保留 |
| 换材质 / 质感 | 「变成陶瓷的」 | `partially_preserved` | 形状、构图、光照方向 |
| 风格化 | 「转成 3D 渲染」「变油画」 | `partially_preserved` 或 `attribute_transfer` | 内容结构保留，观感全换 |
| 换服装 | 「换成这件衣服」 | `partially_preserved` + donor | 走 `outfit-swap` 的 donor 三件套 |
| 角色一致性 | 「换成这个人」 | `attribute_transfer` | 姿势、构图、光向、场景全保留 |

判不准就按**局部改动**处理——它的保留清单最严格，出错代价最小。

## 二、两张清单（本 skill 的核心）

进 `analysis`，也是 `retention_analysis` 的直接来源：

```text
【保留清单】逐项写死
face, facial features, hair, hairstyle, gaze direction, head angle, body pose, limb positions,
skin tone, body build, clothing, framing, camera angle, focal length, background layout, lighting direction

【替换清单】
the ceramic cup on the table → replaced by a tall glass vase with three white tulips

【不动清单】（容易被误改的）
cast shadows on the table, reflections on the window, depth of field falloff
```

三条硬要求：

1. **保留清单必须逐项**，不许写「其余保持不变」——那句话模型看不懂
2. **替换清单写「A 换成 B」，不写「加一个 B」**——后者会让 A 还在
3. **不动清单**专治连带损伤：影子、反射、景深这些光学结果最容易被顺手改掉

## 三、多图分工

| 情形 | 写法 |
|---|---|
| 只有一张图 | 它是内容源，`<Picture 1>` |
| 内容 + 服装/身份/风格参考 | `P1 = 内容`，`P2..= 参考`，按 `h3-prompt-writing` 的 `attribute_transfer` |
| 两张图都是内容（前后对比） | 明确说「`<Picture 1>` 是前，`<Picture 2>` 是后」，不要含糊 |

参考图里的主体必须被排除：`<Picture 2>` 只提供服装/身份，**它的姿势、背景、光线不进输出**。

## 四、六段式填充

**1. `subject_definitions`**

```text
<Subject 1> is the woman in <Picture 1>. Her face, facial features, hair, hairstyle, skin tone and body build come from <Picture 1> and must read as the same person. Her clothing, pose and framing also come from <Picture 1> unless stated otherwise below.

<Picture 1> is the content source: subject, clothing, pose, composition, background and lighting are read from it.
```

有第二张参考图时再加一条，并显式排除它的姿势与背景。

**2. `summary`**

一句话任务书。`h3-prompt-writing` 的范例惯例是用 `[reference generation]` 前缀，照抄即可。

**3. `retention_analysis`** ★ 本 skill 的重点段

逐条对齐第二节的两张清单：

```text
<Subject 1> (appears in [Shot 1]): partially_preserved - face, hair, eyes, skin tone, body build, pose, limb positions and clothing are retained exactly from <Picture 1>.
<Picture 1> (content source): partially_preserved - everything is retained except the ceramic cup on the table, which is replaced by a tall glass vase with three white tulips.
<Picture 1> cast shadows and reflections: fully_preserved - the shadow direction and the window reflection are unchanged.
```

**4. `detailed_description`**

图像任务用**静态单镜头骨架**，不要写成动态视频：

```text
The target video uses a single static shot. [Shot 1] A medium shot frames ... entirely visible from head to feet with space above and below. The camera holds completely still.
```

- 必须有构图锚点防裁切：`entire body visible from head to feet with space above and below`
- 必须写 `The camera holds completely still.`
- 改动点要具体：位置、朝向、与周围物件的关系

**5. `overall_soundscape`** —— 填 `N/A`（图像任务无音轨）

**6. `non_diegetic_music`** —— 填 `N/A`

## 五、输出卫生

- `prompt` 零污染、纯文本、无 Markdown、无元话语、无中文说明
- 不出现「编辑」「修改后」「原图」这类叙述——下游只需要知道画面里是什么
- 不出现 `Note:` / `建议` / `可能`
- 五官与服装只指认不复述

## 六、自检

- [ ] 编辑类型归类了，保留清单和替换清单都进了 `retention_analysis`
- [ ] 保留清单是逐项列出的，没有「其余保持不变」
- [ ] 替换清单写成「A 换成 B」，不是「加一个 B」
- [ ] 不动清单覆盖了影子、反射、景深
- [ ] 多图时写明了谁提供什么，参考图的主体被排除
- [ ] `detailed_description` 是静态镜头骨架 + 构图锚点 + `The camera holds completely still.`
- [ ] 音频两段是 `N/A`
- [ ] 无元话语、无中文、无 Markdown

## 七、边界

- 缩图会丢纹理细节（布料织纹、皮肤质感），精细改动需要高分辨率原图
- 无法保证文字/logo 类内容在重绘后保持原样，涉及文字时要在保留清单里单独点名
- 大面积重绘（超过画面一半）时会退化成「重画一张」，此时保留清单的作用有限，应改用更具体的构图锚点
- 交付的是可生成提示词，不是渲染结果
