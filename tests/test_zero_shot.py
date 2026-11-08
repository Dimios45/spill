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


def test_interactive_task_defaults_record_and_no_grasp_override(monkeypatch):
    args = parser().parse_args(["run", "--hardware", "--zero-shot"])
    assert args.prompt is None and args.record and args.grasp == "auto"
    monkeypatch.setattr("builtins.input", lambda _: "Move only the filled container.")
    assert task_prompt(args.prompt) == "Move only the filled container."


def test_task_entry_rejects_empty_or_eof(monkeypatch):
    from spill.types import SpillError

    with pytest.raises(SpillError, match="non-empty"):
        task_prompt("  ")

    def eof(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(SpillError, match="cancelled"):
        task_prompt(None)
