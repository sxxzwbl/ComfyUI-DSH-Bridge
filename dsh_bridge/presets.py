"""Prompt contracts.

Two generations live here:

* **Task system** (top of file) — six task ids, each mapping to a set of skills
  from `~/.dsh/skills`, a brief, an analysis checklist and a prompt contract. This
  is the path the skill system was built for.
* **Legacy builders** (bottom) — the four original per-mode builders. Still what
  `nodes/dsh_nodes.py` calls; kept untouched so the current node keeps working.

The knowledge itself lives in the skills. This module only carries the wiring, so
when a task's rules change, nothing here has to change.
"""

from __future__ import annotations

# ---------------------------------------------------------------- task system
#
# The four builders below predate the skill system and are kept for the current
# node. Everything from here down is the task-driven path: one task id maps to a
# set of skills to load, a brief, an analysis checklist and a prompt contract.
# The knowledge lives in ~/.dsh/skills; this file only carries the wiring.

TASK_ORDER = (
    "video-replica",
    "person-swap",
    "outfit-swap",
    "action-transfer",
    "style-transfer",
    "image-edit-brief",
)

TASK_LABELS = {
    "video-replica": "视频复刻",
    "person-swap": "人物替换",
    "outfit-swap": "服装替换",
    "action-transfer": "动作迁移",
    "style-transfer": "风格迁移",
    "image-edit-brief": "图像编辑指令",
}

# The combo shows Chinese; the id is what every skill and session name uses.
AUTO_LABEL = "自动判断"
TASK_CHOICES = tuple([AUTO_LABEL] + [TASK_LABELS[key] for key in TASK_ORDER])
LABEL_TO_ID = {label: key for key, label in TASK_LABELS.items()}
LABEL_TO_ID[AUTO_LABEL] = "auto"


def task_id(choice: str) -> str:
    """Map a combo label (Chinese) or a bare id back to the task id."""
    raw = (choice or "").strip()
    if raw in LABEL_TO_ID:
        return LABEL_TO_ID[raw]
    if raw in TASK_LABELS or raw == "auto":
        return raw
    return "auto"


def task_label(task: str) -> str:
    return TASK_LABELS.get(task, AUTO_LABEL)

# Order matters: the task skill goes first so the model reads the task rules
# before the supporting knowledge.
TASK_SKILLS = {
    "video-replica": ("video-replica", "sequence-sheet-read", "shot-grammar", "h3-prompt-writing"),
    "person-swap": ("person-swap", "sequence-sheet-read", "shot-grammar", "h3-prompt-writing"),
    "outfit-swap": (
        "outfit-swap",
        "sequence-sheet-read",
        "shot-grammar",
        "character-sheet",
        "h3-prompt-writing",
    ),
    "action-transfer": ("action-transfer", "sequence-sheet-read", "shot-grammar", "h3-prompt-writing"),
    "style-transfer": ("style-transfer", "sequence-sheet-read", "style-dna", "h3-prompt-writing"),
    "image-edit-brief": ("image-edit-brief", "character-sheet", "h3-prompt-writing"),
}

TASK_BRIEF = {
    "video-replica": "把这段视频读成一份 MiniMax H3 提示词，让下游只看这份文字就能复刻出同款。",
    "person-swap": "把源视频里的人换成参考图中的人，动作、走位、镜头、背景保持不变。",
    "outfit-swap": "把源视频里的人身上的衣服换成服装来源里的那一套，人或场景保持不变。",
    "action-transfer": "把动作源视频里的动作搬到参考图的人物身上，场景另行指定。",
    "style-transfer": "把内容套上风格来源的观感，内容本身不动。",
    "image-edit-brief": "把修改要求写成 MiniMax H3 编辑指令，核心是保留清单与替换清单。",
}

TASK_CHECKLIST = {
    "video-replica": (
        "复刻清单：（场景地标与道具、主体外观与穿着、动作时序、镜头语言、光线调色、音效音乐，各一句）",
        "精度限制：（抽样帧数、无法观察的中间过程）",
    ),
    "person-swap": (
        "替换映射：（S序号→P序号，或「保留原样」）",
        "外观归属：（脸、发型、服装、配饰各跟谁）",
        "保留原样：（声明保留的项，没有就写「无」）",
        "人物盘点：（每人一行：序号、位置、占比、外观性别、是否主体）",
        "依据与提醒：",
    ),
    "outfit-swap": (
        "人物来源路径：（A 只给服装图 / B 人物图+服装图 / C 纯文字，并说明理由）",
        "换装映射：",
        "外观归属：",
        "限制：（走 A 或 C 路径时必须写明「人脸一致性不保证」）",
    ),
    "action-transfer": (
        "动作来源：（几段动作、总时长、抽样帧数）",
        "已剥离：（原人物外观、原服装、原场景、原镜头、原音效）",
        "外观归属：",
        "场景：（文字指定 / 指认图片 / 中性默认并提醒）",
        "起止姿势：",
    ),
    "style-transfer": (
        "内容保持清单：",
        "将被替换：（媒介与渲染方式、材质质感、调色、光照，各一句）",
        "迁移强度：（轻 / 中 / 重）",
        "不取什么：（风格源里的主体与内容，逐项列出）",
    ),
    "image-edit-brief": (
        "编辑类型：",
        "保留清单：（逐项列，不许写「其余保持不变」）",
        "替换清单：（A 换成 B 的写法）",
        "不动清单：（影子、反射、景深）",
    ),
}

_REF2VA_NOTE = (
    "Ref2VA 六段式：subject_definitions / summary / retention_analysis / "
    "detailed_description / overall_soundscape / non_diegetic_music"
)
_T2VA_NOTE = (
    "T2VA 三段式：integrated_multimodal_description / overall_soundscape / non_diegetic_music"
)

TASK_PROMPT_NOTE = {
    "video-replica": _T2VA_NOTE,
    "person-swap": _REF2VA_NOTE,
    "outfit-swap": _REF2VA_NOTE,
    "action-transfer": _REF2VA_NOTE,
    "style-transfer": _REF2VA_NOTE + "（内容源与风格源都是视频时改用 " + _T2VA_NOTE + "）",
    "image-edit-brief": _REF2VA_NOTE,
}


def skills_for(task: str) -> tuple[str, ...]:
    return TASK_SKILLS.get(task, TASK_SKILLS["video-replica"])


def task_brief(
    task: str,
    *,
    sheet_declaration: str = "",
    reference_note: str = "",
    requirement: str = "",
    cast_spec: str = "",
    scene: str = "",
    extra: str = "",
    base_prompt: str = "",
    auto: bool = False,
) -> str:
    """Assemble the user message for one task run.

    `sheet_declaration` is produced by `images.sheet_declaration()` and must be
    passed through verbatim — the model is not allowed to rewrite the ordering or
    timing formula. `reference_note` describes the reference images that follow
    the sheet (which one is a person, which is a garment, and so on).

    With `auto=True` the checklist is not pre-selected: the model must name the task
    on the first line of the analysis, then follow that skill's own contract.

    `base_prompt` carries the previous round's output. The panel keeps the two
    channels apart (chat vs. prompt workbench), so iteration cannot lean on session
    history — the previous version has to be handed over explicitly.
    """
    blocks: list[str] = []
    if requirement.strip():
        blocks.append(f"具体要求：{requirement.strip()}")
    if cast_spec.strip():
        blocks.append(f"槽位与规则说明：{cast_spec.strip()}")
    if scene.strip():
        blocks.append(f"场景指定：{scene.strip()}")
    if extra.strip():
        blocks.append(f"附加要求：{extra.strip()}")
    if base_prompt.strip():
        blocks.append(
            "下面是上一版提示词。请在这一版的基础上按新要求修改：保留仍然成立的部分，"
            "只改动新要求涉及的地方，不要从零重写，也不要改动没被要求改的部分。\n"
            "--- 上一版开始 ---\n"
            f"{base_prompt.strip()}\n"
            "--- 上一版结束 ---"
        )

    parts: list[str] = []
    if sheet_declaration.strip():
        parts.append(sheet_declaration.strip())
    if reference_note.strip():
        parts.append(reference_note.strip())
    if blocks:
        parts.append("\n".join(blocks))

    if auto:
        parts.append(
            "任务：先判断这段需求该用哪个任务，可选 "
            + " / ".join(TASK_ORDER)
            + "。判断完再执行，不要同时做两件事。"
        )
        parts.append(
            "请先作出判断，然后调用 skill 工具加载该任务对应的 skill（以及它的前置 skill），"
            "并严格按那个 skill 执行。"
        )
        checklist = "\n".join(
            (
                "判定任务：（任务名 — 一句依据，依据要指向素材与需求的具体特征）",
                "按该任务 skill 要求的清单逐项填写（本节点不预设清单，以 skill 为准）",
            )
        )
        prompt_note = "按选中任务 skill 规定的输出结构填写"
    else:
        key = task if task in TASK_BRIEF else "video-replica"
        skills = "、".join(skills_for(key))
        parts.append(f"任务：{TASK_BRIEF[key]}")
        parts.append(f"请先调用 skill 工具加载以下 skill，再严格按 {key} 执行：{skills}。")
        checklist = "\n".join(TASK_CHECKLIST[key])
        prompt_note = TASK_PROMPT_NOTE[key]

    parts.append(
        "输出结构严格如下，不要加别的段落：\n"
        "=== ANALYSIS ===\n"
        f"{checklist}\n"
        "=== PROMPT ===\n"
        f"（{prompt_note}）\n"
        "PROMPT 段的硬性要求：\n"
        "1. 正文一律英文。只有对白、歌词、画面上可见的文字保留原语言。\n"
        "2. 纯文本：字段名不加粗、标签不套反引号、不用 Markdown 标题。\n"
        "3. 全文不出现 <Video N>——源视频只作为信息源，不作为生成输入。\n"
        "ANALYSIS 段可以用中文，它是给人看的，不进下游编码器。"
    )
    return "\n\n".join(parts)


SKILL_HINTS = {
    "MiniMax H3": "先调用 skill 工具加载 h3-prompt-writing，然后严格按 H3 的六段结构输出。",
    "LTX-2.5": "先调用 skill 工具加载 ltx-prompt-writing，然后严格按 LTX 的镜头结构输出。",
    "Wan": "按 Wan 视频模型常用结构输出：主体动作、镜头运动、环境与光线。",
    "Flux": "按 Flux 偏好输出：自然语言长句，主体+场景+风格+镜头+光线，不堆砌权重词。",
    "SDXL": "按 SDXL 偏好输出：逗号分隔的标签流，前 8 个标签承担主体与风格。",
    "通用": "输出可直接用于图像生成模型的提示词。",
}

_DETAIL_HINT = {
    "简洁": "输出 1 句话，不超过 40 个词，只保留最关键信息。",
    "标准": "输出 3-5 句，覆盖主体、场景、风格、光线。",
    "详尽": "输出 8-12 句，覆盖主体、场景、风格、光线、构图、镜头、色彩、材质，并给出镜头参数建议。",
}


def _count_line(count: int) -> str:
    if count <= 1:
        return ""
    return (
        f"共 {count} 张图，按连接顺序编号 #1…#{count}；用编号指代具体某一张，"
        "跨图保持一致的主体与风格判断。"
    )


def image_understand(focus: str, detail: str, hint: str, count: int = 1) -> str:
    parts = [
        _count_line(count),
        "分析这张图片，按固定顺序叙述：主体 → 场景 → 风格 → 光线 → 构图/镜头 → 色彩 → 材质。",
        f"关注重点：{focus}。",
        _DETAIL_HINT.get(detail, _DETAIL_HINT["标准"]),
        "输出格式严格如下（不要加任何前后缀、不要用代码块）：",
        "【分析】…",
        "【关键词】词1, 词2, 词3",
        "【JSON】{…}",
        "其中【JSON】是一行合法 JSON，字段：subject, scene, style, lighting, composition, lens, color, materials, text。",
    ]
    if count > 1:
        parts.append("有多个对象时，【JSON】用 {\"images\": [{…}, {…}]} 逐张给出，顺序与 #编号 一致。")
    if hint:
        parts.append(f"附加要求：{hint}")
    return "\n".join(part for part in parts if part)


def image_to_prompt(
    target: str,
    style: str,
    negative: bool,
    json_mode: bool,
    draft: str,
    hint: str,
    count: int = 1,
) -> str:
    skill = SKILL_HINTS.get(target, SKILL_HINTS["通用"])
    parts = [
        _count_line(count),
        f"为这张图片生成提示词。目标模型：{target}。{skill}",
        f"风格形态：{style}。",
        "只输出成品，不要解释、不要用代码块包裹。",
    ]
    if count > 1:
        parts.append(
            "多张图时先判断它们的关系（同一主体的多视角 / 同一场景的不同时刻 / 风格或构图参考），"
            "再据此合成一条提示词，不要逐张罗列。"
        )
    if draft.strip():
        parts.append("已有草稿如下，请在保留有效信息的前提下改写，而不是从零重写：\n" + draft.strip())
    if json_mode:
        parts.append('输出一行合法 JSON：{"positive": "...", "negative": "...", "params": {...}}')
    else:
        parts.append("先输出【正向提示词】，换行后再输出【负向提示词】。" if negative else "输出【正向提示词】。")
    if hint:
        parts.append(f"附加要求：{hint}")
    return "\n".join(part for part in parts if part)


def image_edit(mode: str, instruction: str, hint: str, count: int = 1) -> str:
    parts = [
        _count_line(count),
        f"编辑模式：{mode}。",
        f"修改要求：{instruction.strip() or '（未填写，按画面明显缺陷做最小改动）'}",
        "规则：主体、构图、识别特征保持不变，只改要求里提到的维度；不要引入新主体。",
    ]
    if count > 1:
        parts.append("#1 视为待编辑原图，其余 #2…#N 视为参考（风格 / 背景 / 角色）。")
    if mode == "首帧→尾帧":
        parts.append('输出一行合法 JSON：{"first_frame": "...", "last_frame": "...", "motion": "..."}，'
                     "motion 描述两个关键帧之间的运动与镜头变化。")
        return "\n".join(part for part in parts if part)
    parts.append("输出【重绘提示词】与【负向提示词】两段，不要解释。")
    return "\n".join(part for part in parts if part)


def video_prompt(
    target: str,
    structure: str,
    duration_s: float,
    audio: bool,
    hint: str,
    count: int = 1,
) -> str:
    skill = SKILL_HINTS.get(target, SKILL_HINTS["通用"])
    parts = [
        f"根据这些按时间顺序抽取的帧（共 {count} 张），写出视频生成提示词。目标模型：{target}。{skill}",
        f"成片时长约 {duration_s:g} 秒，结构：{structure}。",
        "只输出成品。",
    ]
    if structure == "分镜timeline":
        parts.append(
            '先输出【总述】，再输出一行合法 JSON：{"duration_s": <数值>, "segments": '
            '[{"t0": <秒>, "t1": <秒>, "desc": "...", "camera": "..."}]}，'
            "段落时间轴必须连续覆盖 0 到 duration_s。"
        )
    elif structure == "单镜头":
        parts.append("输出【提示词】一段，包含主体动作、环境、光线、镜头运动、时长。")
    elif structure == "首尾帧":
        parts.append('输出一行合法 JSON：{"first_frame": "...", "last_frame": "...", "motion": "..."}。')
    else:
        parts.append("输出【运镜描述】一段：景别、机位、运动轨迹、速度节奏。")
    if audio:
        parts.append("追加【声音】一行：环境音与音效，不要写音乐。")
    if hint:
        parts.append(f"附加要求：{hint}")
    return "\n".join(part for part in parts if part)
