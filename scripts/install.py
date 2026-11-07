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

sys.path.insert(0, str(PACKAGE_DIR))
from dsh_bridge import paths as layout  # noqa: E402  (needs the path first)

# Layout classification lives in one place: paths.harness_layout knows about the
# three shipping shapes (unpacked app/dsh, app.asar.unpacked, asar-only) and that
# os.path cannot look inside an asar archive.
HARNESS_MARKER = Path("resources/app/dsh/node_modules/@deepseek-ai")

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


def registry_installs() -> list[Path]:
    """Uninstall entries whose name smells like the harness.

    Electron apps write InstallLocation here, which is the one place a custom
    install directory leaves a trace we can read without walking the disk.
    """
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return []

    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    found: list[Path] = []
    for hive, key_path in roots:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue
        with key:
            for index in range(1024):
                try:
                    sub_name = winreg.EnumKey(key, index)
                except OSError:
                    break
                try:
                    sub = winreg.OpenKey(key, sub_name)
                except OSError:
                    continue
                with sub:
                    def read(name: str) -> str:
                        try:
                            value, _ = winreg.QueryValueEx(sub, name)
                            return str(value) if value else ""
                        except OSError:
                            return ""

                    label = (read("DisplayName") or sub_name).lower()
                    if "harness" not in label and "deepseek" not in label:
                        continue
                    location = read("InstallLocation") or read("DisplayIcon")
                    if not location:
                        continue
                    # DisplayIcon sometimes carries ",0" after the path.
                    location = location.split(",")[0].strip()
                    candidate = Path(location)
                    if candidate.is_file():
                        candidate = candidate.parent
                    if looks_like_harness(candidate) or looks_like_harness(candidate.parent):
                        found.append(candidate if looks_like_harness(candidate) else candidate.parent)
    return found


def drive_sweep() -> list[Path]:
    """One level under each fixed drive, looking for harness-ish folder names.

    Cheaper than a recursive walk and catches installs like ``D:\\Comfyui2`` that
    sit next to ComfyUI rather than in an ``ai`` folder.
    """
    hints = ("harness", "deepseek", "dsh")
    found: list[Path] = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:/")
        try:
            if not root.is_dir():
                continue
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name.lower()
            # Only the OS itself is noise; "Program Files" must stay in scope
            # because Electron apps land there by default.
            if name in {"windows", "$recycle.bin", "system volume information", "recovery"}:
                continue
            if any(hint in name for hint in hints):
                found.append(entry)
                continue
            # <drive>:\<anything>\harness is also common.
            for child_name in ("harness", "ai", "tools"):
                child = entry / child_name
                if child.is_dir():
                    found.append(child)
                    if child_name == "ai":
                        deeper = child / "harness"
                        if deeper.is_dir():
                            found.append(deeper)
    return found


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

    for anchor in (PACKAGE_DIR, *PACKAGE_DIR.parents[:5], home):
        add(anchor / "ai" / "harness")
        add(anchor / "harness")
        add(anchor.parent / "harness")

    for path in registry_installs():
        add(path)
    for path in drive_sweep():
        add(path)
    return seen


def looks_like_harness(path: Path) -> bool:
    return bool(layout.harness_layout(path)["ok"])


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
    return str(layout.harness_layout(harness)["node"] or "")


def find_cli(harness: Path) -> str:
    env = os.environ.get("DSH_BRIDGE_CLI")
    if env:
        return env
    return str(layout.harness_layout(harness)["cli"] or "")


def describe_layout(root: Path, limit: int = 14) -> str:
    """Printable listing of one directory, for when a guess is wrong."""
    try:
        if not root.exists():
            return f"    ({root} 不存在)"
        items = sorted(root.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except OSError as exc:
        return f"    (读不了 {root}：{exc})"
    lines = [f"    {item.name}{'/' if item.is_dir() else ''}" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"    …还有 {len(items) - limit} 项")
    return "\n".join(lines)


def diagnose(root: Path) -> list[str]:
    """Explain why a candidate directory does not qualify, layer by layer."""
    tips: list[str] = [f"你给的路径：{root}"]
    if not root.exists():
        tips.append("这个路径根本不存在 —— 拖拽时如果手滑拖到别的图标上会这样。")
        return tips
    tips.append("该目录下有：")
    tips.append(describe_layout(root))

    resources = root / "resources"
    if not resources.is_dir():
        tips.append("")
        tips.append("没有 resources 子目录，所以这层不是 DSH 安装根。")
        tips.append("要么往上退一层（找到含 resources 的那层），要么往下进一层。")
        return tips

    app_dir = resources / "app"
    asar = resources / "app.asar"
    if app_dir.is_dir():
        dsh = app_dir / "dsh"
        if dsh.is_dir():
            marker = dsh / "node_modules" / "@deepseek-ai"
            if marker.is_dir():
                tips.append("")
                tips.append("结构是对的，但安装器没认出来 —— 这是 bug，请把这段输出发出来。")
                return tips
            tips.append("")
            tips.append("resources\\app\\dsh 存在，但里面缺少 node_modules\\@deepseek-ai。")
            tips.append("这个目录下有：")
            tips.append(describe_layout(dsh))
        else:
            tips.append("")
            tips.append("resources\\app 存在，但没有 dsh 子目录。")
            tips.append("resources\\app 下有：")
            tips.append(describe_layout(app_dir))
    elif asar.is_file():
        tips.append("")
        tips.append("这是 asar 打包版（resources\\app.asar），没有可直接调用的解包目录。")
        tips.append("resources 下有：")
        tips.append(describe_layout(resources))
        tips.append("")
        tips.append("这种情况需要 resources\\app.asar.unpacked，或者换用 DSH 的桌面完整包。")
    else:
        tips.append("")
        tips.append("resources 下既没有 app 目录，也没有 app.asar —— 不像 Electron 应用。")
        tips.append("resources 下有：")
        tips.append(describe_layout(resources))
    return tips


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


def install_profile(
    dsh_home: Path, package_root: str, pipe_path: str, plugin_url: str, force: bool
) -> list[str]:
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
                    # YAML single-quoted scalars are literal: escaping the
                    # backslashes here would hand the plugin '\\\\.\\pipe\\...'
                    # and listen() would then create a pipe nobody can open.
                    "PIPE_PATH": pipe_path,
                    "HARNESS_ROOT": str(package_root),
                    "PLUGIN_URL": plugin_url,
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


def is_writable(path: Path) -> bool:
    """Can this account actually create files here?"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".dsh_bridge_write_probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


ATTACH_BEGIN = "# >>> ComfyUI-DSH-Bridge"
ATTACH_END = "# <<< ComfyUI-DSH-Bridge"


def attach_desktop_profile(
    dsh_home: Path, package_root: str, pipe_path: str, plugin_url: str
) -> list[str]:
    """Make the desktop profile publish its runtime on a named pipe.

    Idempotent: the managed block lives between two markers and is replaced on
    every run, so re-running the installer never stacks duplicate inserts. Rows
    outside the markers belong to the user and are left alone.
    """
    profile = dsh_home / "profiles" / "desktop"
    if not profile.is_dir():
        return [
            f"desktop profile not found at {profile} — 跳过 attach（这台机器没登录过桌面版？）"
        ]
    patch = profile / "cordis.patch.yml"
    block = render(
        VENDOR / "profile" / "desktop-attach.yml.tpl",
        {
            "PIPE_PATH": pipe_path,
            "HARNESS_ROOT": str(package_root),
            "PLUGIN_URL": plugin_url,
        },
    ).rstrip("\n")

    text = patch.read_text(encoding="utf-8") if patch.is_file() else ""
    if ATTACH_BEGIN in text and ATTACH_END in text:
        head, _, rest = text.partition(ATTACH_BEGIN)
        _, _, tail = rest.partition(ATTACH_END)
        text = head + block + tail
    else:
        text = (text.rstrip("\n") + "\n\n" + block + "\n") if text.strip() else block + "\n"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(text, encoding="utf-8")
    return [f"desktop expose -> {patch}"]


def plugin_file_url(plugin_dir: Path) -> str:
    """Absolute file URL for the pipe plugin's entry point."""
    return (plugin_dir / "index.js").resolve().as_uri()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install ComfyUI-DSH-Bridge on this machine.")
    parser.add_argument("--harness", help="DSH desktop install directory")
    parser.add_argument("--dsh-home", help="DSH home directory (default: the one that already has profiles)")
    parser.add_argument("--api-key", help="DeepSeek API key, so the harness need not be signed in")
    parser.add_argument("--pipe", default=r"\\.\pipe\dsh-comfy", help="named pipe the harness listens on")
    parser.add_argument(
        "--attach",
        nargs="?",
        const="desktop",
        default="",
        help="连桌面端已登录的 harness：把 rpc-pipe 挂进 desktop profile 并让本插件 attach 过去",
    )
    parser.add_argument(
        "--attach-pipe",
        default=r"\\.\pipe\dsh-desktop",
        help="attach 模式拨号的管道名（桌面端监听的）",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing config/profile files")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)

    say("ComfyUI-DSH-Bridge installer")
    say(f"  plugin : {PACKAGE_DIR}")
    say(f"  ComfyUI: {comfy_root()}")
    say(
        "  用法: 直接双击=自动安装 | --dry-run=只看不改 | "
        "--api-key sk-xxx=用密钥认证 | 拖 harness 文件夹到 install.bat=手动指定目录"
    )

    harness = find_harness(args.harness)
    if harness is None or not looks_like_harness(harness):
        # A path was supplied, so the useful output is a diagnosis of that path,
        # not a list of ways to supply one.
        if args.harness:
            say("")
            for line in diagnose(Path(args.harness)):
                say(line)
            say("")
            return fail("上面这个路径不合格。按提示调整后重试，或把这段输出发出来。")

        hint = (
            "没有自动找到 DSH 的安装目录。\n"
            "\n"
            "先确认一件事：这台机器装过 DSH 桌面版吗？没装的话先去下载并登录：\n"
            "    https://www.deepseek.com/harness/\n"
            "\n"
            "装过的话，要认的目录长这样（里面必须有这几层）：\n"
            "    <harness>\\resources\\app\\dsh\\node_modules\\@deepseek-ai\\\n"
            "\n"
            "找到之后，三个办法任选一个：\n"
            "  1. 把那个 harness 文件夹直接拖到 install.bat 图标上\n"
            '  2. install.bat --harness "D:\\实际路径\\harness"\n'
            "  3. 设环境变量 DSH_BRIDGE_HARNESS 指向它，再跑一次\n"
            "\n"
            "不知道装在哪：任务管理器找到 DSH 进程 → 右键「打开文件位置」，\n"
            "往上退到含 resources 文件夹的那一层，就是它。"
        )
        if args.dry_run:
            say("\n[install] 没找到 harness，暂时没有可报告的内容。")
            say(hint)
            return 0
        return fail(hint)

    node = find_node(harness)
    cli = find_cli(harness)
    info = layout.harness_layout(harness)
    packed = bool(info.get("packed"))
    dsh_home = Path(args.dsh_home) if args.dsh_home else layout.pick_dsh_home()
    if args.api_key:
        api_key = args.api_key
    else:
        api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DSH_BRIDGE_API_KEY") or ""

    say(f"  harness: {harness}")
    say(f"  layout : {'app.asar (packed)' if packed else 'unpacked directory'}")
    say(f"  node   : {node or '(missing)'}")
    say(f"  cli    : {cli or '(missing)'}")
    say(f"  home   : {dsh_home}")

    # A home belonging to another Windows account is readable but not writable,
    # and this installer has to create plugins/, skills/ and profiles/ inside it.
    if not is_writable(dsh_home):
        own_home = Path(os.path.expanduser("~")) / ".dsh"
        say(f"  [warn] {dsh_home} 当前账号写不进去（大概是别的 Windows 用户建的）")
        if is_writable(own_home):
            say(f"  [warn] 改装到自己的 home：{own_home}")
            dsh_home = own_home
        else:
            return fail(f"两个 home 都不可写，无法继续。用 --dsh-home 指定一个可写目录。")

    stored = (dsh_home / "credentials.yaml").is_file() or (dsh_home / ".credentials.yaml").is_file()
    if api_key:
        auth_line = "DEEPSEEK_API_KEY（不用桌面版登录）"
    elif stored:
        auth_line = "桌面版已登录的凭据"
    else:
        auth_line = "没有凭据 —— 请加 --api-key，否则第一次生成会失败"
    say(f"  auth   : {auth_line}")

    if not node:
        return fail("找不到可用的 node / 启动器。安装脚本会优先用 DSH 自带的运行时。")
    if not cli:
        return fail("找不到 harness CLI 入口，这个 DSH 安装看起来不完整。")
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
    attach_mode = bool(args.attach)
    if attach_mode:
        # Attaching means the desktop app owns the harness; a private spawn would
        # be a second runtime against the same home, so it is opt-in, not a
        # silent fallback that makes the node "work" while proving nothing.
        config["attach_only"] = True
        config["attach_fallback_spawn"] = False
    else:
        config["attach_only"] = False
        config["attach_fallback_spawn"] = True
    config.update(
        {
            "enabled": True,
            "harness_root": str(harness),
            "node_exe": node,
            "cli_entry": cli,
            "electron_run_as_node": packed,
            "dsh_home": str(dsh_home),
            "transport": "pipe",
            "pipe_path": args.attach_pipe if attach_mode else args.pipe,
            "spawn_pipe_path": args.pipe,
            "profile": config.get("profile") or "comfy",
            "workspace": config.get("workspace")
            or str(dsh_home / "comfyui-bridge-workspace"),
        }
    )
    if config.get("provider") == "":
        config.pop("provider")
    if config.get("model") == "":
        config.pop("model")
    if api_key:
        config["api_key"] = api_key
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"\n  config -> {config_path}")

    plugin_dir = dsh_home / "plugins" / "dsh-rpc-pipe"
    wrote = copy_tree(VENDOR / "plugins" / "dsh-rpc-pipe", plugin_dir, args.force)
    say(f"  pipe plugin -> {plugin_dir}  ({wrote} file(s) written)")
    plugin_url = plugin_file_url(plugin_dir)

    # Two more copies, both cheap (two small files each):
    #  - profiles/node_modules: what a bare-specifier `name:` resolves against
    #    when the host walks up from profiles/<name>/;
    #  - profiles/<name>/node_modules: what it resolves against when the host
    #    starts at the profile root itself.
    # The generated profile points at the file URL instead, so neither copy is
    # load-bearing — they exist so a hand-edited patch with a bare name works.
    for target in (
        dsh_home / "profiles" / "node_modules" / "dsh-rpc-pipe",
        dsh_home / "profiles" / (config.get("profile") or "comfy") / "node_modules" / "dsh-rpc-pipe",
    ):
        wrote = copy_tree(VENDOR / "plugins" / "dsh-rpc-pipe", target, args.force)
        say(f"  resolvable   -> {target}  ({wrote} file(s) written)")

    skills_dir = dsh_home / "skills"
    wrote = copy_tree(VENDOR / "skills", skills_dir, args.force)
    count = sum(1 for item in (VENDOR / "skills").iterdir() if item.is_dir())
    say(f"  skills -> {skills_dir}  ({count} skill(s), {wrote} file(s) written)")

    for note in install_profile(
        dsh_home,
        str(info.get("package_root") or harness),
        args.pipe,
        plugin_url,
        args.force,
    ):
        say(f"  {note}")

    if attach_mode:
        for note in attach_desktop_profile(
            dsh_home,
            str(info.get("package_root") or harness),
            args.attach_pipe,
            plugin_url,
        ):
            say(f"  {note}")

    inject = dsh_home / "prompt-inject.md"
    if not inject.exists() or args.force:
        shutil.copy2(VENDOR / "prompt-inject.md", inject)
        say(f"  prompt-inject -> {inject}  (template)")

    if attach_mode:
        say(
            "\nDone（attach 模式：复用桌面端运行时）. Next:\n"
            "  1. 完全退出 DSH 桌面版，再重新打开\n"
            "     （desktop profile 要重新加载才会挂上 rpc-pipe 并在管道上监听）\n"
            "  2. 重启 ComfyUI\n"
            f"  3. 节点应显示已连上桌面端 harness：{args.attach_pipe}\n"
            "\n若节点报 '失败：没有 harness 在监听'，说明桌面版没在跑、或没重启成功，\n"
            "重新打开桌面版即可；本插件不会再偷偷起一个自己的进程。"
        )
        return 0

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
