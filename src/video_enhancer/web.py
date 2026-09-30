"""Local web UI for the video enhancer CLI core."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .ffmpeg import (
    AUDIO_EXPORT_FORMATS,
    ENHANCEMENT_TIMEOUT_SECONDS,
    EXPORT_FORMATS,
    SUPPORTED_VIDEO_CODECS,
    EnhancementOptions,
    FFmpegNotFoundError,
    VideoEnhancerError,
    build_export_command,
    build_ffmpeg_command,
    resolve_ffmpeg,
)
from .presets import get_preset
from .sources import (
    MAX_PROCESS_OUTPUT_BYTES,
    MAX_SOURCE_BYTES,
    SourceError,
    download_source,
    run_bounded_process,
    stop_process,
    validate_download_quality,
    validate_social_url,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_JSON_BODY = 20_000
REQUEST_TIMEOUT_SECONDS = 60
API_TOKEN_HEADER = "x-video-enhancer-token"  # nosec B105
TERMS_VERSION = "2026-08-10"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
BIND_HOSTS = {"127.0.0.1", "localhost"}
MODES = {
    "60": {"fps": ["60"], "scale": ["1"], "preset": ["quality"]},
    "90": {"fps": ["90"], "scale": ["1"], "preset": ["ultra"]},
    "upscale": {
        "no_interpolate": ["1"],
        "scale": ["2"],
        "preset": ["quality"],
    },
}


_WEB_ASSETS = Path(__file__).with_name("web_assets")
HTML = (
    (_WEB_ASSETS / "index.html")
    .read_text(encoding="utf-8")
    .replace("__PAGE_STYLE__", (_WEB_ASSETS / "style.css").read_text(encoding="utf-8"))
    .replace("__PAGE_SCRIPT__", (_WEB_ASSETS / "app.js").read_text(encoding="utf-8"))
)


@dataclass
class Job:
    id: str
    input_path: Path
    output_path: Path
    command: list[str]
    kind: str = "enhancement"
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    error: str = ""
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)
    cancelled: bool = False


@dataclass
class SourceJob:
    id: str
    url: str
    directory: Path
    quality: str = "best"
    status: str = "queued"
    original_path: Path | None = None
    preview_path: Path | None = None
    audio_path: Path | None = None
    platform: str = ""
    media_type: str = ""
    preview_type: str = ""
    item_count: int = 0
    media: dict[str, Any] = field(default_factory=dict)
    format_id: str = ""
    operation: str = ""
    error: str = ""
    logs: list[str] = field(default_factory=list)
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)
    cancelled: bool = False


JOBS: dict[str, Job] = {}
SOURCES: dict[str, SourceJob] = {}
LOCK = threading.Lock()


def _remove_work_files(work_dir: Path) -> None:
    if not work_dir.is_dir():
        return
    for path in work_dir.iterdir():
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)


def clear_session(work_dir: Path, *, force: bool = False) -> None:
    """Forget completed jobs and remove this process's local working files."""

    with LOCK:
        busy = any(job.status in {"queued", "running"} for job in JOBS.values())
        busy = busy or any(
            source.status in {"queued", "downloading"} for source in SOURCES.values()
        )
        if busy and not force:
            raise ValueError("Wait for active jobs to finish before clearing files.")
        if force:
            owned_jobs = [*JOBS.values(), *SOURCES.values()]
            for job in owned_jobs:
                job.cancelled = True
            processes = [job.process for job in owned_jobs if job.process]
            threads = [job.thread for job in owned_jobs if job.thread]
        else:
            JOBS.clear()
            SOURCES.clear()
            _remove_work_files(work_dir)
            return

    if force:
        for process in processes:
            stop_process(process)
        current_thread = threading.current_thread()
        for thread in threads:
            if thread is not current_thread:
                thread.join(timeout=REQUEST_TIMEOUT_SECONDS)
        with LOCK:
            JOBS.clear()
            SOURCES.clear()
            _remove_work_files(work_dir)


def safe_filename(name: str, *, default: str = "video.mp4") -> str:
    """Return a pathless filename safe for local output directories."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._")
    return cleaned or default


def bool_param(params: dict[str, list[str]], name: str) -> bool:
    return params.get(name, ["0"])[0].lower() in {"1", "true", "yes", "on"}


def optional_float(params: dict[str, list[str]], name: str) -> float | None:
    value = params.get(name, [""])[0].strip()
    return float(value) if value else None


def optional_int(params: dict[str, list[str]], name: str) -> int | None:
    value = params.get(name, [""])[0].strip()
    return int(value) if value else None


def build_options(params: dict[str, list[str]]) -> EnhancementOptions:
    """Build core enhancement options from web query parameters."""

    codec = params.get("codec", ["libx264"])[0]
    if codec not in SUPPORTED_VIDEO_CODECS:
        raise ValueError(f"Unknown codec: {codec}")
    return EnhancementOptions(
        preset=get_preset(params.get("preset", ["balanced"])[0]),
        scale_factor=optional_float(params, "scale"),
        fps=optional_int(params, "fps"),
        no_upscale=bool_param(params, "no_upscale"),
        no_interpolate=bool_param(params, "no_interpolate"),
        video_codec=codec,
        overwrite=True,
    )


def run_job(job: Job) -> None:
    """Run FFmpeg while exposing only path-free progress to the browser."""

    with LOCK:
        job.status = "running"
        job.logs.append("Export started.")
    try:
        completed = run_bounded_process(
            job.command,
            timeout=ENHANCEMENT_TIMEOUT_SECONDS,
            max_output_bytes=MAX_PROCESS_OUTPUT_BYTES,
            destination=job.output_path.parent,
            max_directory_growth_bytes=MAX_SOURCE_BYTES,
            directory_limit_error="Export exceeds the 8 GiB limit.",
            process_callback=lambda process: own_process(job, process),
            capture_output=False,
        )
    except subprocess.TimeoutExpired:
        job.output_path.unlink(missing_ok=True)
        with LOCK:
            job.status = "error"
            job.error = "Export exceeded the six-hour time limit."
            job.logs.append(job.error)
        return
    except OSError:
        job.output_path.unlink(missing_ok=True)
        with LOCK:
            job.status = "error"
            job.error = "FFmpeg could not start."
            job.logs.append(job.error)
        return
    except SourceError as exc:
        job.output_path.unlink(missing_ok=True)
        with LOCK:
            job.status = "error"
            job.error = str(exc)
            job.logs.append(job.error)
        return

    return_code = completed.returncode
    with LOCK:
        if (
            return_code == 0
            and job.output_path.is_file()
            and job.output_path.stat().st_size
        ):
            job.status = "done"
            job.logs.append("Export finished.")
        else:
            job.output_path.unlink(missing_ok=True)
            job.status = "error"
            job.error = (
                f"FFmpeg failed with exit code {return_code}."
                if return_code
                else "FFmpeg did not create an output file."
            )
            job.logs.append(job.error)


def job_payload(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "kind": job.kind,
        "error": job.error,
        "logs": job.logs,
        "input_name": job.input_path.name,
        "output_name": job.output_path.name,
        "output_url": f"/files/{job.id}/output",
    }


def source_payload(job: SourceJob) -> dict[str, Any]:
    payload = {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "logs": job.logs,
        "media": job.media,
        "format_id": job.format_id,
        "operation": job.operation,
        "platform": job.platform,
        "media_type": job.media_type,
        "preview_type": job.preview_type,
        "item_count": job.item_count,
        "quality": job.quality,
    }
    if job.original_path:
        payload.update(
            {
                "original_name": job.original_path.name,
                "original_url": f"/files/sources/{job.id}/original",
            }
        )
    if job.preview_path:
        payload["preview_url"] = f"/files/sources/{job.id}/preview"
    if job.audio_path:
        payload.update(
            {
                "audio_name": job.audio_path.name,
                "audio_url": f"/files/sources/{job.id}/audio",
            }
        )
    return payload


def own_process(job: Job | SourceJob, process: subprocess.Popen[bytes] | None) -> None:
    should_stop = False
    with LOCK:
        if process is not None and job.cancelled:
            should_stop = True
        else:
            job.process = process
    if should_stop:
        stop_process(process)


def create_enhancement_job(
    input_path: Path,
    original_name: str,
    params: dict[str, list[str]],
    work_dir: Path,
) -> Job:
    original = safe_filename(original_name)
    output_name = safe_filename(
        params.get("output", [f"{Path(original).stem}-enhanced.mp4"])[0],
        default="enhanced.mp4",
    )
    if Path(output_name).suffix.lower() not in {".mp4", ".mkv", ".mov", ".m4v"}:
        output_name = f"{Path(output_name).stem}.mp4"
    return _create_local_job(
        input_path,
        original,
        output_name,
        work_dir,
        "enhancement",
        lambda output_path: build_ffmpeg_command(
            input_path, output_path, build_options(params)
        ),
    )


def _create_local_job(
    input_path: Path,
    original_name: str,
    output_name: str,
    work_dir: Path,
    kind: str,
    command_builder: Callable[[Path], list[str]],
) -> Job:
    with LOCK:
        if any(job.status in {"queued", "running"} for job in JOBS.values()):
            raise ValueError("Wait for the active export to finish.")
        if any(
            source.status in {"queued", "downloading"} for source in SOURCES.values()
        ):
            raise ValueError("Wait for the active source download to finish.")
        job_id = uuid.uuid4().hex[:12]
        job_dir = work_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        output_path = job_dir / output_name
        try:
            command = command_builder(output_path)
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        for previous in JOBS.values():
            shutil.rmtree(previous.output_path.parent, ignore_errors=True)
        JOBS.clear()
        job = Job(job_id, input_path, output_path, command, kind=kind)
        job.logs.append(f"Loaded {original_name}.")
        thread = threading.Thread(target=run_job, args=(job,), daemon=True)
        job.thread = thread
        JOBS[job_id] = job
        try:
            thread.start()
        except Exception:
            JOBS.pop(job_id, None)
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
    return job


def create_export_job(
    input_path: Path,
    original_name: str,
    body: dict[str, Any],
    work_dir: Path,
) -> Job:
    output_format = str(body.get("format", "")).strip().lower()
    if output_format not in EXPORT_FORMATS:
        raise ValueError(f"Output format must be one of: {', '.join(EXPORT_FORMATS)}.")

    def seconds(name: str) -> float | None:
        value = body.get(name)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Clip {name} must be a number of seconds.") from exc

    start_seconds = seconds("start")
    end_seconds = seconds("end")
    original = safe_filename(original_name)
    output_name = safe_filename(
        f"{Path(original).stem}-export.{output_format}",
        default=f"export.{output_format}",
    )
    kind = "audio-export" if output_format in AUDIO_EXPORT_FORMATS else "media-export"
    return _create_local_job(
        input_path,
        original,
        output_name,
        work_dir,
        kind,
        lambda output_path: build_export_command(
            input_path,
            output_path,
            output_format,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        ),
    )


def run_source_download(job: SourceJob) -> None:
    with LOCK:
        job.status = "downloading"
        job.logs.append("Original source download started.")
    try:
        result = download_source(
            job.url,
            job.directory,
            quality=job.quality,
            process_callback=lambda process: own_process(job, process),
            cancel_callback=lambda: job.cancelled,
        )
    except (OSError, SourceError) as exc:
        shutil.rmtree(job.directory, ignore_errors=True)
        with LOCK:
            job.status = "error"
            job.error = str(exc)
            job.logs.append(str(exc))
        return
    with LOCK:
        job.original_path = result["path"]
        job.preview_path = result["preview_path"]
        job.audio_path = result["audio_path"]
        job.platform = result["platform"]
        job.media_type = result["media_type"]
        job.preview_type = result.get("preview_type", job.media_type)
        job.item_count = result["item_count"]
        job.media = result["media"]
        job.format_id = result["format_id"]
        job.operation = result["operation"]
        job.status = "done"
        job.logs.append("Original source download finished.")


class Handler(BaseHTTPRequestHandler):
    work_dir = Path()
    session_token = ""  # nosec B105

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT_SECONDS)

    def log_message(self, _format: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("cache-control", "no-store")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("x-frame-options", "DENY")
        self.send_header("referrer-policy", "no-referrer")
        self.send_header("cross-origin-opener-policy", "same-origin")
        self.send_header("cross-origin-resource-policy", "same-origin")
        self.send_header(
            "permissions-policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        nonce = getattr(self, "response_nonce", "")
        inline_policy = (
            f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            if nonce
            else "script-src 'none'; style-src 'none'; "
        )
        self.send_header(
            "content-security-policy",
            "default-src 'none'; "
            f"{inline_policy}"
            "img-src 'self'; media-src 'self' blob:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        super().end_headers()

    def allow_request(self, parsed: Any, *, token_required: bool) -> bool:
        try:
            host = urlparse(f"//{self.headers.get('host', '')}").hostname
        except ValueError:
            host = None
        if not host or host.lower().rstrip(".") not in LOCAL_HOSTS:
            self.send_error(HTTPStatus.MISDIRECTED_REQUEST.value)
            return False
        if not token_required:
            return True
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        supplied = self.headers.get(API_TOKEN_HEADER, "") or query_token
        if not self.session_token or not secrets.compare_digest(
            supplied, self.session_token
        ):
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid local session."})
            return False
        return True

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "application/json":
            raise ValueError("JSON requests require application/json.")
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid content length.") from exc
        if length < 0:
            raise ValueError("Invalid content length.")
        if length > MAX_JSON_BODY:
            raise ValueError("JSON request body is too large.")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON request body.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object.")  # noqa: TRY004
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        token_required = parsed.path.startswith(("/api/", "/files/"))
        if not self.allow_request(parsed, token_required=token_required):
            return
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT.value)
            self.end_headers()
            return
        if parsed.path == "/":
            self.response_nonce = secrets.token_urlsafe(18)
            body = HTML.replace("__CSP_NONCE__", self.response_nonce).encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/config":
            ffmpeg = "found"
            try:
                resolve_ffmpeg()
            except FFmpegNotFoundError:
                ffmpeg = "not found"
            self.send_json(
                HTTPStatus.OK,
                {"ffmpeg": ffmpeg},
            )
            return
        if parsed.path.startswith("/api/sources/"):
            source_id = parsed.path.rsplit("/", 1)[-1]
            with LOCK:
                source = SOURCES.get(source_id)
                payload = source_payload(source) if source else None
            if not payload:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Source job not found"})
                return
            self.send_json(HTTPStatus.OK, payload)
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with LOCK:
                job = JOBS.get(job_id)
                payload = job_payload(job) if job else None
            if not payload:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Job not found"})
                return
            self.send_json(HTTPStatus.OK, payload)
            return
        if parsed.path.startswith("/files/sources/"):
            self.serve_source_file(
                parsed.path,
                attachment=parse_qs(parsed.query).get("download") == ["1"],
            )
            return
        if parsed.path.startswith("/files/"):
            self.serve_job_file(
                parsed.path,
                attachment=parse_qs(parsed.query).get("download") == ["1"],
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND.value)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self.allow_request(parsed, token_required=True):
            return
        try:
            if parsed.path == "/api/session/clear":
                self.read_json()
                clear_session(self.work_dir)
                self.send_json(HTTPStatus.OK, {"cleared": True})
                return
            if parsed.path == "/api/sources/download":
                self.send_json(
                    HTTPStatus.ACCEPTED, self.create_source_job(self.read_json())
                )
                return
            if parsed.path.startswith("/api/sources/"):
                self.handle_source_action(parsed.path, self.read_json())
                return
        except (OSError, SourceError, ValueError, VideoEnhancerError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self.send_error(HTTPStatus.NOT_FOUND.value)

    def create_source_job(self, body: dict[str, Any]) -> dict[str, Any]:
        if (
            body.get("terms_accepted") is not True
            or body.get("terms_version") != TERMS_VERSION
        ):
            raise ValueError(
                "Accept the current Terms of Use before downloading media."
            )
        url = str(body.get("url", "")).strip()
        platform = validate_social_url(url)
        quality = validate_download_quality(str(body.get("quality", "best")))
        source_id = uuid.uuid4().hex[:12]
        directory = self.work_dir / f"source-{source_id}"
        source = SourceJob(
            source_id,
            url,
            directory,
            quality=quality,
            platform=platform,
        )
        with LOCK:
            if any(job.status in {"queued", "running"} for job in JOBS.values()):
                raise ValueError("Wait for the active export to finish.")
            if any(job.status in {"queued", "downloading"} for job in SOURCES.values()):
                raise ValueError("Wait for the active source download to finish.")
            JOBS.clear()
            SOURCES.clear()
            _remove_work_files(self.work_dir)
            thread = threading.Thread(
                target=run_source_download,
                args=(source,),
                daemon=True,
            )
            source.thread = thread
            SOURCES[source_id] = source
            try:
                thread.start()
            except Exception:
                SOURCES.pop(source_id, None)
                raise
        return source_payload(source)

    def handle_source_action(self, request_path: str, body: dict[str, Any]) -> None:
        parts = request_path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "sources"]:
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        source_id, action = parts[2], parts[3]
        with LOCK:
            source = SOURCES.get(source_id)
        if not source:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Source job not found"})
            return
        if action == "enhance":
            if body.get("local_processing_accepted") is not True:
                raise ValueError("Confirm local device processing before enhancing.")
            if source.status != "done" or not source.original_path:
                raise ValueError("Download the original source before enhancing it.")
            if source.media_type != "video":
                raise ValueError("Only downloaded videos can be enhanced.")
            mode = str(body.get("mode", "")).strip()
            if mode not in MODES:
                raise ValueError("Enhancement mode must be 60, 90, or upscale.")
            params = {key: list(value) for key, value in MODES[mode].items()}
            suffix = {"60": "60fps", "90": "90fps", "upscale": "2x"}[mode]
            params["output"] = [f"{source.original_path.stem}-{suffix}.mp4"]
            job = create_enhancement_job(
                source.original_path,
                source.original_path.name,
                params,
                self.work_dir,
            )
            self.send_json(HTTPStatus.ACCEPTED, job_payload(job))
            return
        if action == "export":
            if body.get("local_processing_accepted") is not True:
                raise ValueError("Confirm local device processing before exporting.")
            if source.status != "done" or not source.original_path:
                raise ValueError("Download the original source before exporting it.")
            if source.media_type != "video":
                raise ValueError("Only downloaded videos can be converted or trimmed.")
            job = create_export_job(
                source.original_path,
                source.original_path.name,
                body,
                self.work_dir,
            )
            self.send_json(HTTPStatus.ACCEPTED, job_payload(job))
            return
        self.send_error(HTTPStatus.NOT_FOUND.value)

    def serve_source_file(self, request_path: str, *, attachment: bool = False) -> None:
        parts = request_path.strip("/").split("/")
        if len(parts) < 3 or parts[:2] != ["files", "sources"]:
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        with LOCK:
            source = SOURCES.get(parts[2])
            if len(parts) == 4 and source:
                file = {
                    "original": source.original_path,
                    "preview": source.preview_path,
                    "audio": source.audio_path,
                }.get(parts[3])
                content_type = (
                    mimetypes.guess_type(file.name)[0] if file else None
                ) or "application/octet-stream"
            else:
                file = None
                content_type = "application/octet-stream"
        root = self.work_dir.resolve()
        if not file or not file.is_file() or not file.resolve().is_relative_to(root):
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        self.serve_file(file, content_type, attachment=attachment)

    def serve_job_file(self, request_path: str, *, attachment: bool = False) -> None:
        parts = request_path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "files":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        _, job_id, kind = parts
        with LOCK:
            job = JOBS.get(job_id)
            file = job.output_path if job and kind == "output" else None
        root = self.work_dir.resolve()
        if not file or not file.is_file() or not file.resolve().is_relative_to(root):
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        content_type = {
            ".avi": "video/x-msvideo",
            ".gif": "image/gif",
            ".mov": "video/quicktime",
        }.get(file.suffix.lower()) or mimetypes.guess_type(file.name)[0]
        content_type = content_type or "application/octet-stream"
        self.serve_file(file, content_type, attachment=attachment)

    def serve_file(
        self, file: Path, content_type: str, *, attachment: bool = False
    ) -> None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(file, flags)
            try:
                source = os.fdopen(descriptor, "rb")
            except Exception:
                os.close(descriptor)
                raise
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                source.close()
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        try:
            size = metadata.st_size
            start, end = 0, size - 1
            status = HTTPStatus.OK
            requested_range = self.headers.get("range", "").strip()
            if requested_range:
                match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", requested_range)
                if not match or not any(match.groups()):
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE.value)
                    self.send_header("content-range", f"bytes */{size}")
                    self.end_headers()
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    suffix = int(last)
                    start = max(0, size - suffix)
                if start >= size or start > end or (not first and int(last) == 0):
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE.value)
                    self.send_header("content-range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT

            length = max(0, end - start + 1)
            self.send_response(status.value)
            self.send_header("content-type", content_type)
            self.send_header("accept-ranges", "bytes")
            self.send_header("content-length", str(length))
            if status is HTTPStatus.PARTIAL_CONTENT:
                self.send_header("content-range", f"bytes {start}-{end}/{size}")
            disposition = "attachment" if attachment else "inline"
            ascii_name = safe_filename(file.name, default="download")
            if file.suffix and not Path(ascii_name).suffix:
                ascii_name = f"download{file.suffix.lower()}"
            content_disposition = f'{disposition}; filename="{ascii_name}"'
            if ascii_name != file.name:
                content_disposition += f"; filename*=UTF-8''{quote(file.name, safe='')}"
            self.send_header("content-disposition", content_disposition)
            self.end_headers()
            source.seek(start)
            remaining = length
            while remaining and (chunk := source.read(min(1024 * 1024, remaining))):
                self.wfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        finally:
            source.close()


def _interrupt_server(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


def _serve(host: str, port: int, work_dir: Path, *, open_browser: bool = False) -> None:
    Handler.work_dir = work_dir
    Handler.session_token = secrets.token_hex(32)
    work_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = False
    url = f"http://{host}:{server.server_port}/#token={Handler.session_token}"
    print(f"Video Enhancer Web running at {url}")
    if open_browser:
        webbrowser.open(url)
    previous_handlers: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        for name in ("SIGTERM", "SIGHUP"):
            if signum := getattr(signal, name, None):
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, _interrupt_server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        for signum in previous_handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            server.server_close()
            clear_session(work_dir, force=True)
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def run_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    open_browser: bool = False,
) -> None:
    if host.lower().rstrip(".") not in BIND_HOSTS:
        raise ValueError("Video Enhancer can only bind to this device.")
    with tempfile.TemporaryDirectory(prefix="video-enhancer-") as temporary:
        _serve(host, port, Path(temporary), open_browser=open_browser)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Video Enhancer web UI.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--open", action="store_true", help="open the UI in the default browser"
    )
    args = parser.parse_args()
    run_server(port=args.port, open_browser=args.open)


if __name__ == "__main__":
    main()
