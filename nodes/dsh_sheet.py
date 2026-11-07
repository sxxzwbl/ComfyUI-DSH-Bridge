"""Contact-sheet node: one video in, one frame grid plus its metadata out.

Why a separate node instead of letting the prompt node decode video:

* every video-reading skill assumes the model sees ONE composite image plus an
  explicit grid declaration, never a bag of loose frames;
* sampling density and grid geometry are visual decisions the operator should be
  able to see and tune in the graph;
* `VIDEO.get_frame_count()` / `get_frame_rate()` read the container header only,
  so frame count and duration cost nothing to obtain.

Frames are pulled with a streaming decode (or straight out of an in-memory
`VideoComponents`), so peak memory stays at O(max_frames) instead of O(all frames).
A 10 s 720p clip would cost ~2.5 GB if materialised whole.
"""

from __future__ import annotations

import json
from typing import Any

from comfy_api.latest import io

from ..dsh_bridge import config as config_module
from ..dsh_bridge import images as image_tools

CATEGORY = "DSH Bridge"


def _safe(call, fallback):
    try:
        return call()
    except Exception:  # noqa: BLE001 - every probe here is best effort
        return fallback


def video_meta(video: Any) -> tuple[int, float]:
    """(frame_count, fps) from the container header — decodes nothing."""
    total = _safe(lambda: int(video.get_frame_count() or 0), 0)
    rate = _safe(lambda: float(video.get_frame_rate() or 0), 0.0)
    return max(0, total), max(0.0, rate)


def _quadrant(frame: Any) -> int:
    rotation = getattr(frame, "rotation", None)
    if not rotation:
        return 0
    try:
        return int(round(float(rotation) / 90.0)) % 4
    except (TypeError, ValueError):
        return 0


def _frame_array(frame: Any):
    """One decoded frame -> HxWx3 float32 in 0..1, honouring the rotation tag."""
    import numpy as np

    try:
        arr = frame.to_ndarray(format="rgb24")
    except Exception:  # noqa: BLE001 - exotic pixel formats
        arr = np.asarray(frame.to_image().convert("RGB"))
    k = _quadrant(frame)
    if k:
        arr = np.rot90(arr, k=k)
    return np.ascontiguousarray(arr.astype(np.float32) / 255.0)


def _decode_from_source(source: Any, wanted: set[int]) -> dict[int, Any]:
    """Stream-decode `source` and keep only the wanted frame indices."""
    import av

    out: dict[int, Any] = {}
    if not wanted:
        return out
    stop_at = max(wanted)
    with av.open(source, mode="r") as container:
        stream = container.streams.video[0]
        for index, frame in enumerate(container.decode(stream)):
            if index in wanted:
                out[index] = _frame_array(frame)
                if index >= stop_at:
                    break
    return out


def _frames_from_components(video: Any, wanted: set[int]) -> dict[int, Any]:
    """Pull frames straight out of an already-materialised video tensor."""
    import numpy as np

    components = video.get_components()
    images = getattr(components, "images", None)
    if images is None:
        return {}
    batch = images
    if hasattr(batch, "detach"):
        batch = batch.detach().cpu().numpy()
    out: dict[int, Any] = {}
    for index in wanted:
        if 0 <= index < len(batch):
            out[index] = np.ascontiguousarray(np.asarray(batch[index], dtype=np.float32))
    return out


def _collect(video: Any, indices: list[int]) -> list[Any]:
    wanted = set(indices)
    source = _safe(lambda: video.get_stream_source(), None)
    if source is not None and (isinstance(source, (str, bytes)) or hasattr(source, "read")):
        frames = _safe(lambda: _decode_from_source(source, wanted), {})
        if frames:
            return [frames[i] for i in sorted(frames)]
    frames = _safe(lambda: _frames_from_components(video, wanted), {})
    if frames:
        return [frames[i] for i in sorted(frames)]
    raise RuntimeError(
        "could not read frames from the connected video: neither a decodable stream "
        "source nor in-memory components were available"
    )


class DSH_ContactSheet(io.ComfyNode):
    """Video -> frame grid + metadata for the DSH prompt node."""

    @classmethod
    def define_schema(cls):
        defaults = config_module.DEFAULTS
        return io.Schema(
            node_id="DSH_ContactSheet",
            display_name="DSH 帧阵列拼图",
            category=CATEGORY,
            description=(
                "把视频抽成若干帧、按网格拼成一张帧阵列图，并输出 DSH 节点需要的元数据。"
                "不烧数字、不烧时间码、不画网格线；顺序与时间靠元数据表达。"
            ),
            inputs=[
                io.Video.Input("video", display_name="视频", tooltip="接「加载视频」或任何 VIDEO 输出。"),
                io.Int.Input(
                    "max_frames",
                    default=16,
                    min=2,
                    max=64,
                    step=1,
                    display_name="抽多少帧",
                    tooltip="一张拼图最多 16 帧；要更多就拆成两张拼图。",
                ),
                io.Int.Input(
                    "sample_step",
                    default=0,
                    min=0,
                    max=600,
                    step=1,
                    display_name="抽帧步长",
                    tooltip="0 = 自动均匀抽帧。填数字则按固定间隔抽，一般不用改。",
                ),
                io.Int.Input("cols", default=4, min=1, max=8, step=1, display_name="列数"),
                io.Int.Input("rows", default=4, min=1, max=8, step=1, display_name="行数"),
                io.Int.Input(
                    "cell_long",
                    default=int(defaults.get("sheet_cell_long", 400)),
                    min=192,
                    max=1024,
                    step=8,
                    display_name="单格长边",
                    tooltip="每一小格的长边像素。低于 384 时服装纹理与脸部结构会糊。",
                ),
                io.Int.Input(
                    "gap",
                    default=int(defaults.get("sheet_gap", 4)),
                    min=0,
                    max=32,
                    step=1,
                    display_name="格子间隙",
                    tooltip="格子之间的空隙像素，只做视觉分隔。",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="帧阵列"),
                io.String.Output(display_name="时间轴"),
            ],
        )

    @classmethod
    def execute(cls, video, max_frames, sample_step, cols, rows, cell_long, gap):
        import torch

        total, fps = video_meta(video)
        wanted = max(2, int(max_frames))
        capacity = max(1, int(cols) * int(rows))
        wanted = min(wanted, capacity)

        step = int(sample_step or 0)
        if step > 0:
            # Manual stride: the operator asked for a fixed sampling interval, even
            # if that leaves the tail of the clip unobserved.
            indices = [k * step for k in range(wanted)]
            if total:
                indices = [index for index in indices if index < total]
        elif total > 1 and wanted > 1:
            # Automatic: spread evenly from the first frame to the LAST frame so the
            # whole clip is covered. A fixed stride would stop short — 81 frames at
            # 8 samples leaves the final 0.37 s unobserved.
            indices = [
                int(round(k * (total - 1) / float(wanted - 1))) for k in range(wanted)
            ]
        else:
            indices = list(range(wanted))
        if not indices:
            indices = [0]

        frames = _collect(video, indices)
        if not frames:
            raise RuntimeError("video produced no frames to build a sheet from")
        frames = frames[:capacity]

        array = image_tools.build_sheet_array(
            frames,
            cols=int(cols),
            rows=int(rows),
            cell_long=int(cell_long),
            gap=int(gap),
            max_side=int(config_module.DEFAULTS.get("sheet_max_side", 1568)),
        )
        sheet = torch.from_numpy(array).unsqueeze(0)

        # Span is measured between the first and last sampled frame, so it always
        # matches what the sheet actually contains.
        used = indices[: len(frames)]
        coverage = (used[-1] - used[0]) if len(used) > 1 else 0
        step_avg = int(round(coverage / float(len(used) - 1))) if len(used) > 1 else 0
        span = round(coverage / fps, 3) if (fps > 0 and coverage > 0) else 0.0

        meta: dict[str, Any] = {
            "frames": len(frames),
            "cols": int(cols),
            "rows": int(rows),
            "step": step_avg,
        }
        if fps > 0:
            meta["fps"] = round(fps, 3)
        if span > 0:
            meta["span"] = span
        if total:
            meta["total"] = total
        return io.NodeOutput(sheet, json.dumps(meta, ensure_ascii=False, separators=(",", ":")))


NODE_CLASS_MAPPINGS: dict[str, Any] = {"DSH_ContactSheet": DSH_ContactSheet}

NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {
    "DSH_ContactSheet": "DSH 帧阵列拼图",
}
