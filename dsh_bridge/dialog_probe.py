"""Temporary diagnostic: record any native dialog raised after this plugin loads.

Installed from the package `__init__.py` (before most other custom nodes), it hooks
`user32.MessageBoxW/A` and `tkinter.messagebox.*`, then appends a traceback to
`logs/dialog-probe.log` whenever one of them is called. Turn it off with
`enable_dialog_probe: false`, delete the module to remove it entirely.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "dialog-probe.log"
_installed = False


def _write(text: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")
    except OSError:
        pass


def install() -> bool:
    """Hook the dialog APIs once; returns True when the hooks are in place."""
    global _installed
    if _installed:
        return True
    try:
        import ctypes

        user32 = ctypes.windll.user32

        original_w = user32.MessageBoxW

        def _hook_w(hwnd, text, caption, flags):  # noqa: ANN001
            try:
                _write(
                    "MessageBoxW caption=%r text=%r\n%s"
                    % (caption, text, "".join(traceback.format_stack()))
                )
            except Exception:
                pass
            return original_w(hwnd, text, caption, flags)

        user32.MessageBoxW = _hook_w

        try:
            original_a = user32.MessageBoxA

            def _hook_a(hwnd, text, caption, flags):  # noqa: ANN001
                try:
                    _write(
                        "MessageBoxA caption=%r text=%r\n%s"
                        % (caption, text, "".join(traceback.format_stack()))
                    )
                except Exception:
                    pass
                return original_a(hwnd, text, caption, flags)

            user32.MessageBoxA = _hook_a
        except Exception:
            pass

        try:
            import tkinter.messagebox as mb

            original_show = mb._show

            def _hook_show(title=None, message=None, **options):  # noqa: ANN001
                try:
                    _write(
                        "tkinter.messagebox._show title=%r message=%r options=%r\n%s"
                        % (title, message, options, "".join(traceback.format_stack()))
                    )
                except Exception:
                    pass
                return original_show(title, message, **options)

            mb._show = _hook_show

            for name in ("showwarning", "showerror", "showinfo"):
                original_py = getattr(mb, name)

                def _wrap(original_py=original_py, name=name):
                    def wrapper(*args, **kwargs):  # noqa: ANN002, ANN003
                        try:
                            _write(
                                "tkinter.messagebox.%s args=%r\n%s"
                                % (name, args, "".join(traceback.format_stack()))
                            )
                        except Exception:
                            pass
                        return original_py(*args, **kwargs)

                    return wrapper

                setattr(mb, name, _wrap())
        except Exception:
            pass

        _installed = True
        _write(
            "hook installed pid=%s argv=%r sitecustomize=%s cwd=%r"
            % (os.getpid(), sys.argv[:3], "sitecustomize" in sys.modules, os.getcwd())
        )
        try:  # window-level fallback: catches dialogs raised by other processes too
            from .window_watch import start as _start_window_watch

            _start_window_watch()
        except Exception:
            pass
        return True
    except Exception as exc:  # noqa: BLE001
        _write("hook install failed: %r" % (exc,))
        return False
