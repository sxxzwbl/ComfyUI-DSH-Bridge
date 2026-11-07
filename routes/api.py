"""aiohttp routes exposed by the bridge (registered at import time).

ComfyUI copies its `RouteTableDef` into the aiohttp app while building it, so
every route must be declared before the server starts: this module is imported
from the node package's `__init__.py`.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from ..dsh_bridge import BRIDGE

try:  # pragma: no cover - only available inside ComfyUI
    from aiohttp import web
    from server import PromptServer
except Exception:  # pragma: no cover
    web = None  # type: ignore[assignment]
    PromptServer = None  # type: ignore[assignment]

_LOCAL_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost", None}


def _is_local(request: Any) -> bool:
    return getattr(request, "remote", None) in _LOCAL_ADDRESSES


async def _sse(send, event: str, data: dict[str, Any]) -> None:
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    await send(payload.encode("utf-8"))


_REGISTERED = False


def ensure_registered() -> bool:
    """Register the bridge routes once `PromptServer.instance` exists.

    ComfyUI copies its RouteTableDef into the aiohttp app at start-up, so routes
    must exist before the server listens; this is called during package import and
    retried by a short-lived watcher when the server object is not up yet.
    """
    global _REGISTERED
    if _REGISTERED:
        return True
    if PromptServer is None or getattr(PromptServer, "instance", None) is None:
        return False
    _register_routes(PromptServer.instance.routes)
    _REGISTERED = True
    return True


def _register_routes(routes) -> None:

    @routes.get("/dsh_bridge/status")
    async def dsh_status(request):  # noqa: ANN001
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        return web.json_response({"status": BRIDGE.status(), "config": BRIDGE.cfg})

    @routes.post("/dsh_bridge/config")
    async def dsh_config(request):  # noqa: ANN001
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            updates = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "invalid json"}, status=400)
        from ..dsh_bridge import config as config_module

        merged = config_module.save(updates if isinstance(updates, dict) else {})
        BRIDGE.reload()
        return web.json_response({"status": BRIDGE.status(), "config": merged})

    @routes.get("/dsh_bridge/last")
    async def dsh_last(request):  # noqa: ANN001
        """Latest prompt-node result, so the panel can show what the node produced."""
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        node_id = request.query.get("node_id", "")
        payload = BRIDGE.last(node_id)
        if not payload:
            return web.json_response({"found": False, "result": {}})
        return web.json_response({"found": True, "result": payload})

    @routes.get("/dsh_bridge/last/all")
    async def dsh_last_all(request):  # noqa: ANN001
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        return web.json_response({"results": BRIDGE.records()})

    @routes.post("/dsh_bridge/reset")
    async def dsh_reset(request):  # noqa: ANN001
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        await asyncio.to_thread(BRIDGE.reload)
        reconnect = await asyncio.to_thread(BRIDGE.reconnect)
        return web.json_response({"status": BRIDGE.status(), "reconnect": reconnect})

    # --- dsh-purge control -------------------------------------------------
    # The cleanse pass is a file rewrite, not agent work: drive the plugin's CLI
    # directly so no model turn is spent and the report comes back verbatim.

    @routes.get("/dsh_bridge/purge/status")
    async def dsh_purge_status(request):  # noqa: ANN001
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        from ..dsh_bridge import purge as purge_module

        if not purge_module.available(BRIDGE.cfg):
            return web.json_response({"ok": False, "error": "dsh-purge CLI not found"})
        try:
            result = await asyncio.to_thread(purge_module.run, "status", BRIDGE.cfg)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return web.json_response(result)

    @routes.post("/dsh_bridge/purge/{op}")
    async def dsh_purge_run(request):  # noqa: ANN001
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        op = request.match_info.get("op", "")
        if op not in ("apply", "revert"):
            return web.json_response({"ok": False, "error": f"unknown purge op: {op}"}, status=400)
        from ..dsh_bridge import purge as purge_module

        if not purge_module.available(BRIDGE.cfg):
            return web.json_response({"ok": False, "error": "dsh-purge CLI not found"})
        try:
            result = await asyncio.to_thread(purge_module.run, op, BRIDGE.cfg)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        # A purge run reports every patch it could not match as a non-zero exit
        # (`完成但有 N 个补丁失败`), yet the patches that did match are already on
        # disk. Restarting on that "failure" would leave a half-applied tree loaded
        # in memory, so the restart condition is "the CLI actually ran", not "exit 0".
        mode = BRIDGE.status().get("mode")
        ran = bool(result.get("output") or result.get("stderr"))
        if ran and mode == "spawn":
            await asyncio.to_thread(BRIDGE.reload)
            result["reconnect"] = await asyncio.to_thread(BRIDGE.reconnect)
            result["partial"] = not result.get("ok")
        elif mode == "attach":
            result["restart_required"] = True
        return web.json_response(result)

    @routes.post("/dsh_bridge/chat")
    async def dsh_chat(request):  # noqa: ANN001
        if not _is_local(request):
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "invalid json"}, status=400)
        text = str(data.get("text") or "").strip()
        images = list(data.get("images") or [])
        session = str(data.get("session") or "panel").strip() or "panel"
        # The discussion shares the node's session, so it shares the node's
        # pictures too — but only once. Re-sending the same frames on every turn
        # costs tokens and latency for information the model already has.
        node_id = data.get("node_id")
        reused = False
        if node_id not in (None, ""):
            fingerprint = BRIDGE.image_fingerprint(node_id)
            if BRIDGE.images_seen(session, fingerprint):
                reused = True
                text = (
                    "（素材未变：仍是你在前面已经看到的那几张图，这里不再重复附上。"
                    "如有需要请按上文图片回答。）\n\n" + text
                )
            else:
                fresh = BRIDGE.node_images(node_id)
                if fresh:
                    images.extend(fresh)
                    BRIDGE.note_images_sent(session, fingerprint)
        if not text and not images:
            return web.json_response({"error": "empty prompt"}, status=400)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        def progress(stage: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("status", {"stage": stage}))

        def worker() -> None:
            session_id = BRIDGE.session_id(session)
            try:
                result = BRIDGE.ask(session_id, text, images, channel="panel", on_progress=progress)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    (
                        "done",
                        {
                            "text": result.get("text", ""),
                            "usage": result.get("usage", {}),
                            "session": session_id,
                            "images": 0 if reused else len(images),
                            "reused": reused,
                        },
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    (
                        "error",
                        {
                            "code": getattr(exc, "code", type(exc).__name__),
                            "message": str(exc),
                        },
                    ),
                )

        await _sse(response.write, "status", {"stage": "starting"})
        threading.Thread(target=worker, name="dsh-chat", daemon=True).start()
        try:
            while True:
                event, payload = await queue.get()
                await _sse(response.write, event, payload)
                if event in ("done", "error"):
                    break
            await response.write_eof()
        except (ConnectionResetError, asyncio.CancelledError):  # client went away
            pass
        return response


ensure_registered()