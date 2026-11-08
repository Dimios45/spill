import threading
import time

import numpy as np

from spill.cameras import Cameras
from spill.config import Settings
from spill.control import Control
from spill.providers import MockPlanner, MockPolicy
from spill.recording import Recorder, read_events
from spill.robot import MockRobot
from spill.runtime import Runner
from spill.safety import TrajectoryGuard
from spill.types import ARMS
from spill.viewer import Viewer


def harness(tmp_path, policy=None, planner=None):
    settings = Settings(run_dir=str(tmp_path), execution_window_s=None)
    control = Control()
    robot = MockRobot()
    cameras = Cameras(settings.serials, mock=True)
    cameras.start()
    cameras.wait_ready()
    recorder = Recorder(tmp_path, settings, hardware=False, prompt="test")
    viewer = Viewer(None, control, enabled=False)
    guard = TrajectoryGuard(settings.limits, {n: (np.full(6, -3), np.full(6, 3)) for n in ARMS})
    runner = Runner(
        settings,
        control,
        robot,
        cameras,
        planner or MockPlanner(),
        policy or MockPolicy(),
        guard,
        recorder,
        viewer,
    )
    return runner


def cleanup(r):
    r.cameras.close()
    r.recorder.close()
    r.viewer.close()


def test_end_to_end_mock_is_not_claimed_success(tmp_path):
    r = harness(tmp_path)
    try:
        result = r.run("pour")
        assert result.outcome == "unverified"
        assert r.robot.closed and r.robot.parked
        assert len(r.robot.history) > 0
    finally:
        cleanup(r)
    events = list(read_events(r.recorder.path))
    assert any(e["kind"] == "command" for e in events)
    assert events[-1]["kind"] == "result"


def test_network_wait_does_not_consume_motion_budget(tmp_path):
    from spill.types import ActionChunk

    class SlowShortChunks(MockPolicy):
        calls = 0

        def infer(self, obs, commanded):
            self.calls += 1
            requested = time.monotonic()
            time.sleep(0.6)
            return ActionChunk(
                obs.id,
                obs.generation,
                requested,
                20,
                {n: np.tile(commanded[n], (10, 1)) for n in ARMS},
            )

    policy = SlowShortChunks()
    r = harness(tmp_path, policy=policy)
    try:
        r.run("test")  # MockPlanner requests one second of commanded motion.
        assert policy.calls == 2
        report = r.history[0]["report"]
        assert report["rows"] == 20
        assert abs(report["elapsed_s"] - 1) < 1e-6
        assert report["policy_wait_s"] >= 1.2
        assert report["wall_elapsed_s"] >= 2
    finally:
        cleanup(r)


def test_planner_timeout_retries_with_new_observation(tmp_path):
    import httpx
    from openai import APITimeoutError

    class Transient(MockPlanner):
        observations = []

        def decide(self, prompt, observation, history):
            self.observations.append(observation.id)
            if len(self.observations) == 1:
                raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
            return super().decide(prompt, observation, history)

    planner = Transient()
    r = harness(tmp_path, planner=planner)
    r.settings.planner_retry_delay_s = 0.1
    try:
        result = r.run("test")
        assert result.reason != "Hold timeout"
        assert planner.observations[1] > planner.observations[0]
        assert r.robot.history
    finally:
        cleanup(r)
    events = list(read_events(r.recorder.path))
    assert sum(e["kind"] == "planner_retry" for e in events) == 1
    assert (r.recorder.path / "summary.json").exists()


def test_planner_timeout_retry_budget_is_finite(tmp_path):
    import httpx
    from openai import APITimeoutError

    class Unavailable(MockPlanner):
        def decide(self, *args):
            self.calls += 1
            raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))

    planner = Unavailable()
    r = harness(tmp_path, planner=planner)
    r.settings.planner_retry_delay_s = 0
    r.settings.limits.hold_timeout_s = 0.05
    try:
        r.run("test")
        assert planner.calls == 3  # Initial attempt plus two retries.
        assert not r.robot.history
    finally:
        cleanup(r)


def test_stop_does_not_wait_for_cloud(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class Slow(MockPlanner):
        def decide(self, *args):
            started.set()
            release.wait(3)
            return super().decide(*args)

    r = harness(tmp_path, planner=Slow())

    def stop():
        assert started.wait(2)
        r.control.stop()

    t = threading.Thread(target=stop)
    t.start()
    before = time.monotonic()
    try:
        r.run("test")
        assert time.monotonic() - before < 1
        assert r.robot.closed and not r.robot.history
    finally:
        release.set()
        t.join()
        cleanup(r)


def test_pause_discards_late_motion(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class Slow(MockPolicy):
        def infer(self, *args):
            entered.set()
            release.wait(2)
            return super().infer(*args)

    r = harness(tmp_path, policy=Slow())

    def pause_stop():
        assert entered.wait(2)
        r.control.pause()
        release.set()
        time.sleep(0.1)
        r.control.stop()

    t = threading.Thread(target=pause_stop)
    t.start()
    try:
        r.run("test")
        assert not r.robot.history
        assert r.robot.closed
    finally:
        release.set()
        t.join()
        cleanup(r)


def test_camera_failure_stops_in_place(tmp_path):
    r = harness(tmp_path)

    def fail():
        time.sleep(0.1)
        r.cameras.error = "camera unplugged"

    t = threading.Thread(target=fail)
    t.start()
    try:
        result = r.run("test")
        assert result.outcome == "failed"
        assert not r.robot.parked
    finally:
        t.join()
        cleanup(r)


def test_transient_motor_gap_inhibits_commands_and_replans(tmp_path):
    from spill.types import FeedbackGap

    r = harness(tmp_path)
    original_read = r.robot.read
    started = time.monotonic()

    def read():
        elapsed = time.monotonic() - started
        if 0.15 <= elapsed < 0.4:
            assert not r.robot.closed
            raise FeedbackGap("test transient motor gap")
        return original_read()

    r.robot.read = read
    try:
        result = r.run("test")
        assert result.outcome != "failed"
        assert r.robot.parked
    finally:
        cleanup(r)
    events = list(read_events(r.recorder.path))
    gap = next(e["timestamp"] for e in events if e["kind"] == "feedback_gap")
    recovered = next(e["timestamp"] for e in events if e["kind"] == "feedback_recovered")
    assert not any(e["kind"] == "command" and gap <= e["timestamp"] <= recovered for e in events)
    assert any(e["kind"] == "control" for e in events)


def test_sustained_motor_gap_still_shuts_down_in_place(tmp_path):
    from spill.types import FeedbackGap

    r = harness(tmp_path)
    original_read = r.robot.read
    started = time.monotonic()

    def read():
        if time.monotonic() - started >= 0.1:
            raise FeedbackGap("test sustained motor gap")
        return original_read()

    r.robot.read = read
    try:
        result = r.run("test")
        assert result.outcome == "failed"
        assert "grace" in result.reason
        assert r.robot.closed and not r.robot.parked
    finally:
        cleanup(r)


def test_stop_during_feedback_gap_does_not_attempt_home(tmp_path):
    from spill.types import FeedbackGap

    r = harness(tmp_path)
    original_read = r.robot.read
    started = time.monotonic()

    def read():
        if time.monotonic() - started >= 0.1:
            raise FeedbackGap("gap during cancellation")
        return original_read()

    def stop():
        deadline = time.monotonic() + 2
        while r.feedback_gap is None and time.monotonic() < deadline:
            time.sleep(0.01)
        r.control.interrupt()

    r.robot.read = read
    stopper = threading.Thread(target=stop)
    stopper.start()
    try:
        r.run("test")
        assert r.robot.closed and not r.robot.parked
    finally:
        stopper.join()
        cleanup(r)


def test_real_sigint_to_mock_process_parks_and_exits(tmp_path):
    import os
    import signal
    import subprocess
    import sys

    p = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "spill.cli",
            "run",
            "test",
            "--dream-only",
            "--no-viz",
            "--no-record",
            "--seconds",
            "30",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Wait until command execution is recorded, not merely until Python starts.
        deadline = time.monotonic() + 8
        events = []
        while time.monotonic() < deadline:
            files = list(tmp_path.glob("runs/*/events.jsonl"))
            if files:
                events = list(read_events(files[0].parent))
                if any(e["kind"] == "command" for e in events):
                    break
            time.sleep(0.03)
        assert any(e["kind"] == "command" for e in events)
        os.kill(p.pid, signal.SIGINT)
        stdout, _ = p.communicate(timeout=3)
        assert p.returncode == 0, stdout
        final = list(read_events(files[0].parent))[-1]
        assert final["kind"] == "result"
        assert final["hardware"] is False
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_observation_pause_explains_uncertainty_and_resume_resets_budget(tmp_path, capsys):
    class Inspect(MockPlanner):
        def __init__(self):
            super().__init__()
            self.histories = []

        def decide(self, prompt, observation, history):
            self.histories.append(list(history))
            return super().decide(prompt, observation, history).model_copy(update={
                "action": "observe", "explanation": "Contact is occluded",
                "evidence": "Rim hidden by gripper",
            })

    planner = Inspect()
    r = harness(tmp_path, planner=planner)
    r.settings.limits.task_timeout_s = 5
    counts = []

    def operator():
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if r.control.paused:
                counts.append(planner.calls)
                if len(counts) == 1:
                    r.control.resume()
                else:
                    r.control.stop()
                    return
            time.sleep(0.005)
        r.control.stop()

    thread = threading.Thread(target=operator)
    thread.start()
    try:
        r.run("inspect")
        assert counts == [3, 6]
        assert not r.robot.history
        assert planner.histories[1][-1]["motion_executed"] is False
    finally:
        thread.join()
        cleanup(r)
    output = capsys.readouterr().out
    assert "Reason: Contact is occluded" in output
    assert "Evidence: Rim hidden by gripper" in output
    events = list(read_events(r.recorder.path))
    assert [e["count"] for e in events if e["kind"] == "observation_wait"] == [1, 2, 3, 1, 2, 3]


def test_configured_window_overrides_short_planner_duration(tmp_path):
    r = harness(tmp_path)
    r.settings.execution_window_s = 2
    assert Settings().execution_window_s == 20
    try:
        r.run("test")  # MockPlanner requests only one second.
        report = r.history[0]["report"]
        assert report["elapsed_s"] >= 2 - 1e-9
        assert report["chunks"] > 1
    finally:
        cleanup(r)
    events = list(read_events(r.recorder.path))
    window = next(e for e in events if e["kind"] == "execution_window")
    assert window["requested_s"] == 1
    assert window["effective_s"] == 2


def test_recovery_uses_seven_second_window_instead_of_twenty(tmp_path):
    class RecoveryPlanner(MockPlanner):
        def decide(self, *args):
            return super().decide(*args).model_copy(update={"recovery": True})

    r = harness(tmp_path, planner=RecoveryPlanner())
    r.settings.execution_window_s = 20
    try:
        r.run("recover")
        report = r.history[0]["report"]
        assert 7 - 1e-9 <= report["elapsed_s"] < 8
    finally:
        cleanup(r)
    events = list(read_events(r.recorder.path))
    window = next(e for e in events if e["kind"] == "execution_window")
    assert window["effective_s"] == 7
    assert window["recovery"] is True


def test_delayed_acquisition_discards_snapshot_and_pauses(tmp_path):
    r = harness(tmp_path)
    original = r.robot.read
    calls = []

    def delayed():
        value = original()
        calls.append(value[1])
        if len(calls) == 1:
            time.sleep(0.13)
        return value

    r.robot.read = delayed
    try:
        obs = r._capture_observation()
        obs.validate()
        assert len(calls) == 2
        assert obs.state_times == calls[1]
        assert r.control.paused
        assert not r.robot.history
    finally:
        cleanup(r)


def test_repeated_acquisition_delay_fails_closed(tmp_path):
    import pytest

    from spill.types import SafetyError

    r = harness(tmp_path)
    original = r.robot.read

    def delayed():
        value = original()
        time.sleep(0.13)
        return value

    r.robot.read = delayed
    try:
        with pytest.raises(SafetyError, match="delayed twice"):
            r._capture_observation()
        assert not r.robot.history
    finally:
        cleanup(r)


def test_skew_fault_homes_only_with_healthy_motor_feedback(tmp_path):
    from spill.types import ObservationSkewError, SafetyError

    for healthy in (True, False):
        r = harness(tmp_path)
        reads = r.robot.read
        calls = 0

        def read():
            nonlocal calls
            calls += 1
            if not healthy and calls > 1:
                raise SafetyError("motor feedback lost")
            return reads()

        r.robot.read = read
        r._observe = lambda: None
        r.snapshot = lambda: (_ for _ in ()).throw(ObservationSkewError("test skew"))
        try:
            result = r.run("test")
            assert result.outcome == "failed"
            assert r.robot.parked is healthy
        finally:
            cleanup(r)




def test_dream_only_checkpoints_keep_same_session(tmp_path):
    from spill.cli import BaselinePlanner

    class CountingPolicy(MockPolicy):
        resets = 0

        def reset(self, *args):
            self.resets += 1
            super().reset(*args)

    policy = CountingPolicy()
    r = harness(tmp_path, planner=BaselinePlanner(3), policy=policy)
    r.settings.execution_window_s = 1
    r.settings.limits.task_timeout_s = 3
    try:
        r.run("test")
        assert policy.resets == 1
    finally:
        cleanup(r)
    assert any(e['kind'] == 'policy_session_continued' for e in read_events(r.recorder.path))
