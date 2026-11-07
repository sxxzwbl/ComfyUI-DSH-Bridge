"""One-shot installer for ComfyUI-DSH-Bridge.

Does everything that has to happen once per machine, so the plugin itself can stay
free of hardcoded paths:

  1. locate the DSH desktop install (node binary, CLI entry, harness root)
  2. write ``<ComfyUI>/user/default/dsh_bridge/config.json`` with absolute paths
  3. install the ``dsh-rpc-pipe`` plugin into ``<DSH_HOME>/plugins``
  4. install the prompt skills into ``<DSH_HOME>/skills``
  5. generate the ``comfy`` harness profile from the templates in ``vendor/``
  6. seed ``prompt-inject.md`` if the operator has not written one

Run it with ComfyUI stopped:

    python scripts/install.py                 # discover, then install
    python scripts/install.py --dry-run       # show what it found, change nothing
    python scripts/install.py --harness "C:\\tools\\harness" --dsh-home "C:\\Users\\me\\.dsh"

Everything it writes is idempotent: existing files are kept unless ``--force`` is
given, so re-running after an upgrade only fills in what is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
VENDOR = PACKAGE_DIR / "vendor"

HARNESS_MARKER = Path("resources/app/dsh/node_modules/@deepseek-ai")
NODE_RELATIVE = Path("resources/runtime/primary-runtime/dependencies/node/bin/node.exe")
CLI_RELATIVE = Path("resources/app/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js")
CLI_FALLBACK = Path("resources/app/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js")

SKIP_SKILLS = {"__pycache__", ".git"}


def say(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> int:
    say(f"\n[install] {message}")
    return 1


# --------------------------------------------------------------------- discovery
def comfy_root() -> Path:
    """<ComfyUI> — this file lives in <ComfyUI>/custom_nodes/ComfyUI-DSH-Bridge/scripts."""
    return PACKAGE_DIR.parent.parent


def candidate_roots() -> list[Path]:
    seen: list[Path] = []

    def add(path: Path | str | None) -> None:
        if not path:
            return
        candidate = Path(path)
        if candidate not in seen:
            seen.append(candidate)

    for env in ("DSH_BRIDGE_HARNESS", "DSH_HARNESS_ROOT"):
        add(os.environ.get(env))

    home = Path(os.path.expanduser("~"))
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData/Local")
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    for parent in (local / "Programs", local, program_files, home):
        for name in ("DeepSeek Harness", "DeepSeekHarness", "harness", "dsh"):
            add(parent / name)

    for anchor in (PACKAGE_DIR, *PACKAGE_DIR.parents[:4], home):
        add(anchor / "ai" / "harness")
        add(anchor / "harness")

    for drive in "CDEFGHIJ":
        add(Path(f"{drive}:/ai/harness"))
        add(Path(f"{drive}:/harness"))
        add(Path(f"{drive}:/tools/harness"))
    return seen


def looks_like_harness(path: Path) -> bool:
    return (path / HARNESS_MARKER).is_dir()


def deep_scan(anchors: list[Path], depth: int = 3) -> Path | None:
    """Shallow walk under each anchor looking for the harness marker."""
    for anchor in anchors:
        if not anchor.is_dir():
            continue
        if looks_like_harness(anchor):
            return anchor
        try:
            for dirpath, dirnames, _ in os.walk(anchor):
                current = Path(dirpath)
                try:
                    level = len(current.relative_to(anchor).parts)
                except ValueError:
                    level = 99
                if level >= depth:
                    dirnames[:] = []
                    continue
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                if looks_like_harness(current):
                    return current
        except OSError:
            continue
    return None


def find_harness(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    for root in candidate_roots():
        if looks_like_harness(root):
            return root
    return deep_scan(candidate_roots())


def find_node(harness: Path) -> str:
    env = os.environ.get("DSH_BRIDGE_NODE")
    if env and Path(env).is_file():
        return env
    bundled = harness / NODE_RELATIVE
    if bundled.is_file():
        return str(bundled)
    on_path = shutil.which("node")
    return on_path or ""


def find_cli(harness: Path) -> str:
    env = os.environ.get("DSH_BRIDGE_CLI")
    if env and Path(env).is_file():
        return env
    for relative in (CLI_RELATIVE, CLI_FALLBACK):
        candidate = harness / relative
        if candidate.is_file():
            return str(candidate)
    return ""


# --------------------------------------------------------------------- installers
def copy_tree(src: Path, dst: Path, force: bool) -> int:
    """Copy missing files (or everything with force). Returns files written."""
    written = 0
    for item in src.rglob("*"):
        if item.is_dir() or item.name in SKIP_SKILLS:
            continue
        target = dst / item.relative_to(src)
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        written += 1
    return written


def render(template: Path, replacements: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def install_profile(dsh_home: Path, harness: Path, pipe_path: str, force: bool) -> list[str]:
    notes: list[str] = []
    profile = dsh_home / "profiles" / "comfy"
    profile.mkdir(parents=True, exist_ok=True)

    patch_src = VENDOR / "profile" / "cordis.patch.yml.tpl"
    patch_dst = profile / "cordis.patch.yml"
    if not patch_dst.exists() or force:
        patch_dst.write_text(
            render(
                patch_src,
                {
                    "PIPE_PATH": pipe_path.replace("\\", "\\\\"),
                    "HARNESS_ROOT": str(harness).replace("\\", "\\\\"),
                },
            ),
            encoding="utf-8",
        )
        notes.append(f"profile patch -> {patch_dst}")
    else:
        notes.append(f"profile patch kept (exists, use --force to rewrite): {patch_dst}")

    pkg_src = VENDOR / "profile" / "package.json.tpl"
    pkg_dst = profile / "package.json"
    if not pkg_dst.exists() or force:
        pkg_dst.write_text(pkg_src.read_text(encoding="utf-8"), encoding="utf-8")
        notes.append(f"profile manifest -> {pkg_dst}")
    else:
        notes.append(f"profile manifest kept: {pkg_dst}")

    root_yml = profile / "cordis.yml"
    if not root_yml.exists():
        root_yml.write_text(
            "# Generated by ComfyUI-DSH-Bridge. Edit cordis.patch.yml, not this file.\n[]\n",
            encoding="utf-8",
        )
        notes.append(f"profile root -> {root_yml}")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install ComfyUI-DSH-Bridge on this machine.")
    parser.add_argument("--harness", help="DSH desktop install directory")
    parser.add_argument("--dsh-home", help="DSH home directory (default: %%DSH_HOME%% or ~/.dsh)")
    parser.add_argument("--pipe", default=r"\\.\pipe\dsh-comfy", help="named pipe the harness listens on")
    parser.add_argument("--force", action="store_true", help="overwrite existing config/profile files")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)

    say("ComfyUI-DSH-Bridge installer")
    say(f"  plugin : {PACKAGE_DIR}")
    say(f"  ComfyUI: {comfy_root()}")

    harness = find_harness(args.harness)
    if harness is None or not looks_like_harness(harness):
        hint = (
            "Find the folder that contains resources\\app\\dsh\\node_modules\\@deepseek-ai\n"
            "  (the DSH desktop install), then re-run with:\n"
            '    python scripts/install.py --harness "D:\\path\\to\\harness"'
        )
        if args.dry_run:
            say("\n[install] harness not found — nothing to report yet.")
            say(hint)
            return 0
        return fail("DSH harness install not found.\n\n" + hint)

    node = find_node(harness)
    cli = find_cli(harness)
    dsh_home = Path(
        args.dsh_home or os.environ.get("DSH_HOME") or (Path(os.path.expanduser("~")) / ".dsh")
    )

    say(f"  harness: {harness}")
    say(f"  node   : {node or '(missing)'}")
    say(f"  cli    : {cli or '(missing)'}")
    say(f"  home   : {dsh_home}")

    if not node:
        return fail("node executable not found. Install Node.js or pass --harness to the DSH install.")
    if not cli:
        return fail("harness CLI entry not found. The DSH install looks incomplete.")
    if not (VENDOR / "skills").is_dir():
        return fail(f"vendored skills missing at {VENDOR / 'skills'} — this checkout is incomplete.")

    if args.dry_run:
        say("\n[install] dry run: nothing written.")
        return 0

    data_dir = comfy_root() / "user" / "default" / "dsh_bridge"
    data_dir.mkdir(parents=True, exist_ok=True)
    config_path = data_dir / "config.json"

    config = {}
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}
    config.update(
        {
            "enabled": True,
            "harness_root": str(harness),
            "node_exe": node,
            "cli_entry": cli,
            "dsh_home": str(dsh_home),
            "pipe_path": args.pipe,
            "spawn_pipe_path": args.pipe,
            "profile": config.get("profile") or "comfy",
            "workspace": config.get("workspace")
            or str(dsh_home / "comfyui-bridge-workspace"),
        }
    )
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"\n  config -> {config_path}")

    plugin_dir = dsh_home / "plugins" / "dsh-rpc-pipe"
    wrote = copy_tree(VENDOR / "plugins" / "dsh-rpc-pipe", plugin_dir, args.force)
    say(f"  pipe plugin -> {plugin_dir}  ({wrote} file(s) written)")

    skills_dir = dsh_home / "skills"
    wrote = copy_tree(VENDOR / "skills", skills_dir, args.force)
    count = sum(1 for item in (VENDOR / "skills").iterdir() if item.is_dir())
    say(f"  skills -> {skills_dir}  ({count} skill(s), {wrote} file(s) written)")

    for note in install_profile(dsh_home, harness, args.pipe, args.force):
        say(f"  {note}")

    inject = dsh_home / "prompt-inject.md"
    if not inject.exists() or args.force:
        shutil.copy2(VENDOR / "prompt-inject.md", inject)
        say(f"  prompt-inject -> {inject}  (template)")

    say(
        "\nDone. Next:\n"
        "  1. make sure the harness is signed in (DEEPSEEK_API_KEY or the desktop app)\n"
        "  2. start ComfyUI and look for: [DSH-Bridge] loaded; ... nodes=DSH_ContactSheet,DSH_PromptNode\n"
        "  3. open a workflow, add 'DSH 提示词引擎', and press 生成\n"
        "\nIf the node reports '失败：找不到 harness 程序', re-run this script — it writes the\n"
        "absolute paths that the plugin refuses to guess at runtime."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - older interpreters
        pass
    raise SystemExit(main())
