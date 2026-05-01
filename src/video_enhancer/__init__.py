"""Core package for the video-enhancer CLI."""

from .ffmpeg import (
    EnhancementOptions,
    FFmpegExecutionError,
    FFmpegNotFoundError,
    ValidationError,
    VideoEnhancerError,
    build_ffmpeg_command,
    enhance_video,
    format_command,
)
from .filter_backends import (
    build_filter_device_args,
    build_video_filter_chain,
    describe_supported_filter_backends,
    supported_filter_backends,
)
from .encoders import (
    build_video_encoder_args,
    describe_supported_encoders,
    supported_video_codecs,
)
from .presets import EnhancementPreset, available_presets, get_preset

__all__ = [
    "EnhancementOptions",
    "EnhancementPreset",
    "FFmpegExecutionError",
    "FFmpegNotFoundError",
    "ValidationError",
    "VideoEnhancerError",
    "available_presets",
    "build_video_encoder_args",
    "build_filter_device_args",
    "build_ffmpeg_command",
    "build_video_filter_chain",
    "describe_supported_encoders",
    "describe_supported_filter_backends",
    "enhance_video",
    "format_command",
    "get_preset",
    "supported_video_codecs",
    "supported_filter_backends",
]
