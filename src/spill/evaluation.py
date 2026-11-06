from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .config import Calibration, Settings, write_json
from .recording import load_observation, read_events
from .types import ARMS, CAMERAS, ActionChunk, Decision, Frame, Observation, SpillError


def replay(path, settings, args):
    events = list(read_events(path))
    if args.no_viz:
        kinds = {}
        for e in events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print(
            json.dumps(
                dict(
                    path=str(path),
                    events=kinds,
                    results=[e for e in events if e["kind"] == "result"],
                ),
                indent=2,
            )
        )
        return 0
    if args.speed <= 0:
        raise ValueError("Replay speed must be positive")
    from .control import Control
    from .robot import make_rig
    from .viewer import Viewer

    manifest = next(e for e in events if e["kind"] == "manifest")
    config = Settings.model_validate(manifest["settings"])
    profile = next(
        (Calibration.model_validate(e["profile"]) for e in events if e["kind"] == "calibration"),
        None,
    )
    control = Control()
    viewer = Viewer(make_rig(config, profile), control, port=settings.port)
    try:
        with control.signals():
            last = events[0]["timestamp"]
            for e in events:
                deadline = time.monotonic() + max(0, min(2, (e["timestamp"] - last) / args.speed))
                while time.monotonic() < deadline and not control.stopping:
                    time.sleep(0.01)
                if control.stopping:
                    break
                last = e["timestamp"]
                if e["kind"] == "observation":
                    with load_observation(path / "observations" / f"{e['id']:08d}.npz") as data:
                        frames = {
                            n: Frame(data[f"rgb_{n}"], time.monotonic(), e["frames"][n]["sequence"])
                            for n in CAMERAS
                        }
                        obs = Observation(
                            e["id"],
                            control.generation,
                            time.monotonic(),
                            frames,
                            {n: data[f"q_{n}"] for n in ARMS},
                            {n: time.monotonic() for n in ARMS},
                        )
                    viewer.publish(
                        observation=obs, status="REPLAY — no hardware", prompt=manifest["prompt"]
                    )
                elif e["kind"] == "accepted":
                    viewer.publish(
                        chunk=ActionChunk(
                            0,
                            control.generation,
                            time.monotonic(),
                            e["hz"],
                            {n: np.array(e["arms"][n]) for n in ARMS},
                        ),
                        chunk_status="accepted",
                    )
                elif e["kind"] == "decision":
                    viewer.publish(
                        decision=Decision.model_validate(
                            {k: v for k, v in e.items() if k in Decision.model_fields}
                        )
                    )
                elif e["kind"] == "result":
                    viewer.publish(status="Replay finished", detail=e["reason"], chunk=None)
            time.sleep(0.3)
    finally:
        viewer.close()
    if viewer.error:
        raise SpillError(viewer.error)
    return 0


def label(path, args):
    for name in ("initial", "target", "residue", "spilled"):
        if getattr(args, name) < 0:
            raise ValueError("Counts must be nonnegative")
    if args.initial <= 0 or args.initial != args.target + args.residue + args.spilled:
        raise ValueError("Initial count must be positive and equal target + residue + spilled")
    result = dict(
        initial=args.initial,
        target=args.target,
        residue=args.residue,
        spilled=args.spilled,
        upright=args.upright,
        collision=args.collision,
        dropped_cup=args.dropped_cup,
        success=args.initial == args.target
        and args.residue == 0
        and args.spilled == 0
        and args.upright
        and not args.collision
        and not args.dropped_cup,
    )
    destination = path / "human_label.json"
    if destination.exists():
        raise SpillError("Label exists; review it before replacing manually")
    write_json(destination, result)
    return 0


def evaluate(settings, args):
    if args.write_scenes:
        rng = np.random.default_rng(20261106)
        scenes = [
            dict(
                trial=i + 1,
                seed=20261106,
                source_offset_cm=rng.integers(-5, 6, size=2).tolist(),
                target_offset_cm=rng.integers(-5, 6, size=2).tolist(),
                source_yaw_deg=int(rng.integers(-45, 46)),
                initial_pills=10,
                instructions="Offsets from calibrated reachable reference positions; check placement before each run",
            )
            for i in range(20)
        ]
        write_json(Path(args.write_scenes), dict(suite=args.suite, scenes=scenes))
    summaries = {"astra_dream": [], "dream_only": []}
    for path in sorted(Path(settings.run_dir).glob("*/human_label.json")):
        events = list(read_events(path.parent))
        manifest = next(e for e in events if e["kind"] == "manifest")
        mode = next((e for e in events if e["kind"] == "mode"), {})
        if not manifest["hardware"] or mode.get("shadow"):
            continue
        result = next((e for e in reversed(events) if e["kind"] == "result"), {})
        label_data = json.loads(path.read_text())
        autonomous = result.get("interventions", 1) == 0 and result.get("outcome") != "failed"
        summaries["dream_only" if mode.get("dream_only") else "astra_dream"].append(
            dict(
                run=path.parent.name,
                success=label_data["success"] and autonomous,
                elapsed_s=result.get("elapsed_s"),
                label=label_data,
            )
        )
    report = {
        name: dict(
            trials=len(rows),
            successes=sum(r["success"] for r in rows),
            success_rate=sum(r["success"] for r in rows) / len(rows) if rows else None,
            runs=rows,
        )
        for name, rows in summaries.items()
    }
    print(json.dumps(report, indent=2))
    return 0


def export_dataset(paths, output, include_failures=False):
    """Explicit LeRobot v2.1 export; no cloud upload or fine-tuning side effect."""
    import av
    import pandas as pd

    if output.exists():
        raise SpillError(f"Refusing to overwrite {output}")
    prepared = []
    fps = None
    for path in paths:
        events = list(read_events(path))
        manifest = next(e for e in events if e["kind"] == "manifest")
        if not manifest["hardware"]:
            raise SpillError("Mock recordings are not training demonstrations")
        mode = next((e for e in events if e["kind"] == "mode"), {})
        if mode.get("shadow"):
            raise SpillError("Shadow recordings have no executed policy actions")
        if not include_failures:
            label_path = path / "human_label.json"
            if not label_path.exists() or not json.loads(label_path.read_text())["success"]:
                raise SpillError(
                    f"{path}: independent successful label required (or --include-failures)"
                )
        commands = [e for e in events if e["kind"] == "command"]
        if not commands:
            raise SpillError(f"No command data in {path}")
        rates = {e["hz"] for e in commands}
        if len(rates) != 1:
            raise SpillError("Export requires one shared action rate")
        source_fps = next(iter(rates))
        # Dream's dataset validator accepts 30, 15, 10 or 5 Hz, but its default
        # execution loop uses 20 Hz. Downsample actual aligned rows, never invent
        # observations or relabel 20 Hz data as 30 Hz.
        stride = 2 if source_fps == 20 else 1
        export_fps = source_fps / stride
        if export_fps not in (30, 15, 10, 5):
            raise SpillError(
                "Dream training requires 30/15/10/5 Hz; only 20→10 downsampling is supported"
            )
        if fps is not None and fps != export_fps:
            raise SpillError("Export requires one shared output rate")
        fps = export_fps
        # Do not silently compress cloud holds or dropped samples into a fake fixed-rate episode.
        for a, b in zip(commands, commands[1:]):
            if abs((b["timestamp"] - a["timestamp"]) - 1 / source_fps) > 0.25 / source_fps:
                raise SpillError(
                    "Recording is not uniformly sampled; collect continuous demonstrations or resample with explicit hold labels"
                )
        sampled = commands[::stride]
        minimum_frames = int(np.ceil(1.6 * fps)) + 1
        if len(sampled) < minimum_frames:
            raise SpillError(
                f"Dream training requires at least {minimum_frames} frames at {fps:g} Hz (1.6 seconds)"
            )
        prepared.append((path, manifest, sampled))
    if not prepared:
        raise SpillError("No episodes selected")
    roles = dict(top="overhead", left_wrist="wrist_l", right_wrist="wrist_r")
    tasks, episodes, total = [], [], 0
    for episode, (path, manifest, commands) in enumerate(prepared):
        task_index = len(tasks)
        tasks.append(dict(task_index=task_index, task=manifest["prompt"]))
        rows = []
        containers, streams = {}, {}
        try:
            for role in CAMERAS:
                video = (
                    output
                    / "videos"
                    / "chunk-000"
                    / f"observation.images.{roles[role]}"
                    / f"episode_{episode:06d}.mp4"
                )
                video.parent.mkdir(parents=True, exist_ok=True)
                containers[role] = av.open(str(video), "w")
                stream = containers[role].add_stream("libx264", rate=int(fps))
                stream.width, stream.height, stream.pix_fmt = 848, 480, "yuv420p"
                streams[role] = stream
            for index, command in enumerate(commands):
                with load_observation(
                    path / "observations" / f"{command['observation_id']:08d}.npz"
                ) as observation:
                    # Dream training layout is right first, unlike Karma's common policy layout.
                    state = np.concatenate([observation["q_right"], observation["q_left"]]).astype(
                        np.float32
                    )
                    action = np.concatenate(
                        [command["arms"]["right"], command["arms"]["left"]]
                    ).astype(np.float32)
                    rows.append(
                        dict(
                            **{"observation.state": state, "action": action},
                            timestamp=index / fps,
                            frame_index=index,
                            episode_index=episode,
                            index=total + index,
                            task_index=task_index,
                        )
                    )
                    for role in CAMERAS:
                        rgb = observation[f"rgb_{role}"]
                        if rgb.shape != (480, 848, 3):
                            raise SpillError("Unexpected recording camera size")
                        for packet in streams[role].encode(
                            av.VideoFrame.from_ndarray(rgb, format="rgb24")
                        ):
                            containers[role].mux(packet)
            for role in CAMERAS:
                for packet in streams[role].encode():
                    containers[role].mux(packet)
        finally:
            for container in containers.values():
                container.close()
        parquet = output / "data" / "chunk-000" / f"episode_{episode:06d}.parquet"
        parquet.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(parquet, index=False)
        episodes.append(dict(episode_index=episode, tasks=[manifest["prompt"]], length=len(rows)))
        total += len(rows)
    features = {
        "observation.state": dict(dtype="float32", shape=[14], names=None),
        "action": dict(dtype="float32", shape=[14], names=None),
    }
    for key in ("timestamp", "frame_index", "episode_index", "index", "task_index"):
        features[key] = dict(
            dtype="float32" if key == "timestamp" else "int64", shape=[1], names=None
        )
    for role in roles.values():
        features[f"observation.images.{role}"] = dict(
            dtype="video",
            shape=[480, 848, 3],
            names=["height", "width", "channels"],
            info={
                "video.fps": fps,
                "video.codec": "h264",
                "video.pix_fmt": "yuv420p",
                "video.is_depth_map": False,
                "has_audio": False,
            },
        )
    write_json(
        output / "meta" / "info.json",
        dict(
            codebase_version="v2.1",
            robot_type="yam_bimanual",
            fps=fps,
            total_episodes=len(prepared),
            total_frames=total,
            total_tasks=len(tasks),
            total_videos=3 * len(prepared),
            total_chunks=1,
            chunks_size=1000,
            splits={"train": f"0:{len(prepared)}"},
            features=features,
            data_path="data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
            video_path="videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
        ),
    )
    for name, rows in (("tasks", tasks), ("episodes", episodes)):
        (output / "meta" / f"{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows)
        )
    print(f"Exported {len(prepared)} episodes to {output}; validate with Dream before upload.")
    return 0
