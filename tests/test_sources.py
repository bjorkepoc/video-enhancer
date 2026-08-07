from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from video_enhancer import sources
from video_enhancer.sources import (
    SourceError,
    build_download_command,
    download_source,
    parse_ffprobe,
    probe_media,
    validate_social_url,
)


def test_validate_social_url_allows_only_supported_https_hosts() -> None:
    assert validate_social_url("https://vm.tiktok.com/abc") == "tiktok"
    assert validate_social_url("https://www.instagram.com/reel/abc/") == "instagram"
    for url in (
        "http://tiktok.com/a",
        "https://tiktok.com.evil.test/a",
        "https://example.com/a",
        "https://user:secret@tiktok.com/video/1",
        "https://instagram.com:444/reel/1",
        "https://instagram.com:invalid/reel/1",
        "https://[::1",
    ):
        with pytest.raises(SourceError):
            validate_social_url(url)


def test_download_command_uses_best_source_without_recode(tmp_path: Path) -> None:
    command = build_download_command("https://tiktok.com/x", tmp_path)

    assert command[command.index("-f") + 1] == "bv*+ba/b"
    assert command[command.index("--format-sort") + 1] == (
        "res,fps,quality,hdr:12,vcodec,size,br,asr,source"
    )
    for option in (
        "--ignore-config",
        "--no-config-locations",
        "--no-plugin-dirs",
        "--no-cache-dir",
        "--no-exec",
        "--no-cookies-from-browser",
        "--no-progress",
        "--no-playlist",
    ):
        assert option in command
    assert command[command.index("--downloader") + 1] == "native"
    assert command[command.index("--max-filesize") + 1] == "8G"
    assert command[command.index("--socket-timeout") + 1] == "30"
    assert command[command.index("--retries") + 1] == "3"
    assert command[command.index("--fragment-retries") + 1] == "3"
    assert "--recode-video" not in command
    assert "--remux-video" not in command
    assert command[-1] == "https://tiktok.com/x"


def test_download_command_uses_packaged_yt_dlp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "yt-dlp"
    ffmpeg = tmp_path / "ffmpeg"
    monkeypatch.setenv("VIDEO_ENHANCER_YT_DLP", str(packaged))
    monkeypatch.setenv("VIDEO_ENHANCER_FFMPEG", str(ffmpeg))

    command = build_download_command("https://tiktok.com/x", tmp_path)

    assert command[0] == str(packaged)
    assert "-m" not in command[:3]
    assert command[command.index("--ffmpeg-location") + 1] == str(ffmpeg)


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


def test_probe_media_uses_ffprobe_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 16,
                "height": 16,
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "1"},
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(sources.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(sources, "run_bounded_process", run)

    assert probe_media(video)["fps"] == 30.0
    assert calls[0][0][:2] == ["/usr/bin/ffprobe", "-v"]
    assert calls[0][1]["timeout"] == sources.PROBE_TIMEOUT_SECONDS
    assert calls[0][1]["max_output_bytes"] == sources.MAX_PROBE_OUTPUT_BYTES


def test_probe_media_falls_back_to_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    stderr = """
Duration: 00:00:01.00, start: 0.000000, bitrate: 100 kb/s
Stream #0:0: Video: h264, yuv420p, 16x16, 90 kb/s, 30 fps, 30 tbr
Stream #0:1: Audio: aac, 48000 Hz, stereo
"""
    calls: list[list[str]] = []

    monkeypatch.setattr(
        sources.shutil,
        "which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )
    monkeypatch.setattr(
        sources,
        "run_bounded_process",
        lambda command, **kwargs: (
            calls.append(command)
            or subprocess.CompletedProcess(command, 0, "", stderr)
        ),
    )

    assert probe_media(video)["fps"] == 30.0
    assert calls[0][:2] == ["/usr/bin/ffmpeg", "-hide_banner"]


def test_probe_media_reports_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(sources.shutil, "which", lambda name: name)
    monkeypatch.setattr(
        sources,
        "run_bounded_process",
        lambda command, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(command, kwargs["timeout"])
        ),
    )

    with pytest.raises(SourceError, match="verification timed out"):
        probe_media(video)


def test_download_source_returns_contained_file_and_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "video-123.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, f"FILE:{output}\nFORMAT:best-id\n", ""
        ),
    )
    monkeypatch.setattr(
        sources,
        "probe_media",
        lambda path, **kwargs: {"width": 1080, "height": 1920},
    )

    result = download_source("https://tiktok.com/x", tmp_path)

    assert result == {
        "path": output,
        "filename": output.name,
        "format_id": "best-id",
        "operation": "direct",
        "media": {"width": 1080, "height": 1920},
    }


def test_download_source_hides_raw_yt_dlp_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, "", "private platform diagnostic"
        ),
    )

    with pytest.raises(SourceError) as error:
        download_source("https://tiktok.com/x", tmp_path)

    assert str(error.value) == (
        "The source platform did not provide this public video. "
        "Check that the link is public and try again."
    )
    assert "private platform diagnostic" not in str(error.value)


def test_download_source_rejects_file_outside_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "downloads"
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, f"FILE:{outside}\nFORMAT:best\n", ""
        ),
    )

    with pytest.raises(SourceError, match="saved file was not found"):
        download_source("https://tiktok.com/x", destination)


def test_download_source_removes_file_over_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "video.mp4"
    output.write_bytes(b"oversized")
    monkeypatch.setattr(sources, "MAX_SOURCE_BYTES", 4)
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, f"FILE:{output}\nFORMAT:best\n", ""
        ),
    )

    with pytest.raises(SourceError, match="8 GiB"):
        download_source("https://tiktok.com/x", tmp_path)

    assert not output.exists()


def test_yt_dlp_runner_stops_excessive_output() -> None:
    command = [
        sys.executable,
        "-c",
        "import sys,time;sys.stdout.buffer.write(b'x'*65536);sys.stdout.flush();time.sleep(2)",
    ]

    with pytest.raises(SourceError, match="too much output"):
        sources._run_yt_dlp(command, timeout=2, max_output_bytes=1024)


def test_yt_dlp_runner_stops_download_growth(tmp_path: Path) -> None:
    output = tmp_path / "source.part"
    command = [
        sys.executable,
        "-c",
        "import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_bytes(b'x'*65536);time.sleep(2)",
        str(output),
    ]

    with pytest.raises(SourceError, match="8 GiB"):
        sources._run_yt_dlp(
            command,
            timeout=2,
            destination=tmp_path,
            max_output_bytes=4096,
            max_download_bytes=1024,
        )


def test_download_source_removes_new_files_after_runner_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = tmp_path / "keep.txt"
    keep.write_text("keep")

    def fail(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        (tmp_path / "partial.part").write_bytes(b"partial")
        raise SourceError("download limit")

    monkeypatch.setattr(sources, "_run_yt_dlp", fail)

    with pytest.raises(SourceError, match="download limit"):
        download_source("https://tiktok.com/x", tmp_path)

    assert [path.name for path in tmp_path.iterdir()] == ["keep.txt"]
