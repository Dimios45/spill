from __future__ import annotations

import dataclasses
import time
from collections import deque

import numpy as np
from scipy.spatial.transform import Rotation

from .types import ARMS, FeedbackGap, SafetyError


def make_rig(settings, calibration=None):
    from openpi_control.rigs import resolve_rig

    rig = resolve_rig("yam_bimanual")
    arms = []
    for arm in rig.arms:
        changes = dict(interface=settings.interfaces[arm.name])
        if calibration:
            t = np.asarray(calibration.world_from_base[arm.name])
            xyzw = Rotation.from_matrix(t[:3, :3]).as_quat()
            changes.update(
                base_position=tuple(t[:3, 3]), base_rotation_wxyz=tuple(xyzw[[3, 0, 1, 2]])
            )
        arms.append(dataclasses.replace(arm, **changes))
    cameras = tuple(
        dataclasses.replace(
            c,
            serial=settings.serials[c.name] if settings.serials[c.name].isdigit() else c.serial,
            extrinsic=None,
        )
        for c in rig.cameras
    )
    return dataclasses.replace(rig, arms=tuple(arms), cameras=cameras)


class KarmaRobot:
    def __init__(self, rig, limits):
        self.rig, self.limits = rig, limits
        self.session = None
        self.entries = []
        self.last = None
        self.closed = False
        self.telemetry_history = deque(maxlen=60)
        from openpi_control.safety import StateGuard

        self.state_guard = StateGuard(ARMS, max_age_s=limits.state_age_s)

    def connect(self):
        from openpi_control.cli import power_up

        self.session, self.entries = power_up(self.rig)

    def read(self):
        from openpi_control.safety import MAX_STALE_S

        states = self.state_guard.check({e.name: e.arm.latest_state for e in self.entries})
        if states is None:
            raise FeedbackGap("Robot state is not fresh")
        values, times = {}, {}
        for name, state in states.items():
            if str(state.mode) not in {"hold", "direct"}:
                raise SafetyError(f"{name} is not in a policy-compatible mode: {state.mode}")
            if state.effector is None:
                raise SafetyError(f"{name} missing gripper feedback")
            hardware_ages = np.r_[state.joints.frame_age_ms, state.effector.frame_age_ms]
            self.telemetry_history.append(
                dict(
                    arm=name,
                    sampled_at=time.monotonic(),
                    mode=str(state.mode),
                    feedback_age_ms=[float(v) if np.isfinite(v) else None for v in hardware_ages],
                )
            )
            if not np.isfinite(hardware_ages).all() or np.any(
                hardware_ages > self.limits.state_age_s * 1000
            ):
                bad = [
                    f"{'joint_' + str(i + 1) if i < 6 else 'gripper'}={age:.1f}ms"
                    for i, age in enumerate(hardware_ages)
                    if not np.isfinite(age) or age > self.limits.state_age_s * 1000
                ]
                error = (
                    FeedbackGap
                    if np.isfinite(hardware_ages).all()
                    and np.max(hardware_ages) < MAX_STALE_S * 1000
                    else SafetyError
                )
                raise error(
                    f"{name} stale motor CAN feedback: {', '.join(bad)}; "
                    f"limit={self.limits.state_age_s * 1000:g}ms"
                )
            temp = np.r_[state.joints.temperature_c, state.effector.temperature_c]
            if not np.isfinite(temp).all() or np.max(temp) >= self.limits.temperature_c:
                raise SafetyError(f"{name} temperature limit")
            values[name] = np.r_[state.joints.position_rad, state.effector.position]
            times[name] = state.monotonic_timestamp
        return values, times

    def command(self, targets):
        from openpi_control.types import PositionCommand

        if self.closed:
            raise SafetyError("Robot already closed")
        for entry in self.entries:
            q = targets[entry.name]
            entry.arm.command(PositionCommand(q[:6], effector=float(q[-1])))
        self.last = {n: q.copy() for n, q in targets.items()}

    def hold(self):
        # Measured joints + last commanded grip, not measured squeeze deflection.
        q, _ = self.read()
        if self.last:
            for n in ARMS:
                q[n][-1] = self.last[n][-1]
        self.command(q)
        return q

    def close(self, *, park=True):
        from openpi_control.cli import power_down

        if self.closed:
            return 0
        self.closed = True
        if self.session:
            try:
                return power_down(self.session, self.entries, park=park)
            except KeyboardInterrupt:
                # Also cover an interrupt that landed during power_down's final
                # session.close rather than its parking loop. Control suppresses
                # subsequent interrupts until this final close has completed.
                self.session.close()
                return 1
        return 0


class MockRobot:
    """A deterministic joint echo, not a manipulation physics simulator."""

    def __init__(self):
        self.q = {n: np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0]) for n in ARMS}
        self.closed = False
        self.history = []

    def connect(self):
        pass

    def read(self):
        if self.closed:
            raise SafetyError("Mock robot closed")
        return {n: q.copy() for n, q in self.q.items()}, {n: time.monotonic() for n in ARMS}

    def command(self, targets):
        if self.closed:
            raise SafetyError("Command after close")
        self.q = {n: q.copy() for n, q in targets.items()}
        self.history.append(self.q)

    def hold(self):
        return {n: q.copy() for n, q in self.q.items()}

    def close(self, *, park=True):
        self.closed = True
        self.parked = park
        return 0
