"""Mesh-independent conservative capsule checks, using Karma's YAM URDF chain.

This is a calibrated static-cell backstop, not perception of arbitrary obstacles.
Payload envelopes must be included in tool_radius_m / tool_offset.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

from .types import ARMS, SafetyError


def segment_distance(a, b, c, d):
    """Shortest distance between two closed line segments (including degenerate ones)."""
    u, v, w = b - a, d - c, a - c
    aa, bb, cc, dd, ee = u @ u, u @ v, v @ v, u @ w, v @ w
    if aa < 1e-12 and cc < 1e-12:
        return float(np.linalg.norm(w))
    if aa < 1e-12:
        s, t = 0.0, np.clip(ee / cc, 0, 1)
    elif cc < 1e-12:
        s, t = np.clip(-dd / aa, 0, 1), 0.0
    else:
        denom = aa * cc - bb * bb
        s = np.clip((bb * ee - cc * dd) / denom, 0, 1) if denom > 1e-12 else 0.0
        t = (bb * s + ee) / cc
        if t < 0:
            t, s = 0.0, np.clip(-dd / aa, 0, 1)
        elif t > 1:
            t, s = 1.0, np.clip((bb - dd) / aa, 0, 1)
    return float(np.linalg.norm(w + s * u - t * v))


class Kinematics:
    def __init__(self, urdf):
        root = ET.parse(urdf).getroot()
        joints = root.findall("joint")
        children = {j.find("child").get("link") for j in joints}
        link = next(
            node.get("name") for node in root.findall("link") if node.get("name") not in children
        )
        self.chain = []
        while True:
            matches = [j for j in joints if j.find("parent").get("link") == link]
            if not matches:
                break
            if len(matches) != 1:
                raise ValueError("Expected serial YAM chain")
            joint = matches[0]
            origin = joint.find("origin")
            xyz = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ")
            rpy = np.fromstring(origin.get("rpy", "0 0 0"), sep=" ")
            t = np.eye(4)
            t[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()
            t[:3, 3] = xyz
            axis = joint.find("axis")
            axis = (
                np.fromstring(axis.get("xyz"), sep=" ") if axis is not None else np.array([0, 0, 1])
            )
            self.chain.append((t, axis, joint.get("type") != "fixed"))
            link = joint.find("child").get("link")

    def points(self, q, base, tool):
        t = np.array(base, dtype=float)
        result = [t[:3, 3].copy()]
        i = 0
        for origin, axis, actuated in self.chain:
            t = t @ origin
            if actuated:
                r = np.eye(4)
                r[:3, :3] = Rotation.from_rotvec(axis * q[i]).as_matrix()
                t = t @ r
                i += 1
            result.append(t[:3, 3].copy())
        result.append((t @ np.r_[tool, 1])[:3])
        return np.asarray(result)


class CollisionGuard:
    def __init__(self, calibration, limits, rig):
        from openpi_control.config import resolve_model_assets

        self.c = calibration
        self.limits = limits
        self.models = {a.name: Kinematics(resolve_model_assets(a.model).urdf) for a in rig.arms}

    def points(self, name, q):
        return self.models[name].points(q, self.c.world_from_base[name], self.c.tool_offset)

    def check(self, joints):
        segments = {}
        margin = self.limits.collision_margin
        for name in ARMS:
            p = self.points(name, joints[name][:6])
            segments[name] = [
                (a, b, self.c.tool_radius_m if i == len(p) - 2 else self.c.link_radius_m)
                for i, (a, b) in enumerate(zip(p, p[1:]))
            ]
            for i, (a, b, r) in enumerate(segments[name]):
                # Base/shoulder mounting intersects the support plane by design.
                if i >= 2 and min(a[2], b[2]) - r < self.c.table_z + margin:
                    raise SafetyError(f"{name} table clearance")
                if i == len(segments[name]) - 1:
                    if np.any(b - r < np.asarray(self.c.workspace_min) + margin) or np.any(
                        b + r > np.asarray(self.c.workspace_max) - margin
                    ):
                        raise SafetyError(f"{name} tool outside calibrated workspace")
                for box in self.c.obstacles:
                    # Segment vs expanded AABB (conservative capsule-box test).
                    lo, hi = np.asarray(box[0]) - r - margin, np.asarray(box[1]) + r + margin
                    delta = b - a
                    t0, t1 = 0.0, 1.0
                    for axis in range(3):
                        if abs(delta[axis]) < 1e-12:
                            if not lo[axis] <= a[axis] <= hi[axis]:
                                t0, t1 = 1.0, 0.0
                                break
                        else:
                            x, y = sorted(
                                (
                                    (lo[axis] - a[axis]) / delta[axis],
                                    (hi[axis] - a[axis]) / delta[axis],
                                )
                            )
                            t0, t1 = max(t0, x), min(t1, y)
                    if t0 <= t1:
                        raise SafetyError(f"{name} static obstacle clearance")
            # Neighboring links share joints; skip two neighbors around compact wrist.
            for i, (a, b, r) in enumerate(segments[name]):
                for c, d, s in segments[name][i + 3 :]:
                    if segment_distance(a, b, c, d) < r + s + margin:
                        raise SafetyError(f"{name} self clearance")
        for a, b, r in segments["left"]:
            for c, d, s in segments["right"]:
                if segment_distance(a, b, c, d) < r + s + margin:
                    raise SafetyError("Inter-arm clearance")

    def swept(self, start, end):
        delta = max(np.max(np.abs(end[n][:6] - start[n][:6])) for n in ARMS)
        count = max(1, int(np.ceil(delta / self.limits.sweep_step_rad)))
        for t in np.linspace(0, 1, count + 1):
            self.check({n: start[n] + t * (end[n] - start[n]) for n in ARMS})
