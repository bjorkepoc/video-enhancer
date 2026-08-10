"""Finder-launchable entry point for the packaged macOS app."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from video_enhancer.web import run_server


def main() -> None:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bin_dir = bundle_root / "bin"
    yt_dlp = bin_dir / "yt-dlp"
    gallery_dl = bin_dir / "gallery-dl"
    ffmpeg = bin_dir / "ffmpeg"
    if not yt_dlp.is_file():
        raise RuntimeError("The packaged yt-dlp executable is missing.")
    if not ffmpeg.is_file():
        raise RuntimeError("The packaged FFmpeg executable is missing.")
    if not gallery_dl.is_file():
        raise RuntimeError("The packaged gallery-dl executable is missing.")

    os.environ["VIDEO_ENHANCER_YT_DLP"] = str(yt_dlp)
    os.environ["VIDEO_ENHANCER_GALLERY_DL"] = str(gallery_dl)
    os.environ["VIDEO_ENHANCER_FFMPEG"] = str(ffmpeg)
    os.environ["PATH"] = os.pathsep.join(
        part for part in (str(bin_dir), os.environ.get("PATH")) if part
    )
    run_server(port=0, open_browser=True)


if __name__ == "__main__":
    main()
