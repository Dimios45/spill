import time
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from spill.astra_actions import ActionDecision, AstraActions
from spill.config import Settings
from spill.types import ARMS, CAMERAS, Frame, Observation, SafetyError


def decision(action="execute"):
    return ActionDecision(
        action=action, subtasks=["move"], active_subtask="move", instruction="small adjustment",
        explanation="test", evidence="test", outcome="in_progress", duration_s=2, recovery=False,
        moves=[dict(arm="left", joint_delta_rad=[0.05, 0, 0, 0, 0, 0], gripper_delta=-0.05)]
        if action == "execute" else [],
    )


class Recorder:
    def __init__(self):
        self.events = []

    def event(self, kind, **data):
        self.events.append((kind, data))

    def observation(self, *args, **kwargs):
        pass


class Client:
    def __init__(self):
        self.responses = self
        self.closed = 0
        self.calls = 0

    def parse(self, **kwargs):
        self.calls += 1
        self.request = kwargs
        d = decision("execute" if self.calls == 1 else "finish")
        return SimpleNamespace(output_parsed=d, usage=None, model_dump=lambda **_: d.model_dump())

    def close(self):
        self.closed += 1


def setup():
    now = time.monotonic()
    obs = Observation(1, 0, now,
                      {n: Frame(np.zeros((8, 8, 3), dtype=np.uint8), now, 1) for n in CAMERAS},
                      {n: np.array([0., 0., 0., 0., 0., 0., 1.]) for n in ARMS},
                      {n: now for n in ARMS})
    provider = AstraActions(Settings(), Recorder(),
                            {n: (np.full(6, -3.), np.full(6, 3.)) for n in ARMS}, client=Client())
    return provider, obs


def test_single_action_preserves_other_arm_and_original_timestamp():
    p, obs = setup()
    d = p.decide("test", obs, [])
    p.reset(d.instruction, 0)
    chunk = p.infer(obs, obs.joints)
    assert chunk.length == 40 and chunk.hz == 20
    assert chunk.requested_at == obs.timestamp
    np.testing.assert_array_equal(chunk.arms['right'], np.tile(obs.joints['right'], (40, 1)))
    assert chunk.arms['left'][-1, 0] == pytest.approx(.05)
    with pytest.raises(SafetyError, match="consumed"):
        p.infer(obs, obs.joints)
    p.close()
    p.close()
    assert p.client.closed == 1


@pytest.mark.parametrize('bad', ['duplicate', 'large', 'nan', 'pause_motion'])
def test_action_schema_rejects_invalid_motion(bad):
    d = decision().model_dump()
    if bad == 'duplicate':
        d['moves'] *= 2
    if bad == 'large':
        d['moves'][0]['joint_delta_rad'][0] = .5
    if bad == 'nan':
        d['moves'][0]['joint_delta_rad'][0] = float('nan')
    if bad == 'pause_motion':
        d['action'] = 'pause'
    with pytest.raises(ValidationError):
        ActionDecision.model_validate(d)


def test_joint_limit_rejection():
    p, obs = setup()
    obs.joints['left'][0] = 2.99
    with pytest.raises(SafetyError, match="limits"):
        p.decide("test", obs, [])


def test_motion_during_planning_rejects_old_action():
    p, obs = setup()
    p.decide("test", obs, [])
    p.reset("test", 0)
    commanded = {n: q.copy() for n, q in obs.joints.items()}
    commanded['left'][0] += .04
    with pytest.raises(SafetyError, match="anchor"):
        p.infer(obs, commanded)


def test_cancelled_generation_cannot_execute():
    p, obs = setup()
    p.decide("test", obs, [])
    p.reset("test", 1)
    with pytest.raises(SafetyError, match="generation"):
        p.infer(obs, obs.joints)


def test_cli_modes_are_mutually_exclusive():
    from spill.cli import parser
    with pytest.raises(SystemExit):
        parser().parse_args(['run', '--astra-only', '--dream-only'])
