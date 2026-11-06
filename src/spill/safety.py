from __future__ import annotations

import dataclasses
import time

import numpy as np

from .types import ARMS, SafetyError


class TrajectoryGuard:
    def __init__(self, limits, joint_limits, collision=None):
        self.limits = limits
        self.joint_limits = joint_limits
        self.collision = collision
        self.velocity = {n: np.zeros(6) for n in ARMS}

    def reset(self):
        self.velocity = {n: np.zeros(6) for n in ARMS}

    def prepare(self, chunk, start):
        """Bound policy targets like Karma, retaining acceleration and braking limits.

        Keep the original cadence/horizon; unreachable targets are approached
        incrementally. Finish at zero commanded velocity before synchronous hold.
        Never change observation age, native joint bounds, or the configured limits.
        """
        chunk.validate()
        self._check_age(chunk)
        dt = 1 / chunk.hz
        dv = self.limits.max_acceleration * dt

        def braking_speed(distance):
            # Distance includes this tick and every subsequent deceleration tick.
            low = np.zeros(6)
            high = np.full(6, self.limits.max_velocity)
            for _ in range(40):
                speed = (low + high) / 2
                ticks = np.ceil(speed / dv)
                travel = dt * (ticks * speed - dv * ticks * (ticks - 1) / 2)
                fits = travel <= np.maximum(distance, 0)
                low = np.where(fits, speed, low)
                high = np.where(fits, high, speed)
            return low

        arms = {}
        for name in ARMS:
            q = start[name].copy()
            v = self.velocity[name].copy()
            lo, hi = self.joint_limits[name]
            if np.any(q[:6] < lo - self.limits.boundary_recovery_rad) or np.any(
                q[:6] > hi + self.limits.boundary_recovery_rad
            ):
                raise SafetyError(
                    f"{name}: no bounded motion from current state: outside recovery tolerance"
                )
            rows = []
            for i, raw in enumerate(chunk.arms[name]):
                goal = np.clip(raw[:6], lo, hi)
                terminal_speed = (chunk.length - 1 - i) * dv
                lower = np.maximum.reduce(
                    [
                        v - dv,
                        (np.minimum(lo, q[:6]) - q[:6]) / dt,
                        -braking_speed(q[:6] - lo),
                        np.full(6, -terminal_speed),
                    ]
                )
                upper = np.minimum.reduce(
                    [
                        v + dv,
                        (np.maximum(hi, q[:6]) - q[:6]) / dt,
                        braking_speed(hi - q[:6]),
                        np.full(6, terminal_speed),
                    ]
                )
                if np.any(lower > upper + 1e-9):
                    joint = int(np.flatnonzero(lower > upper + 1e-9)[0])
                    raise SafetyError(
                        f"{name}: no bounded motion from current state at row {i}, "
                        f"joint {joint + 1}: position={q[joint]:.6f}rad, "
                        f"velocity={v[joint]:.6f}rad/s, "
                        f"feasible velocity=[{lower[joint]:.6f}, {upper[joint]:.6f}]"
                    )
                v = np.clip((goal - q[:6]) / dt, lower, upper)
                joints = np.clip(q[:6] + v * dt, np.minimum(lo, q[:6]), np.maximum(hi, q[:6]))
                grip_step = self.limits.gripper_velocity * dt
                grip = np.clip(raw[-1], q[-1] - grip_step, q[-1] + grip_step)
                q = np.r_[joints, np.clip(grip, 0, 1)]
                rows.append(q.copy())
            if np.any(q[:6] < lo) or np.any(q[:6] > hi):
                raise SafetyError(f"{name}: boundary recovery did not finish within chunk")
            arms[name] = np.asarray(rows)
        bounded = dataclasses.replace(chunk, arms=arms)
        self.chunk(bounded, start)
        return bounded

    def _check_age(self, chunk):
        age = time.monotonic() - chunk.requested_at
        if age > self.limits.max_chunk_age_s:
            raise SafetyError(
                f"Prediction expired before execution: {age:.2f}s old, "
                f"limit {self.limits.max_chunk_age_s:.2f}s"
            )

    def chunk(self, chunk, start):
        chunk.validate()
        self._check_age(chunk)
        previous = {n: q.copy() for n, q in start.items()}
        velocity = {n: v.copy() for n, v in self.velocity.items()}
        for i in range(chunk.length):
            target = {n: chunk.arms[n][i] for n in ARMS}
            velocity = self._step(target, previous, 1 / chunk.hz, velocity)
            previous = target

    def _step(self, target, previous, dt, velocity):
        result = {}
        for n in ARMS:
            q = target[n]
            lo, hi = self.joint_limits[n]
            if q.shape != (7,) or not np.isfinite(q).all() or not 0 <= q[-1] <= 1:
                raise SafetyError(f"{n} invalid command")
            prev = previous[n][:6]
            tol = self.limits.boundary_recovery_rad
            recovering_low = (prev < lo) & (prev >= lo - tol) & (q[:6] >= prev)
            recovering_high = (prev > hi) & (prev <= hi + tol) & (q[:6] <= prev)
            if np.any((q[:6] < lo) & ~recovering_low) or np.any((q[:6] > hi) & ~recovering_high):
                raise SafetyError(f"{n} joint limit")
            v = (q[:6] - previous[n][:6]) / dt
            if np.max(np.abs(v)) > self.limits.max_velocity + 1e-6:
                raise SafetyError(f"{n} velocity limit")
            if np.max(np.abs(v - velocity[n])) / dt > self.limits.max_acceleration + 1e-6:
                raise SafetyError(f"{n} acceleration limit")
            if abs(q[-1] - previous[n][-1]) / dt > self.limits.gripper_velocity + 1e-6:
                raise SafetyError(f"{n} gripper velocity limit")
            result[n] = v
        if self.collision:
            self.collision.swept(previous, target)
        return result

    def step(self, target, previous, measured, dt):
        for n in ARMS:
            if np.max(np.abs(previous[n][:6] - measured[n][:6])) > self.limits.tracking_error:
                raise SafetyError(f"{n} tracking error")
        self.velocity = self._step(target, previous, dt, self.velocity)
