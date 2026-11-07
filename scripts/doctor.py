"""Diagnose why a prompt comes back empty, and say which setting to change.

Run it from the bridge directory with any Python 3.10+:

    python scripts\\doctor.py

It answers four questions in order: is this checkout the fixed one, what proxies
does ComfyUI actually carry, can the API be reached directly and through those
proxies, and does a real prompt travel end to end. The last line is the verdict.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
API_MODELS = "https://api.deepseek.com/models"
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy")

lines: list[str] = []


def say(message: str = "") -> None:
    print(message, flush=True)
    lines.append(message)


# ----------------------------------------------------------------- connectivity
def probe(url: str, proxy: str | None = None, timeout: float = 10.0) -> tuple[str, float]:
    """Return (verdict, seconds). 'ok' means we got any HTTP answer at all."""
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))  # ignore env, go direct
    opener = urllib.request.build_opener(*handlers)
    started = time.time()
    try:
        with opener.open(url, timeout=timeout) as response:
            response.read(64)
            return "ok(%d)" % response.status, time.time() - started
    except urllib.error.HTTPError as exc:
        # 401/403 still proves the socket, DNS and TLS all worked.
        return "ok(%d)" % exc.code, time.time() - started
    except Exception as exc:  # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, str(exc)[:80]), time.time() - started


# ---------------------------------------------------------------- process env
def _read_proc_env(pid: int) -> tuple[list[str] | None, str]:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")

    class PBI(ctypes.Structure):
        _fields_ = [("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
                    ("Reserved2", ctypes.c_void_p * 2), ("UniqueProcessId", ctypes.c_void_p),
                    ("Reserved3", ctypes.c_void_p)]

    handle = k32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return None, "OpenProcess err=%d" % ctypes.get_last_error()
    try:
        pbi = PBI()
        if ntdll.NtQueryInformationProcess(handle, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None) != 0:
            return None, "NtQueryInformationProcess failed"
        read = ctypes.c_size_t()
        ptr = ctypes.c_void_p()
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(pbi.PebBaseAddress + 0x20),
                                     ctypes.byref(ptr), 8, ctypes.byref(read)):
            return None, "PEB->ProcessParameters unreadable"
        params = ptr.value
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(params + 0x80),
                                     ctypes.byref(ptr), 8, ctypes.byref(read)):
            return None, "Environment pointer unreadable"
        env_ptr = ptr.value
        size = ctypes.c_size_t()
        want = 65536
        if k32.ReadProcessMemory(handle, ctypes.c_void_p(params + 0x3F0),
                                 ctypes.byref(size), 8, ctypes.byref(read)) and 0 < size.value <= 1048576:
            want = int(size.value)
        buf = ctypes.create_string_buffer(want)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(env_ptr), buf, want, ctypes.byref(read)):
            return None, "environment block unreadable"
        text = buf.raw[: read.value].decode("utf-16-le", "replace")
        return [entry for entry in text.split("\x00") if entry], ""
    finally:
        k32.CloseHandle(handle)


def find_comfy_pid() -> int | None:
    if os.name != "nt":
        return None
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
        "| Where-Object { $_.CommandLine -match 'main\\.py' } | Select-Object -First 1 "
        "| Select-Object -ExpandProperty ProcessId"
    )
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (done.stdout or "").strip()
    return int(value) if value.isdigit() else None


def comfy_proxies() -> tuple[dict[str, str], str]:
    pid = find_comfy_pid()
    if pid is None:
        return {}, "ComfyUI 进程没找到（没在运行？）"
    env, err = _read_proc_env(pid)
    if env is None:
        return {}, "pid %d: %s" % (pid, err)
    found = {}
    for entry in env:
        key, _, value = entry.partition("=")
        if key.upper() in {k.upper() for k in PROXY_KEYS}:
            found[key] = value
    return found, "pid %d，共 %d 个环境变量" % (pid, len(env))


# -------------------------------------------------------------------- harness
def pipe_listening(name: str) -> bool:
    try:
        handle = open(name, "r+b", buffering=0)
    except OSError:
        return False
    try:
        handle.close()
    except OSError:
        pass
    return True


def harness_pids(profile: str) -> list[int]:
    if os.name != "nt":
        return []
    # The CLI runs under the Electron binary for a packed install and under the
    # bundled node.exe for an unpacked one, so match both by command line.
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='node.exe' OR Name='DeepSeek Harness.exe'\" "
        "| Where-Object { $_.CommandLine -match 'cli\\.js' -and $_.CommandLine -match '--profile "
        + profile + "' } | Select-Object -ExpandProperty ProcessId"
    )
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in (done.stdout or "").split() if x.isdigit()]


def bridge_status() -> dict | None:
    import json
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/dsh_bridge/status", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def bridge_ask(text: str = "只回两个字：收到", timeout: float = 180.0) -> dict:
    """Send one real prompt through the panel channel and report what came back."""
    import json
    body = json.dumps({"text": text, "session": "doctor-%d" % int(time.time())}).encode("utf-8")
    request = urllib.request.Request("http://127.0.0.1:8188/dsh_bridge/chat", data=body,
                                     headers={"Content-Type": "application/json"})
    result = {"text": "", "error": "", "usage": {}}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            kind = ""
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip()
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                    except Exception:  # noqa: BLE001
                        continue
                    if kind == "done" or "text" in payload:
                        result["text"] = payload.get("text", "")
                        result["usage"] = payload.get("usage") or {}
                    if kind == "error" or pk_error(payload):
                        result["error"] = payload.get("message", "")
    except Exception as exc:  # noqa: BLE001
        result["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    return result


def pk_error(payload: dict) -> bool:
    return bool(payload.get("code") or payload.get("error"))


# ----------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose empty replies from ComfyUI-DSH-Bridge.")
    parser.add_argument("--ask", action="store_true", help="also send one real prompt (needs ComfyUI running)")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds to wait for --ask")
    args = parser.parse_args(argv)

    say("ComfyUI-DSH-Bridge doctor")
    say("  插件目录: %s" % PACKAGE_DIR)

    # 1. is this the fixed checkout?
    say("")
    say("【1】代码版本")
    proc_py = PACKAGE_DIR / "dsh_bridge" / "process.py"
    fixed = False
    if proc_py.is_file():
        source = proc_py.read_text(encoding="utf-8", errors="replace")
        fixed = "_PROXY_KEYS" in source
        say("  process.py: %d bytes, 代理剔除逻辑=%s" % (len(source), "有" if fixed else "没有"))
    else:
        say("  process.py 缺失 —— 这个目录不完整")
    say("  uninstall.py: %s" % ("有" if (PACKAGE_DIR / "scripts" / "uninstall.py").is_file() else "没有"))
    say("  uninstall.bat: %s" % ("有" if (PACKAGE_DIR / "uninstall.bat").is_file() else "没有"))

    # 2. config
    say("")
    say("【2】config.json")
    comfy = PACKAGE_DIR.parent.parent
    cfg_path = comfy / "user" / "default" / "dsh_bridge" / "config.json"
    import json
    cfg = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            say("  读不出来: %s" % exc)
        important = ("attach_only", "pipe_path", "spawn_pipe_path", "strip_proxy_env", "proxy_url",
                     "provider", "model", "max_tokens", "profile", "harness_root", "cli_entry",
                     "electron_run_as_node")
        for key in important:
            if key in cfg:
                say("  %-22s = %r" % (key, cfg[key]))
        for key in ("provider", "model"):
            if key in cfg and not str(cfg.get(key) or "").strip():
                say("  [问题] %s 是空字符串，会覆盖默认值并让 harness 报 no adapter registered" % key)
    else:
        say("  不存在：%s（安装没跑？）" % cfg_path)

    # 2b. credentials — an unauthenticated harness answers nothing and says little
    say("")
    say("【2b】认证")
    dsh_home = Path(str(cfg.get("dsh_home") or (Path(os.path.expanduser("~")) / ".dsh")))
    has_ref = False
    found_creds = False
    for name in (".credentials.yaml", "credentials.yaml"):
        candidate = dsh_home / name
        if candidate.is_file():
            found_creds = True
            try:
                body = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                body = ""
            has_ref = "DEEPSEEK_API_KEY" in body
            say("  %s: 存在（%d 字节）%s" % (candidate, len(body),
                                           "，含 DEEPSEEK_API_KEY" if has_ref else "，不含 DEEPSEEK_API_KEY"))
        else:
            say("  %s: 不存在" % candidate)
    key_in_cfg = str(cfg.get("api_key") or "").strip()
    say("  config.api_key: %s" % ("有" if key_in_cfg else "空"))
    if not key_in_cfg and not has_ref:
        say("  [问题] 既没有 api_key，也没有 DEEPSEEK_API_KEY 凭据 —— 每次生成都会 401，")
        say("         节点只会显示空回复。二选一：在 DSH 桌面版里登录，或安装时加 --api-key sk-xxx。")
    elif not found_creds:
        say("  只有 config.api_key 可用，靠它认证。")

    # 3. proxies as ComfyUI actually carries them
    say("")
    say("【3】ComfyUI 进程环境里的代理")
    proxies, note = comfy_proxies()
    say("  " + note)
    if proxies:
        for key, value in sorted(proxies.items()):
            say("  %-12s = %s" % (key, value))
    else:
        say("  没有代理变量")

    # 4. reachability, both ways
    say("")
    say("【4】api.deepseek.com 可达性")
    verdict_direct, secs = probe(API_MODELS)
    say("  直连          : %-40s %.2fs" % (verdict_direct, secs))
    working_proxy = ""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = proxies.get(key, "")
        if not value:
            continue
        verdict_proxy, secs2 = probe(API_MODELS, proxy=value)
        say("  经 %-9s: %-40s %.2fs" % (key, verdict_proxy, secs2))
        if verdict_proxy.startswith("ok") and not working_proxy:
            working_proxy = value

    # 5. harness + pipe
    say("")
    say("【5】harness 与管道")
    profile = str(cfg.get("profile") or "comfy")
    pipe = str(cfg.get("spawn_pipe_path") or r"\\.\pipe\dsh-comfy")
    pids = harness_pids(profile)
    say("  %s 进程: %s" % (profile, ("pid " + ", ".join(map(str, pids))) if pids else "没有"))
    say("  %s 管道: %s" % (pipe, "在" if pipe_listening(pipe) else "不在"))
    if pids:
        env, err = _read_proc_env(pids[0])
        if env is None:
            say("  harness 环境: 读不到（%s）" % err)
        else:
            leftovers = [e for e in env if e.partition("=")[0].upper() in {k.upper() for k in PROXY_KEYS}]
            say("  harness 环境里的代理: %s" % ("；".join(leftovers) if leftovers else "无"))

    # 6. status + one real prompt
    status = bridge_status()
    if status:
        inner = status.get("status") or status
        say("")
        say("【6】桥接状态")
        for key in ("mode", "alive", "pid", "ready", "last_error"):
            if key in inner:
                say("  %-12s = %r" % (key, inner[key]))
    else:
        say("")
        say("【6】桥接状态: 拿不到（ComfyUI 没在 8188 跑，或插件没加载）")

    ask_result = None
    if args.ask:
        say("")
        say("【7】实测一条消息")
        ask_result = bridge_ask(timeout=args.timeout)
        say("  回复: <<<%s>>>" % ask_result["text"])
        say("  错误: %s" % (ask_result["error"] or "无"))
        say("  usage: %s" % (ask_result["usage"] or "无"))

    # 8. verdict
    say("")
    say("=" * 60)
    direct_ok = verdict_direct.startswith("ok")
    strip = bool(cfg.get("strip_proxy_env", True))
    proxy_url = str(cfg.get("proxy_url") or "").strip()
    empty = ask_result is not None and not ask_result["text"].strip()

    if not fixed:
        say("结论：这个目录还是旧代码，装新版（或确认 custom_nodes 指向的是新目录）。")
    elif proxy_url:
        say("结论：强制走代理 %s。若回复仍空，说明这个代理也不通 api.deepseek.com。" % proxy_url)
    elif direct_ok and strip:
        say("结论：直连可达，且已剔除继承的代理 —— 配置正确。")
        if empty:
            say("      但实测仍空，看【7】的错误；TRANSPORT 之外的错误按错误码处理。")
    elif direct_ok and not strip:
        say("结论：直连可达，但当前保留了继承的代理。改成：")
        say('      "strip_proxy_env": true, "proxy_url": ""')
    elif working_proxy:
        say("结论：直连不通，但经 %s 可达。改成：" % working_proxy)
        say('      "strip_proxy_env": false, "proxy_url": "%s"' % working_proxy)
    else:
        say("结论：直连和继承的代理都不通 api.deepseek.com。先解决网络，")
        say("      或把可用的代理地址写进 proxy_url。")

    out = PACKAGE_DIR / "logs" / "doctor.txt"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
        say("")
        say("（以上内容也写进了 %s）" % out)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())
