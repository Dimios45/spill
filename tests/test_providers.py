import time
from types import SimpleNamespace

import numpy as np
import pytest

from spill.config import Settings
from spill.providers import Dream, normalize_dream_actions, planner_retryable
from spill.types import ARMS, CAMERAS, Frame, Observation, SafetyError


class Recorder:
    path = __import__("pathlib").Path("/tmp")

    def __init__(self):
        self.events = []

    def event(self, kind, **kw):
        self.events.append((kind, kw))

    def observation(self, *a, **kw):
        pass


class Client:
    last_timing = {"rtt_ms": 10}
    grippers = (1, 0)

    def policy(self, config):
        self.config = config

    def reset_episode(self):
        pass

    def set_observation(self, frames, state, **kwargs):
        self.frames, self.state = frames, state

    def get_models(self):
        return [SimpleNamespace(id="dreamlabs/dream-1")]

    def get_action(self, **kwargs):
        self.commanded = kwargs["commanded"]
        return {
            "q_l_chunk": np.tile([0.1, 1, 1, 0, 0, 0, self.grippers[0]], (3, 1)),
            "q_r_chunk": np.tile([0.2, 1, 1, 0, 0, 0, self.grippers[1]], (3, 1)),
        }


@pytest.mark.parametrize("grippers", [(1, 0), (1.02, -0.03)])
def test_dream_roles_gripper_and_chunk_mapping(grippers):
    client = Client()
    client.grippers = grippers
    recorder = Recorder()
    policy = Dream(Settings(), recorder, client=client)
    policy.check_model()
    policy.reset("pour", 0)
    now = time.monotonic()
    obs = Observation(
        1,
        0,
        now,
        {n: Frame(np.zeros((10, 10, 3), np.uint8), now, 1) for n in CAMERAS},
        {n: np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0]) for n in ARMS},
        {n: now for n in ARMS},
    )
    policy.feed(obs)
    chunk = policy.infer(obs, obs.joints)
    assert set(client.frames) == {"video.overhead", "video.wrist_l", "video.wrist_r"}
    assert client.state["state.left_gripper"][0] == 1
    assert client.state["state.left_arm"].dtype == np.float32
    assert "top-down gripper" in client.state["prompt"]
    assert chunk.arms["right"][0, -1] == 0
    assert chunk.arms["left"][0, -1] == 1
    assert chunk.arms["left"][0, 0] == 0.1
    assert client.config["strict"] is True
    raw = next(data for kind, data in recorder.events if kind == "dream_raw")
    assert raw["arms"]["left"][0][-1] == grippers[0]
    assert raw["arms"]["right"][0][-1] == grippers[1]


def test_old_generation_does_not_feed_new_episode():
    client = Client()
    policy = Dream(Settings(), Recorder(), client=client)
    policy.reset("new", 2)
    policy.feed(SimpleNamespace(generation=1))
    assert not hasattr(client, "frames")


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("column", [0, 6])
def test_dream_normalization_rejects_nonfinite(value, column):
    arms = {n: np.zeros((3, 7)) for n in ARMS}
    arms["left"][1, column] = value
    with pytest.raises(SafetyError, match=f"left: nonfinite action at row 1, column {column}"):
        normalize_dream_actions(arms)


def test_normalization_changes_only_gripper_and_preserves_input():
    arms = {n: np.full((3, 7), 2.0) for n in ARMS}
    result = normalize_dream_actions(arms)
    for n in ARMS:
        np.testing.assert_array_equal(result[n][:, :6], arms[n][:, :6])
        np.testing.assert_array_equal(result[n][:, 6], 1)
        np.testing.assert_array_equal(arms[n], 2)


@pytest.mark.parametrize("shape", [(7,), (3, 8), (0, 7), (257, 7)])
def test_normalization_rejects_wrong_shape(shape):
    with pytest.raises(SafetyError, match="expected"):
        normalize_dream_actions({n: np.zeros(shape) for n in ARMS})


def test_planner_retry_classification():
    import httpx
    from openai import APIStatusError, APITimeoutError

    request = httpx.Request("POST", "https://example.invalid")
    assert planner_retryable(APITimeoutError(request=request))
    for code in (400, 401, 403, 404, 408, 409, 429, 500, 503):
        error = APIStatusError(
            "test",
            response=httpx.Response(code, request=request),
            body=None,
        )
        assert planner_retryable(error) == (code in (408, 409, 429, 500, 503))
    assert not planner_retryable(ValueError("invalid decision"))
