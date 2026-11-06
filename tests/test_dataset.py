import json

import numpy as np
import pytest

from spill.dataset import export_v3, sampled_segments
from spill.types import ARMS, CAMERAS, SpillError


def test_sample_gaps_split_episodes_and_use_causal_observations():
    events = [
        dict(kind="dataset_sample", timestamp=t, sampled_at=t, observation_id=i)
        for i, t in enumerate([1.0, 1.034, 1.067, 1.1, 2.0, 2.1])
    ]
    source, segments = sampled_segments(events)
    assert source == "observer_samples"
    assert len(segments) == 2
    assert [r[2]["observation_id"] for r in segments[0]] == [0, 1, 3]
    assert all(t >= sample - 1e-8 for rows in segments for t, sample, _ in rows)


def test_real_karma_v3_sink(tmp_path):
    import pyarrow.parquet as pq

    root = tmp_path / "run"
    (root / "observations").mkdir(parents=True)
    events = [dict(kind="manifest", timestamp=0, hardware=False, prompt="mock top-down grasp")]
    for i in range(5):
        state = {f"q_{n}": np.r_[np.zeros(6), 1.0] for n in ARMS}
        images = {f"rgb_{n}": np.zeros((64, 64, 3), dtype=np.uint8) for n in CAMERAS}
        np.savez(root / "observations" / f"{i:08d}.npz", **state, **images)
        events.append(
            dict(
                kind="dataset_sample",
                timestamp=1 + i * 0.05,
                observation_id=i,
                arms={n: [0] * 6 + [0.25] for n in ARMS},
            )
        )
    events.append(dict(kind="result", timestamp=2, outcome="failed", reason="test fault"))
    (root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    target = export_v3(root)
    info = json.loads((target / "meta/info.json").read_text())
    assert info["codebase_version"] == "v3.0"
    assert info["total_frames"] == 5
    meta = json.loads((target / "spill_rollout.json").read_text())
    assert meta["outcome"] == "failed" and not meta["success_verified"]
    assert meta["complete"] and not meta["hardware"]
    table = pq.read_table(next((target / "data").rglob("*.parquet"))).to_pydict()
    assert table["observation.state"][0][6] == 0  # Karma dataset polarity.
    assert table["action"][0][13] == 0.75
    assert len(list((target / "videos").rglob("*.mp4"))) == 3
    with pytest.raises(SpillError, match="overwrite"):
        export_v3(root)
