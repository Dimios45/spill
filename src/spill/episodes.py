"""Local episode catalog and explicit, non-executable reference context."""

import json
from pathlib import Path


def document_episode(path):
    path = Path(path)
    events_path = path / "events.jsonl"
    manifest, result, decisions, io, errors = {}, None, [], [], []
    counts = {}
    # Preserve incomplete files and mark damaged lines; never rewrite source logs.
    with events_path.open() as source:
        for number, line in enumerate(source, 1):
            try:
                e = json.loads(line)
            except ValueError:
                errors.append(number)
                continue
            kind = e.get("kind", "unknown")
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "manifest":
                manifest = e
            if kind == "result":
                result = {k: e[k] for k in ("outcome", "reason", "elapsed_s")}
            if kind == "decision":
                decisions.append(
                    {
                        k: e.get(k)
                        for k in ("action", "instruction", "explanation", "evidence", "outcome")
                    }
                )
            if kind.startswith(("astra", "dream")):
                io.append(dict(line=number, kind=kind, observation_id=e.get("observation_id")))
    dataset = path / "lerobot_v3"
    info = {}
    if (dataset / "meta/info.json").exists():
        try:
            info = json.loads((dataset / "meta/info.json").read_text())
        except ValueError:
            info = {"error": "invalid or incomplete dataset metadata"}
    notes_path = path / "operator_notes.json"
    notes = json.loads(notes_path.read_text()) if notes_path.exists() else []
    entry = dict(
        run_id=path.name,
        task=manifest.get("prompt"),
        hardware=manifest.get("hardware"),
        models={k: manifest.get("settings", {}).get(k) for k in ("model", "dream")},
        dataset_id=f"local/{path.name}" if info.get("codebase_version") else None,
        dataset_path=str(dataset.resolve()) if dataset.exists() else None,
        dataset_info=info,
        result=result,
        incomplete_log=bool(errors) or result is None,
        invalid_event_lines=errors,
        event_counts=counts,
        decisions=decisions,
        operator_notes=notes,
        event_log=str(events_path.resolve()),
    )
    (path / "episode.json").write_text(json.dumps(entry, indent=2) + "\n")
    (path / "model_io_index.json").write_text(json.dumps(io, indent=2) + "\n")
    lines = [
        f"# Rollout {path.name}",
        "",
        f"Task: {entry['task']}",
        "",
        f"Dataset ID: {entry['dataset_id'] or 'not available'}",
        f"Dataset frames: {info.get('total_frames', 'not established')}",
        f"Result: {result}",
        f"Incomplete log: {entry['incomplete_log']}",
        "",
        "[Full event/API log](events.jsonl) · [Model I/O line index](model_io_index.json)",
        "",
        "## Decisions",
        "",
    ]
    for i, d in enumerate(decisions, 1):
        lines += [
            f"{i}. **{d['action']}**: {d['instruction']}",
            f"   Assessment: {d['explanation']}",
            "",
        ]
    lines += [
        "## Operator notes",
        "",
        *[f"- {note}" for note in notes],
        "",
        "Historical assessments are evidence for review, not verified grasp or transfer labels.",
    ]
    (path / "episode.md").write_text("\n".join(lines) + "\n")
    return entry


def catalog(root):
    root = Path(root)
    entries = [document_episode(p.parent) for p in sorted(root.glob("*/events.jsonl"))]
    (root / "catalog.json").write_text(json.dumps(entries, indent=2) + "\n")
    lines = [
        "# Local rollout catalog",
        "",
        "No data is uploaded. Incomplete runs remain marked.",
        "",
    ]
    for e in entries:
        task = str(e["task"]).replace("\n", " ")
        lines += [
            f"- [{e['run_id']}]({e['run_id']}/episode.md): {task}",
            f"  Dataset: `{e['dataset_id'] or 'not available'}`; "
            f"result: {(e['result'] or {}).get('outcome', 'incomplete')}",
        ]
    (root / "catalog.md").write_text("\n".join(lines) + "\n")
    return root / "catalog.md"


def reference_context(path):
    episode = document_episode(path)
    return {
        k: episode[k]
        for k in ("run_id", "task", "result", "incomplete_log", "operator_notes", "decisions")
    }
