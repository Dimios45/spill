"""Optional isolated SDK runtime to avoid Dream/Karma dependency conflicts."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import threading
import time
from pathlib import Path

from .types import SpillError


class RemoteDreamError(SpillError):
    def __init__(self, reply):
        super().__init__(f"{reply['error_type']}: {reply['error']}")
        self.retryable = reply.get("retryable", False) or reply["error_type"] in (
            "DreamTimeout",
            "DreamSessionExpired",
        )
        self.retry_after_s = reply.get("retry_after_s")


class IsolatedDreamClient:
    def __init__(self, log_dir, *, command=None):
        root = Path(__file__).resolve().parents[2] / "dream_runtime"
        self.log = (Path(log_dir) / "dream-worker.log").open("a")
        env = dict(os.environ, PYTHONUNBUFFERED="1", DREAM_LOG_DIR=str(Path(log_dir) / "dream"))
        self.process = subprocess.Popen(
            command
            or ["uv", "run", "--locked", "--project", str(root), "python", str(root / "worker.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            env=env,
            bufsize=0,
            start_new_session=True,
        )
        self.lock = threading.Lock()
        self.ticks = []
        self.last_timing = {}
        self.mode = "sync"
        self.refill_table = []
        self.timeout_s = 60.0
        self._read_buffer = b""

    def _call(self, op, **args):
        with self.lock:
            if self.process.poll() is not None:
                raise SpillError("Dream worker exited; inspect dream-worker.log")
            body = json.dumps(dict(op=op, args=args), allow_nan=False).encode() + b"\n"
            # A pipe write may block on a slow child; this method is only called
            # before energizing hardware or from the daemon inference worker.
            pending = memoryview(body)
            while pending:
                written = self.process.stdin.write(pending)
                if not written:
                    raise SpillError("Dream worker input stream closed")
                pending = pending[written:]
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + self.timeout_s
                while b"\n" not in self._read_buffer:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        os.killpg(self.process.pid, signal.SIGKILL)
                        raise SpillError("Dream worker response timed out")
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        raise SpillError(
                            "Dream worker closed reply stream; inspect dream-worker.log"
                        )
                    self._read_buffer += chunk
                    if len(self._read_buffer) > 8_000_000:
                        raise SpillError("Oversized Dream worker reply")
            line, self._read_buffer = self._read_buffer.split(b"\n", 1)
            reply = json.loads(line)
            if not reply["ok"]:
                raise RemoteDreamError(reply)
            return reply["result"]

    def policy(self, config):
        self.action_hz = config.get("action_hz", 20)
        self.execution_horizon = config.get("execution_horizon", 30)
        self._call("policy", config=config)
        self.timeout_s = max(30, config.get("timeout_ms", 15000) / 1000 + 5)

    def get_models(self):
        return self._call("get_models")

    def reset_episode(self):
        self.ticks.clear()
        return self._call("reset_episode")

    def set_observation(self, frames, state, *, timestamp):
        self.ticks.append(
            dict(
                frames=frames,
                state={k: v.tolist() if hasattr(v, "tolist") else v for k, v in state.items()},
                timestamp=timestamp,
            )
        )

    def get_action(self, *, commanded):
        ticks, self.ticks = self.ticks, []
        result = self._call("infer", ticks=ticks, commanded=commanded)
        self.last_timing = result["timing"] or {}
        self.mode = result["mode"]
        self.refill_table = result["refill_table"]
        return result["action"]

    def refill_due(self, executed, remaining):
        # Exact public SDK decisions computed after the last reply, with no IPC
        # or cloud wait in the main control loop.
        if not self.refill_table:
            return remaining == 0
        return self.refill_table[min(executed, len(self.refill_table) - 1)][
            min(remaining, len(self.refill_table) - 1)
        ]

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.log):
            if stream:
                stream.close()
