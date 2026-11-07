"""Multi-image test: three connected sockets, one understanding call."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent
PKG_NAME = "ComfyUI_DSH_Bridge_MultiTest"
sys.path.insert(0, str(PKG_DIR))

spec = importlib.util.spec_from_file_location(
    PKG_NAME, PKG_DIR / "__init__.py", submodule_search_locations=[str(PKG_DIR)]
)
pkg = importlib.util.module_from_spec(spec)
sys.modules[PKG_NAME] = pkg
spec.loader.exec_module(pkg)

import torch  # noqa: E402


def solid(rgb, size=256):
    tensor = torch.zeros((1, size, size, 3), dtype=torch.float32)
    tensor[0, :, :, 0] = rgb[0]
    tensor[0, :, :, 1] = rgb[1]
    tensor[0, :, :, 2] = rgb[2]
    return tensor


async def main() -> int:
    understand = pkg.NODE_CLASS_MAPPINGS["DSH_ImageUnderstand"]()
    t0 = time.time()
    analysis, tags, raw_json, status = await understand.run(
        image=solid((1.0, 0.0, 0.0)),          # #1 red
        focus="色彩",
        detail="简洁",
        session="multi-1",
        always_run=True,
        raise_on_error=False,
        # extra sockets, exactly as ComfyUI passes them
        image_2=solid((0.0, 1.0, 0.0)),        # #2 green
        image_3=solid((0.0, 0.0, 1.0)),        # #3 blue
    )
    print(f"[3 images {time.time()-t0:.1f}s] status={status}", flush=True)
    print("analysis:", analysis[:400], flush=True)
    print("json:", raw_json[:400], flush=True)

    prompt_node = pkg.NODE_CLASS_MAPPINGS["DSH_ImageToPrompt"]()
    t0 = time.time()
    prompt, negative, _, status2 = await prompt_node.run(
        image=solid((0.95, 0.6, 0.1)),
        target="通用",
        style="自然语言",
        negative=False,
        json_mode=False,
        session="multi-2",
        always_run=True,
        raise_on_error=False,
        image_2=solid((0.1, 0.4, 0.9)),
    )
    print(f"\n[2 images {time.time()-t0:.1f}s] status={status2}", flush=True)
    print("prompt:", prompt[:300], flush=True)

    hits = sum(1 for word in ("红", "绿", "蓝") if word in (analysis + raw_json))
    ok = status == "ok" and status2 == "ok" and hits >= 2
    print(f"\nMULTI: {'PASS' if ok else 'FAIL'} (colour hits={hits})")
    from dsh_bridge import BRIDGE

    BRIDGE.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
