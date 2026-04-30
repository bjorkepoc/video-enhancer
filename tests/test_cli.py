from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from video_enhancer import cli

ALL_PRESETS = ["fast", "balanced", "quality", "ultra"]


def _invoke_main(args: list[str]) -> int:
    try:
        result = cli.run(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    return int(result or 0)


def _sample_paths(tmp_path: Path) -> tuple[Path, Path]:
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"not a real video; dry-run tests must not decode it")
    return input_path, output_path


@pytest.mark.parametrize("preset", ALL_PRESETS)
def test_dry_run_accepts_public_presets(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, preset: str
) -> None:
    input_path, output_path = _sample_paths(tmp_path)

    exit_code = _invoke_main(
        [str(input_path), str(output_path), "--preset", preset, "--dry-run"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ffmpeg" in captured.out.lower()
    assert str(input_path) in captured.out
    assert str(output_path) in captured.out


def test_dry_run_prints_ffmpeg_command_without_running_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    input_path, output_path = _sample_paths(tmp_path)
    original_run = subprocess.run
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fail_if_called(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        raise AssertionError("dry-run must not execute ffmpeg")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    if getattr(cli, "subprocess", None) is subprocess:
        monkeypatch.setattr(cli.subprocess, "run", fail_if_called)
    if getattr(cli, "run", None) is original_run:
        monkeypatch.setattr(cli, "run", fail_if_called)

    exit_code = _invoke_main(
        [
            str(input_path),
            str(output_path),
            "--preset",
            "balanced",
            "--scale-factor",
            "1.5",
            "--fps",
            "60",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert calls == []
    assert "ffmpeg" in captured.out.lower()
    assert str(input_path) in captured.out
    assert str(output_path) in captured.out
    assert "scale=" in captured.out
    assert "iw*1.5" in captured.out
    assert "ih*1.5" in captured.out
    assert "fps=60" in captured.out


def test_dry_run_wires_no_upscale_and_no_interpolate_flags(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    input_path, output_path = _sample_paths(tmp_path)

    exit_code = _invoke_main(
        [
            str(input_path),
            str(output_path),
            "--preset",
            "quality",
            "--scale-factor",
            "2",
            "--fps",
            "60",
            "--no-upscale",
            "--no-interpolate",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "min(" in captured.out
    assert "iw" in captured.out
    assert "ih" in captured.out
    assert "minterpolate" not in captured.out


def test_dry_run_wires_gpu_encoder_options(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    input_path, output_path = _sample_paths(tmp_path)

    exit_code = _invoke_main(
        [
            str(input_path),
            str(output_path),
            "--preset",
            "ultra",
            "--video-codec",
            "h264_nvenc",
            "--encoder-preset",
            "p7",
            "--quality",
            "16",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "-c:v h264_nvenc" in captured.out
    assert "-preset p7" in captured.out
    assert "-cq:v 16" in captured.out


def test_list_encoders_does_not_require_input_or_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _invoke_main(["--list-encoders"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Supported video encoders" in captured.out
    assert "h264_nvenc" in captured.out
    assert "h264_amf" in captured.out
    assert "h264_qsv" in captured.out


@pytest.mark.parametrize(
    ("option", "value", "expected_error"),
    [
        ("--scale-factor", "0", "scale"),
        ("--fps", "0", "fps"),
        ("--preset", "cinematic", "preset"),
    ],
)
def test_cli_rejects_invalid_options(
    option: str,
    value: str,
    expected_error: str,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    input_path, output_path = _sample_paths(tmp_path)

    exit_code = _invoke_main(
        [str(input_path), str(output_path), option, value, "--dry-run"]
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert expected_error in captured.err.lower()
