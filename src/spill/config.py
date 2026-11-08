from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .types import ARMS, CAMERAS


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Limits(Strict):
    state_age_s: float = Field(default=0.25, gt=0, le=0.25)
    camera_skew_s: float = Field(default=0.1, gt=0, le=0.25)
    max_velocity: float = Field(default=0.3, gt=0)
    max_acceleration: float = Field(default=1.5, gt=0)
    gripper_velocity: float = Field(default=1.0, gt=0)
    tracking_error: float = Field(default=0.25, gt=0)
    boundary_recovery_rad: float = Field(default=0.01, ge=0, le=0.01)
    max_chunk_age_s: float = Field(default=10.0, gt=0)
    temperature_c: float = Field(default=65, gt=0, le=80)
    collision_margin: float = Field(default=0.015, ge=0)
    sweep_step_rad: float = Field(default=0.02, gt=0, le=0.05)
    task_timeout_s: float = Field(default=300, gt=0)
    retries_per_subtask: int = Field(default=2, ge=0, le=10)
    hold_timeout_s: float = Field(default=60, gt=0)


class DreamProfile(Strict):
    checkpoint: str = "dreamlabs/dream-1"
    verified: bool = False
    # Verify joint zeros, signs, camera orientation and base/TCP against the selected model.
    action_hz: float = Field(default=20, ge=1, le=100)
    execution_horizon: int = Field(default=30, ge=1, le=256)
    timeout_ms: int = Field(default=15000, ge=100, le=30000)
    ik: dict | None = Field(default_factory=lambda: {"arm": "yam", "head": "joint"})
    sdk_runtime: Literal["client", "isolated"] = "isolated"
    pacing: Literal["sync", "adaptive"] = "sync"


class Settings(Strict):
    interfaces: dict[str, str] = {"left": "can0", "right": "can1"}
    serials: dict[str, str] = {name: "SET_ME_" + name for name in CAMERAS}
    calibration: str = "config/calibration.json"
    model: str = "gpt-6-astra"
    grasp: Literal["top-down", "auto"] = "auto"
    reference_context: dict | None = None
    # None restores planner-selected durations. Complete a validated chunk before review.
    execution_window_s: float | None = Field(default=20, ge=1, le=30)
    recovery_window_s: float = Field(default=7, ge=1, le=15)
    planner_timeout_s: float = Field(default=45, gt=0, le=120)
    planner_retries: int = Field(default=2, ge=0, le=3)
    planner_retry_delay_s: float = Field(default=2, ge=0, le=30)
    dream: DreamProfile = Field(default_factory=DreamProfile)
    limits: Limits = Field(default_factory=Limits)
    port: int = Field(default=8080, ge=1024, le=65535)
    run_dir: str = "runs"
    viewer_hz: float = Field(default=8, gt=0, le=15)

    @model_validator(mode="after")
    def roles(self):
        if set(self.interfaces) != set(ARMS) or len(set(self.interfaces.values())) != 2:
            raise ValueError("Two distinct left/right CAN interfaces required")
        if set(self.serials) != set(CAMERAS) or len(set(self.serials.values())) != 3:
            raise ValueError("Three distinct camera serials required")
        return self


class Calibration(Strict):
    version: int = 1
    verified: bool = False
    measured_by: str = ""
    measured_at: str = ""
    # Homogeneous transforms: world <- base, world <- top camera,
    # flange <- wrist camera. Never treat these as identical frames.
    world_from_base: dict[str, list[list[float]]]
    camera_transforms: dict[str, list[list[float]]]
    camera_intrinsics: dict[str, list[list[float]]]
    camera_serials: dict[str, str]
    table_z: float
    workspace_min: list[float]
    workspace_max: list[float]
    link_radius_m: float = Field(default=0.055, gt=0)
    tool_offset: list[float]
    tool_radius_m: float = Field(default=0.07, gt=0)
    # Static obstacle boxes, [minimum xyz, maximum xyz].
    obstacles: list[list[list[float]]] = []

    @model_validator(mode="after")
    def geometry(self):
        if set(self.world_from_base) != set(ARMS):
            raise ValueError("Both arm base transforms required")
        if any(
            set(x) != set(CAMERAS)
            for x in (self.camera_transforms, self.camera_intrinsics, self.camera_serials)
        ):
            raise ValueError("All camera transforms, intrinsics and serials required")
        for transform in [*self.world_from_base.values(), *self.camera_transforms.values()]:
            t = np.asarray(transform)
            if t.shape != (4, 4) or not np.isfinite(t).all() or not np.allclose(t[3], [0, 0, 0, 1]):
                raise ValueError("Invalid rigid transform")
            r = t[:3, :3]
            if not np.allclose(r.T @ r, np.eye(3), atol=1e-5) or not np.isclose(
                np.linalg.det(r), 1
            ):
                raise ValueError("Transform rotation must be orthonormal and right handed")
        for intrinsic in self.camera_intrinsics.values():
            k = np.asarray(intrinsic)
            if k.shape != (3, 3) or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0:
                raise ValueError("Invalid camera intrinsics")
        for v in (self.workspace_min, self.workspace_max, self.tool_offset):
            if len(v) != 3 or not np.isfinite(v).all():
                raise ValueError("Expected finite XYZ vector")
        if np.any(np.asarray(self.workspace_min) >= self.workspace_max):
            raise ValueError("Invalid workspace bounds")
        for box in self.obstacles:
            b = np.asarray(box)
            if b.shape != (2, 3) or not np.isfinite(b).all() or np.any(b[0] >= b[1]):
                raise ValueError("Invalid obstacle box")
        return self


def load_settings(path: str | None) -> Settings:
    return Settings.model_validate_json(Path(path).read_text()) if path else Settings()


def run_calibration(settings: Settings, *, hardware: bool, zero_shot: bool):
    """Zero-shot RGB control needs device identity, not measured scene geometry."""
    if not hardware:
        return None
    if any(not value.isdigit() for value in settings.serials.values()):
        raise ValueError("Replace all camera serial placeholders before hardware operation")
    if zero_shot:
        return None
    return load_calibration(settings, hardware=True)


def load_calibration(settings: Settings, *, hardware: bool) -> Calibration:
    c = Calibration.model_validate_json(Path(settings.calibration).read_text())
    if hardware:
        if any(not value.isdigit() for value in settings.serials.values()):
            raise ValueError("Replace all camera serial placeholders before hardware operation")
        if not c.verified or not c.measured_by or not c.measured_at:
            raise ValueError("Complete and verify measured calibration before hardware operation")
        if c.camera_serials != settings.serials:
            raise ValueError("Calibration camera serials do not match configuration")
        if not settings.dream.verified:
            raise ValueError("Verify the Dream model profile before hardware operation")
    return c


def calibration_template(settings: Settings) -> dict:
    transforms = {}
    for name, y in (("left", 0.3), ("right", -0.3)):
        t = np.eye(4)
        t[1, 3] = y
        transforms[name] = t.tolist()
    return dict(
        version=1,
        verified=False,
        measured_by="",
        measured_at="",
        world_from_base=transforms,
        camera_transforms={n: np.eye(4).tolist() for n in CAMERAS},
        camera_intrinsics={n: [[600, 0, 424], [0, 600, 240], [0, 0, 1]] for n in CAMERAS},
        camera_serials=settings.serials,
        table_z=-0.1,
        workspace_min=[-0.8, -1.0, -0.1],
        workspace_max=[1.0, 1.0, 1.2],
        link_radius_m=0.055,
        tool_offset=[0, 0, 0.15],
        tool_radius_m=0.07,
        obstacles=[],
    )


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")
