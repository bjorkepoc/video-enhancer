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
from .sources import SourceError, download_source, inspect_source

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_WORK_DIR = Path("outputs/web")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}
MAX_JSON_BODY = 20_000
MODES = {
    "60": {"fps": ["60"], "scale": ["1"], "preset": ["quality"]},
    "90": {"fps": ["90"], "scale": ["1"], "preset": ["ultra"]},
    "upscale": {
        "no_interpolate": ["1"],
        "scale": ["2"],
        "preset": ["quality"],
    },
}


HTML = """<!doctype html>
<html lang="no">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Enhancer</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f5f7;
      --panel: #fff;
      --ink: #101820;
      --muted: #617085;
      --line: #d7e0ea;
      --accent: #0d7f86;
      --accent-dark: #095f64;
      --success: #247149;
      --warn: #9a5b13;
      --danger: #b42318;
      --log: #101820;
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
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
    h1, h2, h3, p, dl, dd { margin: 0; }
    h1 { font-size: 22px; line-height: 1.1; }
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
      grid-template-columns: minmax(360px, 500px) minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      max-width: 1440px;
      margin: 0 auto;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 16px 45px rgba(22, 34, 48, .06);
    }
    .panel-inner { padding: 20px; }
    .section + .section {
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }
    h2 { margin-bottom: 14px; font-size: 16px; }
    h3 { font-size: 14px; }
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
    .grid, .source-row, .action-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .source-row { grid-template-columns: minmax(0, 1fr) 130px; }
    .action-grid { margin-top: 14px; }
    .segmented {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 3px;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--bg);
      margin-bottom: 18px;
    }
    .segmented button {
      min-height: 38px;
      background: transparent;
      color: var(--muted);
    }
    .segmented button[aria-selected="true"] {
      background: #fff;
      color: var(--ink);
      box-shadow: 0 1px 4px rgba(16, 24, 32, .12);
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
    .segmented button:hover { background: #fff; color: var(--ink); }
    button:disabled { cursor: not-allowed; opacity: .62; }
    button.secondary-button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
    }
    button.secondary-button:hover { border-color: var(--accent); }
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
    .source-summary {
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }
    .source-heading {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 14px;
    }
    .source-heading .meta { margin-top: 4px; }
    .quality-label {
      color: var(--success);
      font-size: 12px;
      font-weight: 800;
      text-align: right;
    }
    .media-meta {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 1px;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--line);
      margin-top: 12px;
    }
    .media-meta div { min-width: 0; padding: 10px; background: #fff; }
    .media-meta dt { color: var(--muted); font-size: 11px; font-weight: 700; }
    .media-meta dd { margin-top: 3px; overflow-wrap: anywhere; font-size: 13px; font-weight: 800; }
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
    .result + .result { margin-top: 10px; }
    .button-status { min-height: 18px; margin-top: 10px; color: var(--danger); }
    @media (max-width: 980px) {
      header, main { display: block; }
      main { padding: 12px; }
      .panel { margin-bottom: 12px; }
      .preview-grid, .grid, .action-grid { grid-template-columns: 1fr; }
      .status-pill { display: inline-block; margin-top: 12px; }
    }
    @media (max-width: 520px) {
      header { padding: 16px; }
      .panel-inner { padding: 16px; }
      .source-row, .media-meta { grid-template-columns: 1fr; }
      .source-heading { display: block; }
      .quality-label { margin-top: 5px; text-align: left; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Video Enhancer</h1>
    <div class="status-pill" id="ffmpeg-status">Kontrollerer FFmpeg...</div>
  </header>

  <main>
    <section class="panel">
      <div class="panel-inner">
        <div class="segmented" role="tablist" aria-label="Videokilde">
          <button id="input-link" type="button" role="tab" aria-selected="true">Link</button>
          <button id="input-local" type="button" role="tab" aria-selected="false">Lokal fil</button>
        </div>

        <div id="link-controls" role="tabpanel">
          <h2>Kildevideo</h2>
          <div class="source-row">
            <label> TikTok- eller Instagram-link
              <input id="source-url" type="url" inputmode="url" autocomplete="url" placeholder="https://...">
            </label>
            <label>Nettleserøkt
              <select id="browser-session">
                <option value="">Ingen</option>
                <option value="safari">Safari</option>
                <option value="chrome">Chrome</option>
                <option value="firefox">Firefox</option>
              </select>
            </label>
          </div>
          <button id="inspect-source" type="button" style="margin-top:14px">Inspiser kilde</button>
          <p class="hint button-status" id="source-error" role="alert"></p>

          <div class="source-summary" id="source-result" hidden>
            <div class="source-heading">
              <div>
                <h3 id="source-title">Kilde</h3>
                <p class="meta" id="source-byline"></p>
              </div>
              <span class="quality-label" id="source-quality">Original platform stream</span>
            </div>
            <label>Kildevariant
              <select id="source-format">
                <option value="">Best tilgjengelig</option>
              </select>
            </label>
            <button id="download-original" type="button" style="margin-top:14px">Last ned original</button>
            <div class="action-grid">
              <button class="secondary-button" id="download-60" type="button" disabled>Lag 60 FPS-kopi</button>
              <button class="secondary-button" id="download-90" type="button" disabled>Lag 90 FPS-kopi</button>
              <button class="secondary-button" id="download-upscale" type="button" disabled>Lag 2x oppskalering</button>
            </div>
            <dl class="media-meta" id="source-media" hidden></dl>
          </div>
        </div>

        <div id="local-controls" role="tabpanel" hidden>
          <h2>Lokal video</h2>
          <div class="filebox">
            <input id="file" type="file" accept="video/*">
            <p class="hint" id="file-hint">Ingen fil valgt</p>
          </div>

          <div class="section">
          <h2>Forbedring</h2>
          <div class="grid">
            <label>Profil
              <select id="preset"></select>
            </label>
            <label>Videokodek
              <select id="codec"></select>
            </label>
            <label>FPS
              <input id="fps" type="number" min="1" step="1" placeholder="Preset default">
            </label>
            <label>Skalering
              <input id="scale" type="number" min="0.1" step="0.1" placeholder="Preset default">
            </label>
            <label class="check"><input id="no-upscale" type="checkbox"> Ingen oppskalering</label>
            <label class="check"><input id="no-interpolate" type="checkbox"> Ingen interpolering</label>
          </div>

          <label style="margin-top:14px">Filnavn
            <input id="output-name" type="text" placeholder="example-enhanced.mp4">
          </label>

          <button id="start" type="button" style="margin-top:14px">Start eksport</button>
          <pre id="command">Kommandoen vises når eksporten starter.</pre>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-inner">
        <div class="preview-grid">
          <div>
            <div class="video-title">Original <span class="meta" id="input-meta">Ikke lastet</span></div>
            <video id="source-video" controls></video>
          </div>
          <div>
            <div class="video-title">Avledet kopi <span class="meta" id="output-meta">Ikke startet</span></div>
            <video id="output-video" controls></video>
          </div>
        </div>

        <div class="section">
          <h2>Resultater</h2>
          <div class="result" id="source-download-result" hidden>
            <div>
              <strong id="source-result-name"></strong>
              <p class="hint" id="source-result-label">Original platform stream</p>
            </div>
            <a class="secondary" id="source-download" href="#" download>Last ned</a>
          </div>
          <div class="result" id="result" hidden>
            <div>
              <strong id="result-name"></strong>
              <p class="hint" id="result-path">Enhanced synthetic copy</p>
            </div>
            <a class="secondary" id="download" href="#" download>Last ned</a>
          </div>
          <pre id="log">Klar.</pre>
        </div>
      </div>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const state = { file: null, poll: null, sourceId: null };

    function setLog(lines) {
      $("log").textContent = lines && lines.length ? lines.join("\\n") : "Klar.";
      $("log").scrollTop = $("log").scrollHeight;
    }

    function safeOutputName(name) {
      const base = name.replace(/\\.[^.]+$/, "").replace(/[^a-z0-9._-]+/gi, "_").replace(/^_+|_+$/g, "");
      return `${base || "video"}-enhanced.mp4`;
    }

    async function loadConfig() {
      const response = await fetch("/api/config");
      const config = await response.json();
      $("ffmpeg-status").textContent = config.ffmpeg ? `FFmpeg: ${config.ffmpeg}` : "FFmpeg: ikke funnet";
      $("preset").innerHTML = config.presets.map((name) => `<option value="${name}">${name}</option>`).join("");
      $("preset").value = "balanced";
      $("codec").innerHTML = config.codecs.map((name) => `<option value="${name}">${name}</option>`).join("");
      $("codec").value = "libx264";
    }

    function setMode(mode) {
      const link = mode === "link";
      $("input-link").setAttribute("aria-selected", String(link));
      $("input-local").setAttribute("aria-selected", String(!link));
      $("link-controls").hidden = !link;
      $("local-controls").hidden = link;
    }

    $("input-link").addEventListener("click", () => setMode("link"));
    $("input-local").addEventListener("click", () => setMode("local"));

    function isSupportedSourceUrl(raw) {
      try {
        const url = new URL(raw);
        const host = url.hostname.toLowerCase();
        return url.protocol === "https:" && ["tiktok.com", "instagram.com"].some(
          (domain) => host === domain || host.endsWith(`.${domain}`)
        );
      } catch (_) {
        return false;
      }
    }

    async function postJSON(path, body) {
      const response = await fetch(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Forespørselen mislyktes");
      return payload;
    }

    function formatVariant(format) {
      const size = format.width && format.height ? `${format.width}x${format.height}` : "Ukjent størrelse";
      const fps = format.fps ? `${format.fps} FPS` : "ukjent FPS";
      const codec = format.vcodec || "ukjent kodek";
      const bitrate = format.tbr ? `${Math.round(format.tbr)} kbps` : "ukjent bitrate";
      const mirrors = format.mirrors > 1 ? `, ${format.mirrors} speil` : "";
      return `${size}, ${fps}, ${codec}, ${bitrate}${mirrors}`;
    }

    function setDerivedDisabled(disabled) {
      ["download-60", "download-90", "download-upscale"].forEach((id) => {
        $(id).disabled = disabled;
      });
    }

    function showSourceInfo(source) {
      state.sourceId = source.id;
      $("source-result").hidden = false;
      $("source-title").textContent = source.info.title || `${source.info.platform || "Video"} ${source.info.id || ""}`;
      $("source-byline").textContent = [source.info.uploader, source.info.duration ? `${source.info.duration}s` : ""].filter(Boolean).join(" · ");
      const select = $("source-format");
      select.replaceChildren(new Option("Best tilgjengelig", ""));
      source.info.formats.forEach((format) => {
        const id = (format.format_ids || [])[0];
        if (id) select.add(new Option(formatVariant(format), id));
      });
      $("download-original").disabled = false;
      setDerivedDisabled(true);
      $("source-media").hidden = true;
      $("source-download-result").hidden = true;
      setLog([`${source.info.formats.length} kildevarianter funnet.`]);
    }

    $("inspect-source").addEventListener("click", async () => {
      const url = $("source-url").value.trim();
      $("source-error").textContent = "";
      if (!isSupportedSourceUrl(url)) {
        $("source-error").textContent = "Bruk en gyldig HTTPS-link fra TikTok eller Instagram.";
        return;
      }
      $("inspect-source").disabled = true;
      setLog(["Inspiserer tilgjengelige kildevarianter..."]);
      try {
        showSourceInfo(await postJSON("/api/sources/inspect", {
          url,
          browser: $("browser-session").value,
        }));
      } catch (error) {
        $("source-error").textContent = error.message;
        setLog([error.message]);
      } finally {
        $("inspect-source").disabled = false;
      }
    });

    $("download-original").addEventListener("click", async () => {
      if (!state.sourceId) return;
      $("download-original").disabled = true;
      setDerivedDisabled(true);
      setLog(["Starter originalnedlasting..."]);
      try {
        const source = await postJSON(`/api/sources/${state.sourceId}/download`, {
          browser: $("browser-session").value,
          format_id: $("source-format").value,
        });
        watchSource(source.id).catch(showPollingError);
      } catch (error) {
        $("source-error").textContent = error.message;
        $("download-original").disabled = false;
        setLog([error.message]);
      }
    });

    function mediaValue(value, suffix = "") {
      return value === null || value === undefined ? "Ukjent" : `${value}${suffix}`;
    }

    function renderMedia(media) {
      const values = [
        ["Oppløsning", media.width && media.height ? `${media.width}x${media.height}` : "Ukjent"],
        ["Bildefrekvens", mediaValue(media.fps, " FPS")],
        ["Video", mediaValue(media.video_codec)],
        ["Lyd", mediaValue(media.audio_codec)],
        ["Bitrate", media.bitrate ? `${Math.round(media.bitrate / 1000)} kbps` : "Ukjent"],
        ["Størrelse", media.size ? `${(media.size / 1024 / 1024).toFixed(1)} MB` : "Ukjent"],
      ];
      $("source-media").replaceChildren(...values.map(([name, value]) => {
        const box = document.createElement("div");
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = name;
        detail.textContent = value;
        box.append(term, detail);
        return box;
      }));
      $("source-media").hidden = false;
    }

    async function watchSource(id) {
      clearInterval(state.poll);
      const tick = async () => {
        const response = await fetch(`/api/sources/${id}`);
        const source = await response.json();
        if (!response.ok) throw new Error(source.error || "Kildejobben ble ikke funnet");
        setLog(source.logs);
        if (source.status === "done") {
          clearInterval(state.poll);
          const label = source.operation === "remuxed" ? "Remuxed without video re-encoding" : "Original platform stream";
          $("source-quality").textContent = label;
          $("source-result-label").textContent = label;
          $("source-result-name").textContent = source.original_name;
          $("source-download").href = source.original_url;
          $("source-download-result").hidden = false;
          $("source-video").src = source.original_url;
          $("source-video").load();
          $("input-meta").textContent = `${mediaValue(source.media.width)}x${mediaValue(source.media.height)} · ${mediaValue(source.media.fps, " FPS")}`;
          renderMedia(source.media);
          $("download-original").disabled = false;
          setDerivedDisabled(false);
        } else if (source.status === "error") {
          clearInterval(state.poll);
          $("source-error").textContent = source.error;
          $("download-original").disabled = false;
        }
      };
      state.poll = setInterval(() => tick().catch(showPollingError), 1000);
      await tick();
    }

    function showPollingError(error) {
      clearInterval(state.poll);
      setLog([error.message]);
      $("start").disabled = false;
      $("download-original").disabled = false;
    }

    async function startSourceEnhancement(mode) {
      if (!state.sourceId) return;
      setDerivedDisabled(true);
      $("result").hidden = true;
      $("output-meta").textContent = "Starter";
      try {
        const job = await postJSON(`/api/sources/${state.sourceId}/enhance`, { mode });
        $("command").textContent = job.command;
        watchJob(job.id, true).catch(showPollingError);
      } catch (error) {
        setDerivedDisabled(false);
        setLog([error.message]);
      }
    }

    $("download-60").addEventListener("click", () => startSourceEnhancement("60"));
    $("download-90").addEventListener("click", () => startSourceEnhancement("90"));
    $("download-upscale").addEventListener("click", () => startSourceEnhancement("upscale"));

    $("file").addEventListener("change", () => {
      const file = $("file").files[0];
      state.file = file || null;
      if (!file) return;
      $("file-hint").textContent = `${file.name} • ${(file.size / 1024 / 1024).toFixed(1)} MB`;
      $("output-name").value = safeOutputName(file.name);
      $("source-video").src = URL.createObjectURL(file);
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
        watchJob(job.id, false).catch(showPollingError);
      } catch (error) {
        setLog([error.message]);
        $("start").disabled = false;
      }
    });

    async function watchJob(id, fromSource) {
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
          if (fromSource) setDerivedDisabled(false);
          $("result").hidden = false;
          $("result-name").textContent = job.output_name;
          $("result-path").textContent = "Enhanced synthetic copy";
          $("download").href = job.output_url;
          $("output-video").src = job.output_url;
          $("output-video").load();
        }
        if (job.status === "error") {
          clearInterval(state.poll);
          $("start").disabled = false;
          if (fromSource) setDerivedDisabled(false);
        }
      };
      state.poll = setInterval(() => tick().catch((error) => {
        showPollingError(error);
        if (fromSource) setDerivedDisabled(false);
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


@dataclass
class SourceJob:
    id: str
    url: str
    info: dict[str, Any]
    directory: Path
    status: str = "inspected"
    original_path: Path | None = None
    media: dict[str, Any] = field(default_factory=dict)
    format_id: str = ""
    operation: str = ""
    error: str = ""
    logs: list[str] = field(default_factory=list)


JOBS: dict[str, Job] = {}
SOURCES: dict[str, SourceJob] = {}
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


def _safe_source_info(info: dict[str, Any]) -> dict[str, Any]:
    formats = []
    for source_format in info.get("formats", []):
        formats.append(
            {
                key: source_format.get(key)
                for key in (
                    "width",
                    "height",
                    "fps",
                    "tbr",
                    "vcodec",
                    "acodec",
                    "ext",
                    "format_ids",
                    "mirrors",
                )
            }
        )
    return {
        key: info.get(key)
        for key in ("id", "platform", "title", "uploader", "duration", "webpage_url")
    } | {"formats": formats}


def source_payload(job: SourceJob) -> dict[str, Any]:
    payload = {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "logs": job.logs,
        "info": _safe_source_info(job.info),
        "media": job.media,
        "format_id": job.format_id,
        "operation": job.operation,
    }
    if job.original_path:
        payload.update(
            {
                "original_name": job.original_path.name,
                "original_url": f"/files/sources/{job.id}/original",
            }
        )
    return payload


def create_enhancement_job(
    input_path: Path,
    original_name: str,
    params: dict[str, list[str]],
    work_dir: Path,
) -> Job:
    original = safe_filename(original_name)
    job_id = uuid.uuid4().hex[:12]
    job_dir = work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
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
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return job


def run_source_download(job: SourceJob, browser: str, format_id: str) -> None:
    with LOCK:
        job.status = "downloading"
        job.logs.append("Original source download started.")
    try:
        result = download_source(job.url, job.directory, browser, format_id)
    except (OSError, SourceError) as exc:
        with LOCK:
            job.status = "error"
            job.error = str(exc)
            job.logs.append(str(exc))
        return
    with LOCK:
        job.original_path = result["path"]
        job.media = result["media"]
        job.format_id = result["format_id"]
        job.operation = result["operation"]
        job.status = "done"
        job.logs.append("Original source download finished.")


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

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid content length.") from exc
        if length > MAX_JSON_BODY:
            raise ValueError("JSON request body is too large.")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON request body.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object.")
        return payload

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
            self.serve_source_file(parsed.path)
            return
        if parsed.path.startswith("/files/"):
            self.serve_job_file(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND.value)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/sources/inspect":
                self.send_json(HTTPStatus.OK, self.inspect_source_job(self.read_json()))
                return
            if parsed.path.startswith("/api/sources/"):
                self.handle_source_action(parsed.path, self.read_json())
                return
            if parsed.path == "/api/jobs":
                payload = self.create_job(parse_qs(parsed.query))
                self.send_json(HTTPStatus.OK, payload)
                return
        except (OSError, SourceError, ValueError, VideoEnhancerError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if parsed.path != "/api/jobs":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return

    def inspect_source_job(self, body: dict[str, Any]) -> dict[str, Any]:
        url = str(body.get("url", "")).strip()
        browser = str(body.get("browser", "")).strip()
        info = inspect_source(url, browser)
        source_id = uuid.uuid4().hex[:12]
        directory = self.work_dir / f"source-{source_id}"
        source = SourceJob(source_id, url, info, directory)
        with LOCK:
            SOURCES[source_id] = source
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
        if action == "download":
            if source.status in {"queued", "downloading"}:
                raise ValueError("Source download is already running.")
            browser = str(body.get("browser", "")).strip()
            format_id = str(body.get("format_id", "")).strip()
            with LOCK:
                source.status = "queued"
                source.error = ""
            threading.Thread(
                target=run_source_download,
                args=(source, browser, format_id),
                daemon=True,
            ).start()
            self.send_json(HTTPStatus.ACCEPTED, source_payload(source))
            return
        if action == "enhance":
            if source.status != "done" or not source.original_path:
                raise ValueError("Download the original source before enhancing it.")
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
        self.send_error(HTTPStatus.NOT_FOUND.value)

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

        return job_payload(create_enhancement_job(input_path, original, params, self.work_dir))

    def serve_source_file(self, request_path: str) -> None:
        parts = request_path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["files", "sources"] or parts[3] != "original":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        with LOCK:
            source = SOURCES.get(parts[2])
            file = source.original_path if source else None
        root = self.work_dir.resolve()
        if (
            not file
            or not file.is_file()
            or not file.resolve().is_relative_to(root)
        ):
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        self.serve_video(file)

    def serve_job_file(self, request_path: str) -> None:
        _, _, job_id, kind = request_path.split("/", 3)
        with LOCK:
            job = JOBS.get(job_id)
            file = job.output_path if job and kind == "output" else None
        if not file or not file.exists():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        self.serve_video(file)

    def serve_video(self, file: Path) -> None:
        self.send_response(HTTPStatus.OK.value)
        self.send_header(
            "content-type",
            "video/mp4" if file.suffix.lower() in {".mp4", ".m4v"} else "application/octet-stream",
        )
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
