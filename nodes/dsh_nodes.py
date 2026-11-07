"""The DSH prompt node: task in, skill-formed prompt out.

The node no longer knows what the four old modes were. It collects media, asks the
harness to load the skills for the selected task, and splits the reply into a clean
prompt slot and an analysis slot.

Media layout:

* ``sheets`` — frame-array images from ``DSH_ContactSheet``. Video-reading tasks
  need one; each sheet carries its own grid/time declaration via ``sheet_meta``.
* ``refs`` — reference images (person, garment, style, or a single content image for
  edit tasks). Which slot means what is stated in ``cast_spec``.

``task`` accepts ``auto``: the model picks the task, states it on the first line of
the analysis, then follows that skill's contract.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Any

from comfy_api.latest import io

from ..dsh_bridge import BRIDGE, error_status
from ..dsh_bridge import images as image_tools
from ..dsh_bridge import output as output_tools
from ..dsh_bridge import presets
from .dsh_sheet import DSH_ContactSheet

CATEGORY = "DSH Bridge"

TASKS = presets.TASK_CHOICES

# Only H3 is wired end to end: every task skill's "落位" section is written for H3.
# LTX needs a compose-ltx variant before it can be offered here.
_TARGETS = ["MiniMax H3"]

# The downstream only needs the prompt. Analysis, notes and the sheet meta go to
# the panel through BRIDGE.record(), which is why they are not sockets any more.
OUTPUT_NAMES = ("prompt", "status")

_SEEN_FAILURES: set[str] = set()


def _max_side() -> int:
    return int(BRIDGE.cfg.get("max_image_side", 1568))


def _video_slots() -> int:
    return max(1, min(100, int(BRIDGE.cfg.get("max_videos", 4))))


def _ref_slots() -> int:
    return max(1, min(100, int(BRIDGE.cfg.get("max_images", 12))))


def _session(logical: str, override: str) -> str:
    name = (override or logical).strip() or logical
    return BRIDGE.session_id(name)


def _fail(exc: BaseException) -> str:
    import traceback

    key = f"{type(exc).__name__}:{exc}"
    if key not in _SEEN_FAILURES:
        _SEEN_FAILURES.add(key)
        print(f"[DSH-Bridge] node failure -> {key}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    return error_status(exc)


def _sorted_autogrow(values: Any) -> list[Any]:
    """Payloads of one autogrow group in socket order (…_0 first)."""
    if not values:
        return []
    if not isinstance(values, dict):
        return [values] if values is not None else []

    def rank(item: tuple[str, Any]) -> int:
        try:
            return int(str(item[0]).rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return 10_000

    return [value for _, value in sorted(values.items(), key=rank) if value is not None]


def _media_inputs() -> list[Any]:
    return [
        io.Autogrow.Input(
            "sheets",
            optional=True,
            display_name="帧阵列图",
            tooltip="接 DSH 帧阵列拼图输出的「帧阵列」图。视频类任务必需。",
            template=io.Autogrow.TemplatePrefix(
                input=io.Image.Input("sheet", optional=True),
                prefix="sheet_",
                min=1,
                max=_video_slots(),
            ),
        ),
        io.Autogrow.Input(
            "refs",
            optional=True,
            display_name="参考图",
            tooltip="人物图、服装图、风格图，或图像编辑要改的那张图。各自含义写在「槽位说明」里。",
            template=io.Autogrow.TemplatePrefix(
                input=io.Image.Input("ref", optional=True),
                prefix="ref_",
                min=1,
                max=_ref_slots(),
            ),
        ),
    ]


OUTPUT_LABELS = {"prompt": "提示词", "status": "状态"}


def _outputs() -> list[Any]:
    return [io.String.Output(display_name=OUTPUT_LABELS.get(name, name)) for name in OUTPUT_NAMES]


@dataclass(frozen=True)
class PicturePlan:
    """Which images earn a ``<Picture N>`` number, and in what order."""

    order: tuple[str, ...]
    excluded: tuple[str, ...]
    sheet_count: int
    ref_count: int


def picture_plan(send_sheet: bool, ref_limit: int, sheet_count: int, ref_count: int) -> PicturePlan:
    """Decide ``<Picture N>`` from the node switches, not from prose.

    The order used to be guessed from the requirement text, which made the same
    sentence mean different things on different days. The switches are the rule
    now: the frame sheet is either part of the generator input or it is not, and
    the reference images take whatever slots are left, in input order.
    """
    if ref_limit and ref_limit > 0:
        ref_count = min(ref_count, ref_limit)
    order: tuple[str, ...] = ()
    if send_sheet and sheet_count > 0:
        order += ("sheet",)
    if ref_count > 0:
        order += ("ref",)

    def count(kind: str) -> int:
        return sheet_count if kind == "sheet" else ref_count

    excluded = tuple(kind for kind in ("sheet", "ref") if kind not in order and count(kind) > 0)
    return PicturePlan(order=order, excluded=excluded, sheet_count=sheet_count, ref_count=ref_count)


def picture_map(plan: "PicturePlan") -> list[dict[str, Any]]:
    """The slot table the panel prints after a run: which image lands where."""
    rows: list[dict[str, Any]] = []
    slot = 1
    role = {"sheet": "动作 / 构图 / 运镜参考", "ref": "身份 / 服装来源"}
    for kind in plan.order:
        count = plan.sheet_count if kind == "sheet" else plan.ref_count
        for index in range(1, count + 1):
            label = "帧图" if kind == "sheet" else f"参考图 {index}"
            rows.append(
                {
                    "kind": kind,
                    "index": index,
                    "label": label,
                    "slot": f"ref_image{slot}",
                    "role": role[kind],
                }
            )
            slot += 1
    return rows


def _reference_note(plan: "PicturePlan") -> str:
    """Number the attachments the way the model has to cite them.

    H3 speaks in ``<Picture N>``, and that number follows the node switches, not
    the wording of the request. Printing the resulting table explicitly is what
    keeps the prompt aligned with the graph the user will actually wire.

    The frame sheet is also not just background reading: when it is numbered it is
    the only reference for action, framing and camera movement. Saying so is what
    makes a person swap keep the original motion instead of inventing new blocking.
    """
    # Only the numbered ones reach the generator; the rest are read here and left out.
    total = sum(
        plan.sheet_count if kind == "sheet" else plan.ref_count for kind in plan.order
    )
    if total <= 0:
        return ""
    lines: list[str] = []
    label = {"sheet": "帧阵列图", "ref": "参考图"}
    counted = [
        f"{label[kind]} {plan.sheet_count if kind == 'sheet' else plan.ref_count} 张"
        for kind in plan.order
        if (plan.sheet_count if kind == "sheet" else plan.ref_count) > 0
    ]
    headline = f"实际输入到生成模型（MiniMax）的图片：共 {total} 张"
    if counted:
        headline += f"（{'、'.join(counted)}）"
    if plan.order:
        headline += "。槽位顺序：" + " → ".join(label[k] for k in plan.order) + "。"
    else:
        headline += "。"
    lines.append(headline)
    lines.append("图片编号（按上面的顺序，不得重排、不得跳过）：")
    index = 1
    for kind in plan.order:
        count = plan.sheet_count if kind == "sheet" else plan.ref_count
        for slot in range(count):
            where = f" {slot + 1}/{count}" if count > 1 else ""
            if kind == "sheet":
                lines.append(
                    f"<Picture {index}> = 帧阵列图{where}：源视频的抽帧拼图，是一张静态图片。"
                    "它是动作、构图、景别与运镜的参考 —— 按格子顺序读成一段连续镜头，"
                    "再把结果写进 detailed_description。图中人物、发型、服装、配饰一律不继承，"
                    "除非需求明确要求保留。"
                )
            else:
                lines.append(
                    f"<Picture {index}> = 参考图{where}：用途见下方槽位说明；"
                    "未作说明时按「人物身份 + 服装来源」理解。"
                )
            index += 1
    for kind in plan.excluded:
        count = plan.sheet_count if kind == "sheet" else plan.ref_count
        if count <= 0:
            continue
        lines.append(
            f"另外：附件末尾还有 {count} 张{label[kind]}，它们**不参与 <Picture N> 编号**，"
            "只用来补足你的理解；提示词里不得引用它们，也不要把它们写进 subject_definitions 或 retention_analysis。"
        )
    lines.append(
        "引用纪律：本次没有任何视频输入，"
        "输出里不得出现 <Video N>、不得出现「跟随源视频」「参考视频」这类说法；"
        "需要指认上述图片时只用 <Picture N>。"
    )
    return "\n".join(lines)


def _slot_text(value: Any) -> str:
    """Normalise ``cast_spec`` before it reaches the brief.

    A workflow saved from an older widget layout can hold a non-string here
    (``true`` showed up once), and that string would be forwarded verbatim as a
    slot declaration, quietly telling the model that slot one is called "true".
    Only real prose survives.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.lower() in {"true", "false", "none", "null", "undefined"}:
        return ""
    return text


def _needs_sheet(task: str) -> bool:
    """Tasks whose whole input is a video-derived sheet."""
    return task in ("video-replica", "person-swap", "outfit-swap", "action-transfer")


def _media_problem(task: str, sheet_count: int, ref_count: int) -> str:
    """Empty string when the attached media can serve this task."""
    if task == "auto":
        if sheet_count or ref_count:
            return ""
        return (
            "「自动判断」至少要有一张输入图：视频类任务把「帧阵列拼图」节点接到「帧阵列图」，"
            "其他任务把图片接到「参考图」。"
        )
    if _needs_sheet(task):
        if sheet_count:
            return ""
        return (
            f"任务「{presets.task_label(task)}」需要帧阵列图：把「帧阵列拼图」节点接到「帧阵列图」输入。"
        )
    if ref_count or sheet_count:
        return ""
    return f"任务「{presets.task_label(task)}」至少需要一张参考图：接到「参考图」输入。"


class DSH_PromptNode(io.ComfyNode):
    """Task-driven prompt engine."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DSH_PromptNode",
            display_name="DSH 提示词引擎",
            category=CATEGORY,
            description=(
                "选一个任务、接上帧阵列图与参考图，DSH 会按对应 skill 产出 MiniMax H3 提示词。"
                "task=auto 时由模型自己判断任务，并在分析段首行说明依据。"
            ),
            inputs=[
                io.Combo.Input(
                    "task",
                    options=list(TASKS),
                    default=presets.AUTO_LABEL,
                    display_name="任务",
                    tooltip="自动判断 = 由模型按需求判断该用哪个任务；也可以直接指定。",
                ),
                io.Combo.Input("target", options=_TARGETS, default="MiniMax H3", display_name="目标模型"),
                io.String.Input(
                    "requirement",
                    multiline=True,
                    default="",
                    display_name="需求",
                    placeholder="用一句话说清要做什么，例如：把视频里的人换成这张图里的人",
                    tooltip="说清要做什么。生成时这段会作为任务说明交给模型。",
                ),
                io.String.Input(
                    "cast_spec",
                    default="",
                    display_name="槽位说明",
                    tooltip="每张参考图分别是什么，例如：参考图1=人物，参考图2=服装；也可以写「保留原服装」这类规则。",
                ),
                io.String.Input(
                    "base_prompt",
                    optional=True,
                    multiline=True,
                    default="",
                    display_name="上一版提示词",
                    tooltip="填了就在这一版基础上改，不填就从素材重新写。",
                ),
                io.String.Input("session", default="default", display_name="会话名"),
                io.Boolean.Input(
                    "send_sheet",
                    default=True,
                    display_name="帧图是否做参考",
                    tooltip=(
                        "开：帧阵列图作为一个 ref_image 输入给 MiniMax，提示词里可以用它指认动作。"
                        "关：帧图只用来读动作，提示词完全不引用它。"
                    ),
                ),
                io.Int.Input(
                    "ref_limit",
                    default=0,
                    min=0,
                    max=12,
                    display_name="参考图数量上限",
                    tooltip="最多用前几张参考图；0 = 全部使用。超出的不发送，也不占 ref_image 槽位。",
                ),
                io.Boolean.Input(
                    "always_run", default=True, display_name="每次强制运行",
                    tooltip="关掉后，输入没变化时 ComfyUI 会复用上次结果。",
                ),
                io.Boolean.Input(
                    "raise_on_error", default=False, display_name="出错即中断",
                    tooltip="开：报错直接中断工作流；关：错误写进状态输出，流程继续。",
                ),
                io.String.Input(
                    "extra_hint", default="", display_name="附加要求",
                    tooltip="临时补充的额外要求，会在生成时一并交给模型。",
                ),
                *_media_inputs(),
                io.String.Input(
                    "sheet_meta",
                    optional=True,
                    force_input=True,
                    default="",
                    display_name="帧阵列时间轴",
                    tooltip="接帧阵列拼图节点的「时间轴」输出。缺了就没有时间信息，只能按格子顺序描述。",
                ),
            ],
            outputs=_outputs(),
            hidden=[io.Hidden.unique_id],
        )

    @classmethod
    def validate_inputs(cls, **kwargs: Any):
        return True

    @classmethod
    def fingerprint_inputs(cls, always_run: bool = True, **kwargs: Any):
        if always_run:
            return float("nan")
        keys = ("task", "target", "requirement", "cast_spec", "session", "sheet_meta", "base_prompt")
        return "|".join(str(kwargs.get(key, "")) for key in keys)

    @classmethod
    async def execute(
        cls,
        task: str,
        target: str,
        requirement: str,
        cast_spec: str,
        session: str,
        send_sheet: bool,
        ref_limit: int,
        always_run: bool,
        raise_on_error: bool,
        extra_hint: str = "",
        base_prompt: str = "",
        sheets: Any = None,
        refs: Any = None,
        sheet_meta: str = "",
    ):
        sheets = _sorted_autogrow(sheets)
        refs = _sorted_autogrow(refs)
        # Drop the tail the user excluded; the limit is applied before anything is
        # decoded, so unused reference images cost nothing.
        if ref_limit and ref_limit > 0:
            refs = refs[:ref_limit]
        cast_spec = _slot_text(cast_spec)
        # Decided before the request is built: it drives both the payload order and
        # the <Picture N> numbering, and it is reported back to the panel.
        plan = picture_plan(bool(send_sheet), 0, len(sheets), len(refs))
        started = time.time()
        # V3 hands hidden inputs to a per-run class clone, not through **kwargs.
        node_id = getattr(getattr(cls, "hidden", None), "unique_id", None)
        chosen = presets.task_id(task)

        def record(payload: dict[str, Any]) -> None:
            """Hand the full result to the panel; the sockets stay clean."""
            BRIDGE.record(
                node_id,
                {
                    "task": chosen,
                    "task_label": presets.task_label(chosen),
                    "target": target,
                    "requirement": requirement,
                    "cast_spec": cast_spec,
                    "base_prompt": base_prompt,
                    "sheets": len(sheets),
                    "refs": len(refs),
                    "send_sheet": bool(send_sheet),
                    "ref_limit": int(ref_limit or 0),
                    "picture_order": list(plan.order),
                    "picture_unused": list(plan.excluded),
                    "picture_map": picture_map(plan),
                    "sheet_meta": sheet_meta,
                    "elapsed_s": round(time.time() - started, 1),
                    **payload,
                },
            )

        try:
            problem = _media_problem(chosen, len(sheets), len(refs))
            if problem:
                raise ValueError(problem)

            # Decode once, then order the payloads the way the user says they will
            # wire them into the generator: the model reads the same sequence here
            # as the one it has to cite, so <Picture N> cannot drift.
            sheet_payloads = [
                image_tools.tensor_to_base64(sheet, sheet_max_side()) for sheet in sheets
            ]
            ref_payloads = [image_tools.tensor_to_base64(ref, _max_side()) for ref in refs]
            pool = {"sheet": sheet_payloads, "ref": ref_payloads}
            pictures: list[str] = []
            for kind in plan.order:
                pictures.extend(pool[kind])
            # Anything the user did not cite still goes along for reading, but it
            # is declared as uncounted so it never earns a <Picture N>.
            for kind in plan.excluded:
                pictures.extend(pool[kind])

            declaration = image_tools.declaration_from_meta(sheet_meta, label="source video")
            # Keep the exact payloads on disk: the chat panel shares this session
            # and must be able to attach the same pictures on its next turn.
            BRIDGE.attach_images(node_id, pictures)
            note = _reference_note(plan)
            brief = presets.task_brief(
                chosen,
                sheet_declaration=declaration,
                reference_note=note,
                requirement=requirement,
                cast_spec=cast_spec,
                extra=extra_hint,
                base_prompt=base_prompt,
                auto=(chosen == "auto"),
            )
            result = await asyncio.to_thread(
                BRIDGE.ask, _session("auto" if chosen == "auto" else chosen, session), brief, pictures
            )
            parsed = output_tools.split_sections(result.get("text", ""))
            prompt = parsed.get("prompt", "")
            if not prompt:
                # The model ignored the banners; ship the raw text so nothing is lost.
                prompt = output_tools.clean_prompt(parsed.get("raw", ""))
            if not prompt.strip():
                # An empty turn is almost always a credential problem: the harness
                # swallows the provider error and reports a successful empty reply.
                # Saying so beats handing the user a blank box to guess at.
                note = (
                    "模型返回了空内容。最常见的原因是 API key 无效或额度不足；"
                    "其次是 baseURL 不可达。请检查 config.json 的 api_key，"
                    "或用环境变量 DEEPSEEK_API_KEY 给一个有效 key。"
                )
                record({"prompt": "", "analysis": note, "notes": "", "status": "空回复"})
                return ("", "空回复")
            record(
                {
                    "prompt": prompt,
                    "analysis": parsed.get("analysis", ""),
                    "notes": parsed.get("notes", ""),
                    "status": "ok",
                }
            )
            return (prompt, "ok")
        except Exception as exc:  # noqa: BLE001
            if raise_on_error:
                record({"prompt": "", "analysis": "", "notes": "", "status": "raised"})
                raise
            code = _fail(exc)
            record({"prompt": "", "analysis": f"{type(exc).__name__}: {exc}", "notes": "", "status": code})
            return ("", code)


def sheet_max_side() -> int:
    """Sheets are already sized by DSH_ContactSheet; never rescale them again."""
    return 100_000


NODE_CLASS_MAPPINGS: dict[str, Any] = {
    "DSH_PromptNode": DSH_PromptNode,
    "DSH_ContactSheet": DSH_ContactSheet,
}

NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {
    "DSH_PromptNode": "DSH 提示词引擎",
    "DSH_ContactSheet": "DSH 帧阵列拼图",
}

# The four mode-pinned legacy nodes were retired with the task refactor: they cannot
# express the new task contracts. Kept as empty mappings so the loader config and the
# package exports stay valid.
LEGACY_NODE_CLASS_MAPPINGS: dict[str, Any] = {}
LEGACY_NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}
