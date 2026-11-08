import json

from spill.episodes import catalog, document_episode, reference_context


def test_catalog_preserves_damaged_sources_and_indexes_model_io(tmp_path):
    run = tmp_path / "trial"
    run.mkdir()
    text = (
        "\n".join(
            json.dumps(e)
            for e in [
                dict(kind="manifest", prompt="Move the object", hardware=True, settings={}),
                dict(kind="astra_request", observation_id=2),
                dict(kind="dream_raw", observation_id=3, arms={}),
                dict(kind="decision", action="pause", explanation="deformed object"),
            ]
        )
        + "\n{damaged"
    )
    (run / "events.jsonl").write_text(text)
    dataset = run / "lerobot_v3/meta"
    dataset.mkdir(parents=True)
    (dataset / "info.json").write_text("")
    (run / "operator_notes.json").write_text(json.dumps(["Object was pinched closed"]))
    entry = document_episode(run)
    assert entry["incomplete_log"] and entry["invalid_event_lines"] == [5]
    assert entry["dataset_id"] is None
    assert (run / "events.jsonl").read_text() == text
    io = json.loads((run / "model_io_index.json").read_text())
    assert [e["line"] for e in io] == [2, 3]
    reference = reference_context(run)
    assert reference["operator_notes"] == ["Object was pinched closed"]
    assert "arms" not in reference and "models" not in reference
    assert catalog(tmp_path).exists()
