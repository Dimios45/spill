from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import threading
import time
from pathlib import Path

from .config import (
    Calibration,
    Settings,
    calibration_template,
    load_calibration,
    load_settings,
    run_calibration,
    write_json,
)
from .defaults import DEFAULT_PROMPT
from .types import SpillError


def parser():
    p = argparse.ArgumentParser(
        prog="spill",
        description="YAM harness. No arguments: Dream-only hardware run using config/local.json. "
        "Explicit run: MOCK unless --hardware or --shadow is supplied.",
    )
    p.add_argument("--config", help="JSON settings (paths relative to current working directory)")
    commands = p.add_subparsers(dest="command", required=True)
    recordings = commands.add_parser("recordings", help="Read-only recorded top-camera gallery")
    recordings.add_argument("--host", default="0.0.0.0")
    recordings.add_argument("--port", type=int, default=8085)
    init = commands.add_parser("init", help="Write example local settings, without overwriting")
    init.add_argument("--output", default="config/local.json")
    doctor = commands.add_parser("doctor", help="Read-only rig/configuration preflight")
    doctor.add_argument("--zero-shot", action="store_true", help="Check without scene calibration")
    doctor.add_argument(
        "--cameras", action="store_true", help="Open cameras and measure availability, no motors"
    )
    doctor.add_argument(
        "--models", action="store_true", help="Check authenticated Dream model access, no motion"
    )
    calibration = commands.add_parser(
        "calibrate", help="Create/import/check measured calibration; never moves arms"
    )
    calibration.add_argument("--import-file")
    calibration.add_argument("--check", action="store_true")
    calibration.add_argument("--capture-intrinsics", action="store_true")
    run = commands.add_parser("run")
    run.add_argument(
        "prompt", nargs="?", help="Task text; defaults to the three-camera pill-transfer prompt"
    )
    run.add_argument("--hardware", action="store_true", help="Use both real arms and cloud APIs")
    run.add_argument(
        "--zero-shot",
        action="store_true",
        help="RGB control without measured calibration; geometric collision checks disabled",
    )
    run.add_argument(
        "--shadow",
        action="store_true",
        help="Use real cameras and models, validate actions but do not execute policy motion (arms hold)",
    )
    run.add_argument("--no-viz", action="store_true")
    run.add_argument("--no-park", action="store_true")
    run.add_argument(
        "--record",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Save rollout as local LeRobot v3 after shutdown (default: enabled)",
    )
    run.add_argument("--grasp", choices=["top-down", "auto"], default="auto")
    modes = run.add_mutually_exclusive_group()
    modes.add_argument(
        "--dream-only", "--dream", dest="dream_only", action="store_true",
        help="Pass the full task directly to Dream (default)"
    )
    modes.add_argument(
        "--astra-only", action="store_true", help="Experimental Astra joint actions; no Dream calls"
    )
    modes.add_argument(
        "--astra-dream", dest="dream_only", action="store_false",
        help="Use Astra planning and progress checks with Dream actions",
    )
    run.set_defaults(dream_only=True)
    run.add_argument("--seconds", type=float, help="Override task time limit")
    run.add_argument(
        "--reference-run", help="Prior local run ID/path as historical context for Astra"
    )
    replay = commands.add_parser("replay")
    replay.add_argument("run_id")
    replay.add_argument("--speed", type=float, default=1)
    replay.add_argument("--no-viz", action="store_true")
    report = commands.add_parser(
        "report", help="Summarize a recorded rollout; no hardware/API access"
    )
    report.add_argument("run_id")
    commands.add_parser("catalog", help="Document all local runs and index model I/O; no API calls")
    v3 = commands.add_parser(
        "export-v3", help="Package recorded samples with Karma's LeRobot v3 writer"
    )
    v3.add_argument("run_id")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--suite", choices=["cup-transfer"], default="cup-transfer")
    evaluate.add_argument("--write-scenes", help="Write reproducible 20-trial scene schedule")
    label = commands.add_parser("label", help="Record independent human benchmark counts")
    label.add_argument("run_id")
    for name in ("initial", "target", "residue", "spilled"):
        label.add_argument("--" + name, type=int, required=True)
    label.add_argument("--upright", action="store_true")
    label.add_argument("--collision", action="store_true")
    label.add_argument("--dropped-cup", action="store_true")
    export = commands.add_parser(
        "export", help="Export command-aligned observations to LeRobot v2.1"
    )
    export.add_argument("run_ids", nargs="+")
    export.add_argument("--output", required=True)
    export.add_argument("--include-failures", action="store_true")
    karma = commands.add_parser(
        "karma", help="Operator-only passthrough to the complete Karma CLI", add_help=False
    )
    karma.add_argument("arguments", nargs=argparse.REMAINDER)
    return p


def run_path(settings, value):
    path = Path(value)
    return path if path.is_dir() else Path(settings.run_dir) / value


def task_prompt(value):
    if value is None:
        value = DEFAULT_PROMPT
    if not value.strip():
        raise SpillError("Enter a non-empty task; robot was not started")
    return value.strip()


def doctor(settings, args):
    from openpi_control.cli import preflight_rig

    from .robot import make_rig

    failures, reports = preflight_rig(make_rig(settings))
    for name, checks in reports:
        for check in checks:
            print(name, check)
    try:
        run_calibration(settings, hardware=True, zero_shot=args.zero_shot)
        print(
            "Zero-shot device configuration: valid"
            if args.zero_shot
            else "Calibration and model-profile declarations: valid"
        )
    except (ValueError, OSError) as exc:
        failures += 1
        print("Configuration:", exc)
    if args.cameras:
        from .cameras import Cameras

        cameras = Cameras(settings.serials)
        try:
            cameras.start()
            cameras.wait_ready()
            print(json.dumps(cameras.intrinsics, indent=2))
        finally:
            cameras.close()
    if args.models:
        from .providers import Dream
        from .recording import Recorder

        rec = Recorder(settings.run_dir, settings, hardware=False, prompt="model preflight")
        policy = None
        try:
            policy = Dream(settings, rec)
            policy.check_model()
            print("Configured Dream model is available")
        finally:
            if policy:
                policy.close()
            rec.close()
    return int(bool(failures))


def calibrate(settings, args):
    target = Path(settings.calibration)
    if args.capture_intrinsics:
        from .cameras import Cameras

        cameras = Cameras(settings.serials)
        try:
            cameras.start()
            cameras.wait_ready()
            output = target.with_name("camera_intrinsics.json")
            write_json(output, dict(serials=settings.serials, cameras=cameras.intrinsics))
            print(f"Captured factory intrinsics: {output}. Extrinsics still require measurement.")
        finally:
            cameras.close()
        return 0
    if args.check:
        load_calibration(settings, hardware=True)
        print(
            "Calibration/profile declarations valid; physical accuracy is not established by this check."
        )
        return 0
    if target.exists():
        raise SpillError(
            f"Refusing to overwrite {target}; select another calibration path in settings"
        )
    if args.import_file:
        c = Calibration.model_validate_json(Path(args.import_file).read_text())
        write_json(target, c.model_dump())
    else:
        write_json(target, calibration_template(settings))
    print(f"Written {target}. Template values are NOT calibration; follow docs/commissioning.md.")
    return 0


def run(settings, args):
    args.prompt = task_prompt(args.prompt)
    if args.reference_run and (args.dream_only or args.astra_only):
        raise SpillError("--reference-run requires --astra-dream")
    if args.reference_run:
        from .episodes import reference_context

        settings.reference_context = reference_context(run_path(settings, args.reference_run))
    else:
        settings.reference_context = None
    from openpi_control.cli import preflight_rig
    from openpi_control.safety import joint_limits

    from .cameras import Cameras
    from .control import Control
    from .geometry import CollisionGuard
    from .providers import Astra, Dream, MockPlanner, MockPolicy
    from .recording import Recorder
    from .robot import KarmaRobot, MockRobot, make_rig
    from .runtime import Runner
    from .safety import TrajectoryGuard
    from .viewer import Viewer

    hardware = args.hardware or args.shadow
    if args.astra_only and not hardware:
        raise SpillError("Use --astra-only with --shadow to validate, or --hardware to execute")
    settings.grasp = args.grasp
    if args.grasp == "top-down":
        args.prompt += (
            " Approach and grasp each cup from above with a top-down gripper orientation; "
            "do not use a sideways approach. Keep the cup upright until positioned over the "
            "receiving cup, and tilt only for pouring. If a top-down grasp is not feasible, "
            "pause instead of switching to a sideways grasp."
        )
    if args.record:
        from .dataset import preflight_export

        preflight_export()  # Fail before energizing; keep heavy imports outside control process.
    if args.seconds is not None:
        settings.limits.task_timeout_s = args.seconds
        settings = Settings.model_validate(settings.model_dump())
    calibration = run_calibration(settings, hardware=hardware, zero_shot=args.zero_shot)
    rig = make_rig(settings, calibration)
    control = Control(park=not args.no_park)
    recorder = Recorder(settings.run_dir, settings, hardware=hardware, prompt=args.prompt)
    recorder.dataset_enabled = args.record
    recorder.event(
        "mode",
        shadow=args.shadow,
        dream_only=args.dream_only,
        zero_shot=args.zero_shot,
        geometric_checks=calibration is not None,
    )
    if hardware and args.zero_shot:
        print(
            "Zero-shot RGB control: no geometric collision checks; motion/telemetry guards active."
        )
    if calibration:
        recorder.event("calibration", profile=calibration.model_dump())
    robot = KarmaRobot(rig, settings.limits) if hardware else MockRobot()
    cameras = Cameras(settings.serials, mock=not hardware)
    viewer = planner = policy = None
    print(f"{'HARDWARE' if hardware else 'MOCK (no hardware, no API calls)'} run: {recorder.path}")
    with control.signals():
        try:
            if hardware:
                failures, reports = preflight_rig(rig)
                if failures:
                    raise SpillError(f"Karma preflight failed: {reports}")
            cameras.start()
            cameras.wait_ready()
            if args.astra_only:
                from .astra_actions import AstraActions

                planner = policy = AstraActions(settings, recorder, joint_limits(rig))
                recorder.event("controller", mode="astra_only", action_space="bounded_joint_delta")
            else:
                planner = (
                    BaselinePlanner(settings.limits.task_timeout_s)
                    if args.dream_only
                    else Astra(settings, recorder)
                    if hardware
                    else MockPlanner()
                )
                policy = Dream(settings, recorder) if hardware else MockPolicy()
            if hardware:
                policy.check_model()
            viewer = Viewer(
                rig,
                control,
                port=settings.port,
                hz=settings.viewer_hz,
                enabled=not args.no_viz,
                uncalibrated=hardware and args.zero_shot,
            )
            if control.stopping:
                return 130
            robot.connect()
            # Wait for fresh motor telemetry without sending any policy command.
            deadline = time.monotonic() + 3
            while True:
                try:
                    initial, _ = robot.read()
                    break
                except Exception:
                    if time.monotonic() >= deadline or control.stopping:
                        raise
                    time.sleep(0.02)
            collision = CollisionGuard(calibration, settings.limits, rig) if calibration else None
            if collision:
                collision.check(initial)
            guard = TrajectoryGuard(settings.limits, joint_limits(rig), collision)
            if args.shadow:
                robot = ShadowRobot(robot)
            runner = Runner(
                settings,
                control,
                robot,
                cameras,
                planner,
                policy,
                guard,
                recorder,
                viewer,
                hardware=hardware,
            )
            result = runner.run(args.prompt)
            print(json.dumps(dataclasses.asdict(result), indent=2))
            if viewer.error:
                print("Viewer warning:", viewer.error)
            return 1 if result.outcome == "failed" else 0
        finally:
            # Covers partial startup and exceptions before Runner owns the session.
            # Faults outside Runner close in place; normal Runner shutdown is idempotent.
            try:
                robot.close(park=False)
            finally:
                cameras.close()
                if viewer:
                    viewer.close()
                # Requests are daemon workers; do not wait on cloud shutdown before motors.
                for provider in (planner, policy):
                    if provider:
                        threading.Thread(
                            target=_close_provider, args=(provider,), daemon=True
                        ).start()
                try:
                    recorder.close()
                    if args.record:
                        from .dataset import export_v3

                        print(f"LeRobot v3: {export_v3(recorder.path)}", flush=True)
                finally:
                    from .episodes import catalog

                    print(f"Rollout catalog: {catalog(settings.run_dir)}", flush=True)


def _close_provider(provider):
    try:
        provider.close()
    except Exception:
        pass


class BaselinePlanner:
    display_name = "Dream-only baseline"
    continuous = True

    def __init__(self, duration):
        self.duration = duration

    def decide(self, prompt, observation, history):
        from .types import Decision

        return Decision(
            action="execute",
            subtasks=[prompt],
            active_subtask=prompt,
            instruction=prompt,
            explanation="Dream-only baseline; operator/count labels determine success",
            evidence="",
            outcome="in_progress",
            duration_s=min(15, self.duration),
            recovery=False,
        )

    def close(self):
        pass


class ShadowRobot:
    shadow = True

    def __init__(self, real):
        self.real = real

    def read(self):
        return self.real.read()

    def command(self, targets):
        pass

    def hold(self):
        return self.real.hold()

    def close(self, *, park=True):
        return self.real.close(park=park)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["--config", "config/local.json", "run", "--hardware", "--zero-shot"]
    args = parser().parse_args(argv)
    if getattr(args, "astra_only", False):
        args.dream_only = False
    try:
        settings = load_settings(args.config)
        if args.command == "recordings":
            from .rollout_viewer import serve

            return serve(settings.run_dir, args.host, args.port)
        if args.command == "karma":
            from openpi_control.cli import main as karma_main

            # This is a foreground operator command, never an Astra tool. Karma's
            # native ownership locks prevent a second process from owning live buses.
            return karma_main(args.arguments)
        if args.command == "init":
            path = Path(args.output)
            if path.exists():
                raise SpillError(f"Already exists: {path}")
            write_json(path, settings.model_dump())
            print(path)
            return 0
        if args.command == "doctor":
            return doctor(settings, args)
        if args.command == "calibrate":
            return calibrate(settings, args)
        if args.command == "run":
            return run(settings, args)
        if args.command == "report":
            from .recording import write_summary

            print(json.dumps(write_summary(run_path(settings, args.run_id)), indent=2))
            return 0
        if args.command == "catalog":
            from .episodes import catalog

            print(catalog(settings.run_dir))
            return 0
        if args.command == "export-v3":
            from .dataset import export_v3

            print(export_v3(run_path(settings, args.run_id)))
            return 0
        from .evaluation import evaluate, export_dataset, label, replay

        if args.command == "replay":
            return replay(run_path(settings, args.run_id), settings, args)
        if args.command == "evaluate":
            return evaluate(settings, args)
        if args.command == "label":
            return label(run_path(settings, args.run_id), args)
        if args.command == "export":
            return export_dataset(
                [run_path(settings, p) for p in args.run_ids],
                Path(args.output),
                args.include_failures,
            )
    except (SpillError, ValueError, OSError) as exc:
        print(f"spill: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
