from __future__ import annotations

import dataclasses
import json
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .types import SafetyError


def serializable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


class Recorder:
    def __init__(self, root, settings, *, hardware, prompt):
        self.path = Path(root) / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        )
        self.path.mkdir(parents=True)
        (self.path / "observations").mkdir()
        self.queue = queue.Queue(maxsize=256)
        self.error = None
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        self.event(
            "manifest",
            schema_version=1,
            settings=settings.model_dump(),
            hardware=hardware,
            prompt=prompt,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def check(self):
        if self.error:
            raise SafetyError(f"Recording failed: {self.error}")

    def _put(self, item):
        self.check()
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            raise SafetyError(
                "Recording queue full; stopping instead of losing audit data"
            ) from None

    def event(self, kind, **data):
        self._put(("event", dict(kind=kind, timestamp=time.monotonic(), **data)))

    def observation(self, obs, purpose):
        self._put(("observation", (obs, purpose)))

    def _worker(self):
        import cv2

        seen = set()
        try:
            with (self.path / "events.jsonl").open("a", buffering=1) as out:
                while True:
                    item = self.queue.get()
                    try:
                        if item is None:
                            return
                        kind, data = item
                        if kind == "observation":
                            obs, purpose = data
                            if obs.id not in seen:
                                payload = {}
                                for name, frame in obs.frames.items():
                                    ok, encoded = cv2.imencode(
                                        ".jpg",
                                        cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2BGR),
                                        [cv2.IMWRITE_JPEG_QUALITY, 95],
                                    )
                                    if not ok:
                                        raise OSError("Observation JPEG encoding failed")
                                    payload[f"jpeg_{name}"] = encoded
                                payload.update({f"q_{n}": q for n, q in obs.joints.items()})
                                np.savez(
                                    self.path / "observations" / f"{obs.id:08d}.npz", **payload
                                )
                                seen.add(obs.id)
                            data = dict(
                                kind="observation",
                                timestamp=obs.timestamp,
                                id=obs.id,
                                generation=obs.generation,
                                purpose=purpose,
                                state_times=obs.state_times,
                                frames={
                                    n: dict(
                                        captured_at=f.captured_at,
                                        sequence=f.sequence,
                                        device_timestamp_ms=f.device_timestamp_ms,
                                    )
                                    for n, f in obs.frames.items()
                                },
                            )
                        out.write(json.dumps(data, default=serializable, allow_nan=False) + "\n")
                    finally:
                        self.queue.task_done()
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def close(self):
        if self.thread.is_alive():
            try:
                self.queue.put(None, timeout=2)
            except queue.Full:
                self.error = "Recording backlog did not drain"
            self.thread.join(timeout=10)
        if self.thread.is_alive():
            self.error = "Recording writer did not finish"
        self.check()
        write_summary(self.path)


def read_events(path):
    with (Path(path) / "events.jsonl").open() as source:
        for line in source:
            yield json.loads(line)


def write_summary(path):
    """Small comparison artifact; never copies image payloads or credentials."""
    path = Path(path)
    counts, requests, astra_s, dream_s, timeline = {}, {}, [], [], []
    motion_s = 0.0
    tokens = 0
    result = None
    start = None
    for event in read_events(path):
        kind = event["kind"]
        start = event["timestamp"] if start is None else start
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "astra_request":
            requests[event["observation_id"]] = event["timestamp"]
        elif kind == "astra":
            elapsed = event.get("elapsed_s")
            if elapsed is None and event["observation_id"] in requests:
                elapsed = event["timestamp"] - requests[event["observation_id"]]
            if elapsed is not None:
                astra_s.append(elapsed)
            tokens += (event.get("usage") or {}).get("total_tokens", 0)
        elif kind == "dream":
            rtt = event.get("timing", {}).get("rtt_ms")
            if rtt is not None:
                dream_s.append(rtt / 1000)
        elif kind == "command":
            motion_s += 1 / event["hz"]
        elif kind == "result":
            result = {k: event[k] for k in ("outcome", "reason", "elapsed_s", "hardware")}
        if kind in (
            "control",
            "rejected",
            "recovery",
            "astra_error",
            "observation_fault",
            "feedback_gap",
            "feedback_recovered",
            "planner_retry",
            "subtask_report",
            "result",
        ):
            timeline.append(
                {
                    "at_s": round(event["timestamp"] - start, 3),
                    "kind": kind,
                    **{
                        k: event[k]
                        for k in (
                            "reason",
                            "error",
                            "error_type",
                            "request_id",
                            "status_code",
                            "attempt",
                            "delay_s",
                            "elapsed_s",
                            "policy_wait_s",
                            "wall_elapsed_s",
                        "gap_s",
                            "rows",
                            "chunks",
                            "outcome",
                        )
                        if k in event
                    },
                }
            )

    def stats(values):
        return (
            dict(
                count=len(values),
                mean_s=float(np.mean(values)),
                p95_s=float(np.percentile(values, 95)),
                max_s=max(values),
            )
            if values
            else None
        )

    summary = dict(
        run_id=path.name,
        result=result,
        event_counts=counts,
        commanded_motion_s=round(motion_s, 3),
        astra_success_latency=stats(astra_s),
        dream_latency=stats(dream_s),
        astra_reported_total_tokens=tokens,
        timeline=timeline,
    )
    (path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


@contextmanager
def load_observation(path):
    """Read current JPEG archives and earlier lossless mock fixtures."""
    import cv2

    with np.load(path, allow_pickle=False) as archive:
        result = {k: archive[k] for k in archive.files}
    for key, value in list(result.items()):
        if key.startswith("jpeg_"):
            image = cv2.imdecode(value, cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Corrupt observation image")
            result["rgb_" + key[5:]] = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    yield result
