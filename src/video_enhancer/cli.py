"""Command-line interface for video-enhancer."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .encoders import describe_supported_encoders, supported_video_codecs
from .ffmpeg import (
    EnhancementOptions,
    VideoEnhancerError,
    enhance_video,
    format_command,
    resolve_ffmpeg,
)
from .filter_backends import describe_supported_filter_backends, supported_filter_backends
from .presets import available_presets, get_preset


def positive_float(value: str) -> float:
    """Parse a positive float for argparse."""

    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number greater than 0") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def positive_int(value: str) -> int:
    """Parse a positive integer for argparse."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number greater than 0") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def quality_value(value: str) -> int:
    """Parse a 0-51 FFmpeg quality value."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number from 0 to 51") from exc
    if not 0 <= parsed <= 51:
        raise argparse.ArgumentTypeError("must be from 0 to 51")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="video-enhancer",
        description="Enhance a video with FFmpeg upscaling and frame interpolation.",
    )
    parser.add_argument("input", type=Path, nargs="?", help="input video file")
    parser.add_argument("output", type=Path, nargs="?", help="output video file")
    parser.add_argument(
        "--preset",
        choices=available_presets(),
        default="balanced",
        help="enhancement preset to use (default: balanced)",
    )
    parser.add_argument(
        "--scale-factor",
        type=positive_float,
        help="override the preset upscale factor, for example 2 or 1.5",
    )
    parser.add_argument(
        "--fps",
        type=positive_int,
        help="override the preset interpolation target FPS",
    )
    parser.add_argument(
        "--no-upscale",
        action="store_true",
        help="guard scaling so the output is never larger than the input dimensions",
    )
    parser.add_argument(
        "--no-interpolate",
        action="store_true",
        help="disable motion interpolation and keep the original frame cadence",
    )
    parser.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="ffmpeg executable name or full path (default: ffmpeg)",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="shortcut for --filter-backend auto",
    )
    parser.add_argument(
        "--filter-backend",
        choices=supported_filter_backends(),
        default="cpu",
        help="video filter backend for enhancement filters (default: cpu)",
    )
    parser.add_argument(
        "--filter-device",
        help="hardware filter device selector, for example 0 or 1",
    )
    parser.add_argument(
        "--video-codec",
        choices=supported_video_codecs(),
        default="libx264",
        help="video encoder codec, including hardware encoders when available",
    )
    parser.add_argument(
        "--encoder-preset",
        help="override encoder preset, e.g. slow, p6, quality",
    )
    parser.add_argument(
        "--quality",
        type=quality_value,
        help="quality level 0-51; lower is higher quality; maps to CRF/CQ/QVBR",
    )
    parser.add_argument(
        "--list-encoders",
        action="store_true",
        help="list supported CPU and hardware encoder codec names",
    )
    parser.add_argument(
        "--list-filter-backends",
        action="store_true",
        help="list supported CPU/GPU filter backend names and local FFmpeg filter support",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace the output file if it already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the FFmpeg command without running it",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_encoders:
        print(describe_supported_encoders())
        return 0
    if args.list_filter_backends:
        preset = get_preset(args.preset)
        try:
            ffmpeg = resolve_ffmpeg(args.ffmpeg)
        except VideoEnhancerError:
            print(describe_supported_filter_backends(preset=preset))
        else:
            print(describe_supported_filter_backends(ffmpeg_path=ffmpeg, preset=preset))
        return 0
    if args.input is None or args.output is None:
        parser.error(
            "input and output are required unless --list-encoders or "
            "--list-filter-backends is used"
        )

    preset = get_preset(args.preset)
    filter_backend = "auto" if args.gpu and args.filter_backend == "cpu" else args.filter_backend
    options = EnhancementOptions(
        preset=preset,
        scale_factor=args.scale_factor,
        fps=args.fps,
        no_upscale=args.no_upscale,
        no_interpolate=args.no_interpolate,
        video_codec=args.video_codec,
        encoder_preset=args.encoder_preset,
        quality=args.quality,
        filter_backend=filter_backend,
        filter_device=args.filter_device,
        overwrite=args.overwrite,
        ffmpeg_path=args.ffmpeg,
    )

    try:
        command = enhance_video(args.input, args.output, options, dry_run=args.dry_run)
    except VideoEnhancerError as exc:
        parser.exit(1, f"video-enhancer: error: {exc}\n")

    if args.dry_run:
        print(format_command(command))
    return 0


def main() -> None:
    """Console-script entry point."""

    raise SystemExit(run())


if __name__ == "__main__":
    main()
