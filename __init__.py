"""ComfyUI-DSH-Bridge: DeepSeek Harness inference node + chat panel."""

from __future__ import annotations

import atexit
import json
from pathlib import Path

from .dsh_bridge import config as config_module

_CONFIG = config_module.load()

# Diagnostic switch: record who raises a native dialog during start-up.
if _CONFIG.get("enable_dialog_probe", False):
    try:
        from .dsh_bridge.dialog_probe import install as _install_dialog_probe

        _install_dialog_probe()
    except Exception:  # noqa: BLE001 - diagnostics never block loading
        pass

NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}
WEB_DIRECTORY = None


def _write_frontend_flags(panel: bool, node_ui: bool) -> None:
    """Publish the front-end switches for the browser modules (`web/_flags.js`)."""
    path = Path(__file__).resolve().parent / "web" / "_flags.js"
    payload = json.dumps({"panel": bool(panel), "nodeUi": bool(node_ui)})
    try:
        path.write_text(f"export const FLAGS = {payload};\n", encoding="utf-8")
    except OSError:
        pass


if not _CONFIG.get("enabled", True):
    _write_frontend_flags(False, False)
    print("[DSH-Bridge] DISABLED by config.json (enabled=false); no nodes, no routes, no frontend")
else:
    from .dsh_bridge import BRIDGE
    from .nodes import (
        LEGACY_NODE_CLASS_MAPPINGS,
        LEGACY_NODE_DISPLAY_NAME_MAPPINGS,
        NODE_CLASS_MAPPINGS as _CLASSES,
        NODE_DISPLAY_NAME_MAPPINGS as _NAMES,
    )

    NODE_CLASS_MAPPINGS = _CLASSES
    NODE_DISPLAY_NAME_MAPPINGS = _NAMES

    _PANEL = bool(_CONFIG.get("enable_panel", True))
    _NODE_UI = bool(_CONFIG.get("enable_node_ui", True))
    _FRONTEND = bool(_CONFIG.get("enable_frontend_ui", True))
    _write_frontend_flags(_PANEL and _FRONTEND, _NODE_UI and _FRONTEND)

    # Frontend assets (panel, mode layout, dynamic image sockets) can be switched
    # off from config.json to isolate a UI problem without touching the node code.
    WEB_DIRECTORY = "./web" if _FRONTEND else None

    # The four single-purpose nodes stay available for older workflows, but only
    # when explicitly enabled, so the node menu keeps one DSH entry by default.
    if _CONFIG.get("legacy_nodes", False):
        NODE_CLASS_MAPPINGS.update(LEGACY_NODE_CLASS_MAPPINGS)
        NODE_DISPLAY_NAME_MAPPINGS.update(LEGACY_NODE_DISPLAY_NAME_MAPPINGS)

    if _PANEL:
        try:  # routes must be declared while ComfyUI builds the aiohttp app
            from .routes import api as _api

            if not _api.ensure_registered():
                import threading
                import time as _time

                def _watch_routes() -> None:
                    for _ in range(120):  # up to ~60s while ComfyUI finishes booting
                        _time.sleep(0.5)
                        try:
                            if _api.ensure_registered():
                                return
                        except Exception:  # noqa: BLE001
                            return

                threading.Thread(target=_watch_routes, name="dsh-route-watch", daemon=True).start()
        except Exception:  # noqa: BLE001 - panel is optional
            _api = None

    atexit.register(BRIDGE.close)

    if _CONFIG.get("warmup_on_start", True):
        BRIDGE.warmup()

    print(
        "[DSH-Bridge] loaded; profile=%s model=%s transport=%s frontend=%s panel=%s nodeUi=%s nodes=%s"
        % (
            _CONFIG.get("profile"),
            _CONFIG.get("model"),
            _CONFIG.get("transport"),
            "on" if WEB_DIRECTORY else "off",
            "on" if _PANEL and _FRONTEND else "off",
            "on" if _NODE_UI and _FRONTEND else "off",
            ",".join(sorted(NODE_CLASS_MAPPINGS)),
        )
    )

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
