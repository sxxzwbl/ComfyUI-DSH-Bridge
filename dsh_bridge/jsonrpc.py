"""Newline-delimited JSON-RPC 2.0 client used to talk to the harness.

The harness side is `@deepseek-ai/dsh-sdk-protocol` driven by our `dsh-rpc-pipe`
plugin: one JSON object per line, requests carry `id` + `method`, responses carry
`id` only, notifications carry `method` only.

A Windows named pipe does not tolerate a blocking ReadFile and a WriteFile on the
same handle from two threads (the write never completes), so this client is fully
synchronous: one thread owns the stream, writes a request, then polls
`PeekNamedPipe` for inbound bytes until the response arrives. Channels are
serialized by their own lock, and every notification seen while a response is
pending is dispatched immediately, so progress events still arrive mid-turn.
"""

from __future__ import annotations

import ctypes
import json
import os
import time
from ctypes import wintypes
from typing import Any, Callable

from .errors import BridgeError

NotificationHandler = Callable[[str, dict[str, Any]], None]

if os.name == "nt":  # pragma: no branch - import guard
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PeekNamedPipe = _kernel32.PeekNamedPipe
    _PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _PeekNamedPipe.restype = wintypes.BOOL
    try:
        import msvcrt  # noqa: F401  (used inside _available)
    except ImportError:  # pragma: no cover
        msvcrt = None  # type: ignore[assignment]
else:  # pragma: no cover
    _kernel32 = None
    _PeekNamedPipe = None
    msvcrt = None  # type: ignore[assignment]

_POLL_INTERVAL = 0.005


class LineClient:
    """Synchronous request/notification client over one duplex byte stream."""

    def __init__(
        self,
        name: str,
        stream: Any,
        on_notification: NotificationHandler | None = None,
    ) -> None:
        self.name = name
        self._stream = stream
        self._on_notification = on_notification
        self._buffer = b""
        self._counter = 0
        self._pending: dict[str, dict[str, Any]] = {}
        self._closed = False
        self._failure: Exception | None = None
        try:
            self._handle = msvcrt.get_osfhandle(stream.fileno()) if msvcrt is not None else None
        except (OSError, ValueError):  # pragma: no cover - non-file transports
            self._handle = None

    # ------------------------------------------------------------------ internals
    def set_notification_handler(self, handler: NotificationHandler) -> None:
        self._on_notification = handler

    def _available(self) -> int:
        """Bytes waiting in the pipe (0 when the transport cannot be peeked)."""
        if self._handle is None or _PeekNamedPipe is None:
            return 1  # unknown: fall back to a blocking read
        count = wintypes.DWORD(0)
        ok = _PeekNamedPipe(self._handle, None, 0, None, ctypes.byref(count), None)
        if not ok:
            raise BridgeError("disconnected", f"PeekNamedPipe failed ({ctypes.get_last_error()})")
        return int(count.value)

    def _dispatch(self, raw: bytes) -> None:
        try:
            frame = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return
        if not isinstance(frame, dict):
            return
        frame_id = frame.get("id")
        method = frame.get("method")
        if frame_id is not None and isinstance(method, str):
            self._answer_server_request(frame_id, method, frame.get("params") or {})
            return
        if frame_id is not None:
            waiter = self._pending.pop(str(frame_id), None)
            if waiter is None:
                return
            error = frame.get("error")
            if isinstance(error, dict):
                waiter["error"] = BridgeError("rpc_error", f"{error.get('code')}: {error.get('message')}")
            else:
                waiter["result"] = frame.get("result")
            waiter["done"] = True
            return
        if isinstance(method, str) and self._on_notification is not None:
            try:
                self._on_notification(method, frame.get("params") or {})
            except Exception:  # noqa: BLE001 - a bad subscriber must not break the loop
                pass

    def _answer_server_request(self, frame_id: Any, method: str, params: dict[str, Any]) -> None:
        if method == "approval/request":
            self._write({"jsonrpc": "2.0", "id": frame_id, "result": {"outcome": "cancelled"}})
        elif method == "user-question/ask":
            self._write({"jsonrpc": "2.0", "id": frame_id, "result": {"cancelled": True}})
        else:
            self._write(
                {"jsonrpc": "2.0", "id": frame_id, "error": {"code": -32601, "message": f"unsupported: {method}"}}
            )

    def _write(self, frame: dict[str, Any]) -> None:
        if self._failure is not None:
            raise self._failure
        payload = (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._stream.write(payload)
        except (OSError, ValueError) as exc:
            self._failure = BridgeError("disconnected", f"write failed: {exc}")
            raise self._failure from exc

    def _pump(self) -> bool:
        """Read and dispatch whatever is available. Returns True if bytes were read."""
        available = self._available()
        if available <= 0:
            return False
        try:
            chunk = self._stream.read(min(available, 65536))
        except (OSError, ValueError) as exc:
            self._failure = BridgeError("disconnected", f"read failed: {exc}")
            raise self._failure from exc
        if not chunk:
            self._failure = BridgeError("disconnected", "peer closed the stream")
            raise self._failure
        self._buffer += chunk
        self._consume()
        return True

    def _consume(self) -> None:
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                return
            line, self._buffer = self._buffer[:newline], self._buffer[newline + 1 :]
            line = line.strip()
            if line:
                self._dispatch(line)

    # ------------------------------------------------------------------ api
    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 300.0) -> Any:
        if self._failure is not None:
            raise self._failure
        self._counter += 1
        request_id = f"{self.name}-{self._counter}"
        waiter = {"done": False, "result": None, "error": None}
        self._pending[request_id] = waiter
        frame: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            frame["params"] = params
        try:
            self._write(frame)
        except Exception:
            self._pending.pop(request_id, None)
            raise

        deadline = time.monotonic() + float(timeout)
        while not waiter["done"]:
            if self._failure is not None:
                self._pending.pop(request_id, None)
                raise self._failure
            try:
                read_something = self._pump()
            except BridgeError:
                self._pending.pop(request_id, None)
                raise
            if waiter["done"]:
                break
            if not read_something:
                if time.monotonic() >= deadline:
                    self._pending.pop(request_id, None)
                    raise BridgeError("timeout", f"{method} produced no response within {timeout:.0f}s")
                time.sleep(_POLL_INTERVAL)
        self._pending.pop(request_id, None)
        if waiter["error"] is not None:
            raise waiter["error"]
        return waiter["result"]

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        frame: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            frame["params"] = params
        self._write(frame)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stream.close()
        except (OSError, ValueError):
            pass

    def start(self) -> None:  # compatibility shim: the client needs no thread
        return
