"""Inspect supported social video sources without exposing media URLs."""

from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import quote_plus, urlsplit


SUPPORTED_HOSTS = {"tiktok.com": "tiktok", "instagram.com": "instagram"}
FORMAT_FIELDS = ("width", "height", "fps", "tbr", "vcodec", "acodec", "ext")
BEST_FORMAT = "bv*+ba/b"
INSPECTION_TIMEOUT_SECONDS = 120
DOWNLOAD_TIMEOUT_SECONDS = 900
SOCKET_TIMEOUT_SECONDS = 30
NETWORK_RETRIES = 3
MAX_SOURCE_SIZE = "8G"
MAX_SOURCE_BYTES = 8 * 1024**3
MAX_YT_DLP_OUTPUT_BYTES = 16 * 1024**2
PROBE_TIMEOUT_SECONDS = 120
PROCESS_POLL_SECONDS = 0.05
PROCESS_STOP_SECONDS = 2


class SourceError(ValueError):
    """Raised when a source URL or inspection result is invalid."""


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


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
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


def _run_yt_dlp(
    command: list[str],
    *,
    timeout: float,
    destination: Path | None = None,
    max_output_bytes: int = MAX_YT_DLP_OUTPUT_BYTES,
    max_download_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run yt-dlp with bounded output, time, and optional download growth."""

    baseline_size = _directory_size(destination) if destination else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    stdout, stderr = process.stdout, process.stderr
    if stdout is None or stderr is None:
        _stop_process(process)
        raise SourceError("yt-dlp output pipes could not be created.")
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

    readers = [
        threading.Thread(target=drain, args=(0, stdout), daemon=True),
        threading.Thread(target=drain, args=(1, stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout
    failure: BaseException | None = None
    while process.poll() is None:
        if output_limit_reached.is_set():
            failure = SourceError("yt-dlp produced too much output.")
        elif (
            destination
            and max_download_bytes is not None
            and _directory_size(destination) - baseline_size > max_download_bytes
        ):
            failure = SourceError("The source download exceeds the 8 GiB limit.")
        elif time.monotonic() >= deadline:
            failure = subprocess.TimeoutExpired(command, timeout)
        if failure:
            _stop_process(process)
            break
        time.sleep(PROCESS_POLL_SECONDS)

    return_code = process.wait()
    for reader in readers:
        reader.join()
    if failure:
        raise failure
    if output_limit_reached.is_set():
        raise SourceError("yt-dlp produced too much output.")
    if (
        destination
        and max_download_bytes is not None
        and _directory_size(destination) - baseline_size > max_download_bytes
    ):
        raise SourceError("The source download exceeds the 8 GiB limit.")
    return subprocess.CompletedProcess(
        command,
        return_code,
        buffers[0].decode("utf-8", "replace"),
        buffers[1].decode("utf-8", "replace"),
    )


def _yt_dlp_command(yt_dlp: str) -> list[str]:
    executable = [sys.executable, "-m", "yt_dlp"] if yt_dlp == "yt-dlp" else [yt_dlp]
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


def inspect_source(url: str, *, yt_dlp: str = "yt-dlp") -> dict[str, Any]:
    normalized_url = url.strip()
    platform = validate_social_url(normalized_url)
    command = [
        *_yt_dlp_command(yt_dlp),
        "--socket-timeout",
        str(SOCKET_TIMEOUT_SECONDS),
        "--retries",
        str(NETWORK_RETRIES),
        "--skip-download",
        "--dump-single-json",
        normalized_url,
    ]
    try:
        completed = _run_yt_dlp(
            command,
            timeout=INSPECTION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceError("Source inspection timed out.") from exc
    except OSError as exc:
        raise SourceError(f"Could not start yt-dlp: {exc}") from exc
    if completed.returncode:
        detail = (
            completed.stderr.strip()[-4000:] or "yt-dlp could not inspect the source."
        )
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
    format_id: str = "",
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
        "-f",
        _selected_format(format_id),
        "-o",
        str(destination / "%(title).80s-%(id)s.%(ext)s"),
        "--print",
        "after_move:FILE:%(filepath)s",
        "--print",
        "after_move:FORMAT:%(format_id)s",
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
    seconds = None
    bitrate = None
    if duration:
        seconds = (
            int(duration.group(1)) * 3600
            + int(duration.group(2)) * 60
            + float(duration.group(3))
        )
        bitrate = int(duration.group(4)) * 1000
    return {
        "width": int(dimensions.group(1)) if dimensions else None,
        "height": int(dimensions.group(2)) if dimensions else None,
        "fps": float(fps.group(1)) if fps else None,
        "video_codec": video_codec.group(1) if video_codec else None,
        "audio_codec": audio_codec.group(1) if audio_codec else None,
        "video_bitrate": int(float(video_bitrate.group(1)) * 1000)
        if video_bitrate
        else None,
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
        try:
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
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed and completed.returncode == 0:
            try:
                media = parse_ffprobe(json.loads(completed.stdout))
                media["size"] = path.stat().st_size
                return media
            except (json.JSONDecodeError, SourceError):
                pass

    ffmpeg_path = shutil.which(ffmpeg)
    if not ffmpeg_path:
        raise SourceError("FFmpeg is required to verify the downloaded file.")
    try:
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
            timeout=PROBE_TIMEOUT_SECONDS,
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
    format_id: str = "",
    *,
    yt_dlp: str = "yt-dlp",
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    if format_id:
        inspected = inspect_source(url, yt_dlp=yt_dlp)
        available = {
            current
            for group in inspected.get("formats", [])
            for current in group.get("format_ids", [])
        }
        if format_id not in available:
            raise SourceError("The selected source format is no longer available.")

    command = build_download_command(url, destination, format_id, yt_dlp=yt_dlp)
    existing = {path.name for path in destination.iterdir()}
    try:
        completed = _run_yt_dlp(
            command,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            destination=destination,
            max_download_bytes=MAX_SOURCE_BYTES,
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
        detail = (
            completed.stderr.strip()[-4000:] or "yt-dlp could not download the source."
        )
        raise SourceError(detail)

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
        selected = values.get("FORMAT", format_id or "best")
        return {
            "path": file_path,
            "filename": file_path.name,
            "format_id": selected,
            "operation": "remuxed" if "+" in selected else "direct",
            "media": probe_media(file_path),
        }
    except (OSError, SourceError):
        _remove_new_entries(destination, existing)
        raise


def search_links(info: dict[str, Any]) -> dict[str, str]:
    title = str(info.get("title", "")).strip()
    suffix = " ".join(
        str(info.get(key, "")).strip() for key in ("uploader", "id")
    ).strip()
    terms = " ".join(part for part in (f'"{title}"' if title else "", suffix) if part)
    encoded = quote_plus(terms)
    return {
        "web": f"https://www.google.com/search?q={encoded}",
        "tiktok": f"https://www.google.com/search?q={quote_plus(f'site:tiktok.com {terms}')}",
        "instagram": f"https://www.google.com/search?q={quote_plus(f'site:instagram.com {terms}')}",
        "google_lens": "https://lens.google.com/",
        "tineye": "https://tineye.com/",
    }


def _ffmpeg_executable(ffmpeg: str) -> str:
    executable = shutil.which(ffmpeg)
    if not executable:
        raise SourceError("FFmpeg is required for frame extraction.")
    return executable


def _duration(path: Path, ffmpeg: str) -> float:
    duration = probe_media(path, ffmpeg=ffmpeg).get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise SourceError("The video duration is unavailable for frame extraction.")
    return float(duration)


def extract_keyframes(
    path: Path, destination: Path, *, ffmpeg: str = "ffmpeg"
) -> list[Path]:
    executable = _ffmpeg_executable(ffmpeg)
    duration = _duration(path, ffmpeg)
    destination.mkdir(parents=True, exist_ok=True)
    frames = [destination / f"frame-{index}.jpg" for index in range(1, 4)]
    for frame, fraction in zip(frames, (0.25, 0.5, 0.75), strict=True):
        try:
            completed = subprocess.run(
                [
                    executable,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{duration * fraction:.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale='min(960,iw)':-2",
                    "-q:v",
                    "2",
                    "-y",
                    str(frame),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            for output in frames:
                output.unlink(missing_ok=True)
            raise SourceError(f"Could not extract keyframes: {exc}") from exc
        if completed.returncode or not frame.is_file():
            for output in frames:
                output.unlink(missing_ok=True)
            detail = (
                completed.stderr.strip()[-2000:] or "FFmpeg did not create a keyframe."
            )
            raise SourceError(detail)
    return frames


def frame_hash(raw: bytes, width: int = 17, height: int = 16) -> int:
    if len(raw) != width * height:
        raise SourceError("Unexpected grayscale frame size.")
    result = 0
    for row in range(height):
        offset = row * width
        for column in range(width - 1):
            result = (result << 1) | (raw[offset + column] < raw[offset + column + 1])
    return result


def sample_frame_hashes(
    path: Path, count: int = 5, *, ffmpeg: str = "ffmpeg"
) -> list[int]:
    if count < 1 or count > 10:
        raise SourceError("Frame sample count must be between 1 and 10.")
    executable = _ffmpeg_executable(ffmpeg)
    duration = _duration(path, ffmpeg)
    hashes = []
    for index in range(1, count + 1):
        try:
            completed = subprocess.run(
                [
                    executable,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{duration * index / (count + 1):.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=17:16,format=gray",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ],
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceError(f"Could not sample video frames: {exc}") from exc
        if completed.returncode:
            detail = completed.stderr.decode("utf-8", "replace").strip()[-2000:]
            raise SourceError(detail or "FFmpeg could not sample the video.")
        hashes.append(frame_hash(completed.stdout))
    return hashes


def compare_hashes(left: list[int], right: list[int]) -> dict[str, Any]:
    if not left or len(left) != len(right):
        raise SourceError("Frame hash lists must have the same number of samples.")
    similarities = [
        1 - ((left_hash ^ right_hash).bit_count() / 256)
        for left_hash, right_hash in zip(left, right, strict=True)
    ]
    score = median(similarities)
    result = (
        "likely_match"
        if score >= 0.85
        else "uncertain"
        if score >= 0.65
        else "different"
    )
    return {"result": result, "score": round(score, 4), "advisory": True}
