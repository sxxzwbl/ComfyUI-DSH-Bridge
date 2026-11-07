"""Step-by-step diagnostic with a stack dump every 15s."""

from __future__ import annotations

import faulthandler
import sys
import time
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_DIR))

faulthandler.dump_traceback_later(20, repeat=True)

from dsh_bridge import config  # noqa: E402
from dsh_bridge.process import HarnessProcess  # noqa: E402
from dsh_bridge.jsonrpc import LineClient  # noqa: E402

cfg = config.load()
print("cfg ok", cfg["pipe_path"], flush=True)

proc = HarnessProcess(cfg)
t0 = time.time()
proc.start()
print(f"spawn returned in {time.time()-t0:.2f}s pid={proc.pid}", flush=True)

t0 = time.time()
stream = proc.open_pipe(timeout=60)
print(f"pipe opened in {time.time()-t0:.2f}s", flush=True)

client = LineClient("diag", stream)
print("client ready", flush=True)

t0 = time.time()
try:
    result = client.request(
        "initialize",
        {
            "cwd": cfg["workspace"],
            "provider": cfg["provider"],
            "model": cfg["model"],
            "maxTokens": 2048,
            "approvalRequests": False,
            "capabilities": {"userQuestions": False},
        },
        timeout=30,
    )
    print(f"initialize ok in {time.time()-t0:.2f}s -> {result}", flush=True)
except Exception as exc:  # noqa: BLE001
    print(f"initialize FAILED in {time.time()-t0:.2f}s: {type(exc).__name__}: {exc}", flush=True)

t0 = time.time()
try:
    client.request(
        "session/query",
        {"sessionId": f"comfyui-diag-{int(time.time())}", "contentBlocks": [{"type": "text", "text": "只回复：OK"}]},
        timeout=60,
    )
    print(f"query accepted in {time.time()-t0:.2f}s", flush=True)
except Exception as exc:  # noqa: BLE001
    print(f"query FAILED: {type(exc).__name__}: {exc}", flush=True)

client.close()
proc.stop()
print("done", flush=True)
faulthandler.cancel_dump_traceback_later()
