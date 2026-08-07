"""Download supported social videos without exposing media URLs."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SUPPORTED_HOSTS = {"tiktok.com": "tiktok", "instagram.com": "instagram"}
BEST_FORMAT = "bv*+ba/b"
BEST_FORMAT_SORT = "res,fps,quality,hdr:12,vcodec,size,br,asr,source"
DOWNLOAD_TIMEOUT_SECONDS = 900
SOCKET_TIMEOUT_SECONDS = 30
NETWORK_RETRIES = 3
MAX_SOURCE_SIZE = "8G"
MAX_SOURCE_BYTES = 8 * 1024**3
MAX_PROCESS_OUTPUT_BYTES = 16 * 1024**2
MAX_YT_DLP_OUTPUT_BYTES = MAX_PROCESS_OUTPUT_BYTES
MAX_PROBE_OUTPUT_BYTES = 4 * 1024**2
PROBE_TIMEOUT_SECONDS = 120
PROCESS_POLL_SECONDS = 0.05
PROCESS_STOP_SECONDS = 2

ProcessCallback = Callable[[subprocess.Popen[bytes] | None], None]


class SourceError(ValueError):
    """Raised when a source URL or download result is invalid."""


def _directory_size(directory: Path) -> int:
    total = 0
    pending = [directory]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except FileNotFoundError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except FileNotFoundError:
                continue
    return total


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        elif os.name == "nt":
            if taskkill := shutil.which("taskkill.exe"):
                subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process.kill()
        else:
            process.terminate()
        process.wait(timeout=PROCESS_STOP_SECONDS)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
        process.wait()


def run_bounded_process(
    command: list[str],
    *,
    timeout: float,
    max_output_bytes: int,
    destination: Path | None = None,
    max_directory_growth_bytes: int | None = None,
    output_limit_error: str = "Process produced too much output.",
    directory_limit_error: str = "Process created too much data.",
    process_callback: ProcessCallback | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a process group with bounded output, time, and directory growth."""

    baseline_size = _directory_size(destination) if destination else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    if process_callback:
        process_callback(process)
    stdout, stderr = process.stdout, process.stderr
    if capture_output and (stdout is None or stderr is None):
        stop_process(process)
        if process_callback:
            process_callback(None)
        raise SourceError("Process output pipes could not be created.")
    buffers = [bytearray(), bytearray()]
    output_size = 0
    output_limit_reached = threading.Event()
    output_lock = threading.Lock()

    def drain(index: int, stream: Any) -> None:
        nonlocal output_size
        try:
            while chunk := stream.read(64 * 1024):
                with output_lock:
                    remaining = max(0, max_output_bytes - output_size)
                    buffers[index].extend(chunk[:remaining])
                    output_size += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        output_limit_reached.set()
        finally:
            stream.close()

    readers = (
        [
            threading.Thread(target=drain, args=(0, stdout), daemon=True),
            threading.Thread(target=drain, args=(1, stderr), daemon=True),
        ]
        if stdout is not None and stderr is not None
        else []
    )
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout
    failure: BaseException | None = None
    while process.poll() is None:
        if output_limit_reached.is_set():
            failure = SourceError(output_limit_error)
        elif (
            destination
            and max_directory_growth_bytes is not None
            and _directory_size(destination) - baseline_size
            > max_directory_growth_bytes
        ):
            failure = SourceError(directory_limit_error)
        elif time.monotonic() >= deadline:
            failure = subprocess.TimeoutExpired(command, timeout)
        if failure:
            stop_process(process)
            break
        time.sleep(PROCESS_POLL_SECONDS)

    return_code = process.wait()
    for reader in readers:
        reader.join()
    if process_callback:
        process_callback(None)
    if failure:
        raise failure
    if output_limit_reached.is_set():
        raise SourceError(output_limit_error)
    if (
        destination
        and max_directory_growth_bytes is not None
        and _directory_size(destination) - baseline_size
        > max_directory_growth_bytes
    ):
        raise SourceError(directory_limit_error)
    return subprocess.CompletedProcess(
        command,
        return_code,
        buffers[0].decode("utf-8", "replace"),
        buffers[1].decode("utf-8", "replace"),
    )


def _run_yt_dlp(
    command: list[str],
    *,
    timeout: float,
    destination: Path | None = None,
    max_output_bytes: int = MAX_YT_DLP_OUTPUT_BYTES,
    max_download_bytes: int | None = None,
    process_callback: ProcessCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run yt-dlp with bounded output, time, and optional download growth."""

    return run_bounded_process(
        command,
        timeout=timeout,
        max_output_bytes=max_output_bytes,
        destination=destination,
        max_directory_growth_bytes=max_download_bytes,
        output_limit_error="yt-dlp produced too much output.",
        directory_limit_error="The source download exceeds the 8 GiB limit.",
        process_callback=process_callback,
    )


def _yt_dlp_command(yt_dlp: str) -> list[str]:
    packaged = os.environ.get("VIDEO_ENHANCER_YT_DLP") if yt_dlp == "yt-dlp" else None
    ffmpeg = os.environ.get("VIDEO_ENHANCER_FFMPEG")
    executable = (
        [packaged]
        if packaged
        else [sys.executable, "-m", "yt_dlp"]
        if yt_dlp == "yt-dlp"
        else [yt_dlp]
    )
    return [
        *executable,
        "--ignore-config",
        "--no-config-locations",
        "--no-plugin-dirs",
        "--no-cache-dir",
        "--no-exec",
        "--no-cookies-from-browser",
        "--no-playlist",
        "--no-progress",
        *(["--ffmpeg-location", ffmpeg] if ffmpeg else []),
        "--downloader",
        "native",
    ]


def validate_social_url(raw: str) -> str:
    try:
        parsed = urlsplit(raw.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise SourceError("Use an HTTPS TikTok or Instagram video URL.") from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise SourceError("Use an HTTPS TikTok or Instagram video URL.")
    host = host.lower().rstrip(".")
    for domain, platform in SUPPORTED_HOSTS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    raise SourceError("Only TikTok and Instagram video URLs are supported.")


def build_download_command(
    url: str,
    destination: Path,
    *,
    yt_dlp: str = "yt-dlp",
) -> list[str]:
    normalized_url = url.strip()
    validate_social_url(normalized_url)
    return [
        *_yt_dlp_command(yt_dlp),
        "--no-overwrites",
        "--max-filesize",
        MAX_SOURCE_SIZE,
        "--socket-timeout",
        str(SOCKET_TIMEOUT_SECONDS),
        "--retries",
        str(NETWORK_RETRIES),
        "--fragment-retries",
        str(NETWORK_RETRIES),
        "--restrict-filenames",
        "--windows-filenames",
        "--format-sort",
        BEST_FORMAT_SORT,
        "-f",
        BEST_FORMAT,
        "-o",
        str(destination / "%(title).80s-%(id)s.%(ext)s"),
        "--print",
        "after_move:FILE:%(filepath)s",
        "--print",
        "after_move:FORMAT:%(format_id)s",
        normalized_url,
    ]


def _number(value: Any, cast: type[int | float]) -> int | float | None:
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
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), {}
    )
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), {}
    )
    if not video:
        raise SourceError("The downloaded file has no video stream.")
    format_data = (
        payload.get("format") if isinstance(payload.get("format"), dict) else {}
    )
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
    seconds = (
        int(duration.group(1)) * 3600
        + int(duration.group(2)) * 60
        + float(duration.group(3))
        if duration
        else None
    )
    return {
        "width": int(dimensions.group(1)) if dimensions else None,
        "height": int(dimensions.group(2)) if dimensions else None,
        "fps": float(fps.group(1)) if fps else None,
        "video_codec": video_codec.group(1) if video_codec else None,
        "audio_codec": audio_codec.group(1) if audio_codec else None,
        "video_bitrate": int(float(video_bitrate.group(1)) * 1000)
        if video_bitrate
        else None,
        "bitrate": int(duration.group(4)) * 1000 if duration else None,
        "duration": seconds,
        "size": None,
    }


def probe_media(
    path: Path,
    *,
    ffprobe: str = "ffprobe",
    ffmpeg: str = "ffmpeg",
    process_callback: ProcessCallback | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        raise SourceError(f"Downloaded file does not exist: {path}")
    ffprobe_path = shutil.which(ffprobe)
    if ffprobe_path:
        try:
            completed = run_bounded_process(
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
                timeout=PROBE_TIMEOUT_SECONDS,
                max_output_bytes=MAX_PROBE_OUTPUT_BYTES,
                output_limit_error="Media verification produced too much output.",
                process_callback=process_callback,
            )
        except subprocess.TimeoutExpired as exc:
            raise SourceError("Media verification timed out.") from exc
        except OSError:
            completed = None
        if completed and completed.returncode == 0:
            try:
                media = parse_ffprobe(json.loads(completed.stdout))
                media["size"] = path.stat().st_size
                return media
            except (json.JSONDecodeError, SourceError):
                pass

    ffmpeg_name = (
        os.environ.get("VIDEO_ENHANCER_FFMPEG", ffmpeg)
        if ffmpeg == "ffmpeg"
        else ffmpeg
    )
    ffmpeg_path = shutil.which(ffmpeg_name)
    if not ffmpeg_path and Path(ffmpeg_name).is_file():
        ffmpeg_path = ffmpeg_name
    if not ffmpeg_path:
        raise SourceError("FFmpeg or ffprobe is required to verify the downloaded file.")
    try:
        completed = run_bounded_process(
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
            timeout=PROBE_TIMEOUT_SECONDS,
            max_output_bytes=MAX_PROBE_OUTPUT_BYTES,
            output_limit_error="Media verification produced too much output.",
            process_callback=process_callback,
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceError("Media verification timed out.") from exc
    except OSError as exc:
        raise SourceError(f"Could not start FFmpeg: {exc}") from exc
    media = _parse_ffmpeg_probe(completed.stderr)
    media["size"] = path.stat().st_size
    return media


def _remove_new_entries(destination: Path, existing: set[str]) -> None:
    for path in destination.iterdir():
        if path.name in existing:
            continue
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)


def download_source(
    url: str,
    destination: Path,
    *,
    yt_dlp: str = "yt-dlp",
    process_callback: ProcessCallback | None = None,
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    command = build_download_command(url, destination, yt_dlp=yt_dlp)
    existing = {path.name for path in destination.iterdir()}
    try:
        completed = _run_yt_dlp(
            command,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            destination=destination,
            max_download_bytes=MAX_SOURCE_BYTES,
            process_callback=process_callback,
        )
    except subprocess.TimeoutExpired as exc:
        _remove_new_entries(destination, existing)
        raise SourceError("The source download timed out.") from exc
    except OSError as exc:
        _remove_new_entries(destination, existing)
        raise SourceError(f"Could not start yt-dlp: {exc}") from exc
    except SourceError:
        _remove_new_entries(destination, existing)
        raise
    if completed.returncode:
        _remove_new_entries(destination, existing)
        raise SourceError(
            "The source platform did not provide this public video. "
            "Check that the link is public and try again."
        )

    try:
        values: dict[str, str] = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition(":")
            if separator and key in {"FILE", "FORMAT"}:
                values[key] = value.strip()
        file_path = Path(values.get("FILE", "")).resolve()
        root = destination.resolve()
        if not file_path.is_relative_to(root) or not file_path.is_file():
            raise SourceError("Download completed, but the saved file was not found.")
        if file_path.stat().st_size > MAX_SOURCE_BYTES:
            file_path.unlink(missing_ok=True)
            raise SourceError("The downloaded source exceeds the 8 GiB limit.")
        selected = values.get("FORMAT", "best")
        return {
            "path": file_path,
            "filename": file_path.name,
            "format_id": selected,
            "operation": "remuxed" if "+" in selected else "direct",
            "media": probe_media(file_path, process_callback=process_callback),
        }
    except (OSError, SourceError):
        _remove_new_entries(destination, existing)
        raise
