"""Package local rollout samples with Karma's existing LeRobot v3 sink.

Encoding runs only after the arms are shut down. Source wall time is preserved
in extra columns; gaps over 200 ms split episodes instead of inventing samples.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .recording import load_observation, read_events
from .types import ARMS, CAMERAS, SpillError


def sampled_segments(events, fps=20):
    samples = [e for e in events if e["kind"] == "dataset_sample"]
    source = "observer_samples"
    if not samples:
        samples = [e for e in events if e["kind"] == "command"]
        source = "legacy_commands_only"
    groups = []
    for event in samples:
        t = event.get("sampled_at", event["timestamp"])
        if not groups or t - groups[-1][-1][0] > 0.2:
            groups.append([])
        groups[-1].append((t, event))
    segments = []
    for group in groups:
        rows = []
        cursor = 0
        for t in np.arange(group[0][0], group[-1][0] + 1e-8, 1 / fps):
            while cursor + 1 < len(group) and group[cursor + 1][0] <= t + 1e-8:
                cursor += 1
            rows.append((float(t), group[cursor][0], group[cursor][1]))
        if rows:
            segments.append(rows)
    return source, segments


def export_v3(run_path):
    from openpi_control.record import (
        LeRobotSink,
        arm_feature_names,
        build_features,
        to_dataset_gripper,
    )

    run_path = Path(run_path)
    events = list(read_events(run_path))
    source, segments = sampled_segments(events)
    if not segments:
        return "No samples to export; raw run log retained"
    root = run_path / "lerobot_v3"
    if root.exists():
        raise SpillError(f"Dataset already exists: {root}; refusing to overwrite")
    manifest = next(e for e in events if e["kind"] == "manifest")
    mode = next((e for e in events if e["kind"] == "mode"), {})
    result = next((e for e in reversed(events) if e["kind"] == "result"), None)
    first_id = segments[0][0][2]["observation_id"]
    with load_observation(run_path / "observations" / f"{first_id:08d}.npz") as obs:
        shapes = {n: obs[f"rgb_{n}"].shape for n in CAMERAS}
    features = build_features(arm_feature_names(ARMS, dict.fromkeys(ARMS, 6)), shapes)
    for name in ("source.elapsed_s", "source.sample_age_s"):
        features[name] = dict(dtype="float32", shape=(1,), names=[name])
    features["source.observation_id"] = dict(dtype="int64", shape=(1,), names=["observation_id"])
    sink = LeRobotSink(
        repo_id=f"local/{run_path.name}",
        root=root,
        fps=20,
        features=features,
        robot_type="yam_bimanual",
    )
    metadata = dict(
        source_run=str(run_path.resolve()),
        source=source,
        fps=20,
        hardware=manifest["hardware"],
        shadow=mode.get("shadow", False),
        task=manifest["prompt"],
        outcome=result.get("outcome", "unverified") if result else "unverified",
        stop_reason=result.get("reason") if result else "incomplete log",
        success_verified=False,
        gripper_convention="Karma dataset: 0=open, 1=closed; native state/actions converted",
        parking_recorded=False,
        resampling="Latest sample at or before each 20 Hz tick; gaps >200ms split episodes",
        episodes=[],
        complete=False,
    )
    meta_path = root / "spill_rollout.json"
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    cached_id, cached = None, None
    try:
        for rows in segments:
            for t, sample_time, event in rows:
                obs_id = event["observation_id"]
                if obs_id != cached_id:
                    with load_observation(run_path / "observations" / f"{obs_id:08d}.npz") as obs:
                        cached = obs
                    cached_id = obs_id
                frame = {
                    "observation.state": np.concatenate([cached[f"q_{n}"] for n in ARMS]).astype(
                        np.float32
                    ),
                    "action": np.concatenate([event["arms"][n] for n in ARMS]).astype(np.float32),
                    "task": manifest["prompt"],
                    "source.elapsed_s": np.array([t - manifest["timestamp"]], dtype=np.float32),
                    "source.sample_age_s": np.array([max(0, t - sample_time)], dtype=np.float32),
                    "source.observation_id": np.array([obs_id], dtype=np.int64),
                }
                frame.update({f"observation.images.{n}": cached[f"rgb_{n}"] for n in CAMERAS})
                for key in ("observation.state", "action"):
                    for index in (6, 13):
                        frame[key][index] = to_dataset_gripper(float(frame[key][index]))
                sink.add_frame(frame)
            sink.save_episode()
            metadata["episodes"].append(
                dict(frames=len(rows), start_s=rows[0][0] - manifest["timestamp"])
            )
            meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    finally:
        sink.finalize()
    metadata["complete"] = True
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return root
