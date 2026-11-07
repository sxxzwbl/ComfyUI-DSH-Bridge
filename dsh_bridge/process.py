"""Spawn and supervise the harness `comfy` profile process."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from . import paths
from .config import _as_bool
from .errors import BridgeError

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Both spellings: os.environ on Windows normalises to upper case, but a caller may
# have set either, and dropping only one spelling leaves the proxy in effect.
_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)



class StdioStream:
    """Duplex adapter over a child's stdout/stdin pair (stdio transport)."""

    def __init__(self, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer

    def write(self, payload: bytes) -> int:
        written = self._writer.write(payload)
        try:
            self._writer.flush()
        except (OSError, ValueError):
            pass
        return written if written is not None else len(payload)

    def read(self, size: int) -> bytes:
        return self._reader.read(size)

    def fileno(self) -> int:
        return self._reader.fileno()

    def close(self) -> None:
        for handle in (self._writer, self._reader):
            try:
                handle.close()
            except (OSError, ValueError):
                pass


class HarnessProcess:
    """Owns the harness this ComfyUI instance talks to.

    Two modes:
      * spawn  (default) — start a private child process and own its lifetime;
      * attach (`attach_only`) — the pipe belongs to somebody else (the desktop
        app), so this object never starts or kills a process. `start()` becomes a
        availability check, and `attach_fallback_spawn` permits degrading to the
        spawn path when the foreign pipe is absent.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._log_handles: list[Any] = []
        self._external = bool(cfg.get("attach_only"))
        if not self._external:
            paths.ensure_dir(paths.LOG_DIR)
            paths.ensure_dir(cfg["workspace"])

    # ------------------------------------------------------------------ state
    @property
    def external(self) -> bool:
        """True when the harness process belongs to another application."""
        return self._external

    @property
    def alive(self) -> bool:
        if self._external:
            return self._pipe_listening()
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        if self._external:
            return None
        return self._proc.pid if self._proc else None

    def _pipe_listening(self) -> bool:
        """Probe the named pipe without handing it to a client channel."""
        try:
            handle = open(str(self.cfg["pipe_path"]), "r+b", buffering=0)
        except OSError:
            return False
        try:
            handle.close()
        except OSError:
            pass
        return True

    # ------------------------------------------------------------------ logs
    def _log_handle(self, name: str):
        path = paths.LOG_DIR / name
        try:
            if path.is_file() and path.stat().st_size > int(self.cfg["log_max_bytes"]):
                backup = path.with_suffix(path.suffix + ".1")
                if backup.is_file():
                    backup.unlink()
                path.replace(backup)
        except OSError:
            pass
        handle = open(path, "ab", buffering=0)
        self._log_handles.append(handle)
        return handle

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["DSH_HOME"] = self.cfg["dsh_home"]
        for key in ("DSH_PROFILE", "DSH_SESSION_ID", "DSH_WEB_URL", "DSH_SHELL"):
            env.pop(key, None)
        # A launcher (ComfyUI's own among them) can export a proxy for its own
        # downloads; inheriting it makes every model request travel through that
        # proxy. When it is a dead local port the harness fails inside fetch and
        # reports only `code: TRANSPORT`, which looks exactly like the model
        # answering with nothing. Drop the proxy variables unless one is asked for.
        proxy_url = str(self.cfg.get("proxy_url") or "").strip()
        if proxy_url:
            for key in _PROXY_KEYS:
                env[key] = proxy_url
        elif _as_bool(self.cfg.get("strip_proxy_env", True)):
            for key in _PROXY_KEYS:
                env.pop(key, None)
        # Derived from the configured harness root, never from a hardcoded drive.
        runtime = paths.harness_root_for(self.cfg)
        if runtime:
            env.setdefault("DSH_PRIMARY_RUNTIME", str(paths.Path(runtime) / "resources" / "runtime" / "primary-runtime"))
        # When the CLI lives inside app.asar the launcher is the Electron binary;
        # it only behaves like node with this set, otherwise it opens the GUI.
        if _as_bool(self.cfg.get("electron_run_as_node", False)):
            env["ELECTRON_RUN_AS_NODE"] = "1"
        # An explicit key beats whatever the desktop app stored, so a machine where
        # DSH was never signed in still works.
        api_key = str(self.cfg.get("api_key") or "").strip()
        if api_key:
            env["DEEPSEEK_API_KEY"] = api_key
        return env

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._external:
            if self._pipe_listening():
                return
            if _as_bool(self.cfg.get("attach_fallback_spawn", True)):
                # The foreign host is gone; fall back to owning a private process
                # so the node still works while the desktop app is closed. The
                # private harness listens on its own pipe, never the foreign one.
                self._external = False
                self.cfg["pipe_path"] = self.cfg.get("spawn_pipe_path") or paths.DEFAULT_PIPE_PATH
                paths.ensure_dir(paths.LOG_DIR)
                paths.ensure_dir(self.cfg["workspace"])
            else:
                raise BridgeError(
                    "attach_unavailable",
                    f"no harness listening on {self.cfg['pipe_path']} "
                    "(start the DSH desktop app, or enable attach_fallback_spawn)",
                )
        if self.alive:
            return
        entry = self.cfg["cli_entry"]
        # A packed install keeps the CLI inside app.asar, which os.path.isfile
        # cannot see into — checking it there would reject a perfectly good
        # install with missing_cli. Only an unpacked entry can be verified.
        packed = _as_bool(self.cfg.get("electron_run_as_node", False))
        if not packed:
            if not os.path.isfile(entry):
                entry = paths.DEFAULT_CLI_ENTRY_FALLBACK
            if not os.path.isfile(entry):
                raise BridgeError(
                    "missing_cli", f"harness CLI entry not found: {self.cfg['cli_entry']}"
                )
        node = self.cfg["node_exe"]
        if not os.path.isfile(node):
            raise BridgeError("missing_node", f"node executable not found: {node}")

        # Popen(cwd=...) fails outright when the working directory is absent, and
        # the workspace lives under DSH_HOME, which may be brand new.
        paths.ensure_dir(self.cfg["workspace"])
        paths.ensure_dir(paths.LOG_DIR)

        argv = [node, "--expose-internals", entry, "--profile", str(self.cfg["profile"])]
        stdout_log = self._log_handle("dsh-stdout.log")
        stderr_log = self._log_handle("dsh-stderr.log")
        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=self.cfg["workspace"],
                env=self._env(),
                stdin=subprocess.PIPE,  # stdin EOF means "shut the runtime down"
                stdout=stdout_log,
                stderr=stderr_log,
                bufsize=0,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise BridgeError("spawn_failed", str(exc)) from exc

    def stop(self, timeout: float = 10.0) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
            except OSError:
                pass
        for handle in self._log_handles:
            try:
                handle.close()
            except OSError:
                pass
        self._log_handles.clear()

    def restart(self) -> None:
        self.stop()
        self.start()

    # ------------------------------------------------------------------ transport
    def open_pipe(self, timeout: float | None = None) -> Any:
        """Open the named pipe for duplex I/O, waiting for the server to appear."""
        path = str(self.cfg["pipe_path"])
        deadline = time.monotonic() + float(timeout or self.cfg["startup_timeout_s"])
        last: Exception | None = None
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise BridgeError(
                    "process_exit", f"harness exited with code {self._proc.returncode} during startup"
                )
            try:
                return open(path, "r+b", buffering=0)
            except OSError as exc:
                last = exc
                time.sleep(0.35)
        raise BridgeError("pipe_unavailable", f"{path}: {last}")

    def open_stdio(self) -> StdioStream:
        """Return a duplex adapter over the child's stdio pipes."""
        if self._external:
            raise BridgeError(
                "attach_stdio",
                "attach mode has no child process; set transport=pipe to share a foreign harness",
            )
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise BridgeError("not_running", "harness process is not running")
        return StdioStream(self._proc.stdout, self._proc.stdin)
