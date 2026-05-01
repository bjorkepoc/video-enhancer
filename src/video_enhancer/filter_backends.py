"""Video filter backend profiles and FFmpeg filter-chain construction."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Iterable, Mapping

from .encoders import get_encoder_profile
from .presets import EnhancementPreset


FILTER_DEVICE_NAME = "ve"


@dataclass(frozen=True)
class FilterBackendProfile:
    """How a video filter backend is exposed to FFmpeg."""

    name: str
    description: str
    default_device: str | None = None


@dataclass(frozen=True)
class FilterBackendProbe:
    """Runtime probe result for a hardware filter backend."""

    backend: str
    success: bool
    detail: str


FILTER_BACKENDS: Mapping[str, FilterBackendProfile] = {
    "cpu": FilterBackendProfile(
        name="cpu",
        description="CPU FFmpeg filters; most compatible",
    ),
    "auto": FilterBackendProfile(
        name="auto",
        description="Pick the best available GPU filter backend, then fall back to CPU",
    ),
    "cuda": FilterBackendProfile(
        name="cuda",
        description="NVIDIA CUDA denoise/upscale filters; interpolation remains CPU",
        default_device="0",
    ),
    "opencl": FilterBackendProfile(
        name="opencl",
        description="OpenCL denoise/sharpen filters; scaling and interpolation remain CPU",
        default_device="0.0",
    ),
    "vulkan": FilterBackendProfile(
        name="vulkan",
        description="Vulkan/libplacebo denoise/upscale filters; interpolation remains CPU",
        default_device="0",
    ),
}


def supported_filter_backends() -> tuple[str, ...]:
    """Return filter backend names in stable display order."""

    return tuple(FILTER_BACKENDS)


def get_filter_backend_profile(name: str) -> FilterBackendProfile:
    """Return metadata for a supported filter backend."""

    try:
        return FILTER_BACKENDS[name]
    except KeyError as exc:
        valid = ", ".join(supported_filter_backends())
        raise ValueError(f"Unknown filter backend '{name}'. Choose one of: {valid}.") from exc


def _effective_dimensions(
    *,
    scale_factor: float,
    no_upscale: bool,
) -> tuple[str, str]:
    if no_upscale:
        return (
            f"trunc(min(iw\\,iw*{scale_factor})/2)*2",
            f"trunc(min(ih\\,ih*{scale_factor})/2)*2",
        )
    return (
        f"trunc(iw*{scale_factor}/2)*2",
        f"trunc(ih*{scale_factor}/2)*2",
    )


def _interpolation_filter(preset: EnhancementPreset, fps: int) -> str:
    interpolation_args = {"fps": str(fps), **preset.interpolation}
    args = ":".join(f"{key}={value}" for key, value in interpolation_args.items())
    return f"minterpolate={args}"


def _cpu_scale_filter(
    *,
    width_expr: str,
    height_expr: str,
    scale_flags: str,
) -> str:
    return f"scale={width_expr}:{height_expr}:flags={scale_flags}"


def _gpu_pre_scale_filters(backend: str, preset: EnhancementPreset) -> list[str]:
    if not preset.pre_scale_filters:
        return []
    if backend == "cuda":
        return [
            "format=nv12",
            "hwupload_cuda",
            "bilateral_cuda=sigmaS=3:sigmaR=0.1:window_size=7",
            "hwdownload",
            "format=yuv420p",
        ]
    if backend == "opencl":
        return [
            "format=yuv420p",
            "hwupload",
            "nlmeans_opencl=s=1.0:p=7:r=15",
            "hwdownload",
            "format=yuv420p",
        ]
    if backend == "vulkan":
        return [
            "format=yuv420p",
            "hwupload",
            "nlmeans_vulkan=s=1.0:p=7:r=15",
            "hwdownload",
            "format=yuv420p",
        ]
    return list(preset.pre_scale_filters)


def _scale_filters(
    *,
    backend: str,
    width_expr: str,
    height_expr: str,
    scale_flags: str,
) -> list[str]:
    if backend == "cuda":
        interp = "bicubic" if scale_flags == "bicubic" else "lanczos"
        return [
            "format=nv12",
            "hwupload_cuda",
            f"scale_cuda=w={width_expr}:h={height_expr}:interp_algo={interp}",
            "hwdownload",
            "format=yuv420p",
        ]
    if backend == "vulkan":
        upscaler = "bicubic" if scale_flags == "bicubic" else "ewa_lanczossharp"
        return [
            "format=yuv420p",
            "hwupload",
            (
                f"libplacebo=w={width_expr}:h={height_expr}:"
                f"upscaler={upscaler}:format=yuv420p"
            ),
            "hwdownload",
            "format=yuv420p",
        ]
    return [_cpu_scale_filter(width_expr=width_expr, height_expr=height_expr, scale_flags=scale_flags)]


def _post_scale_filters(backend: str, preset: EnhancementPreset) -> list[str]:
    if not preset.post_scale_filters:
        return []
    if backend == "opencl":
        return [
            "format=yuv420p",
            "hwupload",
            "unsharp_opencl=lx=5:ly=5:la=0.65:cx=5:cy=5:ca=0.0",
            "hwdownload",
            "format=yuv420p",
        ]
    return list(preset.post_scale_filters)


def build_video_filter_chain(
    preset: EnhancementPreset,
    *,
    scale_factor: float | None = None,
    fps: int | None = None,
    no_upscale: bool = False,
    no_interpolate: bool = False,
    filter_backend: str = "cpu",
) -> str:
    """Return an FFmpeg video filter chain for a CPU or GPU filter backend."""

    get_filter_backend_profile(filter_backend)
    if filter_backend in {"cpu", "auto"}:
        return preset.video_filters(
            scale_factor=scale_factor,
            fps=fps,
            no_upscale=no_upscale,
            no_interpolate=no_interpolate,
        )

    effective_scale = preset.scale_factor if scale_factor is None else scale_factor
    effective_fps = preset.target_fps if fps is None else fps
    width_expr, height_expr = _effective_dimensions(
        scale_factor=effective_scale,
        no_upscale=no_upscale,
    )

    filters = [*_gpu_pre_scale_filters(filter_backend, preset)]
    if not no_interpolate:
        interpolation = _interpolation_filter(preset, effective_fps)
        if preset.interpolate_before_scale:
            filters.append(interpolation)

    filters.extend(
        _scale_filters(
            backend=filter_backend,
            width_expr=width_expr,
            height_expr=height_expr,
            scale_flags=preset.scale_flags,
        )
    )
    filters.extend(_post_scale_filters(filter_backend, preset))

    if not no_interpolate and not preset.interpolate_before_scale:
        filters.append(interpolation)

    return ",".join(filters)


def build_filter_device_args(
    filter_backend: str,
    *,
    filter_device: str | None = None,
) -> list[str]:
    """Return global FFmpeg hardware-device args for a filter backend."""

    profile = get_filter_backend_profile(filter_backend)
    if profile.name in {"cpu", "auto"}:
        return []
    device = filter_device or profile.default_device
    if not device:
        return []
    return [
        "-init_hw_device",
        f"{profile.name}={FILTER_DEVICE_NAME}:{device}",
        "-filter_hw_device",
        FILTER_DEVICE_NAME,
    ]


def preferred_filter_backends(video_codec: str) -> tuple[str, ...]:
    """Return concrete GPU filter backends in preference order."""

    encoder_family = get_encoder_profile(video_codec).family
    if encoder_family == "nvenc":
        return ("cuda", "vulkan", "opencl")
    return ("vulkan", "opencl", "cuda")


def required_filter_names(filter_backend: str, preset: EnhancementPreset) -> tuple[str, ...]:
    """Return FFmpeg filters required by a concrete backend for a preset."""

    get_filter_backend_profile(filter_backend)
    if filter_backend in {"cpu", "auto"}:
        return ()

    required: list[str] = []
    if filter_backend == "cuda":
        required.extend(["hwupload_cuda", "scale_cuda"])
        if preset.pre_scale_filters:
            required.append("bilateral_cuda")
    elif filter_backend == "opencl":
        required.append("hwupload")
        if preset.pre_scale_filters:
            required.append("nlmeans_opencl")
        if preset.post_scale_filters:
            required.append("unsharp_opencl")
    elif filter_backend == "vulkan":
        required.extend(["hwupload", "libplacebo"])
        if preset.pre_scale_filters:
            required.append("nlmeans_vulkan")

    return tuple(dict.fromkeys(required))


_FILTER_LINE_RE = re.compile(r"^\s*[TSC. ]{3}\s+([A-Za-z0-9_]+)\s+")


def available_filter_names(ffmpeg_path: str) -> frozenset[str]:
    """Return filter names exposed by an FFmpeg executable."""

    completed = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-filters"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    return frozenset(
        match.group(1)
        for line in output.splitlines()
        if (match := _FILTER_LINE_RE.match(line))
    )


def _has_required_filters(
    filter_backend: str,
    preset: EnhancementPreset,
    available_filters: Iterable[str],
) -> bool:
    available = set(available_filters)
    return all(name in available for name in required_filter_names(filter_backend, preset))


def _tail_process_output(output: str, *, max_lines: int = 6) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])


def _probe_filter_chain(filter_backend: str) -> str:
    if filter_backend == "cuda":
        return (
            "format=nv12,hwupload_cuda,"
            "bilateral_cuda=sigmaS=3:sigmaR=0.1:window_size=7,"
            "scale_cuda=w=128:h=128:interp_algo=lanczos,"
            "hwdownload,format=yuv420p"
        )
    if filter_backend == "opencl":
        return (
            "format=yuv420p,hwupload,"
            "nlmeans_opencl=s=1.0:p=7:r=15,"
            "unsharp_opencl=lx=5:ly=5:la=0.65:cx=5:cy=5:ca=0.0,"
            "hwdownload,format=yuv420p"
        )
    if filter_backend == "vulkan":
        return (
            "format=yuv420p,hwupload,"
            "nlmeans_vulkan=s=1.0:p=7:r=15,"
            "libplacebo=w=128:h=128:upscaler=ewa_lanczossharp:format=yuv420p,"
            "hwdownload,format=yuv420p"
        )
    raise ValueError(f"Cannot probe non-GPU filter backend '{filter_backend}'.")


def probe_filter_backend(
    ffmpeg_path: str,
    filter_backend: str,
    *,
    filter_device: str | None = None,
    timeout_seconds: int = 20,
) -> FilterBackendProbe:
    """Run a tiny FFmpeg smoke test for a concrete GPU filter backend."""

    profile = get_filter_backend_profile(filter_backend)
    if profile.name in {"cpu", "auto"}:
        return FilterBackendProbe(profile.name, True, "No GPU probe needed.")

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        *build_filter_device_args(profile.name, filter_device=filter_device),
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=64x64:d=0.1",
        "-vf",
        _probe_filter_chain(profile.name),
        "-frames:v",
        "1",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return FilterBackendProbe(profile.name, False, str(exc))

    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode == 0:
        return FilterBackendProbe(profile.name, True, "Runtime probe succeeded.")
    detail = _tail_process_output(output) or f"FFmpeg exited with {completed.returncode}."
    return FilterBackendProbe(profile.name, False, detail)


def resolve_filter_backend(
    requested_backend: str,
    *,
    preset: EnhancementPreset,
    video_codec: str,
    available_filters: Iterable[str] | None = None,
) -> str:
    """Resolve `auto` to a concrete backend, otherwise validate a backend name."""

    get_filter_backend_profile(requested_backend)
    if requested_backend != "auto":
        return requested_backend

    preferred = preferred_filter_backends(video_codec)

    if available_filters is None:
        return preferred[0]

    for candidate in preferred:
        if _has_required_filters(candidate, preset, available_filters):
            return candidate
    return "cpu"


def describe_supported_filter_backends(
    *,
    ffmpeg_path: str | None = None,
    preset: EnhancementPreset | None = None,
) -> str:
    """Return a user-facing description of filter backends and local support."""

    available = available_filter_names(ffmpeg_path) if ffmpeg_path else None
    rows = [
        "Supported filter backends:",
        "  cpu      CPU FFmpeg filters; most compatible",
        "  auto     Pick a GPU backend when required filters are available",
        "  cuda     NVIDIA CUDA denoise/upscale; interpolation remains CPU",
        "  opencl   OpenCL denoise/sharpen; scaling and interpolation remain CPU",
        "  vulkan   Vulkan/libplacebo denoise/upscale; interpolation remains CPU",
    ]
    if available is None:
        rows.extend(
            [
                "",
                "Run with --ffmpeg PATH if FFmpeg is not on PATH.",
            ]
        )
        return "\n".join(rows)

    probe_preset = preset
    rows.append("")
    rows.append("Local FFmpeg runtime check:")
    for backend in ("cuda", "opencl", "vulkan"):
        if probe_preset is None:
            required = ()
        else:
            required = required_filter_names(backend, probe_preset)
        missing = [name for name in required if name not in available]
        if missing:
            status = f"missing {', '.join(missing)}"
        else:
            probe = probe_filter_backend(ffmpeg_path, backend)
            detail = probe.detail.splitlines()[0] if probe.detail else "unknown error"
            status = "ready" if probe.success else f"probe failed: {detail}"
        rows.append(f"  {backend:<7} {status}")

    return "\n".join(rows)
