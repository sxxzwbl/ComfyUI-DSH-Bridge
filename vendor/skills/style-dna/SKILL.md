---
name: style-dna
description: 从一张图或一段视频里抽出可独立复用的风格描述卡（媒介、质感、调色、光照、构图倾向），用于风格迁移、风格复刻或统一多镜头观感。当需要"把这张图的风格套到别的画面"、"让一组镜头看起来同一套调色"、或描述画面质感与光线时使用。
---

# 风格 DNA

风格描述必须能**脱离原图独立使用**。写完自问：把这段字交给一个从没见过原图的人，他能画出同样质感的东西吗？

## 一、五个维度（逐项写）

**1. 媒介 / 渲染方式**
`photographed on 35mm film` / `photographed digitally, shallow depth of field` / `hand-painted gouache illustration` / `3D render with subsurface scattering` / `cel-shaded animation`

**2. 笔触 / 质感**
`visible brush strokes with dry-brush texture` / `clean vector edges, no texture` / `fine film grain, slightly soft corners` / `sharp digital clarity, no grain`

**3. 调色**
要写四件事：色相倾向、对比、饱和度、是否有单一色偏
`warm amber highlights against cool teal shadows, high contrast, medium saturation, slight magenta cast in the midtones`

**4. 光照**
要写五件事：光源数量、方向、硬度、色温、是否有实际光源入画
`single hard key light from upper left, warm 3200K, no fill, deep black shadows, no visible light source in frame`

**5. 构图倾向**
`centered symmetrical composition, generous negative space at the top` / `off-center subject placed on the left third, low horizon`

## 二、必须与内容分离

风格卡里**不许出现主体、场景、动作**：

- 错：`a woman in a red dress lit by warm window light`（把内容和光混在一起）
- 对：`warm directional light from a window at camera-left, soft falloff, low contrast in shadows`

原因：迁移时如果风格卡里带着内容，下游会把那个内容一起搬过去，变成「换人 + 换场景」而不是「换风格」。

### 有风格参考图时：同样只指认、不复述

用户给了风格参考图，就不要再把风格用文字复述一遍——这和人物外观是同一个道理，文字会压过图片。

```text
The look of the target video comes from <Picture 2>: grade, texture, lighting quality and grain are read from it.
<Picture 2>'s subject, composition and content are NOT referenced.
```

文字版 Style DNA 只在两种情况下用：

1. 完全没有风格参考图
2. 只迁移风格的一部分（比如只统一调色）——这时才需要文字点明取哪几项、忽略哪几项

## 三、空词禁令

这些词一律不许出现，出现了等于没描述：

`cinematic` / `beautiful` / `aesthetic` / `high quality` / `8k` / `masterpiece` / `moody` / `vibe` / `stunning` / `professional`

替换方法：把形容词翻译成物理描述。
- `cinematic` → `anamorphic-looking widescreen framing, shallow depth of field, strong backlight haze`
- `moody` → `low-key lighting, single soft source from one side, deep shadows filling most of the frame`

## 四、输出格式

```text
[Style DNA]
Medium: photographed on 35mm film, slight halation around highlights
Texture: fine grain, soft edge falloff, no digital sharpening
Color: warm amber highlights against cool teal shadows, high contrast, medium saturation
Lighting: single hard key from upper left at 3200K, no fill, deep black shadows
Composition: subject on the left third, low horizon line, large negative space at right
```

给下游塞进提示词的紧凑版：

```text
Style: 35mm film look with fine grain and slight halation; warm amber highlights against cool teal shadows, high contrast, medium saturation; single hard key light from upper left at 3200K with no fill; subject on the left third with a low horizon.
```

## 五、两种迁移模式

**整段照搬**（目标画面只换风格，内容和构图都不动）：
`Apply the following look to <Video 1> without changing framing, blocking or timing: <Style DNA>`

**只取部分**（比如只统一调色）：
明确写出取哪几项、忽略哪几项。`Match only the color and lighting of <Picture 2>; composition and texture stay as in <Video 1>.`

不写清取哪几项，下游会把构图也一起改掉。

## 六、多镜头统一观感

一组镜头要看起来像同一套时：

1. 先在一张代表性画面上出一份 Style DNA
2. 其余镜头引用同一份，**字符串完全一致，不许改写**
3. 只允许在注释里说明差异（`this shot is backlit, same grade and grain apply`），不许改风格卡本身

## 七、边界

- 缩图后颗粒感和细微色偏会丢，需要精确复刻质感时要求提供高分辨率原图
- 无法从画面判断拍摄设备与镜头参数，只能描述观察到的光学现象（虚化程度、畸变、光晕），不猜焦段和机型
- 风格卡描述的是「看起来像什么」，不是「怎么拍出来的」

## 八、自检

- [ ] 五个维度都有内容
- [ ] 卡里没有任何主体/场景/动作描述
- [ ] 没有出现空词清单里的任何一个词
- [ ] 调色写了色相、对比、饱和度三项
- [ ] 光照写了方向、硬度、色温
- [ ] 迁移时明确写了取哪几项、忽略哪几项
- [ ] 多镜头引用时字符串完全一致
