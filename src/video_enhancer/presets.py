"""Preset definitions for video enhancement jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class EnhancementPreset:
    """A named set of FFmpeg tuning choices."""

    name: str
    scale_factor: float
    target_fps: int
    scale_flags: str
    interpolation: Mapping[str, str]
    encoder_preset: str
    crf: int
    pre_scale_filters: tuple[str, ...] = ()
    post_scale_filters: tuple[str, ...] = ()
    interpolate_before_scale: bool = False

    def video_filters(
        self,
        *,
        scale_factor: float | None = None,
        fps: int | None = None,
        no_upscale: bool = False,
        no_interpolate: bool = False,
    ) -> str:
        """Return the FFmpeg video filter chain for this preset."""

        effective_scale = self.scale_factor if scale_factor is None else scale_factor
        effective_fps = self.target_fps if fps is None else fps

        if no_upscale:
            width_expr = f"trunc(min(iw\\,iw*{effective_scale})/2)*2"
            height_expr = f"trunc(min(ih\\,ih*{effective_scale})/2)*2"
        else:
            width_expr = f"trunc(iw*{effective_scale}/2)*2"
            height_expr = f"trunc(ih*{effective_scale}/2)*2"

        scale_filter = f"scale={width_expr}:{height_expr}:flags={self.scale_flags}"
        filters = [*self.pre_scale_filters]
        if not no_interpolate:
            interpolation_args = {"fps": str(effective_fps), **self.interpolation}
            minterpolate = ":".join(
                f"{key}={value}" for key, value in interpolation_args.items()
            )
            interpolation_filter = f"minterpolate={minterpolate}"
            if self.interpolate_before_scale:
                filters.append(interpolation_filter)

        filters.append(scale_filter)
        filters.extend(self.post_scale_filters)

        if not no_interpolate and not self.interpolate_before_scale:
            filters.append(interpolation_filter)

        return ",".join(filters)


PRESETS: dict[str, EnhancementPreset] = {
    "fast": EnhancementPreset(
        name="fast",
        scale_factor=2.0,
        target_fps=48,
        scale_flags="bicubic",
        interpolation={"mi_mode": "blend"},
        encoder_preset="veryfast",
        crf=23,
    ),
    "balanced": EnhancementPreset(
        name="balanced",
        scale_factor=2.0,
        target_fps=60,
        scale_flags="lanczos",
        interpolation={
            "mi_mode": "mci",
            "mc_mode": "obmc",
            "me_mode": "bidir",
        },
        encoder_preset="medium",
        crf=20,
    ),
    "quality": EnhancementPreset(
        name="quality",
        scale_factor=2.0,
        target_fps=60,
        scale_flags="lanczos",
        interpolation={
            "mi_mode": "mci",
            "mc_mode": "aobmc",
            "me_mode": "bidir",
            "vsbmc": "1",
        },
        encoder_preset="slow",
        crf=18,
    ),
    "ultra": EnhancementPreset(
        name="ultra",
        scale_factor=2.0,
        target_fps=90,
        scale_flags="lanczos",
        interpolation={
            "mi_mode": "mci",
            "mc_mode": "aobmc",
            "me_mode": "bidir",
            "me": "umh",
            "mb_size": "8",
            "search_param": "48",
            "vsbmc": "1",
            "scd": "fdiff",
            "scd_threshold": "10",
        },
        encoder_preset="slow",
        crf=16,
        pre_scale_filters=("nlmeans=s=1.0:p=7:r=15",),
        post_scale_filters=("unsharp=5:5:0.65:5:5:0.0",),
        interpolate_before_scale=True,
    ),
}


def available_presets() -> tuple[str, ...]:
    """Return preset names in CLI display order."""

    return tuple(PRESETS)


def get_preset(name: str) -> EnhancementPreset:
    """Look up a preset by name."""

    try:
        return PRESETS[name]
    except KeyError as exc:
        valid = ", ".join(available_presets())
        raise ValueError(f"Unknown preset '{name}'. Choose one of: {valid}.") from exc
