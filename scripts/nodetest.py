"""Node-level test: builds real IMAGE tensors and runs the four nodes end to end."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent
PKG_NAME = "ComfyUI_DSH_Bridge_Test"
sys.path.insert(0, str(PKG_DIR))


def load_package():
    spec = importlib.util.spec_from_file_location(
        PKG_NAME, PKG_DIR / "__init__.py", submodule_search_locations=[str(PKG_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = module
    spec.loader.exec_module(module)
    return module


def frame(batch: int, h: int, w: int, rgb):
    import torch

    tensor = torch.zeros((batch, h, w, 3), dtype=torch.float32)
    for index, (r, g, b) in enumerate(rgb):
        tensor[index, :, :, 0] = r
        tensor[index, :, :, 1] = g
        tensor[index, :, :, 2] = b
    return tensor


async def main() -> int:
    pkg = load_package()
    nodes = pkg.NODE_CLASS_MAPPINGS
    print("registered:", sorted(nodes), flush=True)

    # 1) image understand -------------------------------------------------
    node = nodes["DSH_ImageUnderstand"]()
    t0 = time.time()
    analysis, tags, js, status = await node.run(
        image=frame(1, 256, 256, [(0.1, 0.4, 0.9)]),
        focus="整体",
        detail="简洁",
        session="nodetest-understand",
        always_run=True,
        raise_on_error=False,
    )
    print(f"\n[understand {time.time()-t0:.1f}s] status={status}\n  analysis={analysis[:120]!r}\n  tags={tags[:80]!r}\n  json={js[:120]!r}", flush=True)

    # 2) image to prompt --------------------------------------------------
    node = nodes["DSH_ImageToPrompt"]()
    t0 = time.time()
    prompt, negative, js2, status2 = await node.run(
        image=frame(1, 384, 384, [(0.9, 0.7, 0.2)]),
        target="Flux",
        style="自然语言",
        negative=True,
        json_mode=False,
        session="nodetest-prompt",
        always_run=True,
        raise_on_error=False,
    )
    print(f"\n[prompt {time.time()-t0:.1f}s] status={status2}\n  prompt={prompt[:200]!r}\n  negative={negative[:120]!r}", flush=True)

    # 3) image edit -------------------------------------------------------
    node = nodes["DSH_ImageEdit"]()
    t0 = time.time()
    edit_prompt, edit_neg, status3 = await node.run(
        image=frame(1, 320, 320, [(0.2, 0.8, 0.5)]),
        instruction="把背景换成傍晚的城市街道，主体不动",
        mode="换背景",
        session="nodetest-edit",
        always_run=True,
        raise_on_error=False,
    )
    print(f"\n[edit {time.time()-t0:.1f}s] status={status3}\n  prompt={edit_prompt[:200]!r}\n  negative={edit_neg[:100]!r}", flush=True)

    # 4) video prompt -----------------------------------------------------
    node = nodes["DSH_VideoPrompt"]()
    colors = [(0.1, 0.1, 0.1), (0.3, 0.3, 0.35), (0.6, 0.5, 0.3), (0.9, 0.7, 0.2),
              (0.9, 0.5, 0.1), (0.7, 0.3, 0.1), (0.4, 0.2, 0.2), (0.2, 0.15, 0.2)]
    t0 = time.time()
    video_prompt, timeline, motion, status4 = await node.run(
        images=frame(8, 256, 320, colors),
        target="MiniMax H3",
        structure="分镜timeline",
        duration_s=5.0,
        sample_frames=4,
        audio=True,
        session="nodetest-video",
        always_run=True,
        raise_on_error=False,
    )
    print(f"\n[video {time.time()-t0:.1f}s] status={status4}\n  prompt={video_prompt[:240]!r}\n  timeline={timeline[:240]!r}\n  motion={motion[:120]!r}", flush=True)

    ok = all(s == "ok" for s in (status, status2, status3, status4))
    print(f"\nNODES: {'PASS' if ok else 'FAIL'}")
    pkg.NODE_CLASS_MAPPINGS  # keep reference
    from dsh_bridge import BRIDGE

    BRIDGE.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
