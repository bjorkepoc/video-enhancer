from __future__ import annotations

import math
import shlex
import subprocess
from pathlib import Path
from typing import Sequence

import pytest

import video_enhancer.ffmpeg as ffmpeg
from video_enhancer.encoders import supported_video_codecs
from video_enhancer.ffmpeg import (
    EnhancementOptions,
    FFmpegExecutionError,
    ValidationError,
    build_ffmpeg_command,
)
from video_enhancer.presets import available_presets, get_preset

ALL_PRESETS = ["fast", "balanced", "quality", "ultra"]


def _command_parts(command: str | Sequence[object]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return [str(part) for part in command]


def _command_text(command: str | Sequence[object]) -> str:
    return " ".join(_command_parts(command))


def _sample_paths(tmp_path: Path) -> tuple[Path, Path]:
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(
        b"not a real video; command-building tests must not decode it"
    )
    return input_path, output_path


def _build(tmp_path: Path, preset: str = "balanced", **overrides: object) -> list[str]:
    input_path, output_path = _sample_paths(tmp_path)
    options = EnhancementOptions(
        preset=get_preset(preset),
        ffmpeg_path="ffmpeg",
        **overrides,
    )
    return build_ffmpeg_command(
        input_path, output_path, options, check_executable=False
    )


@pytest.mark.parametrize("preset", ALL_PRESETS)
def test_public_presets_build_ffmpeg_commands(tmp_path: Path, preset: str) -> None:
    command = _command_text(_build(tmp_path, preset=preset, scale_factor=2.0, fps=30))

    assert "ffmpeg" in command.lower()
    assert "-i" in command
    assert "input.mp4" in command
    assert "output.mp4" in command


def test_supported_video_codecs_are_cpu_only() -> None:
    assert supported_video_codecs() == ("libx264", "libx265")


@pytest.mark.parametrize("codec", ["libx264", "libx265"])
def test_cpu_video_codecs_use_crf_tuning(tmp_path: Path, codec: str) -> None:
    parts = _command_parts(
        _build(tmp_path, video_codec=codec, encoder_preset="slow", quality=18)
    )

    assert parts[parts.index("-c:v") + 1] == codec
    assert parts[parts.index("-preset") + 1] == "slow"
    assert parts[parts.index("-crf") + 1] == "18"


def test_invalid_video_codec_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="video codec"):
        _build(tmp_path, video_codec="h264_nvenc")


def test_ultra_preset_uses_max_quality_ffmpeg_filters(tmp_path: Path) -> None:
    parts = _command_parts(_build(tmp_path, preset="ultra"))
    filters = parts[parts.index("-vf") + 1]

    assert filters.index("nlmeans=") < filters.index("minterpolate=")
    assert filters.index("minterpolate=") < filters.index("scale=")
    assert filters.index("scale=") < filters.index("unsharp=")
    assert "nlmeans=s=1.0:p=7:r=15" in filters
    assert "unsharp=5:5:0.65:5:5:0.0" in filters
    assert "flags=lanczos" in filters
    assert "fps=90" in filters


def test_scale_factor_and_fps_are_added_to_video_filter_chain(tmp_path: Path) -> None:
    command = _command_text(_build(tmp_path, scale_factor=1.5, fps=60))

    assert "scale=trunc(iw*1.5/2)*2:trunc(ih*1.5/2)*2" in command
    assert "fps=60" in command


def test_no_upscale_guards_scale_with_input_dimensions(tmp_path: Path) -> None:
    command = _command_text(_build(tmp_path, scale_factor=2.0, no_upscale=True))

    assert "scale=" in command
    assert "min(" in command
    assert "iw" in command
    assert "ih" in command


def test_no_interpolate_disables_motion_interpolation_filter(tmp_path: Path) -> None:
    interpolated = _command_text(_build(tmp_path, fps=60, no_interpolate=False))
    not_interpolated = _command_text(_build(tmp_path, fps=60, no_interpolate=True))

    assert "minterpolate" in interpolated
    assert "minterpolate" not in not_interpolated


@pytest.mark.parametrize("bad_preset", ["", "speedy", "cinematic"])
def test_invalid_preset_is_rejected(bad_preset: str) -> None:
    with pytest.raises(ValueError, match="preset"):
        get_preset(bad_preset)


@pytest.mark.parametrize("bad_scale_factor", [0, -0.5, 2.01, math.inf, math.nan])
def test_invalid_scale_factor_is_rejected(
    tmp_path: Path, bad_scale_factor: float
) -> None:
    with pytest.raises(ValidationError, match="scale-factor"):
        _build(tmp_path, scale_factor=bad_scale_factor)


@pytest.mark.parametrize("bad_fps", [0, -1, 241])
def test_invalid_fps_is_rejected(tmp_path: Path, bad_fps: int) -> None:
    with pytest.raises(ValidationError, match="fps"):
        _build(tmp_path, fps=bad_fps)


def test_run_ffmpeg_has_a_runtime_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Sequence[str], dict[str, object]]] = []

    def run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ffmpeg.subprocess, "run", run)

    ffmpeg.run_ffmpeg(["ffmpeg"])

    assert calls == [
        (
            ["ffmpeg"],
            {"check": False, "timeout": ffmpeg.ENHANCEMENT_TIMEOUT_SECONDS},
        )
    ]


def test_run_ffmpeg_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ffmpeg.subprocess, "run", run)

    with pytest.raises(FFmpegExecutionError, match="six-hour"):
        ffmpeg.run_ffmpeg(["ffmpeg"])


def test_missing_input_path_is_rejected(tmp_path: Path) -> None:
    missing_input = tmp_path / "missing.mp4"
    output_path = tmp_path / "output.mp4"
    options = EnhancementOptions(preset=get_preset("balanced"), ffmpeg_path="ffmpeg")

    with pytest.raises(ValidationError, match="does not exist"):
        build_ffmpeg_command(
            missing_input, output_path, options, check_executable=False
        )


def test_available_presets_are_stable() -> None:
    assert available_presets() == tuple(ALL_PRESETS)
