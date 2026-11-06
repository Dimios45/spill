import argparse
import json

import numpy as np
import pandas as pd
import pytest

from spill.config import Settings, write_json
from spill.evaluation import evaluate, export_dataset, label
from spill.types import CAMERAS, SpillError


def make_recording(path, hardware=True):
    (path / "observations").mkdir(parents=True)
    events = [
        dict(
            kind="manifest",
            hardware=hardware,
            prompt="Pour pills",
            settings=Settings().model_dump(),
            timestamp=0,
        ),
        dict(kind="mode", shadow=False, dream_only=False, timestamp=0),
    ]
    for i in range(40):
        state = {
            "q_right": np.array([0.2, 1, 1, 0, 0, 0, 0.7]),
            "q_left": np.array([0.1, 1, 1, 0, 0, 0, 0.3]),
        }
        state.update({f"rgb_{n}": np.zeros((480, 848, 3), np.uint8) for n in CAMERAS})
        np.savez_compressed(path / "observations" / f"{i:08d}.npz", **state)
        events.append(
            dict(
                kind="command",
                timestamp=i / 20,
                observation_id=i,
                hz=20,
                arms={n: state["q_" + n].tolist() for n in ("left", "right")},
            )
        )
    events.append(
        dict(kind="result", interventions=0, outcome="unverified", elapsed_s=1, timestamp=1)
    )
    (path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    write_json(
        path / "human_label.json",
        dict(success=True, initial=10, target=10, residue=0, spilled=0, upright=True),
    )
    return events


def test_export_preserves_dream_right_first_and_native_opening(tmp_path):
    source = tmp_path / "run"
    make_recording(source)
    output = tmp_path / "dataset"
    export_dataset([source], output)
    rows = pd.read_parquet(output / "data/chunk-000/episode_000000.parquet")
    assert rows.iloc[0]["observation.state"][0] == pytest.approx(0.2)
    assert rows.iloc[0]["action"][6] == pytest.approx(0.7)
    assert rows.iloc[0]["action"][7] == pytest.approx(0.1)
    info = json.loads((output / "meta/info.json").read_text())
    assert info["codebase_version"] == "v2.1"
    assert info["total_frames"] == 20
    assert info["fps"] == 10
    assert len(list((output / "videos").rglob("*.mp4"))) == 3


def test_export_rejects_mock_and_timing_gap(tmp_path):
    source = tmp_path / "run"
    events = make_recording(source, hardware=False)
    with pytest.raises(SpillError, match="Mock"):
        export_dataset([source], tmp_path / "out")
    events[0]["hardware"] = True
    events[3]["timestamp"] = 0.2
    (source / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(SpillError, match="uniformly"):
        export_dataset([source], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_evaluation_excludes_mock(tmp_path, capsys):
    make_recording(tmp_path / "run", hardware=False)
    evaluate(
        Settings(run_dir=str(tmp_path)), argparse.Namespace(write_scenes=None, suite="cup-transfer")
    )
    report = json.loads(capsys.readouterr().out)
    assert report["astra_dream"]["trials"] == 0


def test_label_requires_conserved_count(tmp_path):
    args = argparse.Namespace(
        initial=10,
        target=10,
        residue=1,
        spilled=0,
        upright=True,
        collision=False,
        dropped_cup=False,
    )
    with pytest.raises(ValueError):
        label(tmp_path, args)
