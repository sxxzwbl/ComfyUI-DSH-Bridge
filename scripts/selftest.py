"""Standalone self-test: exercises the bridge without a running ComfyUI.

    python scripts/selftest.py            # text + image turn through the pipe
    python scripts/selftest.py --parse    # offline output-parser checks only
"""

from __future__ import annotations

import base64
import json
import sys
import zlib
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_DIR))

from dsh_bridge import output as output_tools  # noqa: E402


def make_png(rgb=(30, 150, 220), size: int = 320) -> bytes:
    import struct

    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def check_parsers() -> int:
    sample = """【分析】一支红色的花在窗台上。\n【关键词】红花, 窗台, 自然光\n【JSON】{"subject": "红花", "scene": "窗台"}"""
    analysis, tags, raw = output_tools.split_analysis(sample)
    print("analysis:", analysis)
    print("tags:", tags)
    print("json:", raw)

    sample2 = "【正向提示词】a red flower on a windowsill, soft light\n【负向提示词】blurry, low contrast"
    pos, neg, _ = output_tools.split_positive_negative(sample2)
    print("positive:", pos)
    print("negative:", neg)

    sample3 = (
        '【总述】一个女孩走过街道。\n{"duration_s": 5, "segments": ['
        '{"t0": 0, "t1": 2.5, "desc": "走近", "camera": "推"},'
        '{"t0": 2.5, "t1": 5, "desc": "离开", "camera": "拉"}]}'
    )
    prompt, raw3, motion = output_tools.split_video(sample3)
    print("video prompt:", prompt)
    print("timeline:", output_tools.normalize_timeline(raw3, 5.0))
    print("motion:", motion)

    ok = bool(analysis and tags and raw and pos and neg and raw3)
    print("PARSERS:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def check_live() -> int:
    from dsh_bridge import BRIDGE

    print("config:", json.dumps({k: BRIDGE.cfg[k] for k in ("profile", "provider", "model", "transport", "pipe_path")}, ensure_ascii=False))

    print("\n-- text turn --")
    result = BRIDGE.ask("comfyui-selftest", "只回复三个字：连通了", [])
    print("answer:", repr(result.get("text")))
    print("usage:", result.get("usage"))

    print("\n-- image turn --")
    png = make_png()
    b64 = base64.b64encode(png).decode("ascii")
    result2 = BRIDGE.ask("comfyui-selftest", "这张图是什么颜色？只回答颜色名。", [b64])
    print("answer:", repr(result2.get("text")))
    print("usage:", result2.get("usage"))

    print("\n-- multi-turn memory --")
    result3 = BRIDGE.ask("comfyui-selftest", "我刚才问了你什么？一句话。", [])
    print("answer:", repr(result3.get("text")))

    ok = bool(result.get("text")) and bool(result2.get("text")) and bool(result3.get("text"))
    print("LIVE:", "PASS" if ok else "FAIL")
    BRIDGE.close()
    return 0 if ok else 1


def main() -> int:
    if "--parse" in sys.argv:
        return check_parsers()
    status = check_parsers()
    return check_live() or status


if __name__ == "__main__":
    raise SystemExit(main())
