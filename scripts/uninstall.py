"""Remove everything the bridge installed, so an upgrade starts from a clean state.

Upgrading by dropping a new checkout into ``custom_nodes`` is not enough: the old
install left a harness profile, plugin copies, skills and a config file behind, and
those are what actually get loaded. This script removes exactly those, and nothing
that belongs to the user (credentials, sessions, their own skills).

Dry run by default — pass ``--yes`` to delete.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
VENDOR = PACKAGE_DIR / "vendor"

# Markers written by scripts/install.py --attach into the desktop profile.
ATTACH_BEGIN = "# >>> ComfyUI-DSH-Bridge"
ATTACH_END = "# <<< ComfyUI-DSH-Bridge"
# Only a prompt-inject.md that we wrote is removed; anything else is the user's.
PROMPT_MARK = "Injected into the system prompt of every run"


def say(message: str = "") -> None:
    print(message, flush=True)


def comfy_root() -> Path:
    """<ComfyUI>, from this file's location: custom_nodes/<plugin>/scripts/x.py."""
    return PACKAGE_DIR.parent.parent


def fail(message: str) -> int:
    say("")
    say("[uninstall] " + message)
    return 1


def find_dsh_home(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DSH_HOME")
    if env:
        return Path(env)
    own = Path(os.path.expanduser("~")) / ".dsh"
    candidates = []
    drive = os.environ.get("SystemDrive") or "C:"
    users = Path(drive.rstrip("\\/") + "/Users")
    try:
        for entry in sorted(users.iterdir()):
            candidate = entry / ".dsh"
            if candidate.is_dir():
                candidates.append(candidate)
    except OSError:
        pass
    if own.is_dir():
        candidates.insert(0, own)
    for home in candidates:
        if (home / "profiles").is_dir():
            return home
    return candidates[0] if candidates else own


def harness_cli_pids(profile: str) -> list[int]:
    """PIDs of bare harness CLI processes for one profile (never the desktop app)."""
    if os.name != "nt":
        return []
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='DeepSeek Harness.exe'\" "
        "| Where-Object { $_.CommandLine -match 'cli\\.js' -and $_.CommandLine -match '--profile "
        + profile
        + "' } | Select-Object -ExpandProperty ProcessId"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def kill(pid: int) -> bool:
    try:
        done = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def remove(path: Path, apply: bool) -> str:
    """Delete one path (file or tree). Returns a short verb for the report."""
    if not path.exists():
        return "absent"
    if not apply:
        return "would delete"
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return "deleted"
    except OSError as exc:
        return "FAILED (%s)" % exc


def backup_tree(path: Path, apply: bool) -> str:
    """Move a tree aside instead of deleting it.

    The harness profile is generated, but a user may have edited the persona or
    added tool rows in it. Renaming costs nothing and makes the reset reversible.
    """
    if not path.exists():
        return "absent"
    target = path.with_name("%s.bak-%s" % (path.name, time.strftime("%Y%m%d-%H%M%S")))
    if not apply:
        return "would keep as " + target.name
    try:
        path.rename(target)
        return "kept as " + target.name
    except OSError as exc:
        return "FAILED (%s)" % exc


def strip_attach_block(patch: Path, apply: bool) -> str:
    """Remove only the marked attach block, leaving the user's own rows alone."""
    if not patch.is_file():
        return "absent"
    try:
        text = patch.read_text(encoding="utf-8")
    except OSError as exc:
        return "unreadable (%s)" % exc
    if ATTACH_BEGIN not in text:
        return "no attach block"
    head, _, rest = text.partition(ATTACH_BEGIN)
    _, _, tail = rest.partition(ATTACH_END)
    cleaned = (head.rstrip("\n") + "\n" + tail.lstrip("\n")).rstrip("\n") + "\n"
    if not apply:
        return "would strip attach block"
    try:
        patch.write_text(cleaned, encoding="utf-8")
        return "attach block removed"
    except OSError as exc:
        return "FAILED (%s)" % exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove ComfyUI-DSH-Bridge from this machine.")
    parser.add_argument("--dsh-home", help="DSH home directory (default: the initialised one)")
    parser.add_argument("--profile", default="comfy", help="harness profile the bridge created")
    parser.add_argument("--comfy", help="ComfyUI directory (default: derived from this file)")
    parser.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    parser.add_argument("--purge-media", action="store_true", help="also delete cached payload images")
    parser.add_argument("--uninstall", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    apply = bool(args.yes)
    comfy = Path(args.comfy).expanduser() if args.comfy else comfy_root()
    dsh_home = find_dsh_home(args.dsh_home)
    profile = args.profile
    data_dir = comfy / "user" / "default" / "dsh_bridge"

    say("ComfyUI-DSH-Bridge uninstaller" + ("" if apply else "  (dry run — nothing is written)"))
    say("  ComfyUI : %s" % comfy)
    say("  DSH home: %s" % dsh_home)
    say("  profile : %s" % profile)

    if not comfy.is_dir():
        return fail("ComfyUI 目录不存在：%s。用 --comfy 指定。" % comfy)
    if not dsh_home.is_dir():
        return fail("DSH home 不存在：%s。用 --dsh-home 指定。" % dsh_home)

    # 1. a leftover harness would keep holding the pipe and serve the old profile
    pids = harness_cli_pids(profile)
    if pids:
        say("")
        say("遗留的 harness 进程（会继续占着管道）：")
        for pid in pids:
            if apply:
                say("  pid %-6d %s" % (pid, "已结束" if kill(pid) else "结束失败，请手动关掉"))
            else:
                say("  pid %-6d would kill" % pid)
    else:
        say("")
        say("没有遗留的 harness 进程。")

    # 2. what the installer wrote
    say("")
    say("要清理的东西：")
    # (label, path, keep-aside-instead-of-delete)
    targets: list[tuple[str, Path, bool]] = [
        ("harness profile", dsh_home / "profiles" / profile, True),
        ("插件副本 plugins/", dsh_home / "plugins" / "dsh-rpc-pipe", False),
        ("插件副本 profiles/node_modules/", dsh_home / "profiles" / "node_modules" / "dsh-rpc-pipe", False),
        ("桥接配置 config.json", data_dir / "config.json", False),
    ]
    if args.purge_media:
        targets.append(("图片缓存 media/", data_dir / "media", False))

    uninstallable_skills = []
    skills_src = VENDOR / "skills"
    if skills_src.is_dir():
        for skill in sorted(skills_src.iterdir()):
            if skill.is_dir():
                uninstallable_skills.append(skill.name)
    for name in uninstallable_skills:
        targets.append(("skill " + name, dsh_home / "skills" / name, False))

    for label, path, keep_aside in targets:
        verb = backup_tree(path, apply) if keep_aside else remove(path, apply)
        say("  %-38s %s  [%s]" % (label, path, verb))

    # 3. the desktop profile's attach block, and our prompt-inject only
    say("")
    say("profile 与注入文件：")
    desktop_patch = dsh_home / "profiles" / "desktop" / "cordis.patch.yml"
    say("  %-38s %s  [%s]" % ("desktop attach 块", desktop_patch, strip_attach_block(desktop_patch, apply)))

    prompt = dsh_home / "prompt-inject.md"
    if prompt.is_file():
        try:
            text = prompt.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if PROMPT_MARK in text:
            say("  %-38s %s  [%s]" % ("prompt-inject.md（本插件写的）", prompt, remove(prompt, apply)))
        else:
            say("  %-38s %s  [保留：内容不是本插件写的]" % ("prompt-inject.md", prompt))
    else:
        say("  %-38s %s  [absent]" % ("prompt-inject.md", prompt))

    # 4. what is deliberately left alone
    say("")
    say("不动的东西（属于你，不属于本插件）：")
    say("  %s" % (dsh_home / ".credentials.yaml"))
    say("  %s" % (dsh_home / "sessions"))
    say("  %s" % (data_dir / "history.jsonl"))
    say("  你自己的 skill（%s 里非本插件安装的那些）" % (dsh_home / "skills"))

    say("")
    if apply:
        say("清理完成。下一步：把新版放到 custom_nodes（同名覆盖），运行 install.bat。")
    else:
        say("这是预演，什么都没删。确认无误后加 --yes 再跑一次：")
        say("  python \"%s\" --yes" % Path(__file__).resolve())
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - older interpreters
        pass
    raise SystemExit(main())
