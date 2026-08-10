from __future__ import annotations

import json
import subprocess
import sys
from http.client import IncompleteRead
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from video_enhancer import sources
from video_enhancer.sources import (
    SourceError,
    build_download_command,
    build_image_download_command,
    build_instagram_image_metadata_command,
    download_source,
    parse_ffprobe,
    probe_media,
    validate_social_url,
)


def test_validate_social_url_allows_only_supported_https_hosts() -> None:
    assert validate_social_url("https://vm.tiktok.com/abc") == "tiktok"
    assert validate_social_url("https://www.instagram.com/reel/abc/") == "instagram"
    assert validate_social_url("https://www.facebook.com/reel/123") == "facebook"
    assert validate_social_url("https://vsco.co/user/media/abc") == "vsco"
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


def test_download_source_rejects_profiles_and_galleries_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda *args, **kwargs: pytest.fail("profile reached yt-dlp"),
    )
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: pytest.fail("profile reached gallery-dl"),
    )
    for index, url in enumerate(
        (
            "https://vsco.co/example/gallery",
            "https://instagram.com/example/",
            "https://tiktok.com/@example",
            "https://facebook.com/example",
        )
    ):
        with pytest.raises(SourceError, match="single-post URL"):
            download_source(url, tmp_path / str(index))

    for url in (
        "https://vsco.co/example/media/abc",
        "https://instagram.com/p/abc/",
        "https://vm.tiktok.com/abc",
        "https://facebook.com/reel/123",
        "https://facebook.com/example/posts/123",
        "https://facebook.com/video.php?v=123",
        "https://facebook.com/story.php?story_fbid=123&id=456",
        "https://facebook.com/video/embed?video_id=123",
        "https://facebook.com/watch/live/?v=123",
        "https://facebook.com/events/123/permalink/456",
        "https://fb.watch/abc",
    ):
        assert sources._is_single_post_url(validate_social_url(url), url)


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


def test_download_command_caps_source_quality_without_upscaling(tmp_path: Path) -> None:
    command = build_download_command(
        "https://tiktok.com/x",
        tmp_path,
        quality="4k",
    )

    assert command[command.index("-f") + 1] == (
        "(bv*[aspect_ratio>=1][height<=2160]/"
        "bv*[aspect_ratio<1][width<=2160])+ba/"
        "(b[aspect_ratio>=1][height<=2160]/"
        "b[aspect_ratio<1][width<=2160])"
    )

    with pytest.raises(SourceError, match="Quality must be"):
        build_download_command(
            "https://tiktok.com/x",
            tmp_path,
            quality="16k",
        )
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


def test_image_download_command_is_bounded_and_ignores_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "gallery-dl"
    monkeypatch.setenv("VIDEO_ENHANCER_GALLERY_DL", str(packaged))

    command = build_image_download_command(
        "https://vsco.co/user/media/abc", tmp_path, quality="480p"
    )

    assert command[0] == str(packaged)
    assert "--config-ignore" in command
    assert command[command.index("--cache-file") + 1] == ":memory:"
    assert command[command.index("-o") + 1] == (
        "downloader.ytdl.format=(bv*[aspect_ratio>=1][height<=480]/"
        "bv*[aspect_ratio<1][width<=480])+ba/"
        "(b[aspect_ratio>=1][height<=480]/b[aspect_ratio<1][width<=480])"
    )
    assert command[command.index("--directory") + 1] == str(tmp_path)
    assert command[command.index("--filesize-max") + 1] == "8G"
    assert command[command.index("--range") + 1] == "1-51"
    assert "mp4" in command[command.index("--filter") + 1]
    assert command[-1] == "https://vsco.co/user/media/abc"


def test_instagram_image_metadata_command_is_anonymous_and_bounded() -> None:
    command = build_instagram_image_metadata_command(
        "https://www.instagram.com/p/example/"
    )

    assert "--ignore-no-formats-error" in command
    assert "--dump-single-json" in command
    assert "--skip-download" in command
    assert "--no-cookies-from-browser" in command
    assert command[command.index("--socket-timeout") + 1] == "30"
    assert command[command.index("--retries") + 1] == "3"
    assert command[-1] == "https://www.instagram.com/p/example/"


def test_stop_process_terminates_windows_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Windows:
        name = "nt"

    process = Mock(pid=123)
    process.poll.return_value = None
    run = Mock()
    monkeypatch.setattr(sources, "os", Windows)
    monkeypatch.setattr(
        sources.shutil,
        "which",
        lambda name: r"C:\Windows\System32\taskkill.exe",
    )
    monkeypatch.setattr(sources.subprocess, "run", run)

    sources.stop_process(process)

    run.assert_called_once_with(
        [r"C:\Windows\System32\taskkill.exe", "/PID", "123", "/T", "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process.wait.assert_called_once_with(timeout=sources.PROCESS_STOP_SECONDS)
    process.terminate.assert_not_called()


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

    result = download_source("https://tiktok.com/@creator/video/123", tmp_path)

    assert result == {
        "path": output,
        "preview_path": output,
        "audio_path": None,
        "filename": output.name,
        "format_id": "best-id",
        "operation": "direct",
        "platform": "tiktok",
        "media_type": "video",
        "preview_type": "video",
        "item_count": 1,
        "media": {"width": 1080, "height": 1920},
    }


def test_download_source_archives_image_post_and_keeps_tiktok_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def download(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        (tmp_path / "one.jpg").write_bytes(b"one")
        (tmp_path / "two.webp").write_bytes(b"two")
        (tmp_path / "sound.mp3").write_bytes(b"sound")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(sources, "_run_gallery_dl", download)

    result = download_source(
        "https://www.tiktok.com/@creator/photo/123", tmp_path
    )

    assert result["media_type"] == "image"
    assert result["item_count"] == 2
    assert result["preview_path"] == tmp_path / "one.jpg"
    assert result["audio_path"] == tmp_path / "sound.mp3"
    assert result["path"] == tmp_path / "images.zip"
    with sources.zipfile.ZipFile(result["path"]) as archive:
        assert archive.namelist() == ["one.jpg", "two.webp"]
    assert not (tmp_path / "two.webp").exists()


def test_download_source_accepts_vsco_video_from_gallery_dl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"

    def download(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        video.write_bytes(b"video")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(sources, "_run_gallery_dl", download)
    monkeypatch.setattr(
        sources,
        "probe_media",
        lambda path, **kwargs: {"width": 1080, "height": 1920, "size": 5},
    )

    result = download_source(
        "https://vsco.co/user/media/abc", tmp_path, quality="1080p"
    )

    assert result["path"] == video
    assert result["preview_type"] == "video"
    assert result["media_type"] == "video"


def test_download_source_rejects_uncapped_progressive_vsco_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def download(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        (tmp_path / "clip.mp4").write_bytes(b"video")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(sources, "_run_gallery_dl", download)
    monkeypatch.setattr(
        sources,
        "probe_media",
        lambda path, **kwargs: {"width": 2160, "height": 3840, "size": 5},
    )

    with pytest.raises(SourceError, match="above the selected source quality"):
        download_source(
            "https://vsco.co/user/media/abc", tmp_path, quality="480p"
        )

    assert list(tmp_path.iterdir()) == []


def test_download_source_archives_mixed_image_and_video_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def download(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        (tmp_path / "one.mp4").write_bytes(b"video")
        (tmp_path / "two.jpg").write_bytes(b"image")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(sources, "_run_gallery_dl", download)

    result = download_source("https://instagram.com/p/example/", tmp_path)

    assert result["media_type"] == "archive"
    assert result["preview_type"] == "video"
    assert result["preview_path"] == tmp_path / "one.mp4"
    assert result["item_count"] == 2
    assert result["path"] == tmp_path / "media.zip"
    with sources.zipfile.ZipFile(result["path"]) as archive:
        assert archive.namelist() == ["one.mp4", "two.jpg"]


def test_download_source_remuxes_facebook_companion_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "facebook-video.mp4"
    audio = tmp_path / "facebook-video.m4a"
    commands: list[list[str]] = []

    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )

    def download(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    def remux(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"combined")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(sources, "_run_gallery_dl", download)
    monkeypatch.setattr(sources, "_find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(sources, "run_bounded_process", remux)
    monkeypatch.setattr(
        sources,
        "probe_media",
        lambda path, **kwargs: {"video_codec": "h264", "audio_codec": "aac"},
    )

    result = download_source("https://facebook.com/watch/?v=123", tmp_path)

    assert result["path"] == tmp_path / "facebook-video-with-audio.mp4"
    assert result["audio_path"] is None
    assert result["operation"] == "remuxed"
    assert commands[0][commands[0].index("-c") + 1] == "copy"
    assert not video.exists()
    assert not audio.exists()


def test_download_source_falls_back_to_original_instagram_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_urls = [
        "https://instagram.test.fbcdn.net/media/one.jpg?stp=original",
        "https://instagram.test.fbcdn.net/media/two.jpg?stp=original",
    ]
    payload = {
        "entries": [
            {
                "id": identifier,
                "formats": [],
                "thumbnails": [
                    {
                        "id": "0",
                        "url": f"https://instagram.test.fbcdn.net/media/{identifier}.jpg?stp=s1080x1080",
                    },
                    {"id": "13", "url": original_url},
                ],
            }
            for identifier, original_url in zip(
                ("one", "two"), original_urls, strict=True
            )
        ]
    }
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )

    def run_yt_dlp(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if "--dump-single-json" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(sources, "_run_yt_dlp", run_yt_dlp)
    requested: list[str] = []

    class Headers:
        @staticmethod
        def get_content_type() -> str:
            return "image/jpeg"

    class Response:
        headers = Headers()

        def __init__(self, url: str) -> None:
            self.url = url
            self.data = f"image:{url}".encode()
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def geturl(self) -> str:
            return self.url

        def read(self, size: int) -> bytes:
            chunk = self.data[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    def open_image(request: object, **kwargs: Any) -> Response:
        url = request.full_url
        requested.append(url)
        return Response(url)

    monkeypatch.setattr(sources, "urlopen", open_image)

    result = download_source(
        "https://www.instagram.com/p/example/?img_index=1", tmp_path
    )

    assert requested == original_urls
    assert result["format_id"] == "instagram-original-images"
    assert result["media_type"] == "image"
    assert result["item_count"] == 2
    assert result["path"] == tmp_path / "images.zip"
    assert result["preview_path"] == tmp_path / "instagram-01-one.jpg"
    with sources.zipfile.ZipFile(result["path"]) as archive:
        assert archive.namelist() == [
            "instagram-01-one.jpg",
            "instagram-02-two.jpg",
        ]


def test_instagram_image_fallback_rejects_untrusted_media_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "entries": [
            {
                "id": "one",
                "formats": [],
                "thumbnails": [{"url": "https://attacker.example/image.jpg"}],
            }
        ]
    }
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0 if "--dump-single-json" in command else 1,
            json.dumps(payload) if "--dump-single-json" in command else "",
            "",
        ),
    )
    monkeypatch.setattr(
        sources,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("untrusted URL was opened"),
    )

    with pytest.raises(SourceError, match="did not provide public media"):
        download_source("https://www.instagram.com/p/example/", tmp_path)


def test_instagram_image_fallback_rejects_partial_mixed_carousel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "entries": [
            {
                "id": "image",
                "formats": [],
                "thumbnails": [
                    {"url": "https://instagram.test.fbcdn.net/media/image.jpg"}
                ],
            },
            {"id": "video", "formats": [{"url": "https://example.invalid"}]},
        ]
    }
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0 if "--dump-single-json" in command else 1,
            json.dumps(payload) if "--dump-single-json" in command else "",
            "",
        ),
    )
    monkeypatch.setattr(
        sources,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("partial carousel was downloaded"),
    )

    with pytest.raises(SourceError, match="did not provide public media"):
        download_source("https://www.instagram.com/p/example/", tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_instagram_image_fallback_stops_when_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "entries": [
            {
                "id": "one",
                "formats": [],
                "thumbnails": [
                    {"url": "https://instagram.test.fbcdn.net/media/one.jpg"}
                ],
            }
        ]
    }
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0 if "--dump-single-json" in command else 1,
            json.dumps(payload) if "--dump-single-json" in command else "",
            "",
        ),
    )

    class Headers:
        @staticmethod
        def get_content_type() -> str:
            return "image/jpeg"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @staticmethod
        def geturl() -> str:
            return "https://instagram.test.fbcdn.net/media/one.jpg"

        @staticmethod
        def read(size: int) -> bytes:
            return b"image"

    monkeypatch.setattr(sources, "urlopen", lambda *args, **kwargs: Response())
    checks = iter((False, False, True))

    with pytest.raises(SourceError, match="cancelled"):
        download_source(
            "https://www.instagram.com/p/example/",
            tmp_path,
            cancel_callback=lambda: next(checks),
        )

    assert list(tmp_path.iterdir()) == []


def test_instagram_image_fallback_cleans_up_interrupted_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "entries": [
            {
                "id": "one",
                "formats": [],
                "thumbnails": [
                    {"url": "https://instagram.test.fbcdn.net/media/one.jpg"}
                ],
            }
        ]
    }
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0 if "--dump-single-json" in command else 1,
            json.dumps(payload) if "--dump-single-json" in command else "",
            "",
        ),
    )

    class Headers:
        @staticmethod
        def get_content_type() -> str:
            return "image/jpeg"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

        @staticmethod
        def geturl() -> str:
            return "https://instagram.test.fbcdn.net/media/one.jpg"

        @staticmethod
        def read(size: int) -> bytes:
            raise IncompleteRead(b"partial")

    monkeypatch.setattr(sources, "urlopen", lambda *args, **kwargs: Response())

    with pytest.raises(SourceError, match="did not provide public media"):
        download_source("https://www.instagram.com/p/example/", tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_source_does_not_extract_tiktok_video_audio_without_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "video.mp4"
    output.write_bytes(b"video")
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, f"FILE:{output}\nFORMAT:best\n", ""
        ),
    )
    monkeypatch.setattr(
        sources,
        "probe_media",
        lambda *args, **kwargs: {"audio_codec": "aac"},
    )

    assert download_source("https://tiktok.com/@creator/video/123", tmp_path)[
        "audio_path"
    ] is None


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
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )

    with pytest.raises(SourceError) as error:
        download_source("https://tiktok.com/@creator/video/123", tmp_path)

    assert str(error.value) == (
        "The source platform did not provide public media for this link. "
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
        download_source("https://tiktok.com/@creator/video/123", destination)


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
        download_source("https://tiktok.com/@creator/video/123", tmp_path)

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
        download_source("https://tiktok.com/@creator/video/123", tmp_path)

    assert [path.name for path in tmp_path.iterdir()] == ["keep.txt"]
