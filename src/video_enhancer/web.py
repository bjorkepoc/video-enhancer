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
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .ffmpeg import (
    ENHANCEMENT_TIMEOUT_SECONDS,
    SUPPORTED_VIDEO_CODECS,
    EnhancementOptions,
    FFmpegNotFoundError,
    VideoEnhancerError,
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


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Image &amp; Video Downloader</title>
  <style nonce="__CSP_NONCE__">
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
    .header-actions { display: flex; align-items: center; gap: 8px; }
    .header-actions button { width: auto; min-height: 36px; }
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
    .grid, .action-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
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
    .mt-8 { margin-top: 8px; }
    .mt-10 { margin-top: 10px; }
    .mt-14 { margin-top: 14px; }
    .source-summary {
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }
    .quality-label {
      display: block;
      color: var(--success);
      font-size: 12px;
      font-weight: 800;
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
    .video-stage {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
      overflow: hidden;
      border-radius: 8px;
      background: #101820;
      touch-action: none;
      user-select: none;
    }
    .video-stage[data-zoomed="true"] { cursor: grab; }
    .video-stage.dragging { cursor: grabbing; }
    .video-stage video,
    .video-stage img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
      transform-origin: 0 0;
      will-change: transform;
    }
    .player-shell:fullscreen {
      display: grid;
      align-content: center;
      padding: 16px;
      background: #101820;
    }
    .player-shell:fullscreen .video-stage {
      width: min(100%, calc((100vh - 140px) * 16 / 9));
      margin: 0 auto;
    }
    .player-shell:fullscreen .frame-controls {
      width: min(100%, calc((100vh - 140px) * 16 / 9));
      margin-left: auto;
      margin-right: auto;
    }
    .player-shell:fullscreen .frame-fps { color: #fff; }
    .zoom-controls button {
      min-height: 38px;
      padding: 0;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
    }
    .zoom-controls button:hover {
      border-color: var(--accent);
      background: #fff;
    }
    .zoom-controls input {
      min-width: 0;
      min-height: 38px;
      margin: 0;
      padding: 0;
    }
    .zoom-controls {
      display: grid;
      grid-template-columns: 38px minmax(80px, 1fr) 38px 48px;
      gap: 8px;
      align-items: center;
      margin-top: 8px;
    }
    .frame-controls {
      display: grid;
      grid-template-columns: 40px minmax(72px, 1fr) 40px minmax(84px, 104px) 40px;
      gap: 8px;
      align-items: center;
      margin-top: 8px;
    }
    .frame-controls button {
      min-height: 38px;
      padding: 0;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
    }
    .frame-controls button:hover { border-color: var(--accent); background: #fff; }
    .frame-controls button[aria-pressed="true"] {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .frame-fps {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 6px;
      align-items: center;
      min-width: 0;
      font-size: 11px;
    }
    .frame-fps input { min-width: 0; min-height: 38px; margin: 0; padding: 0 7px; }
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
    .result > div { min-width: 0; }
    .result strong { overflow-wrap: anywhere; }
    .result + .result { margin-top: 10px; }
    .button-status { min-height: 18px; margin-top: 10px; color: var(--danger); }
    footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      max-width: 1440px;
      margin: 0 auto;
      padding: 0 18px 18px;
      color: var(--muted);
      font-size: 12px;
    }
    footer button { width: auto; min-height: 36px; }
    dialog {
      width: min(560px, calc(100vw - 32px));
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0;
      color: var(--ink);
      background: #fff;
    }
    dialog::backdrop { background: rgba(16, 24, 32, .56); }
    .dialog-body { padding: 20px; }
    .dialog-body p + p { margin-top: 12px; }
    .dialog-actions { display: flex; justify-content: flex-end; margin-top: 18px; }
    .dialog-actions button { width: auto; }
    @media (max-width: 980px) {
      header, main { display: block; }
      main { padding: 12px; }
      .panel { margin-bottom: 12px; }
      .preview-grid, .grid, .action-grid { grid-template-columns: 1fr; }
      .status-pill { display: inline-block; margin-top: 12px; }
      .header-actions { margin-top: 12px; }
    }
    @media (max-width: 520px) {
      header { padding: 16px; }
      .panel-inner { padding: 16px; }
      .media-meta { grid-template-columns: 1fr; }
      .quality-label { margin-top: 5px; }
      footer { display: block; }
      footer button { margin-top: 10px; }
    }

    /* Light creator-studio redesign. */
    :root {
      --bg: #ffffff;
      --panel: #ffffff;
      --ink: #0b0e16;
      --muted: #56627a;
      --line: #d8deea;
      --line-strong: #bcc6d8;
      --surface: #f6f8fc;
      --accent: #2257f4;
      --accent-dark: #1743c9;
      --accent-soft: #eef2ff;
      --success: #0bba75;
      --danger: #dc2626;
      --log: #f6f8fc;
    }
    html { background: #fff; }
    body {
      min-width: 320px;
      background: #fff;
      color: var(--ink);
      font-size: 16px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }
    main {
      display: block;
      max-width: none;
      margin: 0;
      padding: 0;
    }
    .app-container {
      width: min(calc(100% - 48px), 1260px);
      margin-inline: auto;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    button, input, summary, a { -webkit-tap-highlight-color: transparent; }
    button:focus-visible,
    input:focus-visible,
    summary:focus-visible,
    a:focus-visible,
    .video-preview:focus-visible {
      outline: 3px solid rgba(34, 87, 244, .28);
      outline-offset: 3px;
    }
    button:disabled { opacity: .48; }
    svg { flex: 0 0 auto; }

    .site-header {
      position: relative;
      top: auto;
      z-index: 4;
      display: block;
      padding: 0;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      backdrop-filter: blur(18px);
    }
    .header-inner {
      display: flex;
      min-height: 76px;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--ink);
      font-size: 23px;
      font-weight: 760;
      letter-spacing: -.04em;
      white-space: nowrap;
    }
    .brand strong { color: var(--accent); font-weight: 760; }
    .brand-mark { width: 38px; height: 38px; color: var(--accent); }
    .header-actions, .legal-nav, .engine-status {
      display: flex;
      align-items: center;
    }
    .header-actions { gap: 28px; margin: 0; }
    .legal-nav { gap: 24px; }
    .header-actions .header-link,
    .footer-actions button {
      width: auto;
      min-height: 44px;
      padding: 0;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--ink);
      font-size: 15px;
      font-weight: 650;
    }
    .header-link:hover,
    .footer-actions button:hover { background: transparent; color: var(--accent); }
    .engine-status {
      gap: 9px;
      padding-left: 26px;
      border-left: 1px solid var(--line);
      color: var(--ink);
      font-size: 15px;
      font-weight: 650;
      white-space: nowrap;
    }
    .status-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 0 4px rgba(11,186,117,.10);
    }
    [data-state="error"] .status-dot,
    .engine-status[data-state="error"] .status-dot { background: var(--danger); box-shadow: 0 0 0 4px rgba(220,38,38,.10); }
    .status-short { display: none; }

    .hero { padding: 42px 0 20px; }
    .hero h1 {
      max-width: 800px;
      color: var(--ink);
      font-size: clamp(48px, 5.1vw, 72px);
      font-weight: 790;
      letter-spacing: -.065em;
      line-height: 1.01;
    }
    .hero-copy {
      margin-top: 20px;
      color: var(--muted);
      font-size: 19px;
      line-height: 1.48;
      letter-spacing: -.015em;
    }
    .source-form {
      display: grid;
      grid-template-columns: minmax(0, 680px) auto;
      gap: 16px;
      max-width: 1000px;
      margin-top: 18px;
    }
    .url-control { position: relative; }
    .url-control > svg {
      position: absolute;
      top: 50%;
      left: 20px;
      width: 25px;
      height: 25px;
      transform: translateY(-50%);
      fill: none;
      stroke: var(--muted);
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
      pointer-events: none;
    }
    .url-control input {
      width: 100%;
      min-height: 64px;
      margin: 0;
      padding: 0 20px 0 58px;
      border: 1px solid var(--line-strong);
      border-radius: 10px;
      background: #fff;
      color: var(--ink);
      font-size: 17px;
      box-shadow: 0 1px 2px rgba(10,20,40,.02);
    }
    .url-control input::placeholder { color: #7d889d; opacity: 1; }
    .url-control input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(34,87,244,.11); }
    .primary-button {
      display: inline-flex;
      width: auto;
      min-height: 64px;
      align-items: center;
      justify-content: center;
      gap: 12px;
      border-radius: 10px;
      padding: 0 28px;
      background: var(--accent);
      color: #fff;
      font-size: 16px;
      font-weight: 760;
      white-space: nowrap;
      box-shadow: 0 10px 24px rgba(34,87,244,.18);
      transition: background-color .18s ease, transform .18s ease, box-shadow .18s ease;
    }
    .primary-button:hover { background: var(--accent-dark); box-shadow: 0 12px 28px rgba(34,87,244,.24); }
    .primary-button:active { transform: translateY(1px); }
    .primary-button svg,
    .download-link svg {
      width: 21px;
      height: 21px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .rights-note {
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }
    .trust-line {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 15px;
      color: var(--muted);
      font-size: 15px;
    }
    .trust-line svg {
      width: 24px;
      height: 24px;
      fill: none;
      stroke: var(--accent);
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .source-error {
      min-height: 22px;
      margin-top: 5px;
      color: var(--danger);
      font-size: 14px;
      font-weight: 650;
    }

    .house-ad {
      display: flex;
      position: relative;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 28px;
      padding: 18px 20px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--surface);
    }
    .ad-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .house-ad strong { display: block; margin-top: 2px; font-size: 16px; }
    .house-ad p { margin-top: 2px; color: var(--muted); font-size: 14px; }
    .house-ad button {
      width: auto;
      min-height: 44px;
      border: 1px solid var(--line-strong);
      background: #fff;
      color: var(--accent);
      white-space: nowrap;
    }
    .house-ad button:hover { border-color: var(--accent); background: var(--accent-soft); }

    .workspace {
      padding: 0 0 26px;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .workspace-empty { min-height: 150px; padding: 27px 0 30px; }
    .workspace h2,
    .explainer h2 {
      color: var(--ink);
      font-size: 24px;
      font-weight: 760;
      letter-spacing: -.035em;
    }
    .workspace-empty p,
    .workspace-heading p {
      max-width: 620px;
      margin-top: 8px;
      color: var(--muted);
      font-size: 17px;
    }
    .workspace-active { padding: 30px 0 6px; }
    .workspace-heading {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 22px;
    }
    .workspace-status {
      display: flex;
      align-items: center;
      gap: 9px;
      min-height: 44px;
      color: var(--muted);
      font-size: 14px;
      font-weight: 650;
    }
    .preview-grid { grid-template-columns: 1fr 1fr; gap: 18px; }
    .preview-grid[data-single="true"] { grid-template-columns: 1fr; }
    .video-preview {
      min-width: 0;
      padding: 0;
      border-radius: 14px;
    }
    .video-title {
      margin-bottom: 9px;
      color: var(--ink);
      font-size: 16px;
      font-weight: 760;
    }
    .meta { color: var(--muted); font-size: 13px; font-weight: 600; }
    .video-stage {
      border: 1px solid #202a3a;
      border-radius: 14px;
      background: #101724;
      box-shadow: 0 16px 40px rgba(15,23,42,.08);
    }
    .video-empty {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 24px;
      color: #c5cede;
      font-size: 14px;
      text-align: center;
      pointer-events: none;
    }
    .advanced-controls { margin-top: 9px; }
    .advanced-controls summary,
    .activity-log summary {
      min-height: 44px;
      border-radius: 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      list-style-position: inside;
    }
    .advanced-controls summary { display: flex; align-items: center; }
    .advanced-controls summary::before { content: "+"; margin-right: 8px; color: var(--accent); font-size: 18px; }
    .advanced-controls[open] summary::before { content: "−"; }
    .frame-controls,
    .zoom-controls { margin-top: 8px; }
    .frame-controls button,
    .zoom-controls button {
      min-height: 44px;
      border-color: var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
    }
    .frame-controls button:hover,
    .zoom-controls button:hover { border-color: var(--accent); background: var(--accent-soft); }
    .frame-controls button[aria-pressed="true"] { border-color: var(--accent); background: var(--accent); color: #fff; }
    .frame-controls button svg {
      width: 18px;
      height: 18px;
      margin: auto;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .frame-fps { font-size: 11px; color: var(--muted); }
    .frame-fps input { min-height: 44px; border-radius: 8px; }
    .zoom-controls input { accent-color: var(--accent); }

    .source-summary {
      margin-top: 24px;
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--surface);
    }
    .source-summary-heading,
    .result {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }
    .source-summary-heading strong,
    .result strong {
      display: block;
      max-width: 720px;
      margin-top: 3px;
      overflow: hidden;
      color: var(--ink);
      font-size: 16px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .quality-label { color: var(--success); font-size: 12px; letter-spacing: .04em; text-transform: uppercase; }
    .hint { color: var(--muted); font-size: 13px; }
    .download-link {
      display: inline-flex;
      min-height: 46px;
      align-items: center;
      justify-content: center;
      gap: 9px;
      border: 1px solid var(--accent);
      border-radius: 9px;
      padding: 0 16px;
      background: #fff;
      color: var(--accent);
      font-size: 14px;
      font-weight: 760;
      text-decoration: none;
      white-space: nowrap;
    }
    .download-link:hover { background: var(--accent-soft); }
    .download-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
    .media-meta {
      grid-template-columns: repeat(6, minmax(0, 1fr));
      margin-top: 20px;
      border-color: var(--line);
      border-radius: 10px;
      background: var(--line);
    }
    .media-meta[data-kind="image"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .media-meta div { background: #fff; }
    .enhancement-actions { margin-top: 22px; padding-top: 20px; border-top: 1px solid var(--line); }
    .enhancement-actions h3 { margin-bottom: 12px; color: var(--ink); font-size: 15px; }
    .action-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 0; }
    .choice-button {
      display: grid;
      min-height: 66px;
      align-content: center;
      justify-items: start;
      gap: 2px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      color: var(--ink);
      text-align: left;
    }
    .choice-button:hover { border-color: var(--accent); background: var(--accent-soft); }
    .choice-button strong { font-size: 14px; }
    .choice-button span { color: var(--muted); font-size: 12px; font-weight: 600; }
    .result {
      min-height: 84px;
      margin-top: 14px;
      border: 1px solid #b8e8d3;
      border-radius: 14px;
      padding: 18px 20px;
      background: #f4fcf8;
    }
    .activity-log { margin-top: 12px; }
    .activity-log summary { display: inline-flex; align-items: center; }
    pre {
      min-height: 84px;
      max-height: 220px;
      margin-top: 4px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--log);
      color: #314057;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }

    .explainer {
      max-width: 620px;
      padding: 30px 0 42px;
    }
    .steps ol { margin: 12px 0 0; padding: 0; list-style: none; }
    .steps li {
      display: grid;
      grid-template-columns: 46px minmax(0, 1fr);
      gap: 15px;
      align-items: start;
      padding: 12px 0;
    }
    .steps li + li { border-top: 1px solid var(--line); }
    .steps li > span {
      display: grid;
      width: 42px;
      height: 42px;
      place-items: center;
      border: 2px solid var(--accent);
      border-radius: 50%;
      color: var(--ink);
      font-size: 15px;
      font-weight: 760;
    }
    .steps strong { display: block; color: var(--ink); font-size: 15px; }
    .steps p { margin-top: 2px; color: var(--muted); font-size: 14px; }
    .site-footer {
      display: block;
      max-width: none;
      margin: 0;
      padding: 0;
      border-top: 1px solid var(--line);
      background: #fbfcff;
      color: var(--muted);
      font-size: 13px;
    }
    .footer-inner {
      display: flex;
      min-height: 94px;
      align-items: center;
      justify-content: space-between;
      gap: 28px;
    }
    .footer-inner > p { max-width: 760px; }
    .footer-actions { display: flex; align-items: center; gap: 24px; }
    .footer-actions .danger-button {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--danger);
      white-space: nowrap;
    }
    .danger-button svg {
      width: 20px;
      height: 20px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    dialog {
      width: min(720px, calc(100vw - 32px));
      max-height: min(860px, calc(100vh - 32px));
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 28px 90px rgba(15,23,42,.22);
    }
    dialog::backdrop { background: rgba(18,27,44,.44); backdrop-filter: blur(4px); }
    .dialog-body { padding: 30px; }
    .dialog-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
    .dialog-kicker { color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
    .policy-content h2 { margin-top: 3px; font-size: 30px; letter-spacing: -.04em; }
    .policy-content section { margin-top: 22px; padding-top: 20px; border-top: 1px solid var(--line); }
    .policy-content h3 { font-size: 16px; }
    .policy-content section p { margin-top: 7px; color: var(--muted); font-size: 14px; line-height: 1.6; }
    .icon-button {
      width: 44px;
      min-height: 44px;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 50%;
      background: #fff;
      color: var(--ink);
      font-size: 24px;
      font-weight: 500;
    }
    .icon-button:hover { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
    .dialog-actions { margin-top: 26px; }
    .dialog-actions button {
      min-height: 46px;
      border-radius: 9px;
      background: var(--accent);
      color: #fff;
    }
    .dialog-actions button:hover { background: var(--accent-dark); }
    .contact-link {
      display: inline-flex;
      min-height: 44px;
      align-items: center;
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 0 14px;
      color: var(--accent);
      font-size: 14px;
      font-weight: 760;
      text-decoration: none;
    }
    .contact-link:hover { border-color: var(--accent); background: var(--accent-soft); }

    @media (max-width: 980px) {
      .site-header, main { display: block; padding: 0; }
      .header-actions { margin: 0; }
      .preview-grid { grid-template-columns: 1fr; }
      .media-meta { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .footer-inner { align-items: flex-start; flex-direction: column; justify-content: center; padding-block: 24px; }
    }
    @media (max-width: 760px) {
      .app-container { width: min(calc(100% - 40px), 1260px); }
      .header-inner { min-height: 72px; }
      .brand { gap: 7px; font-size: 20px; }
      .brand-mark { width: 33px; height: 33px; }
      .legal-nav { display: none; }
      .engine-status { padding-left: 0; border-left: 0; }
      .status-full { display: none; }
      .status-short { display: inline; }
      .hero { padding-top: 38px; }
      .hero h1 { font-size: clamp(42px, 12vw, 56px); line-height: 1.03; }
      .hero-copy { font-size: 17px; }
      .hero-copy br { display: none; }
      .source-form { grid-template-columns: 1fr; gap: 12px; }
      .url-control input, .primary-button { min-height: 58px; }
      .primary-button { width: 100%; }
      .trust-line { align-items: flex-start; font-size: 15px; }
      .house-ad { align-items: flex-start; flex-direction: column; gap: 14px; }
      .house-ad button { width: 100%; }
      .workspace-empty { min-height: 184px; padding-block: 34px; }
      .workspace-heading { display: block; }
      .workspace-status { margin-top: 10px; }
      .action-grid { grid-template-columns: 1fr; }
      .media-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .source-summary-heading, .result { align-items: flex-start; flex-direction: column; }
      .download-actions { width: 100%; justify-content: flex-start; }
      .download-link { width: 100%; }
      .explainer { padding-block: 34px 42px; }
      .footer-actions { width: 100%; flex-wrap: wrap; justify-content: space-between; gap: 12px 20px; }
      .site-footer button { margin-top: 0; }
    }
    @media (max-width: 430px) {
      .app-container { width: calc(100% - 32px); }
      .header-inner { min-height: 68px; }
      .brand { font-size: 18px; }
      .brand-mark { width: 31px; height: 31px; }
      .engine-status { font-size: 14px; }
      .hero h1 { font-size: 44px; }
      .hero-copy { margin-top: 17px; font-size: 16px; }
      .url-control input { padding-left: 52px; font-size: 15px; }
      .url-control > svg { left: 17px; }
      .primary-button { padding-inline: 18px; font-size: 15px; }
      .rights-note { font-size: 12px; }
      .workspace h2, .explainer h2 { font-size: 22px; }
      .workspace-empty p { font-size: 16px; }
      .steps li { grid-template-columns: 44px minmax(0,1fr); gap: 12px; }
      .footer-actions { justify-content: flex-start; }
      .footer-actions .danger-button { flex-basis: 100%; justify-content: flex-start; }
      .dialog-body { padding: 22px; }
    }

    /* V2: one quiet, sharp product surface. */
    :root {
      --bg: #ffffff;
      --panel: #ffffff;
      --surface: #f7f8fa;
      --ink: #101114;
      --muted: #667085;
      --line: #d9dde5;
      --line-strong: #b8c0cc;
      --accent: #2457f5;
      --accent-dark: #1743cc;
      --accent-soft: #f1f4ff;
      --success: #168455;
      --danger: #b42318;
      --log: #0d1117;
    }
    body { min-width: 320px; background: #fff; color: var(--ink); }
    .app-container { width: min(calc(100% - 40px), 1040px); margin-inline: auto; }
    .site-header {
      display: block;
      position: static;
      padding: 0;
      border-bottom: 1px solid var(--line);
      background: #fff;
      backdrop-filter: none;
    }
    .header-inner {
      display: flex;
      min-height: 60px;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }
    .brand { gap: 0; color: var(--ink); font-size: 17px; font-weight: 650; letter-spacing: -.025em; }
    .brand strong { color: var(--accent); font-weight: 650; }
    .header-actions { margin-left: auto; }
    .engine-status {
      gap: 8px;
      padding: 0;
      border: 0;
      color: var(--ink);
      font-size: 13px;
      font-weight: 600;
    }
    .status-dot { width: 8px; height: 8px; box-shadow: none; }
    main { display: block; max-width: none; margin: 0; padding: 0; }
    .hero { padding: 46px 0 25px; }
    .hero h1 {
      max-width: none;
      color: var(--ink);
      font-size: clamp(34px, 4vw, 44px);
      font-weight: 720;
      line-height: 1.08;
      letter-spacing: -.045em;
    }
    .hero-copy {
      max-width: 640px;
      margin-top: 11px;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.5;
    }
    .source-form {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 184px;
      gap: 10px;
      max-width: none;
      margin-top: 23px;
    }
    .terms-acceptance {
      display: flex;
      grid-column: 1 / -1;
      align-items: flex-start;
      gap: 9px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .terms-acceptance input {
      width: 17px;
      min-height: 17px;
      margin: 1px 0 0;
      flex: 0 0 17px;
    }
    .policy-links {
      display: flex;
      grid-column: 1 / -1;
      gap: 14px;
      margin-top: -3px;
    }
    .policy-links button {
      width: auto;
      min-height: 0;
      padding: 0;
      background: transparent;
      color: var(--accent);
      font-size: 13px;
      font-weight: 650;
      text-decoration: underline;
      text-underline-offset: 2px;
    }
    .policy-links button:hover { background: transparent; color: var(--accent-dark); }
    .url-control { position: relative; }
    .url-control > svg { left: 17px; width: 19px; height: 19px; color: var(--muted); }
    .url-control input {
      min-height: 52px;
      margin: 0;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
      padding: 0 16px 0 49px;
      background: #fff;
      color: var(--ink);
      font-size: 15px;
      box-shadow: none;
    }
    .url-control input::placeholder { color: #8b93a1; opacity: 1; }
    .url-control input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(36,87,245,.14); }
    .primary-button {
      width: 100%;
      min-height: 52px;
      border: 1px solid var(--accent);
      border-radius: 4px;
      padding: 0 18px;
      background: var(--accent);
      box-shadow: none;
      color: #fff;
      font-size: 14px;
      font-weight: 650;
    }
    .primary-button:hover { border-color: var(--accent-dark); background: var(--accent-dark); box-shadow: none; transform: none; }
    .primary-button svg { width: 18px; height: 18px; }
    .source-error { min-height: 0; margin-top: 8px; font-size: 13px; line-height: 1.4; }
    .source-error:empty { display: none; }
    .trust-line {
      align-items: center;
      gap: 8px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .trust-line svg { width: 18px; height: 18px; flex: 0 0 18px; color: var(--accent); }
    .workspace { padding: 20px 0 32px; border-top: 1px solid var(--line); border-bottom: 0; }
    .workspace-empty {
      display: grid;
      min-height: 300px;
      place-content: center;
      justify-items: center;
      padding: 36px 24px;
      border: 1px dashed var(--line-strong);
      border-radius: 4px;
      text-align: center;
    }
    .workspace-empty > svg {
      width: 34px;
      height: 34px;
      margin-bottom: 16px;
      fill: none;
      stroke: var(--muted);
      stroke-width: 1.6;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .workspace h2 { margin: 0; color: var(--ink); font-size: 18px; font-weight: 650; letter-spacing: -.02em; }
    .workspace-empty p { max-width: 360px; margin-top: 7px; color: var(--muted); font-size: 14px; line-height: 1.5; }
    .workspace-active { padding: 4px 0 0; }
    .workspace-heading {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 14px;
    }
    .workspace-status { min-height: 32px; font-size: 13px; font-weight: 500; }
    .workspace-layout {
      display: grid;
      grid-template-columns: minmax(0, 1.65fr) minmax(280px, .9fr);
      gap: 20px;
      align-items: start;
    }
    .preview-grid,
    .preview-grid[data-single="true"] { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; }
    .video-preview { min-width: 0; padding: 0; border-radius: 0; }
    .video-title { margin-bottom: 8px; color: var(--ink); font-size: 13px; font-weight: 650; }
    .meta { margin-left: 6px; color: var(--muted); font-size: 12px; font-weight: 450; }
    .video-stage {
      aspect-ratio: 16 / 10;
      border: 1px solid #242934;
      border-radius: 4px;
      background: #0d1117;
      box-shadow: none;
    }
    .video-empty { color: #aeb7c5; font-size: 13px; }
    .advanced-controls { margin-top: 7px; }
    .advanced-controls summary,
    .activity-log summary {
      min-height: 40px;
      border-radius: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .advanced-controls summary::before { margin-right: 7px; font-size: 15px; }
    .frame-controls button,
    .zoom-controls button,
    .frame-fps input { min-height: 42px; border-radius: 3px; }
    .workspace-panel { min-width: 0; border: 1px solid var(--line); border-radius: 4px; padding: 20px; background: #fff; }
    .source-summary { margin: 0; padding: 0; border: 0; border-radius: 0; background: transparent; }
    .source-summary-heading,
    .result { display: block; }
    .quality-label { color: var(--muted); font-size: 12px; font-weight: 600; letter-spacing: 0; text-transform: none; }
    .source-summary-heading strong,
    .result strong {
      display: block;
      max-width: 100%;
      margin-top: 5px;
      overflow: hidden;
      color: var(--ink);
      font-size: 15px;
      font-weight: 650;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .hint { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.45; }
    .media-meta,
    .media-meta[data-kind="image"] {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0;
      margin-top: 18px;
      overflow: visible;
      border: solid var(--line);
      border-width: 1px 0;
      border-radius: 0;
      background: transparent;
    }
    .media-meta div { min-width: 0; padding: 13px 10px; background: #fff; }
    .media-meta div:first-child { padding-left: 0; }
    .media-meta div:last-child { padding-right: 0; }
    .media-meta div + div { border-left: 1px solid var(--line); }
    .media-meta dt { color: var(--muted); font-size: 10px; font-weight: 600; }
    .media-meta dd { margin-top: 4px; font-size: 12px; font-weight: 650; }
    .download-actions { display: grid; justify-content: stretch; gap: 8px; margin-top: 18px; }
    .download-link {
      width: 100%;
      min-height: 46px;
      border: 1px solid var(--accent);
      border-radius: 3px;
      padding: 0 13px;
      background: #fff;
      color: var(--accent);
      font-size: 13px;
      font-weight: 650;
    }
    .download-link:hover { background: var(--accent-soft); }
    .download-primary { background: var(--accent); color: #fff; }
    .download-primary:hover { background: var(--accent-dark); color: #fff; }
    .download-link svg { width: 17px; height: 17px; }
    .enhancement-actions { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--line); }
    .enhancement-actions h3 { margin: 0 0 10px; color: var(--ink); font-size: 13px; font-weight: 650; }
    .action-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin: 0; }
    .choice-button {
      min-height: 44px;
      place-items: center;
      border: 1px solid var(--line-strong);
      border-radius: 3px;
      padding: 0 8px;
      background: #fff;
      color: var(--accent);
      text-align: center;
    }
    .choice-button:hover { border-color: var(--accent); background: var(--accent-soft); }
    .choice-button strong { font-size: 12px; font-weight: 650; white-space: nowrap; }
    .result { margin-top: 20px; padding: 18px 0 0; border: solid var(--line); border-width: 1px 0 0; border-radius: 0; background: transparent; }
    .result .download-link { margin-top: 15px; }
    .activity-log { margin-top: 16px; border: 1px solid var(--line); border-radius: 3px; }
    .activity-log summary { display: flex; align-items: center; padding: 0 14px; }
    pre { min-height: 84px; margin: 0; border: 0; border-top: 1px solid var(--line); border-radius: 0; padding: 14px; background: var(--log); color: #c8d1dc; }
    .house-ad {
      display: flex;
      min-height: 56px;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin: 0 auto 26px;
      padding: 0;
      border: solid var(--line);
      border-width: 1px 0;
      border-radius: 0;
      background: #fff;
    }
    .house-ad > div { display: flex; align-items: center; gap: 10px; }
    .ad-label { color: var(--muted); font-size: 10px; font-weight: 600; letter-spacing: .08em; }
    .house-ad strong { font-size: 13px; font-weight: 600; }
    .house-ad p { display: none; }
    .house-ad button {
      width: auto;
      min-height: 40px;
      border: 0;
      border-radius: 0;
      padding: 0;
      background: transparent;
      color: var(--accent);
      font-size: 13px;
      font-weight: 650;
    }
    .house-ad button:hover { background: transparent; text-decoration: underline; }
    .ad-bait {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      opacity: 0;
      pointer-events: none;
    }
    .site-footer { border-top: 1px solid var(--line); background: var(--surface); }
    .footer-inner { min-height: 76px; gap: 24px; }
    .footer-inner > p { max-width: 560px; font-size: 12px; line-height: 1.5; }
    .footer-actions { gap: 18px; }
    .site-footer button {
      width: auto;
      min-height: 40px;
      padding: 0;
      border-radius: 0;
      background: transparent;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .site-footer button:hover { background: transparent; color: var(--ink); }
    .footer-actions .danger-button { color: var(--danger); }
    .danger-button svg { width: 17px; height: 17px; }
    dialog { border-radius: 6px; box-shadow: 0 22px 70px rgba(16,17,20,.18); }
    dialog::backdrop { background: rgba(16,17,20,.52); backdrop-filter: none; }
    .dialog-body { padding: 26px; }
    .policy-content h2 { font-size: 26px; }
    .icon-button { border-radius: 3px; }
    .dialog-actions button,
    .contact-link { border-radius: 3px; }
    .adblock-content { max-width: 560px; }
    .adblock-content > p { margin-top: 16px; color: var(--muted); font-size: 15px; line-height: 1.6; }
    .adblock-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .dialog-actions .secondary-dialog-button {
      border: 1px solid var(--line-strong);
      background: #fff;
      color: var(--ink);
    }
    .dialog-actions .secondary-dialog-button:hover { border-color: var(--accent); background: var(--accent-soft); }
    :where(a, button, input, summary):focus-visible {
      outline: 3px solid rgba(36,87,245,.28);
      outline-offset: 2px;
    }

    @media (max-width: 820px) {
      .app-container { width: calc(100% - 32px); }
      .header-inner { min-height: 58px; }
      .brand { font-size: 16px; }
      .status-full { display: none; }
      .status-short { display: inline; }
      .hero { padding: 31px 0 20px; }
      .hero h1 { font-size: clamp(30px, 9vw, 36px); line-height: 1.12; }
      .hero-copy { margin-top: 9px; font-size: 15px; }
      .source-form { grid-template-columns: 1fr; gap: 9px; margin-top: 20px; }
      .url-control input,
      .primary-button { min-height: 52px; }
      .primary-button { width: 100%; }
      .trust-line { align-items: flex-start; margin-top: 13px; font-size: 12px; }
      .workspace { padding: 18px 0 24px; }
      .workspace-empty { min-height: 300px; padding: 32px 20px; }
      .workspace-layout { grid-template-columns: 1fr; gap: 16px; }
      .workspace-heading { align-items: flex-start; flex-direction: column; gap: 4px; }
      .workspace-status { min-height: 26px; }
      .video-stage { aspect-ratio: 4 / 3; }
      .workspace-panel { padding: 18px; }
      .media-meta,
      .media-meta[data-kind="image"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .source-summary-heading,
      .result { display: block; }
      .download-actions { width: 100%; }
      .download-link { width: 100%; }
      .action-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .house-ad { align-items: center; flex-direction: row; gap: 12px; }
      .house-ad > div { min-width: 0; }
      .house-ad strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .house-ad button { width: auto; white-space: nowrap; }
      .footer-inner { align-items: flex-start; flex-direction: column; gap: 12px; padding-block: 20px; }
      .footer-actions { width: 100%; flex-wrap: wrap; justify-content: flex-start; gap: 8px 18px; }
      .footer-actions .danger-button { flex-basis: 100%; }
      .adblock-actions { grid-template-columns: 1fr; }
    }

    @media (max-width: 430px) {
      .header-inner { min-height: 56px; }
      .hero { padding-top: 27px; }
      .hero h1 { font-size: 31px; }
      .url-control input { padding-left: 45px; font-size: 14px; }
      .url-control > svg { left: 15px; }
      .workspace-empty { min-height: 285px; }
      .workspace h2 { font-size: 17px; }
      .workspace-empty p { font-size: 13px; }
      .frame-controls { grid-template-columns: 38px minmax(64px, 1fr) 38px minmax(78px, 94px) 38px; gap: 6px; }
      .action-grid { gap: 5px; }
      .choice-button { padding-inline: 5px; }
      .choice-button strong { font-size: 11px; }
      .house-ad { min-height: 52px; }
      .ad-label { display: none; }
      .dialog-body { padding: 20px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <header class="site-header">
    <div class="header-inner app-container">
      <div class="brand" aria-label="Image and Video Downloader home">
        <span>Media <strong>Downloader</strong></span>
      </div>
      <div class="header-actions">
        <div class="engine-status" id="ffmpeg-status" aria-live="polite">
          <span class="status-dot" aria-hidden="true"></span>
          <span class="status-full">Checking local engine...</span>
          <span class="status-short">Local</span>
        </div>
      </div>
    </div>
  </header>

  <main>
    <section class="hero app-container" aria-labelledby="hero-title">
      <h1 id="hero-title">Image &amp; video downloader</h1>
      <p class="hero-copy">Paste a public post to preview and download its media.</p>
      <form class="source-form" id="source-form">
        <label class="sr-only" for="source-url">Image or video URL</label>
        <div class="url-control">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.4 13.6a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.7 1.7M13.6 10.4a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.7-1.7"/></svg>
          <input id="source-url" type="url" inputmode="url" autocomplete="url" placeholder="Paste a VSCO, Instagram, TikTok or Facebook link" aria-describedby="url-help source-error" required>
        </div>
        <button class="primary-button" id="download-original" type="submit">
          Download media
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg>
        </button>
        <label class="terms-acceptance" for="terms-accepted">
          <input id="terms-accepted" type="checkbox" required>
          <span>I accept the Terms of Use and confirm that I have read the Privacy Notice.</span>
        </label>
        <div class="policy-links" aria-label="Legal information">
          <button type="button" data-dialog="terms-dialog">Read Terms of Use</button>
          <button type="button" data-dialog="privacy-dialog">Read Privacy Notice</button>
        </div>
      </form>
      <p class="source-error" id="source-error" role="alert" aria-live="assertive"></p>
      <p class="trust-line" id="url-help">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4.5 6v5.5c0 4.7 3.2 7.9 7.5 9.5 4.3-1.6 7.5-4.8 7.5-9.5V6L12 3Z"/><path d="m8.8 12 2 2 4.5-4.5"/></svg>
        <span>Supports VSCO, Instagram, TikTok and Facebook <span aria-hidden="true">&middot;</span> Optional enhancement runs locally only after confirmation</span>
      </p>
    </section>

    <section class="workspace app-container" aria-label="Media workspace">
      <div class="workspace-empty" id="workspace-empty">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.4 13.6a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.7 1.7M13.6 10.4a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.7-1.7"/></svg>
        <h2>Paste a supported link</h2>
        <p>Your image or video will appear here to preview and download.</p>
      </div>

      <div class="workspace-active" id="workspace-active" hidden>
        <div class="workspace-heading">
          <h2>Downloaded media</h2>
          <div class="workspace-status"><span class="status-dot" aria-hidden="true"></span><span id="workspace-status" aria-live="polite">Ready</span></div>
        </div>

        <div class="workspace-layout">
          <div class="preview-grid" id="preview-grid" data-single="false">
            <article class="video-preview" id="source-player">
              <div class="video-title">Source <span class="meta" id="input-meta">Not loaded</span></div>
              <div class="player-shell" id="source-shell">
                <div class="video-stage" id="source-stage" data-zoomed="false">
                  <video id="source-video" preload="metadata" playsinline controls></video>
                  <img id="source-image" alt="Downloaded source preview" hidden>
                  <div class="video-empty" id="source-empty">Fetching the best available source...</div>
                </div>
                <details class="advanced-controls" id="source-advanced">
                  <summary>Playback controls</summary>
                  <div class="frame-controls" id="source-frame-controls" role="group" aria-label="Frame controls for original">
                    <button id="source-previous-frame" type="button" aria-label="Previous frame" title="Previous frame" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 7-5 5 5 5"/></svg></button>
                    <button id="source-one-fps" type="button" aria-label="Play one frame per second" title="Play one frame per second" aria-pressed="false" disabled>1 FPS</button>
                    <button id="source-next-frame" type="button" aria-label="Next frame" title="Next frame" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 7 5 5-5 5"/></svg></button>
                    <label class="frame-fps"><span>Step FPS</span><input id="source-frame-fps" type="number" min="1" max="240" step="0.001" value="30" aria-label="Frames per second for original" disabled></label>
                    <button id="source-fullscreen" type="button" aria-label="Fullscreen with frame controls" title="Fullscreen" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4H4v4m12-4h4v4M8 20H4v-4m12 4h4v-4"/></svg></button>
                  </div>
                  <div class="zoom-controls" role="group" aria-label="Zoom controls for original">
                    <button id="source-zoom-out" type="button" aria-label="Zoom out" title="Zoom out" disabled>&minus;</button>
                    <input id="source-zoom" type="range" min="1" max="8" step="0.1" value="1" aria-label="Zoom level for original" disabled>
                    <button id="source-zoom-in" type="button" aria-label="Zoom in" title="Zoom in" disabled>+</button>
                    <button id="source-zoom-reset" type="button" aria-label="Reset zoom" title="Reset zoom" disabled>1&times;</button>
                  </div>
                </details>
              </div>
            </article>

            <article class="video-preview" id="output-player" hidden>
              <div class="video-title">Enhanced <span class="meta" id="output-meta">Not started</span></div>
              <div class="player-shell" id="output-shell">
                <div class="video-stage" id="output-stage" data-zoomed="false">
                  <video id="output-video" preload="metadata" playsinline controls></video>
                  <div class="video-empty" id="output-empty">Creating the enhanced copy on this device...</div>
                </div>
                <details class="advanced-controls">
                  <summary>Playback controls</summary>
                  <div class="frame-controls" id="output-frame-controls" role="group" aria-label="Frame controls for enhanced copy">
                    <button id="output-previous-frame" type="button" aria-label="Previous frame" title="Previous frame" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 7-5 5 5 5"/></svg></button>
                    <button id="output-one-fps" type="button" aria-label="Play one frame per second" title="Play one frame per second" aria-pressed="false" disabled>1 FPS</button>
                    <button id="output-next-frame" type="button" aria-label="Next frame" title="Next frame" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 7 5 5-5 5"/></svg></button>
                    <label class="frame-fps"><span>Step FPS</span><input id="output-frame-fps" type="number" min="1" max="240" step="0.001" value="30" aria-label="Frames per second for enhanced copy" disabled></label>
                    <button id="output-fullscreen" type="button" aria-label="Fullscreen with frame controls" title="Fullscreen" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4H4v4m12-4h4v4M8 20H4v-4m12 4h4v-4"/></svg></button>
                  </div>
                  <div class="zoom-controls" role="group" aria-label="Zoom controls for enhanced copy">
                    <button id="output-zoom-out" type="button" aria-label="Zoom out" title="Zoom out" disabled>&minus;</button>
                    <input id="output-zoom" type="range" min="1" max="8" step="0.1" value="1" aria-label="Zoom level for enhanced copy" disabled>
                    <button id="output-zoom-in" type="button" aria-label="Zoom in" title="Zoom in" disabled>+</button>
                    <button id="output-zoom-reset" type="button" aria-label="Reset zoom" title="Reset zoom" disabled>1&times;</button>
                  </div>
                </details>
              </div>
            </article>
          </div>

          <div class="workspace-panel">
            <section class="source-summary" id="source-result" hidden aria-labelledby="source-ready-title">
              <div class="source-summary-heading">
                <div>
                  <span class="quality-label" id="source-ready-title">Source</span>
                  <strong id="source-result-name"></strong>
                  <p class="hint" id="source-quality">Original platform stream</p>
                </div>
              </div>
              <dl class="media-meta" id="source-media" hidden></dl>
              <div class="download-actions">
                <a class="download-link download-primary" id="source-download" href="#" download><span id="source-download-label">Download source</span> <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m-4-4 4 4 4-4M5 20h14"/></svg></a>
                <a class="download-link" id="source-audio" href="#" download hidden>Download TikTok audio <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m-4-4 4 4 4-4M5 20h14"/></svg></a>
              </div>
              <div class="enhancement-actions" id="enhancement-actions">
                <h3>Enhance video</h3>
                <p class="hint">Runs on this device after confirmation and may use significant CPU, memory, battery and time.</p>
                <div class="action-grid">
                  <button class="choice-button" id="download-60" type="button" disabled><strong>60 FPS</strong></button>
                  <button class="choice-button" id="download-90" type="button" disabled><strong>90 FPS</strong></button>
                  <button class="choice-button" id="download-upscale" type="button" disabled><strong>2&times; Upscale</strong></button>
                </div>
              </div>
            </section>

            <section class="result" id="result" hidden aria-labelledby="result-name">
              <div>
                <span class="quality-label">Enhanced file</span>
                <strong id="result-name"></strong>
                <p class="hint" id="result-path">Enhanced synthetic copy</p>
              </div>
              <a class="download-link download-primary" id="download" href="#" download>Download result <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m-4-4 4 4 4-4M5 20h14"/></svg></a>
            </section>
          </div>
        </div>

        <details class="activity-log">
          <summary>Technical details</summary>
          <pre id="log" aria-live="polite">Ready.</pre>
        </details>
      </div>
    </section>

    <aside class="house-ad app-container" aria-label="Advertisement">
      <span class="ad-bait adsbox advertisement" id="ad-bait" aria-hidden="true"></span>
      <div>
        <span class="ad-label">Advertisement</span>
        <strong>Sponsor Media Downloader</strong>
      </div>
      <button type="button" data-dialog="contact-dialog">Advertise here</button>
    </aside>
  </main>

  <footer class="site-footer">
    <div class="footer-inner app-container">
      <p>Optional enhancement runs on this device only after confirmation. Working files are temporary and can be cleared at any time.</p>
      <div class="footer-actions">
        <button type="button" data-dialog="contact-dialog">Contact</button>
        <button type="button" data-dialog="privacy-dialog">Privacy</button>
        <button type="button" data-dialog="terms-dialog">Terms</button>
        <button class="danger-button" id="clear-session" type="button">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16m-10 4v6m4-6v6M9 4h6l1 3H8l1-3Zm-3 3 1 14h10l1-14"/></svg>
          Clear local files
        </button>
      </div>
    </div>
  </footer>

  <dialog id="adblock-dialog" aria-labelledby="adblock-title">
    <div class="dialog-body adblock-content">
      <div class="dialog-heading">
        <div><p class="dialog-kicker">Support the project</p><h2 id="adblock-title">It looks like ads are being blocked</h2></div>
        <button class="icon-button" type="button" data-close-dialog="adblock-dialog" aria-label="Close ad blocker message">&times;</button>
      </div>
      <p>Ads and direct sponsors help keep Media Downloader free. If you want to support the project, allow ads for this local page.</p>
      <div class="dialog-actions adblock-actions">
        <button id="retry-adblock" type="button">I&rsquo;ve allowed ads</button>
        <button class="secondary-dialog-button" type="button" data-close-dialog="adblock-dialog">Continue without ads</button>
      </div>
    </div>
  </dialog>

  <dialog id="contact-dialog" aria-labelledby="contact-title">
    <div class="dialog-body policy-content">
      <div class="dialog-heading">
        <div><p class="dialog-kicker">Public project contact</p><h2 id="contact-title">Contact Media Downloader</h2></div>
        <button class="icon-button" type="button" data-close-dialog="contact-dialog" aria-label="Close contact information">&times;</button>
      </div>
      <section>
        <h3>Advertising</h3>
        <p>Interested in a clearly labelled, direct sponsor placement with no tracking pixel or ad network? Open a public advertising inquiry on GitHub. Do not include personal data or confidential campaign information.</p>
        <a class="contact-link" href="https://github.com/bjorkepoc/video-enhancer/issues/new?title=Advertising%20inquiry" target="_blank" rel="noopener noreferrer">Open advertising inquiry</a>
      </section>
      <section>
        <h3>Privacy and copyright</h3>
        <p>For private privacy and copyright inquiries, email <a href="mailto:bjorke.poc@gmail.com">bjorke.poc@gmail.com</a>. Do not put personal data, private links, access tokens, or media in a public GitHub issue.</p>
      </section>
      <section>
        <h3>Security</h3>
        <p>Potential vulnerabilities should be reported privately through GitHub's security advisory form.</p>
        <a class="contact-link" href="https://github.com/bjorkepoc/video-enhancer/security/advisories/new" target="_blank" rel="noopener noreferrer">Report security privately</a>
      </section>
      <section>
        <h3>Maintainer</h3>
        <p>Media Downloader is maintained publicly by <a href="https://github.com/bjorkepoc" target="_blank" rel="noopener noreferrer">bjorkepoc</a>.</p>
      </section>
      <div class="dialog-actions"><button type="button" data-close-dialog="contact-dialog">Done</button></div>
    </div>
  </dialog>

  <dialog id="privacy-dialog" aria-labelledby="privacy-title">
    <div class="dialog-body policy-content">
      <div class="dialog-heading">
        <div><p class="dialog-kicker">Last updated August 10, 2026</p><h2 id="privacy-title">Privacy at a glance</h2></div>
        <button class="icon-button" type="button" data-close-dialog="privacy-dialog" aria-label="Close privacy information">&times;</button>
      </div>
      <section>
        <h3>Local processing, no account</h3>
        <p>Media Downloader runs through a local app on this device. There is no account, analytics, ad network, or operator-run cloud storage.</p>
        <p>Submitted links are held in the local app's memory while it is running. Source images, videos, audio, archives, and generated files are written to a temporary folder on this device so they can be processed and previewed.</p>
        <p>Optional video enhancement starts only after you explicitly confirm it. Enhancement uses this device's processor, memory and battery; source media and the enhanced result are not sent to an operator-run enhancement service.</p>
      </section>
      <section>
        <h3>House advertisement</h3>
        <p>The app includes a static project notice seeking a direct sponsor. It is bundled with the app and uses no remote creative, cookie, identifier, impression pixel, or click tracking. A local one-pixel marker checks whether an ad blocker hides the placement so the app can show a dismissible support message; the check sends and stores nothing. Opening its contact link takes you to GitHub, which applies its own terms and privacy policy.</p>
      </section>
      <section>
        <h3>Deletion and downloads</h3>
        <p>You can clear temporary files at any time. The app also removes them after a normal shutdown. A forced shutdown or system crash may leave temporary files until you or the operating system removes them. Files you download remain wherever you save them.</p>
      </section>
      <section>
        <h3>Source platforms</h3>
        <p>When you submit a VSCO, Instagram, TikTok, or Facebook link, this device connects to that platform and its delivery providers. They receive technical request data such as your IP address and apply their own privacy terms. Media Downloader does not send your link, media, or activity to an operator-run cloud service.</p>
      </section>
      <section>
        <h3>Cookies and browser storage</h3>
        <p>This app does not use cookies, localStorage, IndexedDB, analytics identifiers, or advertising identifiers. A one-time security token in the page URL protects the local session; it is not used for tracking and expires when the app stops.</p>
      </section>
      <div class="dialog-actions"><button type="button" data-close-dialog="privacy-dialog">Done</button></div>
    </div>
  </dialog>

  <dialog id="terms-dialog" aria-labelledby="terms-title">
    <div class="dialog-body policy-content">
      <div class="dialog-heading">
        <div><p class="dialog-kicker">Last updated August 10, 2026</p><h2 id="terms-title">Terms of use</h2></div>
        <button class="icon-button" type="button" data-close-dialog="terms-dialog" aria-label="Close terms of use">&times;</button>
      </div>
      <section>
        <h3>About this tool</h3>
        <p>Media Downloader retrieves media from supported public image and video links. It does not index, publish, recommend, or provide account or platform access. Optional enhancement is initiated by you and runs on your device, not on an operator-run enhancement server.</p>
      </section>
      <section>
        <h3>Your responsibility</h3>
        <p>Use Media Downloader only for public content you own or are legally permitted to download and use. Follow applicable law, copyright and privacy rights, and the source platform's terms. Do not use it to access private content, bypass a login or access control, infringe rights, or distribute unlawful content.</p>
      </section>
      <section>
        <h3>Third-party platforms</h3>
        <p>VSCO, Instagram, TikTok, and Facebook are independent services. Media Downloader is not affiliated with, sponsored by, or approved by them. Platform changes may interrupt support without notice.</p>
      </section>
      <section>
        <h3>Quality and availability</h3>
        <p>The tool is provided as available. It does not guarantee a particular resolution, frame rate, codec, availability, or that a platform will expose a downloadable source. Synthetic enhancement can introduce artifacts.</p>
      </section>
      <section>
        <h3>Local resource use</h3>
        <p>Enhancement may use substantial processor, memory, storage and battery resources and may make your device warm or slow. It starts only after separate confirmation, can be stopped by closing the app, leaves the original unchanged, and creates a separate synthetic copy.</p>
      </section>
      <section>
        <h3>Limits of responsibility</h3>
        <p>To the fullest extent permitted by applicable law, the operator is not responsible for your selected content, whether you have permission to use it, compliance with third-party platform terms, local device resource use, interruption, unavailable sources, synthetic artifacts, or indirect loss arising from your use of the tool. The tool is provided as available, without guarantees beyond rights that cannot legally be excluded. Nothing in these terms limits mandatory consumer rights or liability that cannot be excluded by law.</p>
      </section>
      <div class="dialog-actions"><button type="button" data-close-dialog="terms-dialog">Done</button></div>
    </div>
  </dialog>

  <dialog id="local-processing-dialog" aria-labelledby="local-processing-title">
    <form class="dialog-body policy-content" id="local-processing-form">
      <div class="dialog-heading">
        <div><p class="dialog-kicker">Runs on this device</p><h2 id="local-processing-title">Confirm local enhancement</h2></div>
        <button class="icon-button" type="button" data-close-dialog="local-processing-dialog" aria-label="Cancel local enhancement">&times;</button>
      </div>
      <section>
        <h3>Your device does the work</h3>
        <p>This enhancement uses your device's processor, memory, storage and battery. It may take time, make the device warm or temporarily reduce performance. The original remains unchanged and the synthetic result stays on this device.</p>
      </section>
      <label class="terms-acceptance" for="local-processing-accepted">
        <input id="local-processing-accepted" type="checkbox" required>
        <span>I understand and want to start local enhancement.</span>
      </label>
      <div class="dialog-actions">
        <button class="secondary-dialog-button" type="button" data-close-dialog="local-processing-dialog">Cancel</button>
        <button type="submit">Start local enhancement</button>
      </div>
    </form>
  </dialog>

  <script nonce="__CSP_NONCE__">
    const $ = (id) => document.getElementById(id);
    const sessionToken = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    const TERMS_VERSION = "2026-08-10";
    const state = {
      poll: null,
      sourceId: null,
      outputFps: 30,
      pendingEnhancementMode: null,
    };

    function apiFetch(path, options = {}) {
      const headers = new Headers(options.headers || {});
      headers.set("x-video-enhancer-token", sessionToken);
      return fetch(path, { ...options, headers });
    }

    function localFileUrl(path, download = false) {
      const url = new URL(path, window.location.origin);
      url.searchParams.set("token", sessionToken);
      if (download) url.searchParams.set("download", "1");
      return `${url.pathname}${url.search}`;
    }

    function createPlayerController(name) {
      const player = $(`${name}-player`);
      const shell = $(`${name}-shell`);
      const stage = $(`${name}-stage`);
      const video = $(`${name}-video`);
      const fullscreen = $(`${name}-fullscreen`);
      const zoom = $(`${name}-zoom`);
      const zoomOut = $(`${name}-zoom-out`);
      const zoomIn = $(`${name}-zoom-in`);
      const zoomReset = $(`${name}-zoom-reset`);
      const previous = $(`${name}-previous-frame`);
      const oneFps = $(`${name}-one-fps`);
      const next = $(`${name}-next-frame`);
      const fpsInput = $(`${name}-frame-fps`);
      const controls = [
        fullscreen,
        zoom, zoomOut, zoomIn, zoomReset,
        previous, oneFps, next, fpsInput,
      ];
      const pointers = new Map();
      let timer = null;
      let scale = 1;
      let offsetX = 0;
      let offsetY = 0;
      let lastPoint = null;
      let lastPinch = null;

      const fps = () => {
        const value = Number(fpsInput.value);
        return Number.isFinite(value) && value > 0 ? value : 30;
      };
      const stopOneFps = () => {
        if (timer !== null) clearInterval(timer);
        timer = null;
        oneFps.setAttribute("aria-pressed", "false");
      };
      const step = (direction, keepOneFps = false) => {
        if (!keepOneFps) stopOneFps();
        video.pause();
        const duration = Number.isFinite(video.duration) ? video.duration : 0;
        const current = Number.isFinite(video.currentTime) ? video.currentTime : 0;
        const target = current + direction / fps();
        video.currentTime = Math.max(0, Math.min(duration, target));
        if (direction > 0 && target >= duration) stopOneFps();
      };
      const setEnabled = (enabled) => {
        controls.forEach((control) => { control.disabled = !enabled; });
        fullscreen.disabled = !enabled || typeof shell.requestFullscreen !== "function";
      };
      const clampPan = () => {
        const rect = stage.getBoundingClientRect();
        offsetX = Math.min(0, Math.max(rect.width * (1 - scale), offsetX));
        offsetY = Math.min(0, Math.max(rect.height * (1 - scale), offsetY));
      };
      const renderZoom = () => {
        clampPan();
        video.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
        zoom.value = String(Math.round(scale * 10) / 10);
        stage.dataset.zoomed = String(scale > 1);
      };
      const zoomAt = (value, clientX, clientY) => {
        const nextScale = Math.min(8, Math.max(1, Number(value) || 1));
        const rect = stage.getBoundingClientRect();
        const pointX = Number.isFinite(clientX) ? clientX - rect.left : rect.width / 2;
        const pointY = Number.isFinite(clientY) ? clientY - rect.top : rect.height / 2;
        const ratio = nextScale / scale;
        offsetX = pointX - (pointX - offsetX) * ratio;
        offsetY = pointY - (pointY - offsetY) * ratio;
        scale = nextScale;
        renderZoom();
      };
      const resetZoom = () => {
        scale = 1;
        offsetX = 0;
        offsetY = 0;
        renderZoom();
      };
      const gesture = () => {
        const [first, second] = [...pointers.values()];
        return {
          x: (first.x + second.x) / 2,
          y: (first.y + second.y) / 2,
          distance: Math.hypot(second.x - first.x, second.y - first.y),
        };
      };

      fullscreen.addEventListener("click", () => {
        if (document.fullscreenElement === shell) document.exitFullscreen();
        else shell.requestFullscreen().catch(() => {});
      });
      zoom.addEventListener("input", () => zoomAt(Number(zoom.value)));
      zoomOut.addEventListener("click", () => zoomAt(scale - 0.5));
      zoomIn.addEventListener("click", () => zoomAt(scale + 0.5));
      zoomReset.addEventListener("click", resetZoom);
      stage.addEventListener("wheel", (event) => {
        if (zoom.disabled) return;
        event.preventDefault();
        zoomAt(scale * Math.exp(-event.deltaY * 0.002), event.clientX, event.clientY);
      }, { passive: false });
      stage.addEventListener("dblclick", (event) => {
        if (zoom.disabled) return;
        event.preventDefault();
        if (scale >= 7.9) resetZoom();
        else zoomAt(Math.min(8, scale * 2), event.clientX, event.clientY);
      });
      stage.addEventListener("pointerdown", (event) => {
        if (zoom.disabled) return;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (scale > 1 || pointers.size > 1) stage.setPointerCapture(event.pointerId);
        if (pointers.size === 1) lastPoint = { x: event.clientX, y: event.clientY };
        if (pointers.size === 2) lastPinch = gesture();
        if (scale > 1 || pointers.size > 1) stage.classList.add("dragging");
      });
      stage.addEventListener("pointermove", (event) => {
        if (!pointers.has(event.pointerId)) return;
        pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (pointers.size >= 2) {
          const current = gesture();
          if (lastPinch) {
            offsetX += current.x - lastPinch.x;
            offsetY += current.y - lastPinch.y;
            zoomAt(
              scale * current.distance / Math.max(1, lastPinch.distance),
              current.x,
              current.y,
            );
          }
          lastPinch = current;
          event.preventDefault();
          return;
        }
        if (scale > 1 && lastPoint) {
          offsetX += event.clientX - lastPoint.x;
          offsetY += event.clientY - lastPoint.y;
          lastPoint = { x: event.clientX, y: event.clientY };
          renderZoom();
          event.preventDefault();
        }
      });
      const endPointer = (event) => {
        pointers.delete(event.pointerId);
        if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
        lastPinch = pointers.size >= 2 ? gesture() : null;
        lastPoint = pointers.size === 1 ? [...pointers.values()][0] : null;
        if (!pointers.size) stage.classList.remove("dragging");
      };
      stage.addEventListener("pointerup", endPointer);
      stage.addEventListener("pointercancel", endPointer);
      previous.addEventListener("click", () => step(-1));
      next.addEventListener("click", () => step(1));
      oneFps.addEventListener("click", () => {
        if (timer !== null) {
          stopOneFps();
          return;
        }
        video.pause();
        oneFps.setAttribute("aria-pressed", "true");
        timer = setInterval(() => step(1, true), 1000);
      });
      player.addEventListener("keydown", (event) => {
        if (event.target instanceof HTMLInputElement) return;
        if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
          event.preventDefault();
          step(event.key === "ArrowRight" ? 1 : -1);
        } else if (["+", "="].includes(event.key)) {
          event.preventDefault();
          zoomAt(scale + 0.5);
        } else if (event.key === "-") {
          event.preventDefault();
          zoomAt(scale - 0.5);
        } else if (event.key === "0") {
          event.preventDefault();
          resetZoom();
        }
      });
      video.addEventListener("loadedmetadata", () => {
        setEnabled(true);
        resetZoom();
      });
      video.addEventListener("emptied", () => {
        stopOneFps();
        resetZoom();
        setEnabled(false);
      });
      video.addEventListener("play", stopOneFps);
      video.addEventListener("ended", stopOneFps);
      new ResizeObserver(renderZoom).observe(stage);

      return {
        fps,
        setFps(value) {
          const parsed = Number(value);
          const nextFps = Number.isFinite(parsed) && parsed > 0 ? parsed : 30;
          fpsInput.value = String(Math.round(nextFps * 1000) / 1000);
        },
        reset() {
          stopOneFps();
          resetZoom();
          fpsInput.value = "30";
          setEnabled(false);
        },
      };
    }

    const sourceFrames = createPlayerController("source");
    const outputFrames = createPlayerController("output");

   function setLog(lines) {
      const entries = lines && lines.length ? lines : ["Ready."];
      $("log").textContent = entries.join("\\n");
     $("log").scrollTop = $("log").scrollHeight;
      $("workspace-status").textContent = entries[entries.length - 1];
   }

    function showWorkspace(active) {
      $("workspace-empty").hidden = active;
      $("workspace-active").hidden = !active;
    }

    function setEngineStatus(ready, message) {
      const status = $("ffmpeg-status");
      status.dataset.state = ready ? "ready" : "error";
      status.querySelector(".status-full").textContent = message;
      status.querySelector(".status-short").textContent = ready ? "Local" : "Unavailable";
   }

   async function loadConfig() {
     const response = await apiFetch("/api/config");
     const config = await response.json();
      if (!response.ok) throw new Error(config.error || "Invalid local session.");
      setEngineStatus(
        config.ffmpeg === "found",
        config.ffmpeg === "found" ? "Local engine ready" : "FFmpeg unavailable",
      );
   }

    async function postJSON(path, body) {
      const response = await apiFetch(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Request failed.");
      return payload;
    }

    function setDerivedDisabled(disabled) {
      ["download-60", "download-90", "download-upscale"].forEach((id) => {
        $(id).disabled = disabled;
      });
    }

    $("source-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!$("source-form").reportValidity()) return;
      const url = $("source-url").value.trim();
      state.sourceId = null;
      $("download-original").disabled = true;
     $("source-error").textContent = "";
     $("source-result").hidden = true;
      $("result").hidden = true;
      $("source-media").hidden = true;
      $("source-audio").hidden = true;
      $("source-image").hidden = true;
      $("source-image").removeAttribute("src");
      $("source-video").hidden = false;
      $("source-advanced").hidden = false;
      $("enhancement-actions").hidden = false;
      $("output-player").hidden = true;
      $("preview-grid").dataset.single = "false";
      $("source-empty").hidden = false;
      $("source-empty").textContent = "Fetching the best available source...";
      $("output-empty").hidden = false;
      $("output-empty").textContent = "Choose an enhancement after the source is ready.";
      for (const name of ["source", "output"]) {
        const video = $(`${name}-video`);
        video.removeAttribute("src");
        video.load();
      }
      sourceFrames.reset();
      outputFrames.reset();
      showWorkspace(true);
     setDerivedDisabled(true);
      setLog(["Starting source download..."]);
     try {
       const source = await postJSON("/api/sources/download", {
         url,
         terms_accepted: true,
         terms_version: TERMS_VERSION,
       });
       state.sourceId = source.id;
       watchSource(source.id).catch(showPollingError);
      } catch (error) {
        $("source-error").textContent = error.message;
        $("download-original").disabled = false;
        showWorkspace(false);
        setLog([error.message]);
      }
   });

   function mediaValue(value, suffix = "") {
      return value === null || value === undefined ? "Unknown" : `${value}${suffix}`;
   }

   function renderMedia(source) {
     const media = source.media;
     const size = media.size ? `${(media.size / 1024 / 1024).toFixed(1)} MB` : "Unknown";
     const values = source.media_type === "image" ? [
        ["Type", source.item_count > 1 ? "Image archive" : "Image"],
        ["Items", String(source.item_count)],
        ["Size", size],
     ] : [
        ["Resolution", media.width && media.height ? `${media.width}x${media.height}` : "Unknown"],
        ["Frame rate", mediaValue(media.fps, " FPS")],
        ["Video", mediaValue(media.video_codec)],
        ["Audio", mediaValue(media.audio_codec)],
        ["Bitrate", media.bitrate ? `${Math.round(media.bitrate / 1000)} kbps` : "Unknown"],
        ["Size", size],
     ];
      $("source-media").dataset.kind = source.media_type;
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
       const response = await apiFetch(`/api/sources/${id}`);
       const source = await response.json();
        if (!response.ok) throw new Error(source.error || "Source job not found.");
       setLog(source.logs);
       if (source.status === "done") {
         clearInterval(state.poll);
         const image = source.media_type === "image";
         const label = image
           ? source.item_count > 1 ? `${source.item_count} original images` : "Original platform image"
           : source.operation === "remuxed" ? "Remuxed without video re-encoding" : "Original platform stream";
         $("source-quality").textContent = label;
         $("source-result-name").textContent = source.original_name;
         $("source-download").href = localFileUrl(source.original_url, true);
         $("source-download-label").textContent = image
           ? source.item_count > 1 ? "Download all images (.zip)" : "Download image"
           : "Download video";
         if (source.audio_url) {
           $("source-audio").href = localFileUrl(source.audio_url, true);
           $("source-audio").hidden = false;
         }
         $("source-result").hidden = false;
         $("preview-grid").dataset.single = String(image);
         $("output-player").hidden = true;
         $("source-advanced").hidden = image;
         $("enhancement-actions").hidden = image;
         $("source-video").hidden = image;
         $("source-image").hidden = !image;
         if (image) {
           sourceFrames.reset();
           $("source-image").src = localFileUrl(source.preview_url);
           $("input-meta").textContent = `${source.item_count} image${source.item_count === 1 ? "" : "s"}`;
         } else {
           sourceFrames.setFps(source.media.fps);
           $("source-video").src = localFileUrl(source.preview_url);
           $("source-video").load();
           $("input-meta").textContent = `${mediaValue(source.media.width)}x${mediaValue(source.media.height)} · ${mediaValue(source.media.fps, " FPS")}`;
         }
         $("source-empty").hidden = true;
         renderMedia(source);
         $("download-original").disabled = false;
         setDerivedDisabled(image);
          $("workspace-status").textContent = image
            ? "Images ready to download."
            : source.audio_url
              ? "Video and TikTok audio ready to download."
              : "Video ready. Choose an enhancement or download the original.";
       } else if (source.status === "error") {
         clearInterval(state.poll);
         state.sourceId = null;
         $("source-error").textContent = source.error;
         showWorkspace(false);
         $("download-original").disabled = false;
       }
      };
      state.poll = setInterval(() => tick().catch(showPollingError), 1000);
      await tick();
    }

   function showPollingError(error) {
     clearInterval(state.poll);
     setLog([error.message]);
      $("source-error").textContent = error.message;
     $("download-original").disabled = false;
   }

   async function startSourceEnhancement(mode) {
     if (!state.sourceId) return;
     state.outputFps = mode === "upscale" ? sourceFrames.fps() : Number(mode);
     setDerivedDisabled(true);
     $("result").hidden = true;
      $("output-player").hidden = false;
      $("output-meta").textContent = "Starting";
      $("output-empty").hidden = false;
      $("output-empty").textContent = "Creating the enhanced copy on this device...";
      $("output-video").removeAttribute("src");
      $("output-video").load();
     try {
        const job = await postJSON(`/api/sources/${state.sourceId}/enhance`, {
          mode,
          local_processing_accepted: true,
        });
        watchJob(job.id).catch(showPollingError);
      } catch (error) {
        setDerivedDisabled(false);
        setLog([error.message]);
      }
    }

    function requestSourceEnhancement(mode) {
      state.pendingEnhancementMode = mode;
      $("local-processing-accepted").checked = false;
      $("local-processing-dialog").showModal();
    }

    $("local-processing-form").addEventListener("submit", (event) => {
      event.preventDefault();
      if (!event.currentTarget.reportValidity()) return;
      const mode = state.pendingEnhancementMode;
      state.pendingEnhancementMode = null;
      $("local-processing-dialog").close();
      if (mode) startSourceEnhancement(mode);
    });

    $("download-60").addEventListener("click", () => requestSourceEnhancement("60"));
   $("download-90").addEventListener("click", () => requestSourceEnhancement("90"));
   $("download-upscale").addEventListener("click", () => requestSourceEnhancement("upscale"));

    async function watchJob(id) {
     clearInterval(state.poll);
     const tick = async () => {
       const response = await apiFetch(`/api/jobs/${id}`);
       const job = await response.json();
       if (!response.ok) throw new Error(job.error || "Job not found");
        $("output-meta").textContent = job.status.charAt(0).toUpperCase() + job.status.slice(1);
       setLog(job.logs);
       if (job.status === "done") {
         clearInterval(state.poll);
          setDerivedDisabled(false);
         $("result").hidden = false;
         $("result-name").textContent = job.output_name;
         $("result-path").textContent = "Enhanced synthetic copy";
         $("download").href = localFileUrl(job.output_url, true);
         outputFrames.setFps(state.outputFps);
         $("output-video").src = localFileUrl(job.output_url);
         $("output-video").load();
          $("output-empty").hidden = true;
          $("workspace-status").textContent = "Enhanced file ready to download.";
       }
       if (job.status === "error") {
         clearInterval(state.poll);
          setDerivedDisabled(false);
          $("output-empty").textContent = job.error || "The enhanced copy could not be created.";
       }
     };
     state.poll = setInterval(() => tick().catch((error) => {
       showPollingError(error);
        setDerivedDisabled(false);
     }), 1000);
      await tick();
    }

   function resetInterface() {
     clearInterval(state.poll);
     state.poll = null;
     state.sourceId = null;
     $("source-url").value = "";
     $("source-result").hidden = true;
     $("result").hidden = true;
     $("source-media").hidden = true;
     $("source-media").removeAttribute("data-kind");
     $("source-error").textContent = "";
      $("input-meta").textContent = "Not loaded";
      $("output-meta").textContent = "Not started";
      $("source-empty").hidden = false;
      $("source-empty").textContent = "Fetching the best available source...";
      $("source-image").hidden = true;
      $("source-image").removeAttribute("src");
      $("source-video").hidden = false;
      $("source-audio").hidden = true;
      $("source-audio").removeAttribute("href");
      $("source-advanced").hidden = false;
      $("enhancement-actions").hidden = false;
      $("output-player").hidden = true;
      $("preview-grid").dataset.single = "false";
      $("output-empty").hidden = false;
      $("output-empty").textContent = "Choose an enhancement after the source is ready.";
     for (const name of ["source", "output"]) {
       const video = $(`${name}-video`);
       video.removeAttribute("src");
        video.load();
      }
     sourceFrames.reset();
     outputFrames.reset();
     setDerivedDisabled(true);
      showWorkspace(false);
      setLog(["Temporary local files cleared."]);
   }

    $("clear-session").addEventListener("click", async () => {
      $("clear-session").disabled = true;
      try {
        await postJSON("/api/session/clear", {});
        resetInterface();
      } catch (error) {
        setLog([error.message]);
      } finally {
        $("clear-session").disabled = false;
      }
    });

    document.querySelectorAll("[data-dialog]").forEach((button) => {
      button.addEventListener("click", () => $(button.dataset.dialog).showModal());
    });
    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => $(button.dataset.closeDialog).close());
    });
    $("retry-adblock").addEventListener("click", () => window.location.reload());
    window.requestAnimationFrame(() => {
      const bait = $("ad-bait");
      const style = window.getComputedStyle(bait);
      if (
        style.display === "none"
        || style.visibility === "hidden"
        || bait.offsetWidth === 0
        || bait.offsetHeight === 0
      ) {
        $("adblock-dialog").showModal();
      }
    });

    loadConfig().catch((error) => {
      setEngineStatus(false, "Local session unavailable");
      $("source-error").textContent = error.message;
      setLog([error.message]);
    });
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
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)
    cancelled: bool = False


@dataclass
class SourceJob:
    id: str
    url: str
    directory: Path
    status: str = "queued"
    original_path: Path | None = None
    preview_path: Path | None = None
    audio_path: Path | None = None
    platform: str = ""
    media_type: str = ""
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
            source.status in {"queued", "downloading"}
            for source in SOURCES.values()
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
                thread.join()
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
        "item_count": job.item_count,
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


def own_process(
    job: Job | SourceJob, process: subprocess.Popen[bytes] | None
) -> None:
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
    with LOCK:
        if any(job.status in {"queued", "running"} for job in JOBS.values()):
            raise ValueError("Wait for the active export to finish.")
        if any(
            source.status in {"queued", "downloading"}
            for source in SOURCES.values()
        ):
            raise ValueError("Wait for the active source download to finish.")
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
        try:
            command = build_ffmpeg_command(
                input_path, output_path, build_options(params)
            )
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        for previous in JOBS.values():
            shutil.rmtree(previous.output_path.parent, ignore_errors=True)
        JOBS.clear()
        job = Job(job_id, input_path, output_path, command)
        job.logs.append(f"Loaded {original}.")
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


def run_source_download(job: SourceJob) -> None:
    with LOCK:
        job.status = "downloading"
        job.logs.append("Original source download started.")
    try:
        result = download_source(
            job.url,
            job.directory,
            process_callback=lambda process: own_process(job, process),
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
            raise ValueError("Accept the current Terms of Use before downloading media.")
        url = str(body.get("url", "")).strip()
        platform = validate_social_url(url)
        source_id = uuid.uuid4().hex[:12]
        directory = self.work_dir / f"source-{source_id}"
        source = SourceJob(source_id, url, directory, platform=platform)
        with LOCK:
            if any(job.status in {"queued", "running"} for job in JOBS.values()):
                raise ValueError("Wait for the active export to finish.")
            if any(
                job.status in {"queued", "downloading"}
                for job in SOURCES.values()
            ):
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
                    mimetypes.guess_type(file.name)[0]
                    if file
                    else None
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
        content_type = (
            "video/mp4"
            if file.suffix.lower() in {".mp4", ".m4v"}
            else "application/octet-stream"
        )
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
            self.send_header(
                "content-disposition", f'{disposition}; filename="{file.name}"'
            )
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
