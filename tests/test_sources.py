from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from video_enhancer.sources import (
    SourceError,
    browser_args,
    group_formats,
    inspect_source,
    validate_social_url,
)


def completed_json(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["yt-dlp"], 0, json.dumps(payload), "")


def test_validate_social_url_allows_only_supported_https_hosts() -> None:
    assert validate_social_url("https://vm.tiktok.com/abc") == "tiktok"
    assert validate_social_url("https://www.instagram.com/reel/abc/") == "instagram"
    for url in (
        "http://tiktok.com/a",
        "https://tiktok.com.evil.test/a",
        "https://example.com/a",
    ):
        with pytest.raises(SourceError):
            validate_social_url(url)


def test_browser_args_supports_named_browser_sessions() -> None:
    assert browser_args("") == []
    assert browser_args("chrome") == ["--cookies-from-browser", "chrome"]
    with pytest.raises(SourceError):
        browser_args("edge")


def test_group_formats_collapses_cdn_mirrors() -> None:
    grouped = group_formats([
        {"format_id": "1080-0", "width": 1080, "height": 1920, "fps": 30,
         "tbr": 767, "vcodec": "h265", "acodec": "aac", "ext": "mp4"},
        {"format_id": "1080-1", "width": 1080, "height": 1920, "fps": 30,
         "tbr": 767, "vcodec": "h265", "acodec": "aac", "ext": "mp4"},
    ])
    assert grouped[0]["format_ids"] == ["1080-0", "1080-1"]
    assert grouped[0]["mirrors"] == 2


def test_inspect_source_uses_dump_single_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    completed = completed_json({"id": "123", "formats": []})

    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args[0], kwargs))
        return completed

    monkeypatch.setattr(subprocess, "run", run)
    inspect_source("https://www.tiktok.com/@a/video/123", "chrome")

    assert calls == [
        (
            [
                "yt-dlp",
                "--no-playlist",
                "--skip-download",
                "--dump-single-json",
                "--cookies-from-browser",
                "chrome",
                "https://www.tiktok.com/@a/video/123",
            ],
            {"capture_output": True, "text": True, "check": False},
        )
    ]


def test_inspect_source_never_returns_signed_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = completed_json({
        "id": "123", "title": "Sample", "webpage_url": "https://tiktok.com/x",
        "formats": [{"format_id": "best", "url": "https://signed.example/token",
                     "width": 1080, "height": 1920, "vcodec": "h265", "acodec": "aac"}],
    })
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)
    result = inspect_source("https://www.tiktok.com/@a/video/123")
    assert "signed.example" not in json.dumps(result)


def test_inspect_source_omits_signed_thumbnail(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = completed_json({
        "id": "123",
        "thumbnail": "https://signed-thumbnail.example/thumb?token=secret",
        "formats": [],
    })
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)
    result = inspect_source("https://www.tiktok.com/@a/video/123")

    assert "signed-thumbnail.example" not in json.dumps(result)
    assert "thumbnail" not in result


def test_inspect_source_reports_yt_dlp_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_start(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("yt-dlp")

    monkeypatch.setattr(subprocess, "run", fail_to_start)

    with pytest.raises(SourceError, match="Could not start yt-dlp"):
        inspect_source("https://www.tiktok.com/@a/video/123")
