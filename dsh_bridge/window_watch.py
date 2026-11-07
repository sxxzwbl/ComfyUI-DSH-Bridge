"""Diagnostic: watch for native dialog windows from inside the ComfyUI process.

A background thread polls the top-level window list; every visible `#32770` window
with a warning-ish title is appended to `logs/dialog-window.log` together with the
owning PID and executable path. Works even when the dialog blocks the main thread,
because the blocking Win32 call releases the GIL.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "dialog-window.log"

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_INTERESTING = ("警告", "Warning", "warning", "提示", "Notice", "Alert", "加密")


def _write(text: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")
    except OSError:
        pass


def _exe_of(pid: int) -> str:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wt.DWORD(4096)
        buf = ctypes.create_unicode_buffer(4096)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def snapshot() -> list[tuple[int, str, str, bool]]:
    rows: list[tuple[int, str, str, bool]] = []

    def _cb(hwnd, _lparam):
        title = ctypes.create_unicode_buffer(512)
        cls = ctypes.create_unicode_buffer(256)
        _user32.GetWindowTextW(hwnd, title, 512)
        _user32.GetClassNameW(hwnd, cls, 256)
        pid = wt.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rows.append((pid.value, cls.value, title.value, bool(_user32.IsWindowVisible(hwnd))))
        return True

    _user32.EnumWindows(_ENUMPROC(_cb), 0)
    return rows


def _loop(interval: float = 0.4) -> None:
    seen: set[tuple[int, str]] = set()
    _write("window watch started pid=%s" % __import__("os").getpid())
    while True:
        try:
            for pid, cls, title, visible in snapshot():
                if cls != "#32770" or not visible:
                    continue
                if not any(token in title for token in _INTERESTING):
                    continue
                key = (pid, title)
                if key in seen:
                    continue
                seen.add(key)
                _write(
                    "DIALOG pid=%s title=%r exe=%s"
                    % (pid, title, _exe_of(pid))
                )
        except Exception as exc:  # noqa: BLE001
            _write("watch error: %r" % (exc,))
        time.sleep(interval)


_started = False


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="dsh-dialog-watch", daemon=True).start()
