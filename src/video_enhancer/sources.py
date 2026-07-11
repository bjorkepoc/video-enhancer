"""Inspect supported social video sources without exposing media URLs."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit


SUPPORTED_HOSTS = {"tiktok.com": "tiktok", "instagram.com": "instagram"}
SUPPORTED_BROWSERS = {"", "chrome", "safari", "firefox"}
FORMAT_FIELDS = ("width", "height", "fps", "tbr", "vcodec", "acodec", "ext")


class SourceError(ValueError):
    """Raised when a source URL or inspection result is invalid."""


def validate_social_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
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
        yt_dlp,
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
