"""Video encoder profiles for FFmpeg command construction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EncoderProfile:
    """How a supported FFmpeg encoder should be configured."""

    codec: str
    family: str
    description: str
    default_preset: str


ENCODER_PROFILES: dict[str, EncoderProfile] = {
    "libx264": EncoderProfile(
        codec="libx264",
        family="software",
        description="CPU H.264 encoder, best compatibility",
        default_preset="medium",
    ),
    "libx265": EncoderProfile(
        codec="libx265",
        family="software",
        description="CPU HEVC encoder, smaller files but slower",
        default_preset="medium",
    ),
    "h264_nvenc": EncoderProfile(
        codec="h264_nvenc",
        family="nvenc",
        description="NVIDIA NVENC H.264 hardware encoder",
        default_preset="p6",
    ),
    "hevc_nvenc": EncoderProfile(
        codec="hevc_nvenc",
        family="nvenc",
        description="NVIDIA NVENC HEVC hardware encoder",
        default_preset="p6",
    ),
    "av1_nvenc": EncoderProfile(
        codec="av1_nvenc",
        family="nvenc",
        description="NVIDIA NVENC AV1 hardware encoder",
        default_preset="p6",
    ),
    "h264_amf": EncoderProfile(
        codec="h264_amf",
        family="amf",
        description="AMD AMF H.264 hardware encoder",
        default_preset="quality",
    ),
    "hevc_amf": EncoderProfile(
        codec="hevc_amf",
        family="amf",
        description="AMD AMF HEVC hardware encoder",
        default_preset="quality",
    ),
    "av1_amf": EncoderProfile(
        codec="av1_amf",
        family="amf",
        description="AMD AMF AV1 hardware encoder",
        default_preset="quality",
    ),
    "h264_qsv": EncoderProfile(
        codec="h264_qsv",
        family="qsv",
        description="Intel Quick Sync H.264 hardware encoder",
        default_preset="slow",
    ),
    "hevc_qsv": EncoderProfile(
        codec="hevc_qsv",
        family="qsv",
        description="Intel Quick Sync HEVC hardware encoder",
        default_preset="slow",
    ),
    "av1_qsv": EncoderProfile(
        codec="av1_qsv",
        family="qsv",
        description="Intel Quick Sync AV1 hardware encoder",
        default_preset="slow",
    ),
}


def supported_video_codecs() -> tuple[str, ...]:
    """Return supported video codec names in stable display order."""

    return tuple(ENCODER_PROFILES)


def get_encoder_profile(codec: str) -> EncoderProfile:
    """Return encoder profile metadata for a supported codec."""

    try:
        return ENCODER_PROFILES[codec]
    except KeyError as exc:
        valid = ", ".join(supported_video_codecs())
        raise ValueError(f"Unknown video codec '{codec}'. Choose one of: {valid}.") from exc


def build_video_encoder_args(
    *,
    codec: str,
    default_software_preset: str,
    quality: int,
    encoder_preset: str | None = None,
) -> list[str]:
    """Build FFmpeg args for CPU and hardware encoder families.

    Hardware encoders speed up the final encode step when the user's FFmpeg
    build and GPU support it. Filter acceleration is controlled separately with
    --filter-backend.
    """

    profile = get_encoder_profile(codec)
    effective_preset = encoder_preset or (
        default_software_preset if profile.family == "software" else profile.default_preset
    )

    args = ["-c:v", codec]
    if profile.family == "software":
        return [*args, "-preset", effective_preset, "-crf", str(quality)]
    if profile.family == "nvenc":
        return [*args, "-preset", effective_preset, "-rc", "vbr", "-cq:v", str(quality), "-b:v", "0"]
    if profile.family == "amf":
        return [
            *args,
            "-quality",
            effective_preset,
            "-rc",
            "qvbr",
            "-qvbr_quality_level",
            str(quality),
        ]
    if profile.family == "qsv":
        return [*args, "-preset", effective_preset, "-global_quality", str(quality)]

    raise ValueError(f"Unsupported encoder family '{profile.family}' for codec '{codec}'.")


def describe_supported_encoders() -> str:
    """Return a user-facing encoder list for CLI output."""

    rows = [
        "Supported video encoders:",
        "  CPU:",
        "    libx264     H.264, most compatible",
        "    libx265     HEVC, smaller files, slower",
        "  NVIDIA NVENC:",
        "    h264_nvenc  H.264 hardware encoding",
        "    hevc_nvenc  HEVC hardware encoding",
        "    av1_nvenc   AV1 hardware encoding",
        "  AMD AMF:",
        "    h264_amf    H.264 hardware encoding",
        "    hevc_amf    HEVC hardware encoding",
        "    av1_amf     AV1 hardware encoding",
        "  Intel Quick Sync:",
        "    h264_qsv    H.264 hardware encoding",
        "    hevc_qsv    HEVC hardware encoding",
        "    av1_qsv     AV1 hardware encoding",
        "",
        "Note: --video-codec controls encoding only.",
        "Use --filter-backend or --gpu for optional GPU enhancement filters.",
    ]
    return "\n".join(rows)
