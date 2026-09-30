const $ = (id) => document.getElementById(id);
const sessionToken =
  new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
const TERMS_VERSION = "2026-08-10";
const state = {
  poll: null,
  sourceId: null,
  outputFps: 30,
  pendingLocalAction: null,
  localJobActive: false,
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
    zoom,
    zoomOut,
    zoomIn,
    zoomReset,
    previous,
    oneFps,
    next,
    fpsInput,
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
    controls.forEach((control) => {
      control.disabled = !enabled;
    });
    fullscreen.disabled =
      !enabled || typeof shell.requestFullscreen !== "function";
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
    const pointX = Number.isFinite(clientX)
      ? clientX - rect.left
      : rect.width / 2;
    const pointY = Number.isFinite(clientY)
      ? clientY - rect.top
      : rect.height / 2;
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
  stage.addEventListener(
    "wheel",
    (event) => {
      if (zoom.disabled) return;
      event.preventDefault();
      zoomAt(
        scale * Math.exp(-event.deltaY * 0.002),
        event.clientX,
        event.clientY,
      );
    },
    { passive: false },
  );
  stage.addEventListener("dblclick", (event) => {
    if (zoom.disabled) return;
    event.preventDefault();
    if (scale >= 7.9) resetZoom();
    else zoomAt(Math.min(8, scale * 2), event.clientX, event.clientY);
  });
  stage.addEventListener("pointerdown", (event) => {
    if (zoom.disabled) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (scale > 1 || pointers.size > 1)
      stage.setPointerCapture(event.pointerId);
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
          (scale * current.distance) / Math.max(1, lastPinch.distance),
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
    if (stage.hasPointerCapture(event.pointerId))
      stage.releasePointerCapture(event.pointerId);
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
  $("log").textContent = entries.join("\n");
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
  status.querySelector(".status-short").textContent = ready
    ? "Local"
    : "Unavailable";
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
  ["download-60", "download-90", "download-upscale", "create-export"].forEach(
    (id) => {
      $(id).disabled = disabled;
    },
  );
}

function setLocalJobActive(active) {
  state.localJobActive = active;
  $("download-original").disabled = active;
}

function showSourceLoading() {
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
  $("output-image").hidden = true;
  $("output-image").removeAttribute("src");
  $("output-advanced").hidden = false;
  $("preview-grid").dataset.single = "false";
  $("source-empty").hidden = false;
  $("source-empty").textContent = "Fetching the best available source...";
  $("output-empty").hidden = false;
  $("output-empty").textContent =
    "Choose an enhancement after the source is ready.";
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
}

$("source-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.localJobActive) return;
  if (!$("source-form").reportValidity()) return;
  const url = $("source-url").value.trim();
  $("download-original").disabled = true;
  $("source-error").textContent = "";
  try {
    const source = await postJSON("/api/sources/download", {
      url,
      quality: $("source-quality-select").value,
      terms_accepted: true,
      terms_version: TERMS_VERSION,
    });
    state.sourceId = source.id;
    showSourceLoading();
    watchSource(source.id).catch(showPollingError);
  } catch (error) {
    $("source-error").textContent = error.message;
    $("download-original").disabled = false;
    setLog([error.message]);
  }
});

function mediaValue(value, suffix = "") {
  return value === null || value === undefined
    ? "Unknown"
    : `${value}${suffix}`;
}

function renderMedia(source) {
  const media = source.media;
  const size = media.size
    ? `${(media.size / 1024 / 1024).toFixed(1)} MB`
    : "Unknown";
  const values =
    source.media_type !== "video"
      ? [
          [
            "Type",
            source.media_type === "archive"
              ? "Media archive"
              : source.item_count > 1
                ? "Image archive"
                : "Image",
          ],
          ["Items", String(source.item_count)],
          ["Size", size],
        ]
      : [
          [
            "Resolution",
            media.width && media.height
              ? `${media.width}x${media.height}`
              : "Unknown",
          ],
          ["Frame rate", mediaValue(media.fps, " FPS")],
          ["Video", mediaValue(media.video_codec)],
          ["Audio", mediaValue(media.audio_codec)],
          [
            "Bitrate",
            media.bitrate
              ? `${Math.round(media.bitrate / 1000)} kbps`
              : "Unknown",
          ],
          ["Size", size],
        ];
  $("source-media").dataset.kind = source.media_type;
  $("source-media").replaceChildren(
    ...values.map(([name, value]) => {
      const box = document.createElement("div");
      const term = document.createElement("dt");
      const detail = document.createElement("dd");
      term.textContent = name;
      detail.textContent = value;
      box.append(term, detail);
      return box;
    }),
  );
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
      const image = source.preview_type === "image";
      const archive = source.media_type === "archive";
      const video = source.media_type === "video";
      const label = archive
        ? `${source.item_count} original files`
        : image
          ? source.item_count > 1
            ? `${source.item_count} original images`
            : "Original platform image"
          : source.operation === "remuxed"
            ? "Remuxed without video re-encoding"
            : "Original platform stream";
      $("source-quality").textContent = label;
      $("source-result-name").textContent = source.original_name;
      $("source-download").href = localFileUrl(source.original_url, true);
      $("source-download-label").textContent = archive
        ? "Download all media (.zip)"
        : image
          ? source.item_count > 1
            ? "Download all images (.zip)"
            : "Download image"
          : "Download video";
      if (source.audio_url) {
        $("source-audio").href = localFileUrl(source.audio_url, true);
        $("source-audio").hidden = false;
      }
      $("source-result").hidden = false;
      $("preview-grid").dataset.single = String(!video);
      $("output-player").hidden = true;
      $("source-advanced").hidden = image;
      $("enhancement-actions").hidden = !video;
      $("source-video").hidden = image;
      $("source-image").hidden = !image;
      if (image) {
        sourceFrames.reset();
        $("source-image").src = localFileUrl(source.preview_url);
        $("input-meta").textContent =
          `${source.item_count} image${source.item_count === 1 ? "" : "s"}`;
      } else {
        sourceFrames.setFps(source.media.fps);
        $("source-video").src = localFileUrl(source.preview_url);
        $("source-video").load();
        $("input-meta").textContent = archive
          ? `${source.item_count} original files`
          : `${mediaValue(source.media.width)}x${mediaValue(source.media.height)} · ${mediaValue(source.media.fps, " FPS")}`;
      }
      $("source-empty").hidden = true;
      renderMedia(source);
      $("download-original").disabled = false;
      setDerivedDisabled(!video);
      $("workspace-status").textContent = archive
        ? "Media archive ready to download."
        : image
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
  $("output-meta").textContent = "Error";
  $("output-empty").hidden = false;
  $("output-empty").textContent = error.message;
  $("download-original").disabled = false;
}

async function startSourceEnhancement(mode) {
  if (!state.sourceId) return;
  state.outputFps = mode === "upscale" ? sourceFrames.fps() : Number(mode);
  setLocalJobActive(true);
  setDerivedDisabled(true);
  $("result").hidden = true;
  $("output-player").hidden = false;
  $("output-meta").textContent = "Starting";
  $("output-empty").hidden = false;
  $("output-empty").textContent =
    "Creating the enhanced copy on this device...";
  $("output-video").removeAttribute("src");
  $("output-video").load();
  $("output-video").hidden = false;
  $("output-image").removeAttribute("src");
  $("output-image").hidden = true;
  $("output-advanced").hidden = false;
  try {
    const job = await postJSON(`/api/sources/${state.sourceId}/enhance`, {
      mode,
      local_processing_accepted: true,
    });
    watchJob(job.id).catch((error) => {
      showPollingError(error);
      setLocalJobActive(false);
      setDerivedDisabled(false);
    });
  } catch (error) {
    setLocalJobActive(false);
    setDerivedDisabled(false);
    showPollingError(error);
  }
}

async function startSourceExport() {
  if (!state.sourceId) return;
  const format = $("export-format").value;
  const audio = ["mp3", "aac", "m4a", "wav", "aiff", "flac", "wma"].includes(
    format,
  );
  const preview = format === "gif" || ["mp4", "m4v", "mov"].includes(format);
  state.outputFps = format === "gif" ? 15 : sourceFrames.fps();
  setLocalJobActive(true);
  setDerivedDisabled(true);
  $("result").hidden = true;
  $("output-player").hidden = !preview;
  $("output-meta").textContent = "Starting";
  $("output-empty").hidden = false;
  $("output-empty").textContent =
    "Creating the converted or trimmed copy on this device...";
  $("output-video").removeAttribute("src");
  $("output-video").load();
  $("output-video").hidden = format === "gif";
  $("output-image").removeAttribute("src");
  $("output-image").hidden = true;
  $("output-advanced").hidden = format === "gif";
  try {
    const job = await postJSON(`/api/sources/${state.sourceId}/export`, {
      format,
      start: $("clip-start").value,
      end: $("clip-end").value,
      local_processing_accepted: true,
    });
    watchJob(job.id).catch((error) => {
      showPollingError(error);
      setLocalJobActive(false);
      setDerivedDisabled(false);
    });
  } catch (error) {
    setLocalJobActive(false);
    setDerivedDisabled(false);
    showPollingError(error);
  }
}

function requestLocalProcessing(action) {
  state.pendingLocalAction = action;
  $("local-processing-accepted").checked = false;
  $("local-processing-dialog").showModal();
}

$("local-processing-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const action = state.pendingLocalAction;
  state.pendingLocalAction = null;
  $("local-processing-dialog").close();
  if (action) action();
});

$("download-60").addEventListener("click", () =>
  requestLocalProcessing(() => startSourceEnhancement("60")),
);
$("download-90").addEventListener("click", () =>
  requestLocalProcessing(() => startSourceEnhancement("90")),
);
$("download-upscale").addEventListener("click", () =>
  requestLocalProcessing(() => startSourceEnhancement("upscale")),
);
$("create-export").addEventListener("click", () =>
  requestLocalProcessing(startSourceExport),
);

async function watchJob(id) {
  clearInterval(state.poll);
  const tick = async () => {
    const response = await apiFetch(`/api/jobs/${id}`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "Job not found");
    $("output-meta").textContent =
      job.status.charAt(0).toUpperCase() + job.status.slice(1);
    setLog(job.logs);
    if (job.status === "done") {
      clearInterval(state.poll);
      setLocalJobActive(false);
      setDerivedDisabled(false);
      const audio = job.kind === "audio-export";
      const extension = job.output_name.split(".").pop().toLowerCase();
      const gif = extension === "gif";
      const video = ["mp4", "m4v", "mov"].includes(extension);
      $("result").hidden = false;
      $("result-name").textContent = job.output_name;
      $("result-path").textContent =
        job.kind === "enhancement"
          ? "Enhanced synthetic copy"
          : audio
            ? "Local audio export"
            : "Local converted or trimmed copy";
      $("download").href = localFileUrl(job.output_url, true);
      $("output-player").hidden = !gif && !video;
      $("output-video").hidden = !video;
      $("output-image").hidden = !gif;
      $("output-advanced").hidden = !video;
      if (gif) {
        $("output-image").src = localFileUrl(job.output_url);
        $("output-empty").hidden = true;
      } else if (video) {
        outputFrames.setFps(state.outputFps);
        $("output-video").src = localFileUrl(job.output_url);
        $("output-video").load();
        $("output-empty").hidden = true;
      }
      $("workspace-status").textContent = audio
        ? "Audio file ready to download."
        : job.kind === "enhancement"
          ? "Enhanced file ready to download."
          : "Converted or trimmed file ready to download.";
    }
    if (job.status === "error") {
      clearInterval(state.poll);
      setLocalJobActive(false);
      setDerivedDisabled(false);
      $("output-empty").textContent =
        job.error || "The enhanced copy could not be created.";
      $("source-error").textContent =
        job.error || "The local file could not be created.";
    }
  };
  state.poll = setInterval(
    () =>
      tick().catch((error) => {
        showPollingError(error);
        setLocalJobActive(false);
        setDerivedDisabled(false);
      }),
    1000,
  );
  await tick();
}

function resetInterface() {
  clearInterval(state.poll);
  state.poll = null;
  state.sourceId = null;
  state.pendingLocalAction = null;
  setLocalJobActive(false);
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
  $("clip-start").value = "";
  $("clip-end").value = "";
  $("source-advanced").hidden = false;
  $("enhancement-actions").hidden = false;
  $("output-player").hidden = true;
  $("output-image").hidden = true;
  $("output-image").removeAttribute("src");
  $("output-advanced").hidden = false;
  $("preview-grid").dataset.single = "false";
  $("output-empty").hidden = false;
  $("output-empty").textContent =
    "Choose an enhancement after the source is ready.";
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
    style.display === "none" ||
    style.visibility === "hidden" ||
    bait.offsetWidth === 0 ||
    bait.offsetHeight === 0
  ) {
    $("adblock-dialog").showModal();
  }
});

loadConfig().catch((error) => {
  setEngineStatus(false, "Local session unavailable");
  $("source-error").textContent = error.message;
  setLog([error.message]);
});
