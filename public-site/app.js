import { processLocally, terminateLocalProcessor } from "./local-processor.js";

const TERMS_VERSION = "2026-08-10.2";
const $ = (id) => document.getElementById(id);
const state = {
  resolved: null,
  primary: null,
  sourceBlob: null,
  enhancedURL: null,
  zoom: 1,
  oneFpsTimer: null,
  gen: 0,
};

function setStatus(message, isError = false) {
  $("form-status").textContent = message;
  $("form-status").style.color = isError ? "var(--danger)" : "var(--muted)";
}

function safeName(value, fallback = "media") {
  const cleaned = String(value || fallback).replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "");
  return (cleaned || fallback).slice(0, 80);
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "Source controlled";
  const units = ["B", "KB", "MB", "GB"];
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** unit).toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function resetMedia() {
  state.gen += 1;
  clearInterval(state.oneFpsTimer);
  state.oneFpsTimer = null;
  $("one-fps").setAttribute("aria-pressed", "false");
  state.sourceBlob = null;
  state.primary = null;
  state.resolved = null;
  if (state.enhancedURL) URL.revokeObjectURL(state.enhancedURL);
  state.enhancedURL = null;
  $("source-video").pause();
  $("source-video").removeAttribute("src");
  $("source-image").removeAttribute("src");
  $("enhanced-video").pause();
  $("enhanced-video").removeAttribute("src");
  $("result").hidden = true;
  $("empty-state").hidden = false;
  $("enhanced-result").hidden = true;
  $("enhance-progress").value = 0;
  $("enhance-percent").value = "0%";
  $("enhance-status").textContent = "Ready to enhance. No processing has started.";
  $("processing-accepted").checked = false;
  $("download-actions").replaceChildren();
  $("carousel").replaceChildren();
  setZoom(1);
}

async function postJSON(path, payload) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(path, {
      method: "POST",
      credentials: "omit",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `The resolver returned HTTP ${response.status}.`);
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The source platform took too long to respond. Try again.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function addMeta(term, value) {
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = term;
  dd.textContent = value;
  $("result-meta").append(dt, dd);
}

function safeUrl(value) {
  try {
    const url = new URL(value, location.origin);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function downloadButton(media, label, primary = false) {
  const link = document.createElement("a");
  link.className = `button${primary ? " button-primary" : ""}`;
  const href = safeUrl(media.downloadUrl);
  if (href) {
    link.href = href;
    link.download = media.filename || "media";
  } else {
    link.setAttribute("aria-disabled", "true");
  }
  link.textContent = label;
  return link;
}

function setPreviewSource(element, media) {
  const preview = safeUrl(media.previewUrl);
  const direct = safeUrl(media.directUrl) || preview;
  element.onerror = direct === preview ? null : () => {
    element.onerror = null;
    element.src = preview;
  };
  element.src = direct;
}

function renderCarousel(images) {
  const container = $("carousel");
  container.replaceChildren();
  container.hidden = images.length < 2;
  images.forEach((media, index) => {
    const figure = document.createElement("figure");
    figure.className = "carousel-item";
    const image = document.createElement("img");
    image.loading = "lazy";
    setPreviewSource(image, media);
    image.alt = `Source image ${index + 1}`;
    const link = downloadButton(media, `Download image ${index + 1}`);
    figure.append(image, link);
    container.append(figure);
  });
}

function renderResult(data) {
  const media = Array.isArray(data.media) ? data.media : [];
  const videos = media.filter((item) => item.kind === "video");
  const images = media.filter((item) => item.kind === "image");
  const audio = media.filter((item) => item.kind === "audio");
  const primary = videos[0] || images[0];
  if (!primary) throw new Error("The source page did not expose a supported original media file.");

  resetMedia();
  state.resolved = data;
  state.primary = primary;
  $("empty-state").hidden = true;
  $("result").hidden = false;
  $("platform-name").textContent = `${data.platform || "source"} ${primary.kind}`;
  $("result-title").textContent = data.title || `${data.platform || "Source"} media`;
  $("result-author").textContent = data.author ? `@${String(data.author).replace(/^@/, "")}` : "Public source";
  $("result-meta").replaceChildren();
  addMeta("Type", primary.kind === "video" ? "Original video" : "Original image");
  addMeta("Resolution", primary.width && primary.height ? `${primary.width} × ${primary.height}` : "Best exposed source");
  if (primary.fps) addMeta("Frame rate", `${primary.fps} FPS`);
  addMeta("Format", primary.extension ? primary.extension.toUpperCase() : "Source format");
  addMeta("File size", formatBytes(primary.bytes));

  const video = $("source-video");
  const image = $("source-image");
  const isVideo = primary.kind === "video";
  video.hidden = !isVideo;
  image.hidden = isVideo;
  $("viewer-controls").hidden = false;
  $("frame-back").disabled = !isVideo;
  $("frame-forward").disabled = !isVideo;
  $("one-fps").disabled = !isVideo;
  $("step-fps").disabled = !isVideo;
  if (isVideo) {
    setPreviewSource(video, primary);
    video.load();
    $("step-fps").value = String(primary.fps || 30);
  } else {
    setPreviewSource(image, primary);
  }

  const actions = $("download-actions");
  actions.replaceChildren(downloadButton(primary, `Download original (${(primary.extension || primary.kind).toUpperCase()})`, true));
  audio.forEach((item) => actions.append(downloadButton(item, "Download original audio")));
  for (const item of [...videos.slice(1), ...images.slice(primary.kind === "image" ? 1 : 0)]) {
    actions.append(downloadButton(item, `Download ${item.kind}`));
  }

  renderCarousel(images);
  $("enhance-section").hidden = !isVideo;
  if (data.note) setStatus(data.note);
  else setStatus("Original media ready. Nothing has been saved to Downloads yet.");
}

$("source-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!$("source-form").reportValidity()) return;
  if (!$("terms-accepted").checked) {
    setStatus("Accept the current Terms of Use before resolving media.", true);
    return;
  }

  const button = $("get-media");
  button.disabled = true;
  setStatus("Resolving the public source…");
  try {
    const data = await postJSON("/api/resolve", {
      url: $("source-url").value.trim(),
      termsAccepted: true,
      termsVersion: TERMS_VERSION,
    });
    renderResult(data);
  } catch (error) {
    resetMedia();
    setStatus(error.message || "The media could not be resolved.", true);
  } finally {
    button.disabled = false;
  }
});

function setZoom(value) {
  state.zoom = Math.max(1, Math.min(8, Number(value) || 1));
  $("zoom-range").value = String(state.zoom);
  $("zoom-output").value = `${state.zoom}×`;
  $("media-stage").style.setProperty("--zoom", state.zoom);
}

$("zoom-out").addEventListener("click", () => setZoom(state.zoom - 0.5));
$("zoom-in").addEventListener("click", () => setZoom(state.zoom + 0.5));
$("zoom-reset").addEventListener("click", () => setZoom(1));
$("zoom-range").addEventListener("input", (event) => setZoom(event.currentTarget.value));

function stepFrame(direction) {
  const video = $("source-video");
  if (video.hidden) return;
  video.pause();
  const fps = Math.max(1, Math.min(240, Number($("step-fps").value) || 30));
  video.currentTime = Math.max(0, Math.min(video.duration || Infinity, video.currentTime + direction / fps));
}

$("frame-back").addEventListener("click", () => stepFrame(-1));
$("frame-forward").addEventListener("click", () => stepFrame(1));
$("one-fps").addEventListener("click", () => {
  if (state.oneFpsTimer) {
    clearInterval(state.oneFpsTimer);
    state.oneFpsTimer = null;
    $("one-fps").setAttribute("aria-pressed", "false");
    return;
  }
  $("source-video").pause();
  state.oneFpsTimer = setInterval(() => stepFrame(1), 1000);
  $("one-fps").setAttribute("aria-pressed", "true");
});

async function fetchSourceBlob(gen) {
  if (state.sourceBlob) return state.sourceBlob;
  for (const url of new Set([state.primary.directUrl, state.primary.previewUrl].filter(Boolean))) {
    try {
      const response = await fetch(url, { credentials: "omit" });
      if (!response.ok) continue;
      const declared = Number(response.headers.get("content-length")) || 0;
      if (declared > 500 * 1024 * 1024) throw new Error("This file is too large for safe in-browser processing. Download the original or use the desktop app.");
      const blob = await response.blob();
      if (blob.size > 500 * 1024 * 1024) throw new Error("This file is too large for safe in-browser processing. Download the original or use the desktop app.");
      if (gen === state.gen) state.sourceBlob = blob;
      return blob;
    } catch (error) {
      if (/too large/i.test(error.message || "")) throw error;
    }
  }
  throw new Error("The source media could not be loaded for local processing.");
}

async function runEnhancement(mode, button) {
  if (!$("processing-accepted").checked) {
    $("enhance-status").textContent = "Confirm local device processing before starting.";
    $("processing-accepted").focus();
    return;
  }

  const controls = [...document.querySelectorAll("[data-mode]")];
  controls.forEach((control) => { control.disabled = true; });
  const originalLabel = button.textContent;
  button.textContent = "Working…";
  const filter = document.querySelector('input[name="filter"]:checked')?.value || "none";
  $("enhance-progress").value = 0;
  const gen = state.gen;

  try {
    const source = await fetchSourceBlob(gen);
    const result = await processLocally(source, {
      mode,
      filter,
      onProgress: (ratio) => {
        const progress = Math.max(0, Math.min(1, ratio || 0));
        $("enhance-progress").value = progress;
        $("enhance-percent").value = `${Math.round(progress * 100)}%`;
      },
      onStatus: (message) => { $("enhance-status").textContent = message; },
    });
    if (gen !== state.gen || !state.primary) return;

    if (state.enhancedURL) URL.revokeObjectURL(state.enhancedURL);
    state.enhancedURL = URL.createObjectURL(result.blob);
    const title = safeName(state.resolved?.title, "media");
    const suffix = mode === "audio" ? "audio" : mode === "upscale" ? "2x" : `${mode}fps`;
    const download = $("enhanced-download");
    download.href = state.enhancedURL;
    download.download = `${title}-${suffix}.${result.extension}`;
    download.textContent = mode === "audio" ? "Download extracted MP3" : "Download enhanced video";
    const outputVideo = $("enhanced-video");
    if (mode === "audio") {
      outputVideo.pause();
      outputVideo.removeAttribute("src");
    } else {
      outputVideo.src = state.enhancedURL;
    }
    outputVideo.hidden = mode === "audio";
    $("enhanced-result").hidden = false;
    $("enhance-status").textContent = "Local file ready. It is not saved until you choose Download.";
  } catch (error) {
    $("enhance-status").textContent = error.message || "Local processing failed.";
  } finally {
    button.textContent = originalLabel;
    controls.forEach((control) => { control.disabled = false; });
  }
}

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => runEnhancement(button.dataset.mode, button));
});

document.querySelectorAll("[data-dialog]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    $(button.dataset.dialog).showModal();
  });
});

window.addEventListener("beforeunload", () => {
  terminateLocalProcessor();
  if (state.enhancedURL) URL.revokeObjectURL(state.enhancedURL);
});

resetMedia();
