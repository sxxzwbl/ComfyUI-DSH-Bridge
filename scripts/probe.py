"""M0 smoke probe for the ComfyUI <-> DeepSeek Harness bridge.

Spawns the harness `comfy` profile, talks JSON-RPC over the named pipe, runs one
text query and one image query, then verifies that `shutdown` closes only the
connection (the host process must survive), and finally reconnects once more.

Usage:
    python probe.py [--pipe \\\\.\\pipe\\dsh-comfy] [--keep]

Every frame received is appended to logs/probe-sample.jsonl for event-shape
calibration.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Paths come from the shared probe (and thus from config.json after the installer
# has run), never from literals: this file ships to other machines.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dsh_bridge import paths as _paths

    NODE = str(_paths.DEFAULT_NODE_EXE)
    CLI = str(_paths.DEFAULT_CLI_ENTRY)
    DSH_HOME = str(_paths.DEFAULT_DSH_HOME)
    WORKSPACE = str(_paths.DEFAULT_WORKSPACE)
    ASAR = str(Path(_paths.DEFAULT_HARNESS_ROOT) / "resources" / "app.asar") if _paths.DEFAULT_HARNESS_ROOT else ""
except Exception:  # noqa: BLE001 - the probe must run even without the package
    NODE = os.environ.get("DSH_BRIDGE_NODE", "")
    CLI = os.environ.get("DSH_BRIDGE_CLI", "")
    DSH_HOME = os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))
    WORKSPACE = str(Path(DSH_HOME) / "comfyui-bridge-workspace")
    ASAR = ""

HERE = Path(__file__).resolve().parent
LOGS = HERE.parent / "logs"
SAMPLE = LOGS / "probe-sample.jsonl"


def make_png(rgb: tuple[int, int, int], size: int = 256) -> bytes:
    """Solid-colour PNG, no third-party dependency."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


class PipeClient:
    """Minimal newline-delimited JSON-RPC client over a Windows named pipe."""

    def __init__(self, path: str, timeout: float = 300.0) -> None:
        self.path = path
        self.timeout = timeout
        self.fh = open(path, "r+b", buffering=0)
        self._buf = b""
        self._next_id = 0
        self.notifications: list[dict] = []

    # -- framing ---------------------------------------------------------
    def _read_line(self) -> str:
        deadline = time.time() + self.timeout
        while b"\n" not in self._buf:
            if time.time() > deadline:
                raise TimeoutError(f"no frame within {self.timeout}s")
            chunk = self.fh.read(65536)
            if not chunk:
                raise EOFError("pipe closed by peer")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8", "replace")

    def _write(self, frame: dict) -> None:
        self.fh.write((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))

    # -- protocol --------------------------------------------------------
    def notify_frames(self, frame: dict) -> None:
        self.notifications.append(frame)
        try:
            with SAMPLE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(frame, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def request(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        self._next_id += 1
        rid = f"probe-{self._next_id}"
        frame = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            frame["params"] = params
        self._write(frame)
        deadline = time.time() + (timeout or self.timeout)
        while True:
            if time.time() > deadline:
                raise TimeoutError(f"{method}: no response within {timeout or self.timeout}s")
            raw = self._read_line()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"  [skip non-json] {raw[:200]}")
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"{method} -> error {msg['error']}")
                return msg.get("result") or {}
            self.notify_frames(msg)

    def close(self) -> None:
        try:
            self.fh.close()
        except OSError:
            pass


def spawn_harness(log_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["DSH_HOME"] = DSH_HOME
    for key in ("DSH_PROFILE", "DSH_SESSION_ID", "DSH_WEB_URL", "DSH_SHELL"):
        env.pop(key, None)
    # Electron/asar paths are resolved from this env when the desktop host looks
    # for its bundled runtime payload.
    runtime = Path(_paths.DEFAULT_HARNESS_ROOT) / "resources" / "runtime" / "primary-runtime"
    if _paths.DEFAULT_HARNESS_ROOT:
        env.setdefault("DSH_PRIMARY_RUNTIME", str(runtime))
    stdout_log = open(log_dir / "dsh-stdout.log", "ab", buffering=0)
    stderr_log = open(log_dir / "dsh-stderr.log", "ab", buffering=0)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [NODE, "--expose-internals", CLI, "--profile", "comfy"],
        cwd=WORKSPACE,
        env=env,
        # stdin must stay open: the sdk-app startup provider maps stdin EOF to a
        # bounded shutdown of the whole runtime.
        stdin=subprocess.PIPE,
        stdout=stdout_log,
        stderr=stderr_log,
        creationflags=creationflags,
    )
    print(f"harness pid={proc.pid}")
    return proc


def wait_for_pipe(path: str, proc: subprocess.Popen, timeout: float = 120.0) -> PipeClient:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"harness exited early with code {proc.returncode}")
        try:
            return PipeClient(path)
        except OSError as exc:  # pipe not created yet
            last = exc
            time.sleep(0.5)
    raise TimeoutError(f"pipe {path} never appeared ({last})")


def last_assistant_text(notifications: list[dict]) -> str:
    """Best-effort extraction of the final assistant text from session events."""
    texts: list[str] = []

    def collect(node, out):
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                out.append(node["text"])
            for value in node.values():
                collect(value, out)
        elif isinstance(node, list):
            for value in node:
                collect(value, out)

    for frame in notifications:
        params = frame.get("params") or {}
        event = params.get("event") or {}
        if event.get("type") == "assistant/message":
            got: list[str] = []
            collect(event, got)
            joined = "".join(got).strip()
            if joined:
                texts.append(joined)
    return texts[-1] if texts else ""


def run_session(client: PipeClient, label: str) -> str:
    print(f"\n== {label} ==")
    result = client.request(
        "session/query",
        {
            "sessionId": "comfyui-probe",
            "contentBlocks": [],
        },
        timeout=5,
    )
    return json.dumps(result, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", default="\\\\.\\pipe\\dsh-comfy")
    parser.add_argument("--keep", action="store_true", help="leave the harness running")
    args = parser.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text("", encoding="utf-8")
    session_id = f"comfyui-probe-{int(time.time())}"

    proc = spawn_harness(LOGS)
    client = None
    try:
        client = wait_for_pipe(args.pipe, proc)
        print(f"pipe connected: {args.pipe}")

        t0 = time.time()
        init = client.request(
            "initialize",
            {
                "cwd": WORKSPACE,
                "provider": "deepseek-official",
                "model": "deepseek-flash",
                "maxTokens": 8192,
                "approvalRequests": False,
                "capabilities": {"userQuestions": False},
            },
            timeout=180,
        )
        print(f"initialize ok in {time.time()-t0:.1f}s -> {json.dumps(init, ensure_ascii=False)}")

        # --- text query -------------------------------------------------
        client.request(
            "session/query",
            {
                "sessionId": "comfyui-probe",
                "contentBlocks": [{"type": "text", "text": "只回复两个字：收到"}],
            },
            timeout=30,
        )
        t0 = time.time()
        client.request("session/wait", {"sessionId": session_id}, timeout=300)
        print(f"text turn done in {time.time()-t0:.1f}s")
        answer = last_assistant_text(client.notifications)
        print(f"assistant text: {answer[:200]!r}")

        # --- image query ------------------------------------------------
        png = make_png((220, 30, 40))
        b64 = base64.b64encode(png).decode("ascii")
        client.notifications.clear()
        client.request(
            "session/query",
            {
                "sessionId": "comfyui-probe",
                "contentBlocks": [
                    {
                        "type": "text",
                        "text": "这张图的主色调是什么颜色？只回答颜色名，不要解释。",
                    },
                    {"type": "image", "data": b64, "mimeType": "image/png"},
                ],
            },
            timeout=60,
        )
        t0 = time.time()
        client.request("session/wait", {"sessionId": session_id}, timeout=300)
        print(f"image turn done in {time.time()-t0:.1f}s")
        image_answer = last_assistant_text(client.notifications)
        print(f"image answer: {image_answer[:200]!r}")

        # --- shutdown closes only this connection -----------------------
        client.request("shutdown", None, timeout=30)
        client.close()
        client = None
        time.sleep(2)
        alive = proc.poll() is None
        print(f"host process alive after shutdown: {alive}")

        # --- reconnect ---------------------------------------------------
        again = wait_for_pipe(args.pipe, proc, timeout=60)
        init2 = again.request(
            "initialize",
            {
                "cwd": WORKSPACE,
                "provider": "deepseek-official",
                "model": "deepseek-flash",
                "maxTokens": 2048,
                "approvalRequests": False,
            },
            timeout=180,
        )
        print(f"reconnect initialize ok -> {json.dumps(init2, ensure_ascii=False)}")
        again.request("shutdown", None, timeout=30)
        again.close()

        ok = bool(answer) and bool(image_answer) and alive
        print(f"\nRESULT: {'PASS' if ok else 'PARTIAL'}")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 - probe reports any failure
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        try:
            print((LOGS / "dsh-stderr.log").read_text(encoding="utf-8", errors="replace")[-4000:])
        except OSError:
            pass
        return 2
    finally:
        if client is not None:
            client.close()
        if not args.keep and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
