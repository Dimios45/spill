from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

ARMS = ("left", "right")
CAMERAS = ("top", "left_wrist", "right_wrist")


class SpillError(RuntimeError):
    pass


class SafetyError(SpillError):
    pass


class FeedbackGap(SafetyError):
    """Transient feedback loss: inhibit commands while waiting for fresh state."""


@dataclass(frozen=True)
class Frame:
    rgb: np.ndarray
    captured_at: float
    sequence: int
    device_timestamp_ms: float = 0.0


@dataclass(frozen=True)
class Observation:
    id: int
    generation: int
    timestamp: float
    frames: dict[str, Frame]
    # Native convention throughout: [six radians, opening], opening 1 = open.
    joints: dict[str, np.ndarray]
    state_times: dict[str, float]

    def validate(self, max_age: float = 0.25, max_skew: float = 0.1) -> None:
        now = time.monotonic()
        if set(self.frames) != set(CAMERAS) or set(self.joints) != set(ARMS):
            raise SafetyError("Incomplete camera or arm observation")
        times = [f.captured_at for f in self.frames.values()] + list(self.state_times.values())
        if len(self.state_times) != 2 or any(
            not np.isfinite(t) or not 0 <= now - t <= max_age for t in times
        ):
            raise SafetyError("Stale or future-dated camera/robot state")
        if max(times) - min(times) > max_skew:
            raise SafetyError("Camera/state time skew exceeds limit")
        for q in self.joints.values():
            if q.shape != (7,) or not np.isfinite(q).all() or not 0 <= q[-1] <= 1:
                raise SafetyError("Invalid native joint/gripper state")
        for f in self.frames.values():
            if f.rgb.ndim != 3 or f.rgb.shape[2] != 3 or f.rgb.dtype != np.uint8:
                raise SafetyError("Expected uint8 RGB camera image")


@dataclass(frozen=True)
class ActionChunk:
    observation_id: int
    generation: int
    requested_at: float
    hz: float
    arms: dict[str, np.ndarray]
    timing: dict = field(default_factory=dict)

    def validate(self) -> None:
        if set(self.arms) != set(ARMS) or not np.isfinite(self.hz) or not 1 <= self.hz <= 100:
            raise SafetyError("Invalid action roles or rate")
        shapes = [a.shape for a in self.arms.values()]
        if (
            shapes[0] != shapes[1]
            or len(shapes[0]) != 2
            or shapes[0][1] != 7
            or not 1 <= shapes[0][0] <= 256
        ):
            raise SafetyError("Expected matching [H, 7] left/right action arrays")
        for name, a in self.arms.items():
            if not np.isfinite(a).all():
                raise SafetyError(f"{name}: nonfinite action")
            if np.any((a[:, -1] < 0) | (a[:, -1] > 1)):
                raise SafetyError(
                    f"{name}: gripper opening outside [0, 1]: "
                    f"range [{a[:, -1].min()}, {a[:, -1].max()}]"
                )

    @property
    def length(self):
        return len(self.arms["left"])


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["execute", "observe", "pause", "finish"]
    subtasks: list[str] = Field(max_length=12)
    active_subtask: str
    instruction: str
    explanation: str
    evidence: str
    outcome: Literal["in_progress", "success", "unverified", "failed"]
    # A subtask is short enough to reobserve instead of acting blindly for a minute.
    duration_s: float = Field(ge=1, le=15)
    recovery: bool


@dataclass
class ExecutionReport:
    rows: int = 0
    chunks: int = 0
    error: str = ""
    elapsed_s: float = 0
    policy_wait_s: float = 0
    wall_elapsed_s: float = 0


@dataclass
class RunResult:
    outcome: str
    reason: str
    elapsed_s: float
    hardware: bool
    interventions: int
