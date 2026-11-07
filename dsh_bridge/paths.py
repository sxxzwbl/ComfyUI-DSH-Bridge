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

# The harness desktop app is an Electron build and ships its runtime in one of
# three shapes. Only the first two are visible to ordinary file APIs; the third
# lives inside app.asar, which `os.path` cannot look into at all — for that one
# the archive's own existence is the evidence.
_DSH_ENTRY = Path("dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js")
_PACKED_ENTRIES = (
    Path("resources/app") / _DSH_ENTRY,
    Path("resources/app.asar.unpacked") / _DSH_ENTRY,
)
_ASAR_ARCHIVE = Path("resources/app.asar")
_ASAR_ENTRY = _ASAR_ARCHIVE / _DSH_ENTRY

_NODE_RELATIVE = Path("resources/runtime/primary-runtime/dependencies/node/bin/node.exe")
_ELECTRON_RELATIVE = Path("DeepSeek Harness.exe")


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


def harness_layout(root: Path | str | None) -> dict[str, object]:
    """Classify one candidate directory.

    Returns ``{"ok": bool, "cli": str, "node": str, "packed": bool}``. ``packed``
    means the CLI sits inside app.asar, so the launcher must be the Electron
    binary in ``ELECTRON_RUN_AS_NODE`` mode rather than the bundled node.exe.
    """
    if not root:
        return {"ok": False, "cli": "", "node": "", "packed": False}
    base = Path(root)
    for relative in _PACKED_ENTRIES:
        cli = base / relative
        if cli.is_file():
            node = _first_existing(base / _NODE_RELATIVE, base / _ELECTRON_RELATIVE)
            return {"ok": True, "cli": str(cli), "node": str(node or ""), "packed": False}
    if (base / _ASAR_ARCHIVE).is_file():
        # Unverifiable from here by design, so trust the archive and the Electron
        # binary; the first request will prove it either way.
        cli = base / _ASAR_ENTRY
        electron = base / _ELECTRON_RELATIVE
        bundled = base / _NODE_RELATIVE
        if electron.is_file():
            return {"ok": True, "cli": str(cli), "node": str(electron), "packed": True}
        if bundled.is_file():
            return {"ok": True, "cli": str(cli), "node": str(bundled), "packed": True}
    return {"ok": False, "cli": "", "node": "", "packed": False}


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
        if bool(harness_layout(root)["ok"]):
            return root
    return None


def _probe_node(harness_root: Path | None) -> str:
    env = os.environ.get("DSH_BRIDGE_NODE")
    if env:
        return env
    if harness_root is not None:
        layout = harness_layout(harness_root)
        if layout["node"]:
            return str(layout["node"])
    on_path = shutil.which("node")
    if on_path:
        return on_path
    return str((harness_root or PACKAGE_DIR) / _NODE_RELATIVE)


def _probe_cli(harness_root: Path | None) -> str:
    env = os.environ.get("DSH_BRIDGE_CLI")
    if env:
        return env
    if harness_root is not None:
        layout = harness_layout(harness_root)
        if layout["cli"]:
            return str(layout["cli"])
    return str((harness_root or PACKAGE_DIR) / _PACKED_ENTRIES[0])


def _probe_dsh_home() -> str:
    env = os.environ.get("DSH_HOME")
    if env:
        return env
    return str(Path(os.path.expanduser("~")) / ".dsh")


def dsh_home_candidates() -> list[Path]:
    """Every ``.dsh`` home this process can plausibly use.

    The harness may have been initialised by a different Windows account than the
    one running ComfyUI (this happens on shared boxes), so the other profiles are
    worth looking at before falling back to an empty home of our own.
    """
    homes: list[Path] = []

    def add(path: Path) -> None:
        if path not in homes:
            homes.append(path)

    env = os.environ.get("DSH_HOME")
    if env:
        add(Path(env))
    own = Path(os.path.expanduser("~")) / ".dsh"
    add(own)

    drive = os.environ.get("SystemDrive") or "C:"
    users = Path(drive.rstrip("\\/") + "/Users")
    try:
        for entry in sorted(users.iterdir()):
            candidate = entry / ".dsh"
            if candidate.is_dir():
                add(candidate)
    except OSError:
        pass
    return homes


def pick_dsh_home() -> Path:
    """Prefer a home that already looks initialised, else our own."""
    homes = dsh_home_candidates()
    for home in homes:
        # profiles/ or credentials are the marks of a harness that has been run.
        if (home / "profiles").is_dir() or (home / "credentials.yaml").is_file() or (
            home / ".credentials.yaml"
        ).is_file():
            return home
    return homes[0] if homes else Path(os.path.expanduser("~")) / ".dsh"


def _probe_dsh_home() -> str:
    return str(pick_dsh_home())


# Resolved once at import; `scripts/install.py` writes the real values to
# config.json so a published checkout never depends on this probe succeeding.
HARNESS_ROOT = find_harness_root()
_LAYOUT = harness_layout(HARNESS_ROOT) if HARNESS_ROOT else {"cli": "", "node": "", "packed": False}
DEFAULT_NODE_EXE = _probe_node(HARNESS_ROOT)
DEFAULT_CLI_ENTRY = _probe_cli(HARNESS_ROOT)
DEFAULT_CLI_ENTRY_FALLBACK = DEFAULT_CLI_ENTRY
DEFAULT_HARNESS_ROOT = str(HARNESS_ROOT) if HARNESS_ROOT else ""
DEFAULT_ELECTRON_RUN_AS_NODE = bool(_LAYOUT.get("packed"))
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
