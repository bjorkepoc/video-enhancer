"""FFmpeg command construction and execution for video enhancement."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .encoders import build_video_encoder_args, get_encoder_profile
from .presets import EnhancementPreset


class VideoEnhancerError(Exception):
    """Base class for user-facing video enhancer errors."""


class ValidationError(VideoEnhancerError):
    """Raised when input or output paths are invalid."""


class FFmpegNotFoundError(VideoEnhancerError):
    """Raised when the ffmpeg executable cannot be found."""


class FFmpegExecutionError(VideoEnhancerError):
    """Raised when ffmpeg exits unsuccessfully."""


@dataclass(frozen=True)
class EnhancementOptions:
    """Options used to construct an FFmpeg enhancement command."""

    preset: EnhancementPreset
    scale_factor: float | None = None
    fps: int | None = None
    no_upscale: bool = False
    no_interpolate: bool = False
    video_codec: str = "libx264"
    encoder_preset: str | None = None
    quality: int | None = None
    overwrite: bool = False
    ffmpeg_path: str = "ffmpeg"


def validate_paths(input_path: Path, output_path: Path, *, overwrite: bool = False) -> None:
    """Validate input and output paths before building or running FFmpeg."""

    if not input_path.exists():
        raise ValidationError(f"Input video does not exist: {input_path}")
    if not input_path.is_file():
        raise ValidationError(f"Input path is not a file: {input_path}")
    if output_path.exists() and output_path.is_dir():
        raise ValidationError(f"Output path is a directory: {output_path}")
    if output_path.exists() and not overwrite:
        raise ValidationError(
            f"Output file already exists: {output_path}. Use --overwrite to replace it."
        )
    if not output_path.parent.exists():
        raise ValidationError(f"Output directory does not exist: {output_path.parent}")
    if input_path.resolve() == output_path.resolve():
        raise ValidationError("Input and output must be different files.")
    if not output_path.suffix:
        raise ValidationError("Output path must include a file extension such as .mp4 or .mkv.")


def validate_options(options: EnhancementOptions) -> None:
    """Validate enhancement values that may come from CLI overrides."""

    if options.scale_factor is not None and options.scale_factor <= 0:
        raise ValidationError("--scale-factor must be greater than 0.")
    if options.fps is not None and options.fps <= 0:
        raise ValidationError("--fps must be greater than 0.")
    if options.quality is not None and not 0 <= options.quality <= 51:
        raise ValidationError("--quality must be between 0 and 51.")
    try:
        get_encoder_profile(options.video_codec)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def resolve_ffmpeg(ffmpeg_path: str = "ffmpeg") -> str:
    """Return an executable FFmpeg path or raise a clear user-facing error."""

    candidate = Path(ffmpeg_path)
    if candidate.parent != Path(".") and candidate.exists():
        if candidate.is_file():
            return str(candidate)
        raise FFmpegNotFoundError(f"FFmpeg path is not a file: {ffmpeg_path}")

    resolved = shutil.which(ffmpeg_path)
    if resolved:
        return resolved

    raise FFmpegNotFoundError(
        "FFmpeg was not found. Install FFmpeg and ensure 'ffmpeg' is on PATH, "
        "or pass --ffmpeg with the full path to the executable."
    )


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    options: EnhancementOptions,
    *,
    check_executable: bool = True,
) -> list[str]:
    """Build the FFmpeg command for an enhancement job."""

    validate_options(options)
    validate_paths(input_path, output_path, overwrite=options.overwrite)
    ffmpeg = resolve_ffmpeg(options.ffmpeg_path) if check_executable else options.ffmpeg_path
    filters = options.preset.video_filters(
        scale_factor=options.scale_factor,
        fps=options.fps,
        no_upscale=options.no_upscale,
        no_interpolate=options.no_interpolate,
    )
    video_encoder_args = build_video_encoder_args(
        codec=options.video_codec,
        default_software_preset=options.preset.encoder_preset,
        quality=options.quality if options.quality is not None else options.preset.crf,
        encoder_preset=options.encoder_preset,
    )

    return [
        ffmpeg,
        "-hide_banner",
        "-y" if options.overwrite else "-n",
        "-i",
        str(input_path),
        "-vf",
        filters,
        *video_encoder_args,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def format_command(command: Sequence[str]) -> str:
    """Return a shell-friendly representation of a command."""

    if os.name == "nt":
        return subprocess.list2cmdline(list(command))
    return shlex.join(command)


def run_ffmpeg(command: Sequence[str]) -> None:
    """Run FFmpeg and convert low-level failures into clear CLI errors."""

    try:
        completed = subprocess.run(command, check=False)
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            "FFmpeg was not found while starting the process. Install FFmpeg and ensure "
            "'ffmpeg' is on PATH, or pass --ffmpeg with the full path to the executable."
        ) from exc

    if completed.returncode != 0:
        raise FFmpegExecutionError(f"FFmpeg failed with exit code {completed.returncode}.")


def enhance_video(
    input_path: Path,
    output_path: Path,
    options: EnhancementOptions,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Build and optionally run an FFmpeg enhancement command."""

    command = build_ffmpeg_command(
        input_path,
        output_path,
        options,
        check_executable=not dry_run,
    )
    if not dry_run:
        run_ffmpeg(command)
    return command
