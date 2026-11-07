"""Route test: boots the bridge routes on a throwaway aiohttp app and streams one chat."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent
PKG_NAME = "ComfyUI_DSH_Bridge_RouteTest"
sys.path.insert(0, str(PKG_DIR))

from aiohttp import web  # noqa: E402


def load_package():
    """Load the node package the way ComfyUI does, with a fake `server` module."""
    fake = types.ModuleType("server")
    routes = web.RouteTableDef()

    class _PromptServer:
        instance = types.SimpleNamespace(routes=routes)

    fake.PromptServer = _PromptServer
    sys.modules["server"] = fake

    spec = importlib.util.spec_from_file_location(
        PKG_NAME, PKG_DIR / "__init__.py", submodule_search_locations=[str(PKG_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PKG_NAME] = module
    spec.loader.exec_module(module)

    api = importlib.import_module(f"{PKG_NAME}.routes.api")
    api.ensure_registered()
    return module, api, routes


async def main() -> int:
    pkg, api, routes = load_package()
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001 - test only
    base = f"http://127.0.0.1:{port}"
    print(f"listening on {base}", flush=True)
    print("routes:", [f"{r.method} {r.path}" for r in routes], flush=True)

    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/dsh_bridge/status") as response:
            status_payload = await response.json()
            print("status:", json.dumps(status_payload["status"], ensure_ascii=False), flush=True)

        events: list[tuple[str, dict]] = []
        async with session.post(
            f"{base}/dsh_bridge/chat",
            json={"text": "只回复两个字：在线", "session": "routetest"},
        ) as response:
            print("chat status:", response.status, response.headers.get("Content-Type"), flush=True)
            event = "message"
            async for raw in response.content:
                line = raw.decode("utf-8").rstrip("\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    events.append((event, payload))
                    print(f"  {event}: {json.dumps(payload, ensure_ascii=False)[:160]}", flush=True)

        async with session.post(f"{base}/dsh_bridge/reset") as response:
            print("reset:", response.status, flush=True)

    await runner.cleanup()
    from dsh_bridge import BRIDGE

    BRIDGE.close()

    kinds = {name for name, _ in events}
    done = [payload for name, payload in events if name == "done"]
    ok = {"status", "done"} <= kinds and bool(done and done[0].get("text"))
    print("ROUTES:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
