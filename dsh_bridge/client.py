"""One initialized harness channel: handshake, prompt, completion, text extraction."""

from __future__ import annotations

import threading
from typing import Any, Callable

from .errors import BridgeError
from .jsonrpc import LineClient
from .process import HarnessProcess

EventCallback = Callable[[str, dict[str, Any]], None]


def _deep_texts(node: Any, out: list[str], allow: bool = False) -> None:
    """Collect `text` values from content-shaped nodes only (never from reasoning)."""
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "reasoning":
            return
        if node_type == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
            return
        if allow and isinstance(node.get("text"), str) and "role" not in node:
            out.append(node["text"])
        for value in node.values():
            _deep_texts(value, out, allow)
    elif isinstance(node, list):
        for value in node:
            _deep_texts(value, out, allow)


def assistant_text(event: dict[str, Any]) -> str:
    """Extract the assistant answer text from one `assistant/message` event."""
    data = event.get("data") or {}
    message = data.get("message") or {}
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
    if not parts:
        _deep_texts(content, parts)
    return "".join(parts).strip()


def assistant_usage(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data") or {}
    usage = data.get("usage")
    return usage if isinstance(usage, dict) else {}


def last_assistant_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "assistant/message":
            text = assistant_text(event)
            if text:
                return text
    return ""


def last_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        usage = assistant_usage(event)
        if usage:
            return usage
    return {}


class Channel:
    """One client connection to the harness (own socket, own lock, own sessions)."""

    def __init__(
        self,
        name: str,
        cfg: dict[str, Any],
        proc: HarnessProcess,
        on_event: EventCallback | None = None,
    ) -> None:
        self.name = name
        self.cfg = cfg
        self.proc = proc
        self.on_event = on_event
        self._lock = threading.RLock()
        self._client: LineClient | None = None
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._status: dict[str, str] = {}
        self._handle: Any = None
        self._initialized = False
        self._known_sessions: set[str] = set()

    # ------------------------------------------------------------------ setup
    def connect(self) -> None:
        with self._lock:
            if self._client is not None and self._initialized:
                return
            self.proc.start()
            if str(self.cfg["transport"]) == "stdio":
                stream = self.proc.open_stdio()
            else:
                stream = self.proc.open_pipe()
            client = LineClient(self.name, stream, on_notification=self._on_notification)
            client.start()
            self._handle = stream
            self._client = client
            self._initialized = False
            try:
                self._initialize()
            except Exception:
                self._teardown()
                raise

    def _initialize(self) -> None:
        assert self._client is not None
        result = self._client.request(
            "initialize",
            {
                "cwd": self.cfg["workspace"],
                "provider": self.cfg["provider"],
                "model": self.cfg["model"],
                "maxTokens": int(self.cfg["max_tokens"]),
                "approvalRequests": False,
                "capabilities": {"userQuestions": False},
            },
            timeout=float(self.cfg["startup_timeout_s"]),
        )
        info = (result or {}).get("serverInfo") or {}
        if info.get("name") != "deepseek-harness-sdk-runtime":
            raise BridgeError("bad_handshake", f"unexpected serverInfo: {info}")
        self._initialized = True

    def _teardown(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
        self._client = None
        self._handle = None
        self._initialized = False
        self._known_sessions.clear()

    # ------------------------------------------------------------------ sessions
    def _ensure_session(self, session_id: str) -> None:
        """Resume a persisted session so a new process can keep using its id.

        `agents.create` rejects an id that already exists on disk, so a reused
        sessionId must be resumed first. A missing session simply falls through to
        creation on the first prompt.
        """
        if session_id in self._known_sessions or self._client is None:
            return
        try:
            self._client.request("session/resume", {"sessionId": session_id}, timeout=120.0)
        except BridgeError:
            pass
        self._known_sessions.add(session_id)

    # ------------------------------------------------------------------ events
    def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        session_id = str(params.get("sessionId") or "")
        if method == "session.event":
            event = params.get("event") or {}
            if session_id and isinstance(event, dict):
                bucket = self._events.setdefault(session_id, [])
                bucket.append(event)
                if len(bucket) > 400:
                    del bucket[:200]
                if self.on_event is not None:
                    self.on_event(method, params)
        elif method == "session.status":
            status = str(params.get("status") or "")
            if session_id:
                self._status[session_id] = status
                if self.on_event is not None:
                    self.on_event(method, params)
        elif method in ("session.query.completed", "subagent.started", "subagent.finished"):
            if self.on_event is not None:
                self.on_event(method, params)

    # ------------------------------------------------------------------ prompt
    def ask(
        self,
        session_id: str,
        blocks: list[dict[str, Any]],
        timeout: float | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Queue one prompt and wait for the turn to settle."""
        if not blocks:
            raise BridgeError("empty_prompt", "content blocks are empty")
        with self._lock:
            self.connect()
            self._events[session_id] = []
            self._ensure_session(session_id)
            if on_progress is not None:
                on_progress("queued")
            payload = {"sessionId": session_id, "contentBlocks": blocks}
            try:
                receipt = self._client.request(  # type: ignore[union-attr]
                    "session/query", payload, timeout=120.0
                )
            except BridgeError as exc:
                if "already exists" not in str(exc):
                    raise
                self._known_sessions.discard(session_id)
                self._ensure_session(session_id)
                receipt = self._client.request(  # type: ignore[union-attr]
                    "session/query", payload, timeout=120.0
                )
            kind = (receipt or {}).get("kind")
            if kind == "command":
                if on_progress is not None:
                    on_progress("command")
                return {"kind": "command", "text": "", "usage": {}, "receipt": receipt}
            if on_progress is not None:
                on_progress("running")
            self._client.request(  # type: ignore[union-attr]
                "session/wait",
                {"sessionId": session_id},
                timeout=float(timeout or self.cfg["request_timeout_s"]),
            )
            events = list(self._events.get(session_id, []))
            text = last_assistant_text(events)
            usage = last_usage(events)
            if on_progress is not None:
                on_progress("idle")
            return {"kind": "prompt", "text": text, "usage": usage, "receipt": receipt, "events": events}

    def close(self, graceful: bool = True) -> None:
        """Tear the channel down, optionally asking the server to release its agent.

        A bare socket close makes the pipe plugin dispose its per-connection server
        asynchronously, and the Agent it owns lingers for a moment; a new connection
        that immediately reuses the same sessionId then collides with it
        (`session "..." already exists`). Sending `shutdown` first lets that
        teardown finish, which is what a deliberate reconnect wants.
        """
        with self._lock:
            if graceful and self._client is not None and self._initialized:
                try:
                    self._client.request("shutdown", None, timeout=5.0)
                except Exception:  # noqa: BLE001 - the socket may already be gone
                    pass
            self._teardown()

    @property
    def ready(self) -> bool:
        return self._client is not None and self._initialized
