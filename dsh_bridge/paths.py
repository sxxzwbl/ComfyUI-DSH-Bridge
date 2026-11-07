"""Filesystem locations used by the bridge.

Nothing here may assume a particular install path: the plugin ships to other
machines, so every location is either discovered or configured. Resolution order
is always

1. environment variable (``DSH_BRIDGE_NODE`` / ``DSH_BRIDGE_CLI`` / ``DSH_HOME``)
2. ``config.json`` under the ComfyUI user directory
3. a fast probe of the usual places (this module)
4. the deep scan in ``scripts/install.py``, which writes the answer to config.json

The probe below has to stay cheap — it runs at import time, while ComfyUI is
starting. The deep scan is a separate, one-off step.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PACKAGE_DIR / "logs"
VENDOR_DIR = PACKAGE_DIR / "vendor"

# The harness desktop app is an Electron build: this directory inside it always
# exists and is what the bridge actually imports from.
_HARNESS_MARKER = Path("resources") / "app" / "dsh" / "node_modules" / "@deepseek-ai"

_NODE_RELATIVE = Path("resources/runtime/primary-runtime/dependencies/node/bin/node.exe")
_CLI_RELATIVE = Path(
    "resources/app/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js"
)
_CLI_FALLBACK_RELATIVE = Path(
    "resources/app/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"
)


def _first_existing(*candidates: Path | str | None) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate)
        except (TypeError, ValueError):
            continue
        if path.is_file():
            return path
    return None


def _candidate_harness_roots() -> list[Path]:
    """Cheap guesses only — no disk walks here."""
    roots: list[Path] = []
    for raw in (
        os.environ.get("DSH_BRIDGE_HARNESS"),
        os.environ.get("DSH_HARNESS_ROOT"),
    ):
        if raw:
            roots.append(Path(raw))

    home = Path(os.path.expanduser("~"))
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData/Local")
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    for parent in (local / "Programs", local, program_files, home):
        for name in ("DeepSeek Harness", "DeepSeekHarness", "harness", "dsh"):
            roots.append(parent / name)

    # This machine keeps it on a data drive; the pattern also covers "portable
    # copy dropped next to a ComfyUI install".
    for anchor in (PACKAGE_DIR, *PACKAGE_DIR.parents[:3], home):
        roots.append(anchor / "ai" / "harness")
        roots.append(anchor / "harness")

    for drive in "CDEFGH":
        roots.append(Path(f"{drive}:/ai/harness"))
        roots.append(Path(f"{drive}:/harness"))
    return roots


def find_harness_root() -> Path | None:
    """Best-effort harness install directory, or None when nothing is found."""
    for root in _candidate_harness_roots():
        if (root / _HARNESS_MARKER).is_dir():
            return root
    return None


def _probe_node(harness_root: Path | None) -> str:
    env = os.environ.get("DSH_BRIDGE_NODE")
    if env:
        return env
    if harness_root is not None:
        found = _first_existing(harness_root / _NODE_RELATIVE)
        if found:
            return str(found)
    on_path = shutil.which("node")
    if on_path:
        return on_path
    return str((harness_root or PACKAGE_DIR) / _NODE_RELATIVE)


def _probe_cli(harness_root: Path | None) -> str:
    env = os.environ.get("DSH_BRIDGE_CLI")
    if env:
        return env
    if harness_root is not None:
        found = _first_existing(
            harness_root / _CLI_RELATIVE,
            harness_root / _CLI_FALLBACK_RELATIVE,
        )
        if found:
            return str(found)
    return str((harness_root or PACKAGE_DIR) / _CLI_RELATIVE)


def _probe_dsh_home() -> str:
    env = os.environ.get("DSH_HOME")
    if env:
        return env
    return str(Path(os.path.expanduser("~")) / ".dsh")


# Resolved once at import; `scripts/install.py` writes the real values to
# config.json so a published checkout never depends on this probe succeeding.
HARNESS_ROOT = find_harness_root()
DEFAULT_NODE_EXE = _probe_node(HARNESS_ROOT)
DEFAULT_CLI_ENTRY = _probe_cli(HARNESS_ROOT)
DEFAULT_CLI_ENTRY_FALLBACK = (
    str(HARNESS_ROOT / _CLI_FALLBACK_RELATIVE) if HARNESS_ROOT else DEFAULT_CLI_ENTRY
)
DEFAULT_HARNESS_ROOT = str(HARNESS_ROOT) if HARNESS_ROOT else ""
DEFAULT_DSH_HOME = _probe_dsh_home()
DEFAULT_WORKSPACE = str(Path(DEFAULT_DSH_HOME) / "comfyui-bridge-workspace")
DEFAULT_PIPE_PATH = r"\\.\pipe\dsh-comfy"


def harness_root_for(cfg: dict) -> str:
    """The harness root in effect for one config, without re-probing."""
    explicit = str(cfg.get("harness_root") or "").strip()
    if explicit:
        return explicit
    cli = str(cfg.get("cli_entry") or "")
    marker = "node_modules"
    if marker in cli:
        head = cli.split(marker)[0].rstrip("\\/")
        if head:
            return head
    return DEFAULT_HARNESS_ROOT


def ensure_dir(path: os.PathLike[str] | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def comfy_base_dir() -> Path:
    """ComfyUI root, resolved through folder_paths when available."""
    try:
        import folder_paths  # type: ignore

        base = folder_paths.base_path
        if base:
            return Path(base)
    except Exception:  # pragma: no cover - depends on ComfyUI runtime
        pass
    # PACKAGE_DIR = <ComfyUI>/custom_nodes/ComfyUI-DSH-Bridge
    return PACKAGE_DIR.parent.parent


def user_dir() -> Path:
    """ComfyUI per-user directory (`<ComfyUI>/user`)."""
    try:
        import folder_paths  # type: ignore

        getter = getattr(folder_paths, "get_user_directory", None)
        if callable(getter):
            value = getter()
            if value:
                return Path(value)
    except Exception:  # pragma: no cover
        pass
    return comfy_base_dir() / "user"


def bridge_data_dir() -> Path:
    return ensure_dir(user_dir() / "default" / "dsh_bridge")


def config_file() -> Path:
    return bridge_data_dir() / "config.json"


def sessions_file() -> Path:
    return bridge_data_dir() / "sessions.json"


def history_file() -> Path:
    return bridge_data_dir() / "history.jsonl"


def media_dir() -> Path:
    """Decoded payloads of the last run, kept so the chat panel can re-attach them."""
    return ensure_dir(bridge_data_dir() / "media")
