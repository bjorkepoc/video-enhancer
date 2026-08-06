"""Local web UI for the video enhancer CLI core."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
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
from .sources import SourceError, download_source, validate_social_url

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_JSON_BODY = 20_000
REQUEST_TIMEOUT_SECONDS = 60
API_TOKEN_HEADER = "x-video-enhancer-token"  # nosec B105
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
  <title>Video Enhancer</title>
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
    .video-stage video {
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
    .media-meta {
      grid-template-columns: repeat(6, minmax(0, 1fr));
      margin-top: 20px;
      border-color: var(--line);
      border-radius: 10px;
      background: var(--line);
    }
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
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <header class="site-header">
    <div class="header-inner app-container">
      <div class="brand" aria-label="Video Enhancer home">
        <svg class="brand-mark" viewBox="0 0 44 44" aria-hidden="true">
          <path d="M9 5.5 36 22 9 38.5Z" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linejoin="round"/>
          <path d="m16 15 12 7-12 7Z" fill="currentColor"/>
        </svg>
        <span>Video <strong>Enhancer</strong></span>
      </div>
      <div class="header-actions">
        <nav class="legal-nav" aria-label="Legal information">
          <button class="header-link" type="button" data-dialog="contact-dialog">Contact</button>
          <button class="header-link" type="button" data-dialog="privacy-dialog">Privacy</button>
          <button class="header-link" type="button" data-dialog="terms-dialog">Terms</button>
        </nav>
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
      <h1 id="hero-title">Paste a video link.<br>Keep the files.</h1>
      <p class="hero-copy">Fetch the best available public source to this device.<br> Create optional 60 FPS, 90 FPS, or 2&times; versions locally.</p>
      <form class="source-form" id="source-form">
        <label class="sr-only" for="source-url">Video URL</label>
        <div class="url-control">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.4 13.6a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.7 1.7M13.6 10.4a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.7-1.7"/></svg>
          <input id="source-url" type="url" inputmode="url" autocomplete="url" placeholder="https://www.example.com/video" aria-describedby="url-help" required>
        </div>
        <button class="primary-button" id="download-original" type="submit">
          Get best available source
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg>
        </button>
      </form>
      <p class="rights-note" id="url-help">Public TikTok and Instagram links only. Use content you own or are allowed to download.</p>
      <p class="trust-line">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4.5 6v5.5c0 4.7 3.2 7.9 7.5 9.5 4.3-1.6 7.5-4.8 7.5-9.5V6L12 3Z"/><path d="m8.8 12 2 2 4.5-4.5"/></svg>
        No account. No operator cloud. Temporary processing stays on this device.
      </p>
      <p class="source-error" id="source-error" role="alert" aria-live="assertive"></p>
    </section>

    <aside class="house-ad app-container" aria-label="Advertisement">
      <div>
        <span class="ad-label">Advertisement</span>
        <strong>Sponsor Video Enhancer</strong>
        <p>Reach creators who work with social video through a direct, tracking-free placement.</p>
      </div>
      <button type="button" data-dialog="contact-dialog">Advertise here</button>
    </aside>

    <section class="workspace app-container" aria-labelledby="workspace-title">
      <div class="workspace-empty" id="workspace-empty">
        <h2 id="workspace-title">Your workspace</h2>
        <p>Paste a link above to load the source, choose an enhancement, and download the result.</p>
      </div>

      <div class="workspace-active" id="workspace-active" hidden>
        <div class="workspace-heading">
          <div>
            <h2>Preview &amp; enhance</h2>
            <p>Compare the original with a locally generated copy.</p>
          </div>
          <div class="workspace-status"><span class="status-dot" aria-hidden="true"></span><span id="workspace-status" aria-live="polite">Ready</span></div>
        </div>

        <div class="preview-grid">
          <article class="video-preview" id="source-player" tabindex="0">
            <div class="video-title">Original <span class="meta" id="input-meta">Not loaded</span></div>
            <div class="player-shell" id="source-shell">
              <div class="video-stage" id="source-stage" data-zoomed="false">
                <video id="source-video" preload="metadata" playsinline controls></video>
                <div class="video-empty" id="source-empty">Fetching the best available source...</div>
              </div>
              <details class="advanced-controls">
                <summary>Advanced comparison controls</summary>
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

          <article class="video-preview" id="output-player" tabindex="0">
            <div class="video-title">Enhanced <span class="meta" id="output-meta">Not started</span></div>
            <div class="player-shell" id="output-shell">
              <div class="video-stage" id="output-stage" data-zoomed="false">
                <video id="output-video" preload="metadata" playsinline controls></video>
                <div class="video-empty" id="output-empty">Choose an enhancement after the source is ready.</div>
              </div>
              <details class="advanced-controls">
                <summary>Advanced comparison controls</summary>
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

        <section class="source-summary" id="source-result" hidden aria-labelledby="source-ready-title">
          <div class="source-summary-heading">
            <div>
              <span class="quality-label" id="source-ready-title">Source ready</span>
              <strong id="source-result-name"></strong>
              <p class="hint" id="source-quality">Original platform stream</p>
            </div>
            <a class="download-link" id="source-download" href="#" download>Download source <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m-4-4 4 4 4-4M5 20h14"/></svg></a>
          </div>
          <dl class="media-meta" id="source-media" hidden></dl>
          <div class="enhancement-actions">
            <h3>Choose an enhancement</h3>
            <div class="action-grid">
              <button class="choice-button" id="download-60" type="button" disabled><strong>60 FPS</strong><span>Smoother motion</span></button>
              <button class="choice-button" id="download-90" type="button" disabled><strong>90 FPS</strong><span>Ultra-smooth motion</span></button>
              <button class="choice-button" id="download-upscale" type="button" disabled><strong>2&times; Upscale</strong><span>Higher resolution</span></button>
            </div>
          </div>
        </section>

        <section class="result" id="result" hidden aria-labelledby="result-name">
          <div>
            <span class="quality-label">Enhanced file ready</span>
            <strong id="result-name"></strong>
            <p class="hint" id="result-path">Enhanced synthetic copy</p>
          </div>
          <a class="download-link" id="download" href="#" download>Download result <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m-4-4 4 4 4-4M5 20h14"/></svg></a>
        </section>

        <details class="activity-log">
          <summary>Activity details</summary>
          <pre id="log" aria-live="polite">Ready.</pre>
        </details>
      </div>
    </section>

    <section class="explainer app-container" aria-labelledby="how-title">
      <div class="steps">
        <h2 id="how-title">How it works</h2>
        <ol>
          <li><span>1</span><div><strong>Load a public link</strong><p>Paste a link to a publicly available video.</p></div></li>
          <li><span>2</span><div><strong>Choose an enhancement</strong><p>Select 60 FPS, 90 FPS, or 2&times; to process locally.</p></div></li>
          <li><span>3</span><div><strong>Download your file</strong><p>Save the enhanced file to your device.</p></div></li>
        </ol>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="footer-inner app-container">
      <p>Processing runs through a local app on this device. Working files are temporary and can be cleared at any time.</p>
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

  <dialog id="contact-dialog" aria-labelledby="contact-title">
    <div class="dialog-body policy-content">
      <div class="dialog-heading">
        <div><p class="dialog-kicker">Public project contact</p><h2 id="contact-title">Contact Video Enhancer</h2></div>
        <button class="icon-button" type="button" data-close-dialog="contact-dialog" aria-label="Close contact information">&times;</button>
      </div>
      <section>
        <h3>Advertising</h3>
        <p>Interested in a clearly labelled, direct sponsor placement with no tracking pixel or ad network? Open a public advertising inquiry on GitHub. Do not include personal data or confidential campaign information.</p>
        <a class="contact-link" href="https://github.com/bjorkepoc/video-enhancer/issues/new?title=Advertising%20inquiry" target="_blank" rel="noopener noreferrer">Open advertising inquiry</a>
      </section>
      <section>
        <h3>Privacy and copyright</h3>
        <p>A private privacy and copyright contact is not published yet. Do not put personal data, private links, access tokens, or media in a public GitHub issue.</p>
      </section>
      <section>
        <h3>Security</h3>
        <p>Potential vulnerabilities should be reported privately through GitHub's security advisory form.</p>
        <a class="contact-link" href="https://github.com/bjorkepoc/video-enhancer/security/advisories/new" target="_blank" rel="noopener noreferrer">Report security privately</a>
      </section>
      <section>
        <h3>Maintainer</h3>
        <p>Video Enhancer is maintained publicly by <a href="https://github.com/bjorkepoc" target="_blank" rel="noopener noreferrer">bjorkepoc</a>.</p>
      </section>
      <div class="dialog-actions"><button type="button" data-close-dialog="contact-dialog">Done</button></div>
    </div>
  </dialog>

  <dialog id="privacy-dialog" aria-labelledby="privacy-title">
    <div class="dialog-body policy-content">
      <div class="dialog-heading">
        <div><p class="dialog-kicker">Last updated August 6, 2026</p><h2 id="privacy-title">Privacy at a glance</h2></div>
        <button class="icon-button" type="button" data-close-dialog="privacy-dialog" aria-label="Close privacy information">&times;</button>
      </div>
      <section>
        <h3>Local processing, no account</h3>
        <p>Video Enhancer runs through a local app on this device. There is no account, analytics, ad network, or operator-run cloud storage.</p>
        <p>Submitted links are held in the local app's memory while it is running. Source videos and generated files are written to a temporary folder on this device so they can be processed and previewed.</p>
      </section>
      <section>
        <h3>House advertisement</h3>
        <p>The app includes a static project notice seeking a direct sponsor. It is bundled with the app and uses no remote creative, cookie, identifier, impression pixel, or click tracking. Opening its contact link takes you to GitHub, which applies its own terms and privacy policy.</p>
      </section>
      <section>
        <h3>Deletion and downloads</h3>
        <p>You can clear temporary files at any time. The app also removes them after a normal shutdown. A forced shutdown or system crash may leave temporary files until you or the operating system removes them. Files you download remain wherever you save them.</p>
      </section>
      <section>
        <h3>Source platforms</h3>
        <p>When you submit a TikTok or Instagram link, this device connects to that platform and its delivery providers. They receive technical request data such as your IP address and apply their own privacy terms. Video Enhancer does not send your link, video, or activity to an operator-run cloud service.</p>
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
        <div><p class="dialog-kicker">Last updated August 6, 2026</p><h2 id="terms-title">Terms of use</h2></div>
        <button class="icon-button" type="button" data-close-dialog="terms-dialog" aria-label="Close terms of use">&times;</button>
      </div>
      <section>
        <h3>About this tool</h3>
        <p>Video Enhancer is a local tool for supported public video links. It does not host, index, publish, recommend, or redistribute videos, and it provides no account or platform access.</p>
      </section>
      <section>
        <h3>Your responsibility</h3>
        <p>Use Video Enhancer only for public content you own or are legally permitted to download and use. Follow applicable law, copyright and privacy rights, and the source platform's terms. Do not use it to access private content, bypass a login or access control, infringe rights, or distribute unlawful content.</p>
      </section>
      <section>
        <h3>Third-party platforms</h3>
        <p>TikTok and Instagram are independent services. Video Enhancer is not affiliated with, sponsored by, or approved by them. Platform changes may interrupt support without notice.</p>
      </section>
      <section>
        <h3>Quality and availability</h3>
        <p>The tool is provided as available. It does not guarantee a particular resolution, frame rate, codec, availability, or that a platform will expose a downloadable source. Synthetic enhancement can introduce artifacts.</p>
      </section>
      <div class="dialog-actions"><button type="button" data-close-dialog="terms-dialog">Done</button></div>
    </div>
  </dialog>

  <script nonce="__CSP_NONCE__">
    const $ = (id) => document.getElementById(id);
    const sessionToken = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    const state = {
      poll: null,
      sourceId: null,
      outputFps: 30,
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
       const source = await postJSON("/api/sources/download", { url });
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

   function renderMedia(media) {
     const values = [
        ["Resolution", media.width && media.height ? `${media.width}x${media.height}` : "Unknown"],
        ["Frame rate", mediaValue(media.fps, " FPS")],
       ["Video", mediaValue(media.video_codec)],
        ["Audio", mediaValue(media.audio_codec)],
        ["Bitrate", media.bitrate ? `${Math.round(media.bitrate / 1000)} kbps` : "Unknown"],
        ["Size", media.size ? `${(media.size / 1024 / 1024).toFixed(1)} MB` : "Unknown"],
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
       const response = await apiFetch(`/api/sources/${id}`);
       const source = await response.json();
        if (!response.ok) throw new Error(source.error || "Source job not found.");
       setLog(source.logs);
       if (source.status === "done") {
         clearInterval(state.poll);
         const label = source.operation === "remuxed" ? "Remuxed without video re-encoding" : "Original platform stream";
         $("source-quality").textContent = label;
         $("source-result-name").textContent = source.original_name;
         $("source-download").href = localFileUrl(source.original_url, true);
         $("source-result").hidden = false;
         sourceFrames.setFps(source.media.fps);
         $("source-video").src = localFileUrl(source.original_url);
         $("source-video").load();
          $("source-empty").hidden = true;
         $("input-meta").textContent = `${mediaValue(source.media.width)}x${mediaValue(source.media.height)} · ${mediaValue(source.media.fps, " FPS")}`;
         renderMedia(source.media);
         $("download-original").disabled = false;
         setDerivedDisabled(false);
          $("workspace-status").textContent = "Source ready. Choose an enhancement or download the original.";
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
      $("output-meta").textContent = "Starting";
      $("output-empty").hidden = false;
      $("output-empty").textContent = "Creating the enhanced copy on this device...";
      $("output-video").removeAttribute("src");
      $("output-video").load();
     try {
        const job = await postJSON(`/api/sources/${state.sourceId}/enhance`, { mode });
        watchJob(job.id).catch(showPollingError);
      } catch (error) {
        setDerivedDisabled(false);
        setLog([error.message]);
      }
    }

    $("download-60").addEventListener("click", () => startSourceEnhancement("60"));
   $("download-90").addEventListener("click", () => startSourceEnhancement("90"));
   $("download-upscale").addEventListener("click", () => startSourceEnhancement("upscale"));

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
     $("source-error").textContent = "";
      $("input-meta").textContent = "Not loaded";
      $("output-meta").textContent = "Not started";
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


@dataclass
class SourceJob:
    id: str
    url: str
    directory: Path
    status: str = "queued"
    original_path: Path | None = None
    media: dict[str, Any] = field(default_factory=dict)
    format_id: str = ""
    operation: str = ""
    error: str = ""
    logs: list[str] = field(default_factory=list)


JOBS: dict[str, Job] = {}
SOURCES: dict[str, SourceJob] = {}
LOCK = threading.Lock()


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
        JOBS.clear()
        SOURCES.clear()

    if not work_dir.is_dir():
        return
    for path in work_dir.iterdir():
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)


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
        completed = subprocess.run(
            job.command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=ENHANCEMENT_TIMEOUT_SECONDS,
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
    with LOCK:
        if any(job.status in {"queued", "running"} for job in JOBS.values()):
            raise ValueError("Wait for the active export to finish.")
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
        job = Job(job_id, input_path, output_path, command)
        job.logs.append(f"Loaded {original}.")
        JOBS[job_id] = job
    try:
        threading.Thread(target=run_job, args=(job,), daemon=True).start()
    except Exception:
        with LOCK:
            JOBS.pop(job_id, None)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return job


def run_source_download(job: SourceJob) -> None:
    with LOCK:
        job.status = "downloading"
        job.logs.append("Original source download started.")
    try:
        result = download_source(job.url, job.directory)
    except (OSError, SourceError) as exc:
        shutil.rmtree(job.directory, ignore_errors=True)
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
        url = str(body.get("url", "")).strip()
        validate_social_url(url)
        source_id = uuid.uuid4().hex[:12]
        directory = self.work_dir / f"source-{source_id}"
        source = SourceJob(source_id, url, directory)
        with LOCK:
            SOURCES[source_id] = source
        try:
            threading.Thread(
                target=run_source_download,
                args=(source,),
                daemon=True,
            ).start()
        except Exception:
            with LOCK:
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

    def serve_source_file(self, request_path: str, *, attachment: bool = False) -> None:
        parts = request_path.strip("/").split("/")
        if len(parts) < 3 or parts[:2] != ["files", "sources"]:
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        with LOCK:
            source = SOURCES.get(parts[2])
            if len(parts) == 4 and parts[3] == "original":
                file = source.original_path if source else None
                content_type = (
                    "video/mp4"
                    if file and file.suffix.lower() in {".mp4", ".m4v"}
                    else "application/octet-stream"
                )
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


def _serve(host: str, port: int, work_dir: Path, *, open_browser: bool = False) -> None:
    Handler.work_dir = work_dir
    Handler.session_token = secrets.token_hex(32)
    work_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    url = f"http://{host}:{server.server_port}/#token={Handler.session_token}"
    print(f"Video Enhancer Web running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
        clear_session(work_dir, force=True)


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
