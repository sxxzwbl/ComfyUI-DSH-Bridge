"""Process-wide bridge singleton: one harness process, several channels."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from typing import Any, Callable

from . import config, paths, presets
from .client import Channel
from .errors import BridgeError
from .process import HarnessProcess

_RECOVERABLE = {"disconnected", "process_exit", "pipe_unavailable", "timeout", "write_failed"}


class Bridge:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cfg: dict[str, Any] = config.load()
        self._proc: HarnessProcess | None = None
        self._channels: dict[str, Channel] = {}
        self._last_error = ""
        self._warm_started = False
        # Node outputs never land in the graph, so the panel cannot read them.
        # Each prompt node records its last result here; the panel fetches it.
        self._records: dict[str, dict[str, Any]] = {}
        # Chat runs in the same session as the node, so it must show the model
        # the same pictures. Each run leaves its payloads on disk; chat attaches
        # whatever the bound node produced most recently.
        self._images: dict[str, list[str]] = {}
        # node -> content fingerprint of those payloads
        self._image_fp: dict[str, str] = {}
        # (session, fingerprint) -> number of turns that already carried them
        self._image_turns: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------------ records
    def record(self, node_id: Any, payload: dict[str, Any]) -> None:
        """Remember the last task result for one prompt node."""
        key = str(node_id or "").strip() or "-"
        with self._lock:
            entry = dict(payload)
            entry["node_id"] = key
            entry["ts"] = time.time()
            self._records[key] = entry

    def last(self, node_id: Any = "") -> dict[str, Any]:
        """Latest result for one node, or for any node when `node_id` is empty."""
        key = str(node_id or "").strip()
        with self._lock:
            if key:
                return dict(self._records.get(key, {}))
            if not self._records:
                return {}
            newest = max(self._records.values(), key=lambda item: item.get("ts", 0.0))
            return dict(newest)

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            ordered = sorted(self._records.values(), key=lambda item: item.get("ts", 0.0), reverse=True)
            return [dict(item) for item in ordered]

    # ------------------------------------------------------------------ media
    def attach_images(self, node_id: Any, images: list[str] | None) -> None:
        """Persist the payloads one run just sent, so the discussion can reuse them.

        The prompt node is the only place the tensors are decoded; chat is a plain
        HTTP call, so it can only see what was written down here beforehand.
        """
        key = str(node_id or "").strip() or "-"
        folder = paths.ensure_dir(paths.media_dir() / key)
        for stale in folder.glob("img_*.png"):
            try:
                stale.unlink()
            except OSError:
                continue
        saved: list[str] = []
        for index, encoded in enumerate(images or []):
            try:
                data = base64.b64decode(encoded)
            except Exception:  # noqa: BLE001 - a corrupt payload must not fail the run
                continue
            target = folder / f"img_{index:02d}.png"
            try:
                target.write_bytes(data)
            except OSError:
                continue
            saved.append(str(target))
        with self._lock:
            self._images[key] = saved
            # The fingerprint decides whether a later chat turn has to carry the
            # pictures again: same payloads, same session, nothing new to send.
            self._image_fp[key] = hashlib.sha1("".join(images or []).encode("utf-8")).hexdigest()[:16]

    def image_fingerprint(self, node_id: Any = "") -> str:
        """Stable id for the payloads the node last produced (empty if none yet)."""
        key = str(node_id or "").strip() or "-"
        with self._lock:
            if key not in self._image_fp and "-" in self._image_fp:
                key = "-"
            return self._image_fp.get(key, "")

    def images_seen(self, session: str, fingerprint: str, max_turns: int = 8) -> bool:
        """True when this session already received these payloads and can reuse them.

        After `max_turns` the pictures are sent once more: a long discussion gets
        compacted, and a model that lost the images would answer blind. The retry
        costs one turn of tokens instead of repeating them on every turn.
        """
        if not fingerprint:
            return False
        with self._lock:
            turns = self._image_turns.get((session, fingerprint), 0)
            return 0 < turns < max_turns

    def note_images_sent(self, session: str, fingerprint: str) -> int:
        """Record that a session received these payloads; returns turns since."""
        if not fingerprint:
            return 0
        with self._lock:
            key = (session, fingerprint)
            turns = self._image_turns.get(key, 0) + 1
            self._image_turns[key] = turns
            return turns

    def reset_images_sent(self, session: str, fingerprint: str) -> None:
        with self._lock:
            self._image_turns.pop((session, fingerprint), None)

    def node_images(self, node_id: Any = "", limit: int = 8) -> list[str]:
        """Base64 of the images the node last sent, ready to attach to a chat turn."""
        key = str(node_id or "").strip() or "-"
        with self._lock:
            if key not in self._images and "-" in self._images:
                key = "-"
            files = list(self._images.get(key, []))[:limit]
        out: list[str] = []
        for path in files:
            try:
                data = paths.Path(path).read_bytes()
            except OSError:
                continue
            out.append(base64.b64encode(data).decode("ascii"))
        return out

    # ------------------------------------------------------------------ config
    @property
    def cfg(self) -> dict[str, Any]:
        return self._cfg

    def reload(self) -> dict[str, Any]:
        with self._lock:
            self.close()
            config.reset_cache()
            self._cfg = config.load(refresh=True)
            return self._cfg

    # ------------------------------------------------------------------ process
    def _ensure_proc(self) -> HarnessProcess:
        if self._proc is None:
            self._proc = HarnessProcess(self._cfg)
        return self._proc

    def _channel(self, name: str) -> Channel:
        with self._lock:
            channel = self._channels.get(name)
            proc = self._ensure_proc()
            if channel is None:
                channel = Channel(name, self._cfg, proc)
                self._channels[name] = channel
            return channel

    def _recover(self) -> None:
        with self._lock:
            self._last_error = "recovering"
            for channel in self._channels.values():
                try:
                    channel.close()  # shutdown first so the server releases its agent
                except Exception:  # noqa: BLE001
                    pass
            self._channels.clear()
            if self._proc is not None:
                self._proc.stop()
                self._proc = None

    # ------------------------------------------------------------------ sessions
    def session_id(self, logical: str) -> str:
        return f"{self._cfg.get('session_prefix', 'comfyui')}-{logical}"

    def _log_history(self, session: str, task: str, text: str, usage: dict[str, Any]) -> None:
        try:
            record = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "session": session,
                "task": task[:4000],
                "answer": text[:20000],
                "usage": usage,
            }
            with paths.history_file().open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ api
    def ask(
        self,
        session: str,
        task: str,
        images: list[str] | None = None,
        channel: str = "nodes",
        timeout: float | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Send one prompt, wait for the turn, return `{text, usage, status}`."""
        blocks: list[dict[str, Any]] = [{"type": "text", "text": task}]
        for b64 in images or []:
            blocks.append({"type": "image", "data": b64, "mimeType": "image/png"})

        last_error: Exception | None = None
        for attempt in (0, 1):
            try:
                result = self._channel(channel).ask(session, blocks, timeout=timeout, on_progress=on_progress)
                self._last_error = ""
                self._log_history(session, task, result.get("text", ""), result.get("usage", {}))
                return result
            except BridgeError as exc:
                last_error = exc
                self._last_error = f"{exc.code}: {exc}"
                if attempt == 0 and exc.code in _RECOVERABLE and self._cfg.get("auto_restart", True):
                    self._recover()
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._last_error = f"{type(exc).__name__}: {exc}"
                if attempt == 0 and self._cfg.get("auto_restart", True):
                    self._recover()
                    continue
                raise
        raise BridgeError("ask_failed", str(last_error))

    def status(self) -> dict[str, Any]:
        proc = self._proc
        if proc is not None:
            attached = proc.external
        else:
            attached = bool(self._cfg.get("attach_only"))
        return {
            "enabled": bool(self._cfg.get("enabled", True)),
            "transport": self._cfg.get("transport"),
            "mode": "attach" if attached else "spawn",
            "attach_only": bool(self._cfg.get("attach_only")),
            "pipe_path": self._cfg.get("pipe_path"),
            "profile": self._cfg.get("profile"),
            "provider": self._cfg.get("provider"),
            "model": self._cfg.get("model"),
            "pid": proc.pid if proc else None,
            "alive": bool(proc and proc.alive),
            "channels": sorted(self._channels),
            "ready": [name for name, ch in self._channels.items() if ch.ready],
            "last_error": self._last_error,
        }

    def warmup(self) -> None:
        """Connect and handshake in the background (no model call)."""
        if not self._cfg.get("warmup_on_start", True) or self._warm_started:
            return
        self._warm_started = True

        def run() -> None:
            time.sleep(6)  # stay out of the way of ComfyUI's own start-up
            try:
                self._channel("nodes").connect()
                self._channel("panel").connect()
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"{type(exc).__name__}: {exc}"

        threading.Thread(target=run, name="dsh-warmup", daemon=True).start()

    def close(self) -> None:
        with self._lock:
            for channel in self._channels.values():
                try:
                    channel.close()
                except Exception:  # noqa: BLE001
                    pass
            self._channels.clear()
            if self._proc is not None:
                self._proc.stop()
                self._proc = None

    def reconnect(self) -> dict[str, Any]:
        """Tear every channel down and dial again (attach or spawn, per config).

        Used by the panel's reconnect button: after the harness host restarts, the
        old sockets are dead but still cached here, and any prompt would otherwise
        pay a failed attempt before `_recover` kicks in.
        """
        with self._lock:
            for channel in self._channels.values():
                try:
                    channel.close()
                except Exception:  # noqa: BLE001
                    pass
            self._channels.clear()
            if self._proc is not None:
                self._proc.stop()
                self._proc = None

        ready: list[str] = []
        errors: list[str] = []
        for name in ("nodes", "panel"):
            try:
                self._channel(name).connect()
                ready.append(name)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        self._last_error = "; ".join(errors)
        return {"ok": not errors, "ready": ready, "errors": errors, "status": self.status()}

    # convenience wrappers -------------------------------------------------
    def understand(self, b64: str, focus: str, detail: str, hint: str, session: str) -> dict[str, Any]:
        return self.ask(session, presets.image_understand(focus, detail, hint), [b64])

    def image_prompt(
        self,
        b64: str,
        target: str,
        style: str,
        negative: bool,
        json_mode: bool,
        draft: str,
        hint: str,
        session: str,
    ) -> dict[str, Any]:
        return self.ask(session, presets.image_to_prompt(target, style, negative, json_mode, draft, hint), [b64])

    def edit(self, b64: str, mode: str, instruction: str, hint: str, session: str) -> dict[str, Any]:
        return self.ask(session, presets.image_edit(mode, instruction, hint), [b64])

    def video(
        self,
        frames: list[str],
        target: str,
        structure: str,
        duration_s: float,
        audio: bool,
        hint: str,
        session: str,
    ) -> dict[str, Any]:
        return self.ask(
            session, presets.video_prompt(target, structure, duration_s, audio, hint), frames
        )


BRIDGE = Bridge()
