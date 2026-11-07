"""Bridge configuration: JSON file under the ComfyUI user directory."""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "transport": "pipe",
    # `attach_only`: talk to a harness that is already listening (the desktop app,
    # or any other host mounting dsh-rpc-pipe) instead of owning a child process.
    # With `attach_fallback_spawn`, a missing pipe falls back to the spawn path
    # below, so a stopped desktop degrades to the local `comfy` profile.
    "attach_only": False,
    "attach_fallback_spawn": True,
    "pipe_path": paths.DEFAULT_PIPE_PATH,
    # Pipe the harness we spawn ourselves listens on. Only consulted when an
    # `attach_only` connection degrades to spawning; `pipe_path` above is what the
    # bridge dials in attach mode.
    "spawn_pipe_path": paths.DEFAULT_PIPE_PATH,
    # Absolute install paths are written here by `scripts/install.py`; the probe
    # in `paths.py` is only a first guess so a fresh checkout still boots.
    "harness_root": paths.DEFAULT_HARNESS_ROOT,
    "node_exe": paths.DEFAULT_NODE_EXE,
    "cli_entry": paths.DEFAULT_CLI_ENTRY,
    "dsh_home": paths.DEFAULT_DSH_HOME,
    # Set when the CLI lives inside app.asar: the launcher is then the Electron
    # binary, which only acts as node under ELECTRON_RUN_AS_NODE=1.
    "electron_run_as_node": paths.DEFAULT_ELECTRON_RUN_AS_NODE,
    # Optional. When set, the spawned harness authenticates with this key instead
    # of the desktop app's stored credentials, which is what makes the bridge work
    # for a Windows account that never signed in to DSH.
    "api_key": "",
    # The harness inherits this process's environment, and a launcher that exports
    # HTTP(S)_PROXY points every model request at that proxy. A dead local proxy
    # then fails inside fetch and the harness reports it as a generic
    # `code: TRANSPORT` — the model looks like it returned an empty reply, and
    # retries never recover. api.deepseek.com is reachable directly on the machines
    # this runs on, so the proxy variables are dropped by default. Set this to
    # False to keep the inherited values, or set `proxy_url` to force one.
    "strip_proxy_env": True,
    "proxy_url": "",
    "profile": "comfy",
    "workspace": paths.DEFAULT_WORKSPACE,
    "provider": "deepseek-official",
    "model": "deepseek-flash",
    "max_tokens": 8192,
    "warmup_on_start": True,
    "startup_timeout_s": 120,
    "request_timeout_s": 300,
    "max_image_side": 1568,
    "max_images": 12,
    "max_videos": 4,
    "max_frames": 12,
    "default_sample_frames": 6,
    # Contact-sheet geometry for the video-reading tasks. `sheet_cell_long` is the
    # long edge of one cell; 384-400 is the floor before garment texture and facial
    # structure stop being readable. `sheet_max_side` must stay at or below the
    # per-image budget (1568) or the encoder rescales the sheet a second time.
    "sheet_cell_long": 400,
    "sheet_gap": 4,
    "sheet_max_side": 1568,
    "auto_restart": True,
    "log_max_bytes": 4_194_304,
    "enable_panel": True,
    "enable_frontend_ui": True,
    "enable_node_ui": True,
    "legacy_nodes": False,
    "session_prefix": "comfyui",
    # Panel-driven dsh-purge control. Empty `purge_cli` falls back to
    # <dsh_home>/profiles/*/node_modules/dsh-purge/bin/dsh-purge.js.
    "purge_cli": "",
    "purge_timeout_s": 300,
}

_ENV_OVERRIDES = {
    "DSH_BRIDGE_ATTACH": "attach_only",
    "DSH_BRIDGE_PIPE": "pipe_path",
    "DSH_BRIDGE_PROFILE": "profile",
    "DSH_BRIDGE_MODEL": "model",
    "DSH_BRIDGE_PROVIDER": "provider",
    "DSH_BRIDGE_NODE": "node_exe",
    "DSH_BRIDGE_CLI": "cli_entry",
    "DSH_BRIDGE_TRANSPORT": "transport",
}

_CACHE: dict[str, Any] | None = None

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return bool(text)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(refresh: bool = False) -> dict[str, Any]:
    """Load defaults + config.json + environment overrides."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    cfg = copy.deepcopy(DEFAULTS)
    path = paths.config_file()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg = _merge(cfg, data)
        except (OSError, json.JSONDecodeError):
            pass
    for env_key, field in _ENV_OVERRIDES.items():
        value = os.environ.get(env_key)
        if value:
            cfg[field] = value
    for flag in (
        "attach_only",
        "attach_fallback_spawn",
        "enabled",
        "warmup_on_start",
        "auto_restart",
        "electron_run_as_node",
    ):
        if flag in cfg:
            cfg[flag] = _as_bool(cfg[flag])
    cfg["dsh_home"] = os.environ.get("DSH_HOME") or cfg.get("dsh_home") or paths.DEFAULT_DSH_HOME
    # A key in the environment wins, so a shared machine can keep it out of the
    # per-user config file.
    env_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DSH_BRIDGE_API_KEY")
    if env_key and not cfg.get("api_key"):
        cfg["api_key"] = env_key
    _CACHE = cfg
    return cfg


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Persist a partial update and refresh the cache."""
    global _CACHE
    cfg = load(refresh=True)
    merged = _merge(cfg, updates)
    path = paths.config_file()
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    _CACHE = merged
    return merged


def reset_cache() -> None:
    global _CACHE
    _CACHE = None
