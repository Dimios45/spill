import pytest

from spill.cli import parser, task_prompt
from spill.config import Settings, run_calibration
from spill.control import Control


def test_zero_shot_needs_no_calibration_file_or_attestation(tmp_path):
    settings = Settings(
        calibration=str(tmp_path / "absent.json"),
        serials={
            "top": "348523020354",
            "left_wrist": "254623070863",
            "right_wrist": "254623070417",
        },
    )
    assert not settings.dream.verified
    assert run_calibration(settings, hardware=True, zero_shot=True) is None
    # Opting into zero-shot does not weaken the calibrated path.
    with pytest.raises(FileNotFoundError):
        run_calibration(settings, hardware=True, zero_shot=False)


def test_zero_shot_rejects_device_placeholders():
    with pytest.raises(ValueError, match="serial placeholders"):
        run_calibration(Settings(), hardware=True, zero_shot=True)


def test_zero_shot_does_not_imply_hardware_or_disable_parking():
    args = parser().parse_args(["run", "Pour", "--zero-shot"])
    assert not args.hardware and not args.shadow and not args.no_park
    control = Control(park=not args.no_park)
    control.interrupt()
    assert control.stopping and control.park
    control.interrupt()
    assert not control.park


def test_doctor_zero_shot_flag():
    assert parser().parse_args(["doctor", "--zero-shot"]).zero_shot


def test_default_task_record_and_no_grasp_override():
    from spill.defaults import DEFAULT_PROMPT

    args = parser().parse_args(["run", "--hardware", "--zero-shot"])
    assert args.record and args.grasp == "auto" and args.dream_only
    assert task_prompt(args.prompt) == DEFAULT_PROMPT
    assert task_prompt("  Custom task  ") == "Custom task"


def test_task_entry_rejects_empty():
    from spill.types import SpillError

    with pytest.raises(SpillError, match="non-empty"):
        task_prompt("  ")


def test_bare_command_selects_local_hardware_without_starting_it(monkeypatch):
    from spill import cli

    captured = {}

    def fake_load(path):
        captured["config"] = path
        return Settings()

    def fake_run(settings, args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "load_settings", fake_load)
    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main([]) == 0
    args = captured["args"]
    assert captured["config"] == "config/local.json"
    assert args.hardware and args.zero_shot and args.dream_only
    assert args.record and not args.no_park
    assert Settings().dream.checkpoint == "dreamlabs/dream-1-beta"
    assert cli.main(["run", "--astra-only", "--shadow"]) == 0
    assert not captured["args"].dream_only


def test_explicit_modes():
    assert not parser().parse_args(["run"]).hardware
    assert parser().parse_args(["run", "--dream"]).dream_only
    assert not parser().parse_args(["run", "--astra-dream"]).dream_only
    with pytest.raises(SystemExit):
        parser().parse_args(["run", "--astra-dream", "--dream-only"])
