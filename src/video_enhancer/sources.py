"""Inspect supported social video sources without exposing media URLs."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SUPPORTED_HOSTS = {"tiktok.com": "tiktok", "instagram.com": "instagram"}
SUPPORTED_BROWSERS = {"", "chrome", "safari", "firefox"}
FORMAT_FIELDS = ("width", "height", "fps", "tbr", "vcodec", "acodec", "ext")
BEST_FORMAT = "bv*+ba/b"


class SourceError(ValueError):
    """Raised when a source URL or inspection result is invalid."""


def _yt_dlp_command(yt_dlp: str) -> list[str]:
    return [sys.executable, "-m", "yt_dlp"] if yt_dlp == "yt-dlp" else [yt_dlp]


def validate_social_url(raw: str) -> str:
    try:
        parsed = urlsplit(raw.strip())
    except ValueError as exc:
        raise SourceError("Use an HTTPS TikTok or Instagram video URL.") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise SourceError("Use an HTTPS TikTok or Instagram video URL.")
    host = parsed.hostname.lower().rstrip(".")
    for domain, platform in SUPPORTED_HOSTS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    raise SourceError("Only TikTok and Instagram video URLs are supported.")


def browser_args(browser: str) -> list[str]:
    if browser not in SUPPORTED_BROWSERS:
        raise SourceError("Browser session must be none, chrome, safari, or firefox.")
    return ["--cookies-from-browser", browser] if browser else []


def _format_key(format_data: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(format_data.get(field) for field in FORMAT_FIELDS)


def _sort_value(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def group_formats(formats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for format_data in formats:
        key = _format_key(format_data)
        group = groups.get(key)
        if group is None:
            group = {field: format_data.get(field) for field in FORMAT_FIELDS}
            group["format_ids"] = []
            groups[key] = group
        group["format_ids"].append(format_data.get("format_id"))

    result = list(groups.values())
    for group in result:
        group["mirrors"] = len(group["format_ids"])
    result.sort(
        key=lambda group: (
            _sort_value(group.get("width")) * _sort_value(group.get("height")),
            _sort_value(group.get("fps")),
            _sort_value(group.get("tbr")),
        ),
        reverse=True,
    )
    return result


def inspect_source(
    url: str, browser: str = "", *, yt_dlp: str = "yt-dlp"
) -> dict[str, Any]:
    normalized_url = url.strip()
    platform = validate_social_url(normalized_url)
    command = [
        *_yt_dlp_command(yt_dlp),
        "--no-playlist",
        "--skip-download",
        "--dump-single-json",
        *browser_args(browser),
        normalized_url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise SourceError(f"Could not start yt-dlp: {exc}") from exc
    if completed.returncode:
        detail = completed.stderr.strip() or "yt-dlp could not inspect the source."
        raise SourceError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SourceError("yt-dlp returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise SourceError("yt-dlp returned an invalid source record.")

    raw_formats = payload.get("formats", [])
    if not isinstance(raw_formats, list):
        raw_formats = []
    return {
        "id": payload.get("id"),
        "platform": platform,
        "title": payload.get("title"),
        "uploader": payload.get("uploader"),
        "duration": payload.get("duration"),
        "webpage_url": payload.get("webpage_url", normalized_url),
        "formats": group_formats(raw_formats),
    }


def _selected_format(format_id: str) -> str:
    if not format_id:
        return BEST_FORMAT
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", format_id):
        raise SourceError("Invalid source format.")
    return f"{format_id}+ba/{format_id}"


def build_download_command(
    url: str,
    destination: Path,
    browser: str = "",
    format_id: str = "",
    *,
    yt_dlp: str = "yt-dlp",
) -> list[str]:
    normalized_url = url.strip()
    validate_social_url(normalized_url)
    return [
        *_yt_dlp_command(yt_dlp),
        "--no-playlist",
        "--no-overwrites",
        "--restrict-filenames",
        "--windows-filenames",
        "-f",
        _selected_format(format_id),
        "-o",
        str(destination / "%(title).80s-%(id)s.%(ext)s"),
        "--print",
        "after_move:FILE:%(filepath)s",
        "--print",
        "after_move:FORMAT:%(format_id)s",
        *browser_args(browser),
        normalized_url,
    ]


def _number(value: Any, cast: type[int] | type[float]) -> int | float | None:
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _fps(value: Any) -> float | None:
    if not isinstance(value, str):
        return _number(value, float)
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator) if float(denominator) else None
    except (ValueError, ZeroDivisionError):
        return _number(value, float)


def parse_ffprobe(payload: dict[str, Any]) -> dict[str, Any]:
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    if not video:
        raise SourceError("The downloaded file has no video stream.")
    format_data = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    return {
        "width": _number(video.get("width"), int),
        "height": _number(video.get("height"), int),
        "fps": _fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "video_bitrate": _number(video.get("bit_rate"), int),
        "bitrate": _number(format_data.get("bit_rate"), int),
        "duration": _number(format_data.get("duration"), float),
        "size": _number(format_data.get("size"), int),
    }


def _parse_ffmpeg_probe(stderr: str) -> dict[str, Any]:
    video_line = next((line for line in stderr.splitlines() if " Video: " in line), "")
    if not video_line:
        raise SourceError("The downloaded file has no video stream.")
    audio_line = next((line for line in stderr.splitlines() if " Audio: " in line), "")
    duration = re.search(
        r"Duration:\s*(\d+):(\d+):([\d.]+).*?bitrate:\s*(\d+)\s*kb/s", stderr
    )
    dimensions = re.search(r"(?<!\d)(\d{2,5})x(\d{2,5})(?!\d)", video_line)
    fps = re.search(r",\s*([\d.]+)\s*fps(?:,|\s)", video_line)
    video_codec = re.search(r"Video:\s*([^,\s(]+)", video_line)
    audio_codec = re.search(r"Audio:\s*([^,\s(]+)", audio_line)
    video_bitrate = re.search(r",\s*([\d.]+)\s*kb/s(?:,|\s)", video_line)
    seconds = None
    bitrate = None
    if duration:
        seconds = int(duration.group(1)) * 3600 + int(duration.group(2)) * 60 + float(duration.group(3))
        bitrate = int(duration.group(4)) * 1000
    return {
        "width": int(dimensions.group(1)) if dimensions else None,
        "height": int(dimensions.group(2)) if dimensions else None,
        "fps": float(fps.group(1)) if fps else None,
        "video_codec": video_codec.group(1) if video_codec else None,
        "audio_codec": audio_codec.group(1) if audio_codec else None,
        "video_bitrate": int(float(video_bitrate.group(1)) * 1000) if video_bitrate else None,
        "bitrate": bitrate,
        "duration": seconds,
        "size": None,
    }


def probe_media(
    path: Path, *, ffprobe: str = "ffprobe", ffmpeg: str = "ffmpeg"
) -> dict[str, Any]:
    if not path.is_file():
        raise SourceError(f"Downloaded file does not exist: {path}")
    ffprobe_path = shutil.which(ffprobe)
    if ffprobe_path:
        completed = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            try:
                media = parse_ffprobe(json.loads(completed.stdout))
                media["size"] = path.stat().st_size
                return media
            except (json.JSONDecodeError, SourceError):
                pass

    ffmpeg_path = shutil.which(ffmpeg)
    if not ffmpeg_path:
        raise SourceError("FFmpeg is required to verify the downloaded file.")
    completed = subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    media = _parse_ffmpeg_probe(completed.stderr)
    media["size"] = path.stat().st_size
    return media


def _remove_parts(destination: Path) -> None:
    for part in destination.glob("*.part"):
        part.unlink(missing_ok=True)


def download_source(
    url: str,
    destination: Path,
    browser: str = "",
    format_id: str = "",
    *,
    yt_dlp: str = "yt-dlp",
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    if format_id:
        inspected = inspect_source(url, browser, yt_dlp=yt_dlp)
        available = {
            current
            for group in inspected.get("formats", [])
            for current in group.get("format_ids", [])
        }
        if format_id not in available:
            raise SourceError("The selected source format is no longer available.")

    command = build_download_command(
        url, destination, browser, format_id, yt_dlp=yt_dlp
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        _remove_parts(destination)
        raise SourceError("The source download timed out.") from exc
    except OSError as exc:
        _remove_parts(destination)
        raise SourceError(f"Could not start yt-dlp: {exc}") from exc
    if completed.returncode:
        _remove_parts(destination)
        detail = completed.stderr.strip() or "yt-dlp could not download the source."
        raise SourceError(detail)

    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"FILE", "FORMAT"}:
            values[key] = value.strip()
    file_path = Path(values.get("FILE", "")).resolve()
    root = destination.resolve()
    if not file_path.is_relative_to(root) or not file_path.is_file():
        raise SourceError("Download completed, but the saved file was not found.")
    selected = values.get("FORMAT", format_id or "best")
    return {
        "path": file_path,
        "filename": file_path.name,
        "format_id": selected,
        "operation": "remuxed" if "+" in selected else "direct",
        "media": probe_media(file_path),
    }
