"""dsh-purge control from the ComfyUI side.

The purge plugin's cleanse pass rewrites harness files on disk: prompt-layer and
code-default patches, `dsh` shim injection, and the override document. That work
is a plain file operation and does not need a live agent turn, so the panel drives
the plugin's own CLI (`bin/dsh-purge.js`) instead of asking the model to call
`purge_apply` — no tokens spent, no risk of the model paraphrasing the report.

Nothing here restarts anything: `apply` only rewrites files. The new defaults
reach a process on its next start, which is what the panel's "reconnect" button is
for when the bridge owns the process, and what a desktop restart is for when the
bridge is attached to the desktop app.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from .errors import BridgeError

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_FLAGS = {"status": "--status", "apply": "--apply", "revert": "--revert"}


def _candidates(cfg: dict[str, Any]) -> list[str]:
    home = str(cfg.get("dsh_home") or "")
    out: list[str] = []
    explicit = str(cfg.get("purge_cli") or "").strip()
    if explicit:
        out.append(explicit)
    if home:
        rel = os.path.join("profiles", "desktop", "node_modules", "dsh-purge", "bin", "dsh-purge.js")
        out.append(os.path.join(home, rel))
        rel = os.path.join("profiles", "node_modules", "dsh-purge", "bin", "dsh-purge.js")
        out.append(os.path.join(home, rel))
    return out


def resolve_cli(cfg: dict[str, Any]) -> str:
    """First existing dsh-purge CLI on this machine, or an empty string."""
    for path in _candidates(cfg):
        if os.path.isfile(path):
            return path
    return ""


def available(cfg: dict[str, Any]) -> bool:
    return bool(resolve_cli(cfg))


def _harness_base(cfg: dict[str, Any]) -> str:
    """The `@deepseek-ai` directory the bridge's harness actually loads from.

    The purge CLI runs outside the harness, so it cannot infer this from a plugin
    context and would otherwise pick up an unrelated copy (for example an npx cache
    from an earlier run). `cli_entry` is
    `<...>/@deepseek-ai/dsh-desktop-host/lib/cli.js`, so walking up three levels
    lands on the plugin root the running process really uses.
    """
    explicit = str(cfg.get("purge_base") or "").strip()
    if explicit:
        return explicit
    entry = str(cfg.get("cli_entry") or "").strip()
    if entry:
        root = os.path.dirname(os.path.dirname(os.path.dirname(entry)))
        if os.path.isdir(root):
            return root
    home = str(cfg.get("dsh_home") or "")
    if home:
        return os.path.join(home, "profiles", "node_modules", "@deepseek-ai")
    return ""


def run(op: str, cfg: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
    """Run one purge CLI command and return its report.

    Raises BridgeError for an unknown operation or a missing CLI; a non-zero exit
    from the CLI itself is reported in the result, not raised, so the panel can
    show whatever the plugin printed.
    """
    flag = _FLAGS.get(op)
    if flag is None:
        raise BridgeError("purge_op", f"unknown purge operation: {op}")
    cli = resolve_cli(cfg)
    if not cli:
        raise BridgeError(
            "purge_missing",
            "dsh-purge CLI not found (looked under $DSH_HOME/profiles/*/node_modules/dsh-purge)",
        )
    node = str(cfg.get("node_exe") or "")
    if not os.path.isfile(node):
        node = "node"
    env = dict(os.environ)
    home = str(cfg.get("dsh_home") or env.get("DSH_HOME") or "")
    if home:
        env["DSH_HOME"] = home
    base = _harness_base(cfg)
    if base and os.path.isdir(base):
        env["DSH_BASE"] = base
    try:
        completed = subprocess.run(
            [node, cli, flag],
            cwd=home or None,
            env=env,
            capture_output=True,
            timeout=float(timeout or cfg.get("purge_timeout_s", 300)),
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("purge_timeout", f"dsh-purge {flag} timed out") from exc
    except OSError as exc:
        raise BridgeError("purge_spawn", str(exc)) from exc

    stdout = (completed.stdout or b"").decode("utf-8", "replace").strip()
    stderr = (completed.stderr or b"").decode("utf-8", "replace").strip()
    if op == "status":
        # dsh-purge discovers every DSH install on the machine and headlines
        # whichever it finds first, which is not necessarily the one this bridge
        # loads. Name the live host up front so a second install's numbers (an
        # untouched portable copy, say) are not mistaken for the working tree.
        base = _harness_base(cfg)
        if base:
            stdout = (
                f"[bridge] live host / 本插件实际加载:\n  {base}\n"
                "[bridge] 「插件根」显示的是 dsh-purge 探测到的第一份安装；apply 会清洗它找到的所有宿主。\n\n"
                + stdout
            )
    return {
        "op": op,
        "ok": completed.returncode == 0,
        "code": completed.returncode,
        "cli": cli,
        "output": stdout,
        "stderr": stderr[-4000:],
    }
