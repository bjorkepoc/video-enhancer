from __future__ import annotations

from video_enhancer.presets import get_preset
from video_enhancer.web import build_options, safe_filename


def test_safe_filename_removes_paths_and_unsafe_chars() -> None:
    assert safe_filename("../../my video!!.mp4") == "my_video_.mp4"


def test_build_options_uses_existing_preset_and_toggles() -> None:
    options = build_options(
        {
            "preset": ["fast"],
            "scale": ["1.5"],
            "fps": ["48"],
            "no_upscale": ["1"],
            "no_interpolate": ["true"],
            "codec": ["libx265"],
        }
    )

    assert options.preset == get_preset("fast")
    assert options.scale_factor == 1.5
    assert options.fps == 48
    assert options.no_upscale is True
    assert options.no_interpolate is True
    assert options.video_codec == "libx265"
