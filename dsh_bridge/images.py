"""IMAGE tensor -> PNG/base64 helpers."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Any, Iterable

from .errors import BridgeError


def _to_numpy(tensor: Any):
    import numpy as np

    arr = tensor
    if hasattr(arr, "detach"):
        arr = arr.detach().cpu().numpy()
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr[..., None]
    return arr


def frame_to_png(frame: Any, max_side: int = 1568) -> bytes:
    """Convert one HxWxC float image (0..1) into PNG bytes."""
    import numpy as np
    from PIL import Image

    arr = _to_numpy(frame)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[-1] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    arr = arr[..., :3]
    arr = np.clip(arr, 0.0, 1.0)
    image = Image.fromarray((arr * 255.0 + 0.5).astype(np.uint8), "RGB")
    width, height = image.size
    scale = min(1.0, float(max_side) / float(max(width, height)))
    if scale < 0.999:
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=4)
    return buffer.getvalue()


def png_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def tensor_to_base64(image: Any, max_side: int = 1568) -> str:
    """Encode a single IMAGE batch element (1xHxWxC or HxWxC) to base64 PNG."""
    arr = _to_numpy(image)
    if arr.ndim == 4:
        arr = arr[0]
    return png_to_base64(frame_to_png(arr, max_side))


def flatten_batches(values: Iterable[Any]) -> list[Any]:
    """Expand any mix of HxWxC and BxHxWxC values into a flat frame list."""
    frames: list[Any] = []
    for value in values:
        if value is None:
            continue
        arr = _to_numpy(value)
        if arr.ndim == 3:
            frames.append(arr)
        elif arr.ndim == 4:
            frames.extend(arr[index] for index in range(int(arr.shape[0])))
        else:
            raise BridgeError("bad_image", f"expected HxWxC or BxHxWxC image, got shape {arr.shape}")
    if not frames:
        raise BridgeError("no_frames", "no images were connected")
    return frames


def frames_to_base64(frames: list[Any], max_side: int = 1568, limit: int = 12) -> list[str]:
    """Encode frames in order, keeping at most `limit` of them."""
    if not frames:
        raise BridgeError("no_frames", "no images were connected")
    keep = frames if limit <= 0 else frames[: int(limit)]
    return [png_to_base64(frame_to_png(frame, max_side)) for frame in keep]


def sample_indices(count: int, wanted: int) -> list[int]:
    if count <= 0:
        raise BridgeError("no_frames", "the image batch is empty")
    wanted = max(1, min(int(wanted), count))
    if wanted == 1:
        return [0]
    step = (count - 1) / float(wanted - 1)
    indices = sorted({int(round(i * step)) for i in range(wanted)})
    return indices


def batch_to_base64(
    image: Any,
    max_frames: int = 12,
    sample_frames: int = 0,
    max_side: int = 1568,
) -> list[str]:
    """Encode a batch, evenly sampling down to `sample_frames` (0 = cap only)."""
    arr = _to_numpy(image)
    if arr.ndim == 3:
        arr = arr[None, ...]
    if arr.ndim != 4:
        raise BridgeError("bad_image", f"expected BxHxWxC image, got shape {arr.shape}")
    total = int(arr.shape[0])
    limit = max(1, min(int(max_frames), total))
    wanted = int(sample_frames) if int(sample_frames) > 0 else limit
    wanted = max(1, min(wanted, limit))
    return [png_to_base64(frame_to_png(arr[i], max_side)) for i in sample_indices(total, wanted)]


def video_to_frames(video: Any) -> Any | None:
    """Best-effort frame extraction from a ComfyUI VIDEO value."""
    if video is None:
        return None
    for attr in ("get_components", "as_components"):
        getter = getattr(video, attr, None)
        if callable(getter):
            try:
                components = getter()
            except Exception:  # noqa: BLE001 - optional path
                continue
            frames = getattr(components, "images", None)
            if frames is not None:
                return frames
            if isinstance(components, dict):
                for key in ("images", "frames"):
                    if key in components and components[key] is not None:
                        return components[key]
    frames = getattr(video, "images", None)
    return frames


# --------------------------------------------------------------- contact sheet
#
# Every video-reading skill in the prompt system assumes the model sees ONE
# composite image plus an explicit grid declaration, not a bag of loose frames.
# A 16-cell sheet costs the same as an 8-cell one, so the default is to spend the
# whole budget.

SHEET_GAP = 4
SHEET_CELL_LONG = 400
SHEET_MAX_SIDE = 1568
SHEET_MAX_FRAMES = 16


@dataclass(frozen=True)
class SheetPlan:
    """How many frames to sample and how to lay them out."""

    frames: int
    cols: int
    rows: int
    sheets: int

    @property
    def total_sheets(self) -> int:
        return self.sheets


def plan_sheet(duration: float) -> SheetPlan:
    """Frame density table, mirrored from the `sequence-sheet-read` skill.

    <=2s 12 frames (4x3) | <=10s 16 (4x4) | <=20s two 16-cell sheets | else one
    sheet per ~12 seconds. Short clips are not short-changed: the token cost of a
    sheet does not depend on how many cells it holds.
    """
    length = max(0.0, float(duration or 0.0))
    if length <= 2.0:
        return SheetPlan(frames=12, cols=4, rows=3, sheets=1)
    if length <= 10.0:
        return SheetPlan(frames=16, cols=4, rows=4, sheets=1)
    if length <= 20.0:
        return SheetPlan(frames=16, cols=4, rows=4, sheets=2)
    return SheetPlan(frames=16, cols=4, rows=4, sheets=max(2, int(round(length / 12.0))))


def segment_bounds(duration: float, plan: SheetPlan, index: int = 0) -> tuple[float, float]:
    """Time span covered by sheet `index`, with the last one pinned to duration."""
    length = max(0.0, float(duration or 0.0))
    span = length / max(1, plan.total_sheets)
    start = span * index
    end = start + span if index < plan.total_sheets - 1 else length
    return start, max(start, end)


def segment_times(duration: float, plan: SheetPlan, index: int = 0) -> list[float]:
    """Evenly spaced sample timestamps for one sheet."""
    start, end = segment_bounds(duration, plan, index)
    count = max(1, plan.frames)
    if count == 1 or end <= start:
        return [start]
    step = (end - start) / float(count - 1)
    return [start + step * k for k in range(count)]


def _frame_to_pil(frame: Any):
    import numpy as np
    from PIL import Image

    arr = _to_numpy(frame)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[-1] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=-1)
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    arr = np.clip(arr[..., :3], 0.0, 1.0)
    return Image.fromarray((arr * 255.0 + 0.5).astype(np.uint8), "RGB")


def compose_sheet(
    frames: Iterable[Any],
    *,
    cols: int,
    rows: int,
    cell_long: int = SHEET_CELL_LONG,
    gap: int = SHEET_GAP,
    max_side: int = SHEET_MAX_SIDE,
):
    """Tile frames row-major into one PIL image.

    No burned labels, no timecode, no grid lines: numbers on the image get
    described as scene content by the model. Order and timing are carried by
    `sheet_declaration()` instead.
    """
    from PIL import Image

    cells = []
    for frame in frames:
        image = _frame_to_pil(frame)
        width, height = image.size
        scale = float(cell_long) / float(max(width, height))
        if scale < 0.999:
            image = image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS
            )
        cells.append(image)
    if not cells:
        raise BridgeError("no_frames", "no frames available to build a contact sheet")

    cell_w = max(cell.size[0] for cell in cells)
    cell_h = max(cell.size[1] for cell in cells)
    canvas = Image.new(
        "RGB",
        (cols * cell_w + (cols + 1) * gap, rows * cell_h + (rows + 1) * gap),
        (0, 0, 0),
    )
    for position, cell in enumerate(cells):
        row, column = divmod(position, cols)
        canvas.paste(cell, (gap + column * (cell_w + gap), gap + row * (cell_h + gap)))
    if max(canvas.size) > max_side:
        scale = float(max_side) / float(max(canvas.size))
        canvas = canvas.resize(
            (max(1, round(canvas.size[0] * scale)), max(1, round(canvas.size[1] * scale))),
            Image.LANCZOS,
        )
    return canvas


def build_sheet_array(
    frames: Iterable[Any],
    *,
    cols: int,
    rows: int,
    cell_long: int = SHEET_CELL_LONG,
    gap: int = SHEET_GAP,
    max_side: int = SHEET_MAX_SIDE,
):
    """Same layout as `compose_sheet`, returned as an HxWx3 float32 array in 0..1."""
    import numpy as np

    canvas = compose_sheet(
        frames, cols=cols, rows=rows, cell_long=cell_long, gap=gap, max_side=max_side
    )
    return np.asarray(canvas, dtype=np.float32) / 255.0


def build_contact_sheet(
    frames: Iterable[Any],
    *,
    cols: int,
    rows: int,
    cell_long: int = SHEET_CELL_LONG,
    gap: int = SHEET_GAP,
    max_side: int = SHEET_MAX_SIDE,
) -> bytes:
    """Tile frames row-major into one PNG (used when handing the sheet to the SDK)."""
    canvas = compose_sheet(
        frames, cols=cols, rows=rows, cell_long=cell_long, gap=gap, max_side=max_side
    )
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def sheet_declaration(
    plan: SheetPlan,
    duration: float,
    *,
    index: int = 0,
    label: str = "",
) -> str:
    """The fixed English block that must be attached to every sheet.

    Wording follows the `sequence-sheet-read` template on purpose: the 12-cell probe
    only scored perfectly because the declaration named the grid, the row-major order
    and the exact time formula. Do not paraphrase it.
    """
    start, end = segment_bounds(duration, plan, index)
    span = max(0.0, end - start)
    count = max(1, plan.frames)
    subject = label.strip() or "clip"
    if plan.total_sheets > 1:
        headline = (
            f"Input: sheet {index + 1} of {plan.total_sheets} for the {subject} — a "
            f"{plan.cols}x{plan.rows} contact sheet containing {count} frames sampled "
            f"uniformly from {start:.2f}s to {end:.2f}s of it."
        )
    else:
        headline = (
            f"Input: the frame sheet for the {subject} — a {plan.cols}x{plan.rows} "
            f"contact sheet containing {count} frames sampled uniformly from "
            f"{start:.2f}s to {end:.2f}s of it."
        )
    if count == 1:
        formula = f"The single cell is at approximately {start:.2f} seconds."
    else:
        formula = (
            f"Frame #k is at approximately {start:.2f} + (k-1)/({count - 1}) x {span:.2f} seconds."
        )
    return "\n".join(
        [
            headline,
            "Ordering: left-to-right, then top-to-bottom. The top-left cell is frame #1; "
            f"the bottom-right cell is frame #{count}.",
            formula,
            "Ignore the sheet borders, the gaps between cells, and any letterboxing; "
            "they are not part of the scene.",
        ]
    )


def declaration_from_meta(meta_text: str, *, label: str = "") -> str:
    """Rebuild the sheet declaration from the JSON emitted by `DSH_ContactSheet`.

    Returns an empty string when the meta carries no `span` — the caller then skips
    the declaration entirely and the model falls back to ordinal-only reading.
    """
    import json

    raw = (meta_text or "").strip()
    if not raw:
        return ""
    try:
        meta = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(meta, dict):
        return ""
    frames = int(meta.get("frames") or 0)
    cols = int(meta.get("cols") or 0)
    rows = int(meta.get("rows") or 0)
    span = float(meta.get("span") or 0.0)
    if frames < 1 or cols < 1 or rows < 1 or span <= 0:
        return ""
    plan = SheetPlan(frames=frames, cols=cols, rows=rows, sheets=1)
    return sheet_declaration(plan, span, label=label)


def image_blocks(data_urls: Iterable[str], text: str) -> list[dict[str, Any]]:
    """Build SDK content blocks: text first, then encoded images."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for b64 in data_urls:
        blocks.append({"type": "image", "data": b64, "mimeType": "image/png"})
    return blocks
