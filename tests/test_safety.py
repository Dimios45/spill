import dataclasses
import time
from types import SimpleNamespace

import numpy as np
import pytest

from spill.config import Calibration, Limits, Settings, calibration_template
from spill.control import Control
from spill.geometry import CollisionGuard, segment_distance
from spill.robot import MockRobot, make_rig
from spill.safety import TrajectoryGuard
from spill.types import ARMS, CAMERAS, ActionChunk, Frame, Observation, SafetyError


def observation():
    now = time.monotonic()
    return Observation(
        1,
        0,
        now,
        {n: Frame(np.zeros((8, 8, 3), np.uint8), now, 1) for n in CAMERAS},
        {n: np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0]) for n in ARMS},
        {n: now for n in ARMS},
    )


def guard():
    return TrajectoryGuard(Limits(), {n: (np.full(6, -3.0), np.full(6, 3.0)) for n in ARMS})


def chunk(obs):
    return ActionChunk(
        obs.id,
        obs.generation,
        time.monotonic(),
        20,
        {n: np.tile(q, (3, 1)) for n, q in obs.joints.items()},
    )


@pytest.mark.parametrize("bad", ["stale", "missing", "skew", "nan", "future", "gripper"])
def test_observation_rejects_bad_inputs(bad):
    o = observation()
    if bad == "stale":
        o.frames["top"] = dataclasses.replace(o.frames["top"], captured_at=time.monotonic() - 1)
    if bad == "missing":
        del o.frames["left_wrist"]
    if bad == "skew":
        o.frames["top"] = dataclasses.replace(o.frames["top"], captured_at=time.monotonic() - 0.2)
    if bad == "nan":
        o.joints["left"][0] = np.nan
    if bad == "future":
        o.state_times["right"] = time.monotonic() + 1
    if bad == "gripper":
        o.joints["left"][-1] = -1
    with pytest.raises(SafetyError):
        o.validate()


@pytest.mark.parametrize(
    "bad", ["nan", "shape", "gripper", "limits", "velocity", "acceleration", "expired"]
)
def test_rejects_unsafe_chunk(bad):
    o = observation()
    c = chunk(o)
    if bad == "nan":
        c.arms["left"][0, 0] = np.nan
    if bad == "shape":
        c.arms["left"] = np.zeros((4, 7))
    if bad == "gripper":
        c.arms["left"][0, -1] = 2
    if bad == "limits":
        c.arms["left"][0, 0] = 4
    if bad == "velocity":
        c.arms["left"][0, 0] = 0.1
    if bad == "acceleration":
        c.arms["left"][0, 0] = 0.01
    if bad == "expired":
        c = dataclasses.replace(c, requested_at=time.monotonic() - Limits().max_chunk_age_s - 1)
    with pytest.raises(SafetyError):
        guard().chunk(c, o.joints)


def test_tracking_error():
    o = observation()
    previous = {n: q.copy() for n, q in o.joints.items()}
    previous["left"][0] += 0.3
    with pytest.raises(SafetyError, match="tracking"):
        guard().step(previous, previous, o.joints, 0.05)


def test_bounded_prediction_preserves_guards_at_joint_boundary():
    g = guard()
    start = {n: np.r_[np.full(6, 2.99), 0.5] for n in ARMS}
    actions = {n: np.tile(np.r_[np.full(6, 8.0), 1.0], (48, 1)) for n in ARMS}
    raw = ActionChunk(1, 0, time.monotonic() - 4.5, 20, actions)
    bounded = g.prepare(raw, start)
    assert bounded.requested_at == raw.requested_at
    assert bounded.length == raw.length
    previous = start
    for i in range(bounded.length):
        target = {n: a[i] for n, a in bounded.arms.items()}
        g.step(target, previous, previous, 1 / bounded.hz)
        previous = target
    for n in ARMS:
        assert np.max(bounded.arms[n][:, :6]) <= 3
        assert np.any(bounded.arms[n][:, :6] > start[n][:6])
        np.testing.assert_allclose(g.velocity[n], 0, atol=1e-9)
        np.testing.assert_array_equal(raw.arms[n][:, 0], 8)


def test_bounded_prediction_still_rejects_expired_input():
    o = observation()
    old = dataclasses.replace(
        chunk(o), requested_at=time.monotonic() - Limits().max_chunk_age_s - 1
    )
    with pytest.raises(SafetyError, match="expired"):
        guard().prepare(old, o.joints)


def test_bounded_prediction_keeps_collision_checks():
    class Collision:
        def swept(self, *args):
            raise SafetyError("test obstacle")

    o = observation()
    g = guard()
    g.collision = Collision()
    with pytest.raises(SafetyError, match="test obstacle"):
        g.prepare(chunk(o), o.joints)


def test_bounded_prediction_rejects_infeasible_start():
    o = observation()
    o.joints["left"][0] = 4
    with pytest.raises(SafetyError, match="no bounded motion"):
        guard().prepare(chunk(o), o.joints)


def test_bounded_prediction_never_repairs_nonfinite_actions():
    o = observation()
    c = chunk(o)
    c.arms["left"][0, 0] = np.nan
    with pytest.raises(SafetyError, match="nonfinite"):
        guard().prepare(c, o.joints)


def test_small_outside_start_recovers_without_acceleration_jump():
    g = guard()
    start = {n: np.r_[np.full(6, -3.004768), 1.0] for n in ARMS}
    raw = ActionChunk(
        1,
        0,
        time.monotonic(),
        20,
        {n: np.tile(np.r_[np.full(6, -3.1), 1.0], (48, 1)) for n in ARMS},
    )
    bounded = g.prepare(raw, start)
    previous = start
    for i in range(bounded.length):
        target = {n: a[i] for n, a in bounded.arms.items()}
        g.step(target, previous, previous, 0.05)
        previous = target
    for n in ARMS:
        assert bounded.arms[n][0, 0] < -3  # No illegal one-tick acceleration.
        assert bounded.arms[n][-1, 0] >= -3
        assert np.all(np.diff(bounded.arms[n][:, 0]) >= -1e-9)


def test_boundary_recovery_never_allows_moving_further_out():
    g = guard()
    previous = {n: np.r_[np.full(6, -3.004), 1.0] for n in ARMS}
    target = {n: q.copy() for n, q in previous.items()}
    target["right"][0] -= 0.0001
    with pytest.raises(SafetyError, match="joint limit"):
        g.step(target, previous, previous, 0.05)


def test_valid_hold_and_gripper_polarity():
    o = observation()
    guard().chunk(chunk(o), o.joints)
    assert o.joints["left"][-1] == 1


def test_cancellation_invalidates_generations_and_never_resumes_stop():
    c = Control()
    g = c.generation
    c.pause()
    assert not c.permits(g)
    c.resume()
    assert not c.permits(g)
    assert c.permits(c.generation)
    c.stop()
    c.resume()
    assert not c.permits(c.generation)


def test_ctrl_c_semantics():
    c = Control()
    c.interrupt()
    assert c.stopping and c.park
    c.parking = True
    with pytest.raises(KeyboardInterrupt):
        c.interrupt()


def test_repeated_interrupt_before_parking_requests_immediate_close():
    c = Control()
    c.interrupt()
    c.interrupt()
    assert not c.park


def test_mock_forbids_commands_after_close():
    robot = MockRobot()
    q, _ = robot.read()
    robot.close()
    with pytest.raises(SafetyError):
        robot.command(q)


def test_segment_distance_degenerate_parallel_crossing():
    def v(x):
        return np.array(x, dtype=float)

    assert segment_distance(
        v([0, 0, 0]), v([1, 0, 0]), v([0.5, -1, 0]), v([0.5, 1, 0])
    ) == pytest.approx(0)
    assert segment_distance(
        v([0, 0, 0]), v([1, 0, 0]), v([0, 1, 0]), v([1, 1, 0])
    ) == pytest.approx(1)
    assert segment_distance(
        v([0, 0, 0]), v([0, 0, 0]), v([1, 0, 0]), v([2, 0, 0])
    ) == pytest.approx(1)


def test_calibration_requires_rigid_transforms():
    template = calibration_template(Settings())
    template["world_from_base"]["left"][0][0] = 2
    with pytest.raises(ValueError):
        Calibration.model_validate(template)


def test_interarm_collision_and_sweep():
    config = Settings()
    c = Calibration.model_validate(calibration_template(config))
    guard = CollisionGuard(c, config.limits, make_rig(config))
    # Isolate inter-arm behavior from model geometry with separated synthetic segments.
    guard.points = lambda name, q: np.array([[0, 0, 1.0], [0.1, 0, 1.0]])
    with pytest.raises(SafetyError, match="Inter-arm"):
        guard.check({n: np.zeros(7) for n in ARMS})
    seen = []
    guard.check = lambda q: seen.append(q)
    a = {n: np.zeros(7) for n in ARMS}
    b = {n: np.full(7, 0.1) for n in ARMS}
    guard.swept(a, b)
    assert len(seen) >= 6


def test_karma_shutdown_failure_still_closes_other_arm_and_session(monkeypatch):
    from openpi_control.cli import power_down

    calls = []

    class Arm:
        capabilities = SimpleNamespace(supports_move_to_ready=True)

        def __init__(self, name):
            self.name = name

        def close(self, **kwargs):
            calls.append(self.name)
            if self.name == "left":
                raise RuntimeError("fault")

    entries = [SimpleNamespace(name=n, arm=Arm(n)) for n in ARMS]
    session = SimpleNamespace(close=lambda: calls.append("session"))
    assert power_down(session, entries) == 1
    assert calls == ["left", "right", "session"]


def test_second_interrupt_in_karma_shutdown_still_closes_session():
    from openpi_control.cli import power_down

    calls = []

    def interrupt(**kwargs):
        raise KeyboardInterrupt

    entries = [
        SimpleNamespace(
            name="left",
            arm=SimpleNamespace(
                capabilities=SimpleNamespace(supports_move_to_ready=True), close=interrupt
            ),
        )
    ]
    assert power_down(SimpleNamespace(close=lambda: calls.append("closed")), entries) == 1
    assert calls == ["closed"]


def test_hold_keeps_commanded_grip_despite_measured_deflection():
    from spill.robot import KarmaRobot

    robot = KarmaRobot.__new__(KarmaRobot)
    measured = {n: np.array([0.0, 1, 1, 0, 0, 0, 0.45]) for n in ARMS}
    robot.last = {n: np.array([0.0, 1, 1, 0, 0, 0, 0.1]) for n in ARMS}
    robot.read = lambda: (measured, {})
    sent = []
    robot.command = lambda targets: sent.append(targets)
    result = robot.hold()
    assert result["left"][-1] == 0.1
    assert sent[0]["right"][-1] == 0.1


def test_karma_adapter_reads_property_and_checks_hardware_feedback_age():
    from openpi_control.types import ArmMode, ArmRole, ArmState, EffectorState, JointState

    from spill.robot import KarmaRobot

    now = time.monotonic()
    joints = JointState(
        tuple(f"joint{i}" for i in range(6)),
        np.array([0.0, 1, 1, 0, 0, 0]),
        np.zeros(6),
        np.zeros(6),
        np.full(6, 25.0),
        np.zeros(6),
        frame_age_ms=np.zeros(6),
    )

    def state(name, joint=joints):
        return ArmState(
            name, ArmRole.FOLLOWER, joint, EffectorState(0.5), now, time.time(), 1, ArmMode.HOLD
        )

    robot = KarmaRobot(None, Limits())
    robot.entries = [
        SimpleNamespace(name=n, arm=SimpleNamespace(latest_state=state(n))) for n in ARMS
    ]
    values, times = robot.read()
    assert values["left"].shape == (7,)
    assert times["right"] == now
    stale = dataclasses.replace(joints, frame_age_ms=np.full(6, 500.0))
    robot.entries[0].arm.latest_state = state("left", stale)
    with pytest.raises(SafetyError, match="CAN feedback"):
        robot.read()


def test_repeated_interrupts_do_not_abandon_final_cleanup():
    c = Control()
    c.parking = True
    with pytest.raises(KeyboardInterrupt):
        c.interrupt()
    c.interrupt()  # third and subsequent Ctrl+C cannot bypass de-energization
