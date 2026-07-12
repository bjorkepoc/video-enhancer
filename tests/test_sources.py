from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import video_enhancer.sources as sources
from video_enhancer.sources import (
    SourceError,
    build_download_command,
    browser_args,
    compare_hashes,
    download_source,
    extract_keyframes,
    frame_hash,
    group_formats,
    inspect_source,
    parse_ffprobe,
    probe_media,
    search_links,
    sample_frame_hashes,
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


def test_validate_social_url_rejects_malformed_ipv6() -> None:
    with pytest.raises(SourceError, match="Use an HTTPS TikTok or Instagram video URL"):
        validate_social_url("https://[::1")


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


def test_group_formats_sorts_by_resolution_then_fps_then_bitrate() -> None:
    grouped = group_formats([
        {"format_id": "low-resolution", "width": 720, "height": 1280,
         "fps": 120, "tbr": 999, "vcodec": "h264", "acodec": "aac", "ext": "mp4"},
        {"format_id": "high-resolution-low-fps", "width": 1080, "height": 1920,
         "fps": 30, "tbr": 100, "vcodec": "h264", "acodec": "aac", "ext": "mp4"},
        {"format_id": "high-resolution-high-fps-low-bitrate", "width": 1080,
         "height": 1920, "fps": 60, "tbr": 100, "vcodec": "h264", "acodec": "aac", "ext": "mp4"},
        {"format_id": "high-resolution-high-fps-high-bitrate", "width": 1080,
         "height": 1920, "fps": 60, "tbr": 200, "vcodec": "h264", "acodec": "aac", "ext": "mp4"},
    ])

    assert [group["format_ids"][0] for group in grouped] == [
        "high-resolution-high-fps-high-bitrate",
        "high-resolution-high-fps-low-bitrate",
        "high-resolution-low-fps",
        "low-resolution",
    ]


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
                sys.executable,
                "-m",
                "yt_dlp",
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


def test_download_command_is_source_first_and_has_no_recode_flags(tmp_path: Path) -> None:
    command = build_download_command("https://tiktok.com/x", tmp_path)

    assert command[command.index("-f") + 1] == "bv*+ba/b"
    assert "--recode-video" not in command
    assert "--remux-video" not in command


def test_download_command_adds_audio_to_an_inspected_format(tmp_path: Path) -> None:
    command = build_download_command(
        "https://instagram.com/reel/x", tmp_path, "chrome", "dash-1080v"
    )

    assert command[command.index("-f") + 1] == "dash-1080v+ba/dash-1080v"
    assert command[-3:] == ["--cookies-from-browser", "chrome", "https://instagram.com/reel/x"]


def test_download_command_rejects_unsafe_format_id(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="Invalid source format"):
        build_download_command("https://tiktok.com/x", tmp_path, format_id="best;rm")


def test_parse_ffprobe_reports_saved_stream() -> None:
    media = parse_ffprobe(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "30/1",
                    "bit_rate": "664000",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {
                "duration": "105.03",
                "size": "10076075",
                "bit_rate": "767000",
            },
        }
    )

    assert media == {
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "video_codec": "hevc",
        "audio_codec": "aac",
        "video_bitrate": 664000,
        "bitrate": 767000,
        "duration": 105.03,
        "size": 10076075,
    }


def test_probe_media_falls_back_to_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    completed = subprocess.CompletedProcess(
        ["ffmpeg"],
        0,
        "",
        """Duration: 00:01:45.03, start: 0.000000, bitrate: 767 kb/s
Stream #0:0: Audio: aac (HE-AAC), 44100 Hz, stereo
Stream #0:1: Video: hevc (Main), yuv420p, 1080x1920, 664 kb/s, 30 fps, 30 tbr
""",
    )
    monkeypatch.setattr(sources.shutil, "which", lambda name: None if name == "ffprobe" else name)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

    media = probe_media(video)

    assert (media["width"], media["height"], media["fps"]) == (1080, 1920, 30.0)
    assert media["video_codec"] == "hevc"
    assert media["audio_codec"] == "aac"
    assert media["duration"] == 105.03
    assert media["bitrate"] == 767000
    assert media["size"] == 5


def test_download_source_rejects_format_not_in_current_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sources,
        "inspect_source",
        lambda *args, **kwargs: {"formats": [{"format_ids": ["available"]}]},
    )

    with pytest.raises(SourceError, match="no longer available"):
        download_source("https://tiktok.com/x", tmp_path, format_id="missing")


def test_download_source_returns_contained_file_and_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "video-123.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        sources,
        "inspect_source",
        lambda *args, **kwargs: {"formats": [{"format_ids": ["best-id"]}]},
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, f"FILE:{output}\nFORMAT:best-id\n", ""
        ),
    )
    monkeypatch.setattr(sources, "probe_media", lambda path: {"width": 1080, "height": 1920})

    result = download_source("https://tiktok.com/x", tmp_path, format_id="best-id")

    assert result == {
        "path": output,
        "filename": output.name,
        "format_id": "best-id",
        "operation": "direct",
        "media": {"width": 1080, "height": 1920},
    }


def test_search_links_cover_metadata_and_both_platforms() -> None:
    links = search_links(
        {"id": "123", "title": "Closet Cleanout", "uploader": "aurora"}
    )

    assert set(links) == {"web", "tiktok", "instagram", "google_lens", "tineye"}
    assert "Closet+Cleanout" in links["web"]
    assert "site%3Atiktok.com" in links["tiktok"]
    assert "site%3Ainstagram.com" in links["instagram"]


def test_frame_hash_compares_horizontal_grayscale_differences() -> None:
    rising = bytes(range(17)) * 16
    falling = bytes(reversed(range(17))) * 16

    assert frame_hash(rising).bit_count() == 256
    assert frame_hash(falling) == 0
    with pytest.raises(SourceError, match="frame size"):
        frame_hash(b"short")


def test_compare_hashes_classifies_match_uncertain_and_different() -> None:
    assert compare_hashes([0], [0])["result"] == "likely_match"
    assert compare_hashes([0], [(1 << 80) - 1])["result"] == "uncertain"
    assert compare_hashes([0], [(1 << 256) - 1])["result"] == "different"
    assert compare_hashes([0], [0])["advisory"] is True

    with pytest.raises(SourceError, match="same number"):
        compare_hashes([0], [0, 1])


def test_extract_keyframes_uses_three_bounded_ffmpeg_seeks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    calls: list[list[str]] = []
    monkeypatch.setattr(sources, "_duration", lambda path, ffmpeg: 100.0)
    monkeypatch.setattr(sources, "_ffmpeg_executable", lambda ffmpeg: ffmpeg)

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    frames = extract_keyframes(video, tmp_path / "frames")

    assert [frame.name for frame in frames] == [
        "frame-1.jpg",
        "frame-2.jpg",
        "frame-3.jpg",
    ]
    assert [command[command.index("-ss") + 1] for command in calls] == [
        "25.000",
        "50.000",
        "75.000",
    ]
    assert all(command[command.index("-frames:v") + 1] == "1" for command in calls)


def test_sample_frame_hashes_reads_five_fixed_size_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    raw = bytes(range(17)) * 16
    calls: list[list[str]] = []
    monkeypatch.setattr(sources, "_duration", lambda path, ffmpeg: 60.0)
    monkeypatch.setattr(sources, "_ffmpeg_executable", lambda ffmpeg: ffmpeg)

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, raw, b"")

    monkeypatch.setattr(subprocess, "run", run)

    hashes = sample_frame_hashes(video)

    assert len(hashes) == 5
    assert all(value.bit_count() == 256 for value in hashes)
    assert all("scale=17:16,format=gray" in command for command in calls)
