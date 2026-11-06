import time
from types import SimpleNamespace

import numpy as np
import pytest

from spill.config import Limits
from spill.robot import KarmaRobot
from spill.types import FeedbackGap, SafetyError


@pytest.mark.parametrize("age,error_type", [(400, FeedbackGap), (1000, SafetyError)])
def test_stale_feedback_names_motor_and_retains_diagnostics(age, error_type):
    robot = KarmaRobot(None, Limits())
    for name in ("left", "right"):
        state = SimpleNamespace(
            is_fresh=lambda _: True,
            mode="hold",
            monotonic_timestamp=time.monotonic(),
            joints=SimpleNamespace(
                position_rad=np.zeros(6), frame_age_ms=np.ones(6), temperature_c=np.full(6, 25)
            ),
            effector=SimpleNamespace(
                position=1.0, frame_age_ms=age if name == "right" else 1, temperature_c=25
            ),
        )
        robot.entries.append(SimpleNamespace(name=name, arm=SimpleNamespace(latest_state=state)))
    with pytest.raises(
        error_type, match=f"right stale motor CAN feedback: gripper={age}.0ms"
    ) as caught:
        robot.read()
    assert type(caught.value) is error_type
    assert robot.telemetry_history[-1]["feedback_age_ms"][-1] == age
