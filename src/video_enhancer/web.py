"""Local web UI for the video enhancer CLI core."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .encoders import supported_video_codecs
from .ffmpeg import (
    EnhancementOptions,
    FFmpegNotFoundError,
    VideoEnhancerError,
    build_ffmpeg_command,
    format_command,
    resolve_ffmpeg,
)
from .presets import available_presets, get_preset

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_WORK_DIR = Path("outputs/web")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Enhancer Web</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #fff;
      --ink: #101820;
      --muted: #617085;
      --line: #d7e0ea;
      --accent: #0d7f86;
      --accent-dark: #095f64;
      --log: #101820;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      padding: 22px 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.84);
      backdrop-filter: blur(16px);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 22px; line-height: 1.1; }
    .sub { margin-top: 5px; color: var(--muted); font-size: 14px; }
    .status-pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 9px 12px;
      background: #fff;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    main {
      display: grid;
      grid-template-columns: minmax(330px, 520px) minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      max-width: 1500px;
      margin: 0 auto;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 16px 45px rgba(22, 34, 48, .06);
    }
    .panel-inner { padding: 18px; }
    .section + .section {
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }
    h2 { margin-bottom: 14px; font-size: 16px; }
    label { display: block; color: var(--muted); font-size: 13px; font-weight: 700; }
    input, select, button {
      width: 100%;
      min-height: 42px;
      border-radius: 7px;
      font: inherit;
      letter-spacing: 0;
    }
    input, select {
      margin-top: 7px;
      border: 1px solid var(--line);
      padding: 0 11px;
      background: #fff;
      color: var(--ink);
    }
    input:focus, select:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(13, 127, 134, .13);
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .check {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 42px;
      color: var(--ink);
      font-weight: 700;
    }
    .check input {
      width: 18px;
      min-height: 18px;
      margin: 0;
    }
    button {
      border: 0;
      padding: 0 16px;
      background: var(--accent);
      color: #fff;
      font-weight: 850;
      cursor: pointer;
    }
    button:hover { background: var(--accent-dark); }
    button:disabled { cursor: not-allowed; opacity: .62; }
    .secondary {
      display: inline-grid;
      place-items: center;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 14px;
      background: #fff;
      color: var(--ink);
      font-weight: 800;
      text-decoration: none;
    }
    .filebox {
      display: grid;
      gap: 10px;
      border: 1px dashed #b7c5d4;
      border-radius: 8px;
      padding: 16px;
      background: #fbfdff;
    }
    .hint { color: var(--muted); font-size: 13px; line-height: 1.45; }
    video {
      width: 100%;
      aspect-ratio: 16 / 9;
      border-radius: 8px;
      background: #101820;
      display: block;
    }
    .preview-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }
    .video-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
      font-weight: 850;
    }
    .meta { color: var(--muted); font-size: 13px; font-weight: 600; }
    pre {
      margin: 10px 0 0;
      min-height: 120px;
      max-height: 260px;
      overflow: auto;
      border-radius: 8px;
      padding: 13px;
      background: var(--log);
      color: #c7f5ef;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .result {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      min-height: 72px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfdff;
    }
    .result[hidden] { display: none; }
    @media (max-width: 980px) {
      header, main { display: block; }
      main { padding: 12px; }
      .panel { margin-bottom: 12px; }
      .preview-grid, .grid { grid-template-columns: 1fr; }
      .status-pill { display: inline-block; margin-top: 12px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Video Enhancer</h1>
      <p class="sub">Local FFmpeg export on this Mac. No upload, no cloud.</p>
    </div>
    <div class="status-pill" id="ffmpeg-status">Checking FFmpeg...</div>
  </header>

  <main>
    <section class="panel">
      <div class="panel-inner">
        <div class="section">
          <h2>1. Input Video</h2>
          <div class="filebox">
            <input id="file" type="file" accept="video/*">
            <p class="hint" id="file-hint">Choose a local video. Export files are written under outputs/web/.</p>
          </div>
        </div>

        <div class="section">
          <h2>2. Enhancement Settings</h2>
          <div class="grid">
            <label>Preset
              <select id="preset"></select>
            </label>
            <label>Video Codec
              <select id="codec"></select>
            </label>
            <label>FPS
              <input id="fps" type="number" min="1" step="1" placeholder="Preset default">
            </label>
            <label>Scale Factor
              <input id="scale" type="number" min="0.1" step="0.1" placeholder="Preset default">
            </label>
            <label class="check"><input id="no-upscale" type="checkbox"> No upscale</label>
            <label class="check"><input id="no-interpolate" type="checkbox"> No interpolate</label>
          </div>
        </div>

        <div class="section">
          <h2>3. Output</h2>
          <label>Output Filename
            <input id="output-name" type="text" placeholder="example-enhanced.mp4">
          </label>
          <p class="hint" style="margin-top:8px">MP4 is the safest target for browser playback.</p>
        </div>

        <div class="section">
          <button id="start" type="button">Start Export</button>
          <pre id="command">Command preview will appear after export starts.</pre>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-inner">
        <div class="preview-grid">
          <div>
            <div class="video-title">Input Preview <span class="meta" id="input-meta"></span></div>
            <video id="input-video" controls></video>
          </div>
          <div>
            <div class="video-title">Output Preview <span class="meta" id="output-meta">Not started</span></div>
            <video id="output-video" controls></video>
          </div>
        </div>

        <div class="section">
          <h2>Status & Progress</h2>
          <div class="result" id="result" hidden>
            <div>
              <strong id="result-name"></strong>
              <p class="hint" id="result-path"></p>
            </div>
            <a class="secondary" id="download" href="#" download>Download</a>
          </div>
          <pre id="log">Ready.</pre>
        </div>
      </div>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const state = { file: null, poll: null };

    function setLog(lines) {
      $("log").textContent = lines && lines.length ? lines.join("\\n") : "Ready.";
      $("log").scrollTop = $("log").scrollHeight;
    }

    function safeOutputName(name) {
      const base = name.replace(/\\.[^.]+$/, "").replace(/[^a-z0-9._-]+/gi, "_").replace(/^_+|_+$/g, "");
      return `${base || "video"}-enhanced.mp4`;
    }

    async function loadConfig() {
      const response = await fetch("/api/config");
      const config = await response.json();
      $("ffmpeg-status").textContent = config.ffmpeg ? `FFmpeg: ${config.ffmpeg}` : "FFmpeg: not found";
      $("preset").innerHTML = config.presets.map((name) => `<option value="${name}">${name}</option>`).join("");
      $("preset").value = "balanced";
      $("codec").innerHTML = config.codecs.map((name) => `<option value="${name}">${name}</option>`).join("");
      $("codec").value = "libx264";
    }

    $("file").addEventListener("change", () => {
      const file = $("file").files[0];
      state.file = file || null;
      if (!file) return;
      $("file-hint").textContent = `${file.name} • ${(file.size / 1024 / 1024).toFixed(1)} MB`;
      $("output-name").value = safeOutputName(file.name);
      $("input-video").src = URL.createObjectURL(file);
      $("input-meta").textContent = file.type || "local file";
    });

    $("start").addEventListener("click", async () => {
      if (!state.file) {
        setLog(["Choose a video first."]);
        return;
      }

      $("start").disabled = true;
      $("result").hidden = true;
      $("output-video").removeAttribute("src");
      $("output-video").load();
      setLog(["Uploading local file to the local enhancer..."]);

      const params = new URLSearchParams({
        preset: $("preset").value,
        codec: $("codec").value,
        output: $("output-name").value || safeOutputName(state.file.name),
      });
      if ($("fps").value) params.set("fps", $("fps").value);
      if ($("scale").value) params.set("scale", $("scale").value);
      if ($("no-upscale").checked) params.set("no_upscale", "1");
      if ($("no-interpolate").checked) params.set("no_interpolate", "1");

      try {
        const response = await fetch(`/api/jobs?${params}`, {
          method: "POST",
          headers: {
            "content-type": "application/octet-stream",
            "x-file-name": state.file.name,
          },
          body: state.file,
        });
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || "Export failed to start");
        $("command").textContent = job.command;
        watchJob(job.id);
      } catch (error) {
        setLog([error.message]);
        $("start").disabled = false;
      }
    });

    async function watchJob(id) {
      clearInterval(state.poll);
      const tick = async () => {
        const response = await fetch(`/api/jobs/${id}`);
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || "Job not found");
        $("output-meta").textContent = job.status;
        setLog(job.logs);
        if (job.status === "done") {
          clearInterval(state.poll);
          $("start").disabled = false;
          $("result").hidden = false;
          $("result-name").textContent = job.output_name;
          $("result-path").textContent = job.output_path;
          $("download").href = job.output_url;
          $("output-video").src = job.output_url;
          $("output-video").load();
        }
        if (job.status === "error") {
          clearInterval(state.poll);
          $("start").disabled = false;
        }
      };
      state.poll = setInterval(() => tick().catch((error) => {
        clearInterval(state.poll);
        $("start").disabled = false;
        setLog([error.message]);
      }), 1000);
      await tick();
    }

    loadConfig().catch((error) => setLog([error.message]));
  </script>
</body>
</html>
"""


@dataclass
class Job:
    id: str
    input_path: Path
    output_path: Path
    command: list[str]
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    error: str = ""


JOBS: dict[str, Job] = {}
LOCK = threading.Lock()


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
    if codec not in supported_video_codecs():
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


def append_log(job: Job, line: str) -> None:
    with LOCK:
        job.logs.append(line.rstrip())
        job.logs = job.logs[-300:]


def run_job(job: Job) -> None:
    """Run FFmpeg for a job and keep a small in-memory log."""

    # ponytail: in-memory job table; persist jobs when multi-user/history matters.
    with LOCK:
        job.status = "running"
        job.logs.append("Export started.")
    try:
        process = subprocess.Popen(
            job.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        with LOCK:
            job.status = "error"
            job.error = str(exc)
            job.logs.append(str(exc))
        return

    assert process.stdout is not None
    for line in process.stdout:
        if line.strip():
            append_log(job, line)
    return_code = process.wait()
    with LOCK:
        if return_code == 0:
            job.status = "done"
            job.logs.append("Export finished.")
        else:
            job.status = "error"
            job.error = f"FFmpeg failed with exit code {return_code}."
            job.logs.append(job.error)


def job_payload(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "logs": job.logs,
        "command": format_command(job.command),
        "input_name": job.input_path.name,
        "output_name": job.output_path.name,
        "output_path": str(job.output_path),
        "output_url": f"/files/{job.id}/output",
    }


class Handler(BaseHTTPRequestHandler):
    work_dir = DEFAULT_WORK_DIR

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = HTML.encode("utf-8")
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
                {"presets": available_presets(), "codecs": supported_video_codecs(), "ffmpeg": ffmpeg},
            )
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
        if parsed.path.startswith("/files/"):
            self.serve_job_file(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND.value)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/jobs":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return

        try:
            payload = self.create_job(parse_qs(parsed.query))
        except (OSError, ValueError, VideoEnhancerError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self.send_json(HTTPStatus.OK, payload)

    def create_job(self, params: dict[str, list[str]]) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            raise ValueError("No input video received.")

        original = safe_filename(self.headers.get("x-file-name", "input.mp4"))
        suffix = Path(original).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            suffix = ".mp4"

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.work_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        input_path = job_dir / f"input{suffix}"
        remaining = length
        with input_path.open("wb") as file:
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Upload ended before the full video was received.")
                file.write(chunk)
                remaining -= len(chunk)

        output_name = safe_filename(
            params.get("output", [f"{Path(original).stem}-enhanced.mp4"])[0],
            default="enhanced.mp4",
        )
        if Path(output_name).suffix.lower() not in {".mp4", ".mkv", ".mov", ".m4v"}:
            output_name = f"{Path(output_name).stem}.mp4"
        output_path = job_dir / output_name
        command = build_ffmpeg_command(input_path, output_path, build_options(params))
        job = Job(job_id, input_path, output_path, command)
        job.logs.append(f"Loaded {original}.")
        with LOCK:
            JOBS[job_id] = job
        thread = threading.Thread(target=run_job, args=(job,), daemon=True)
        thread.start()
        return job_payload(job)

    def serve_job_file(self, request_path: str) -> None:
        _, _, job_id, kind = request_path.split("/", 3)
        with LOCK:
            job = JOBS.get(job_id)
            file = job.output_path if job and kind == "output" else None
        if not file or not file.exists():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        self.send_response(HTTPStatus.OK.value)
        self.send_header("content-type", "video/mp4")
        self.send_header("content-length", str(file.stat().st_size))
        self.send_header("content-disposition", f'inline; filename="{file.name}"')
        self.end_headers()
        with file.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)


def run_server(host: str, port: int, work_dir: Path, *, open_browser: bool = False) -> None:
    Handler.work_dir = work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"Video Enhancer Web running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Video Enhancer web UI.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--open", action="store_true", help="open the UI in the default browser")
    args = parser.parse_args()
    run_server(args.host, args.port, args.work_dir, open_browser=args.open)


if __name__ == "__main__":
    main()
