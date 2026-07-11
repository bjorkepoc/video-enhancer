"""Video encoder helpers for FFmpeg command construction."""

from __future__ import annotations

SUPPORTED_VIDEO_CODECS = ("libx264", "libx265")


def supported_video_codecs() -> tuple[str, ...]:
    """Return supported video codec names in stable display order."""

    return SUPPORTED_VIDEO_CODECS


def validate_video_codec(codec: str) -> None:
    if codec not in SUPPORTED_VIDEO_CODECS:
        valid = ", ".join(SUPPORTED_VIDEO_CODECS)
        raise ValueError(f"Unknown video codec '{codec}'. Choose one of: {valid}.")


def build_video_encoder_args(
    *,
    codec: str,
    default_preset: str,
    quality: int,
    encoder_preset: str | None = None,
) -> list[str]:
    """Build FFmpeg args for the CPU encoders this tool keeps."""

    validate_video_codec(codec)
    return [
        "-c:v",
        codec,
        "-preset",
        encoder_preset or default_preset,
        "-crf",
        str(quality),
    ]


def describe_supported_encoders() -> str:
    """Return a user-facing encoder list for CLI output."""

    return "\n".join(
        [
            "Supported video encoders:",
            "  libx264  H.264, most compatible",
            "  libx265  HEVC, smaller files, slower",
        ]
    )
