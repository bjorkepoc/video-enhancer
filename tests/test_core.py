from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

import pytest

from video_enhancer import (
    EnhancementOptions,
    ValidationError,
    available_presets,
    build_ffmpeg_command,
    get_preset,
    supported_video_codecs,
)

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
    input_path.write_bytes(b"not a real video; command-building tests must not decode it")
    return input_path, output_path


def _build(tmp_path: Path, preset: str = "balanced", **overrides: object) -> list[str]:
    input_path, output_path = _sample_paths(tmp_path)
    options = EnhancementOptions(
        preset=get_preset(preset),
        ffmpeg_path="ffmpeg",
        **overrides,
    )
    return build_ffmpeg_command(
        input_path,
        output_path,
        options,
        check_executable=False,
    )


@pytest.mark.parametrize("preset", ALL_PRESETS)
def test_public_presets_build_ffmpeg_commands(tmp_path: Path, preset: str) -> None:
    command = _command_text(_build(tmp_path, preset=preset, scale_factor=2.0, fps=30))

    assert "ffmpeg" in command.lower()
    assert "-i" in command
    assert "input.mp4" in command
    assert "output.mp4" in command


def test_presets_change_encoder_tuning(tmp_path: Path) -> None:
    commands = {
        preset: _command_text(_build(tmp_path, preset=preset, scale_factor=2.0, fps=30))
        for preset in ALL_PRESETS
    }

    assert available_presets() == tuple(ALL_PRESETS)
    assert len(set(commands.values())) == len(ALL_PRESETS)
    assert commands["fast"] != commands["balanced"]
    assert commands["quality"] != commands["balanced"]
    assert commands["ultra"] != commands["quality"]


@pytest.mark.parametrize(
    ("preset", "encoder_preset", "crf"),
    [
        ("fast", "veryfast", "23"),
        ("balanced", "medium", "20"),
        ("quality", "slow", "18"),
        ("ultra", "slow", "16"),
    ],
)
def test_presets_apply_expected_encoder_settings(
    tmp_path: Path, preset: str, encoder_preset: str, crf: str
) -> None:
    parts = _command_parts(_build(tmp_path, preset=preset))

    assert parts[parts.index("-preset") + 1] == encoder_preset
    assert parts[parts.index("-crf") + 1] == crf


def test_supported_video_codecs_are_public_and_ordered() -> None:
    assert supported_video_codecs() == (
        "libx264",
        "libx265",
        "h264_nvenc",
        "hevc_nvenc",
        "av1_nvenc",
        "h264_amf",
        "hevc_amf",
        "av1_amf",
        "h264_qsv",
        "hevc_qsv",
        "av1_qsv",
    )


@pytest.mark.parametrize(
    ("codec", "expected_args"),
    [
        ("libx264", ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]),
        ("libx265", ["-c:v", "libx265", "-preset", "medium", "-crf", "20"]),
        (
            "h264_nvenc",
            ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq:v", "20", "-b:v", "0"],
        ),
        (
            "h264_amf",
            [
                "-c:v",
                "h264_amf",
                "-quality",
                "quality",
                "-rc",
                "qvbr",
                "-qvbr_quality_level",
                "20",
            ],
        ),
        (
            "h264_qsv",
            ["-c:v", "h264_qsv", "-preset", "slow", "-global_quality", "20"],
        ),
    ],
)
def test_video_codec_profiles_build_expected_encoder_args(
    tmp_path: Path, codec: str, expected_args: list[str]
) -> None:
    parts = _command_parts(_build(tmp_path, video_codec=codec))

    start = parts.index("-c:v")
    assert parts[start : start + len(expected_args)] == expected_args


def test_quality_and_encoder_preset_override_hardware_codec(tmp_path: Path) -> None:
    parts = _command_parts(
        _build(
            tmp_path,
            video_codec="h264_nvenc",
            encoder_preset="p7",
            quality=16,
        )
    )

    assert parts[parts.index("-preset") + 1] == "p7"
    assert parts[parts.index("-cq:v") + 1] == "16"


def test_invalid_video_codec_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="video codec"):
        _build(tmp_path, video_codec="magic_gpu")


@pytest.mark.parametrize("bad_quality", [-1, 52])
def test_invalid_quality_is_rejected(tmp_path: Path, bad_quality: int) -> None:
    with pytest.raises(ValidationError, match="quality"):
        _build(tmp_path, quality=bad_quality)


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
    assert "me=umh" in filters
    assert "mb_size=8" in filters
    assert "search_param=48" in filters
    assert "scd=fdiff" in filters
    assert "scd_threshold=10" in filters


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


@pytest.mark.parametrize("bad_scale_factor", [0, -0.5])
def test_invalid_scale_factor_is_rejected(
    tmp_path: Path, bad_scale_factor: float
) -> None:
    with pytest.raises(ValidationError, match="scale-factor"):
        _build(tmp_path, scale_factor=bad_scale_factor)


@pytest.mark.parametrize("bad_fps", [0, -1])
def test_invalid_fps_is_rejected(tmp_path: Path, bad_fps: int) -> None:
    with pytest.raises(ValidationError, match="fps"):
        _build(tmp_path, fps=bad_fps)


def test_missing_input_path_is_rejected(tmp_path: Path) -> None:
    missing_input = tmp_path / "missing.mp4"
    output_path = tmp_path / "output.mp4"
    options = EnhancementOptions(preset=get_preset("balanced"), ffmpeg_path="ffmpeg")

    with pytest.raises(ValidationError, match="does not exist"):
        build_ffmpeg_command(
            missing_input,
            output_path,
            options,
            check_executable=False,
        )
