import { FFmpeg } from "./vendor/ffmpeg/index.js";

const CORE_BASE = "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm";
const CORE_FILES = {
  js: {
    url: `${CORE_BASE}/ffmpeg-core.js`,
    type: "text/javascript",
    maxBytes: 500_000,
    sha256: "67a48f11645f85439f3fde4f2119042c16b374b910206b7a7a24f342e28dcae3",
  },
  wasm: {
    url: `${CORE_BASE}/ffmpeg-core.wasm`,
    type: "application/wasm",
    maxBytes: 40_000_000,
    sha256: "9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7",
  },
};

const MAX_INPUT_BYTES = 500 * 1024 * 1024;
const JOB_TIMEOUT_MS = 6 * 60 * 60 * 1000;

let engine;
let enginePromise;
let running = false;

function hex(bytes) {
  return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function downloadCoreFile(file, onLoadProgress) {
  const response = await fetch(file.url, { cache: "force-cache", credentials: "omit" });
  if (!response.ok || !response.body) throw new Error("The local processing engine could not be downloaded.");

  const declared = Number(response.headers.get("content-length")) || 0;
  if (declared > file.maxBytes) throw new Error("The local processing engine exceeded its safety limit.");

  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    if (received > file.maxBytes) {
      await reader.cancel();
      throw new Error("The local processing engine exceeded its safety limit.");
    }
    chunks.push(value);
    onLoadProgress?.(declared ? received / declared : 0);
  }

  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }

  const digest = hex(await crypto.subtle.digest("SHA-256", bytes));
  if (digest !== file.sha256) throw new Error("The local processing engine failed its integrity check.");
  return URL.createObjectURL(new Blob([bytes], { type: file.type }));
}

export async function loadLocalProcessor({ onProgress, onStatus } = {}) {
  if (engine?.loaded) return engine;
  if (enginePromise) return enginePromise;

  enginePromise = (async () => {
    onStatus?.("Downloading the local processing engine (about 31 MB)…");
    const coreURL = await downloadCoreFile(CORE_FILES.js, (ratio) => onProgress?.(ratio * 0.02));
    const wasmURL = await downloadCoreFile(CORE_FILES.wasm, (ratio) => onProgress?.(0.02 + ratio * 0.08));
    try {
      engine = new FFmpeg();
      await engine.load({ coreURL, wasmURL });
      onProgress?.(0.1);
      return engine;
    } finally {
      URL.revokeObjectURL(coreURL);
      URL.revokeObjectURL(wasmURL);
    }
  })().catch((error) => {
    enginePromise = undefined;
    engine?.terminate();
    engine = undefined;
    throw error;
  });

  return enginePromise;
}

function selectedFilters(mode, filter) {
  const filters = [];
  if (mode === "90") filters.push("nlmeans=s=1.0:p=7:r=15");
  if (filter === "clean") filters.push("hqdn3d=1.5:1.5:6:6");

  if (mode === "60") {
    filters.push("minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1");
  } else if (mode === "90") {
    filters.push("minterpolate=fps=90:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=umh:mb_size=8:search_param=48:vsbmc=1:scd=fdiff:scd_threshold=10");
  }

  filters.push(mode === "upscale"
    ? "scale=trunc(iw*2/2)*2:trunc(ih*2/2)*2:flags=lanczos"
    : "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos");

  if (mode === "90" || filter === "sharpen") filters.push("unsharp=5:5:0.65:5:5:0.0");
  return filters.join(",");
}

export function buildLocalCommand(mode, filter = "none") {
  if (mode === "audio") {
    return ["-i", "input.media", "-vn", "-c:a", "libmp3lame", "-q:a", "2", "output.mp3"];
  }
  if (!new Set(["60", "90", "upscale"]).has(mode)) throw new Error("Unknown local processing mode.");
  if (!new Set(["none", "clean", "sharpen"]).has(filter)) throw new Error("Unknown local filter.");

  return [
    "-i", "input.media",
    "-vf", selectedFilters(mode, filter),
    "-c:v", "libx264",
    "-preset", mode === "90" ? "slow" : "medium",
    "-crf", mode === "90" ? "16" : "18",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-movflags", "+faststart",
    "output.mp4",
  ];
}

export async function processLocally(source, { mode, filter = "none", onProgress, onStatus } = {}) {
  if (!(source instanceof Blob) || !source.size) throw new Error("No source media is available for local processing.");
  if (source.size > MAX_INPUT_BYTES) throw new Error("This file is too large for safe in-browser processing. Download the original or use the desktop app.");
  if (running) throw new Error("A local processing job is already running.");

  running = true;
  const ffmpeg = await loadLocalProcessor({ onProgress, onStatus });
  const outputName = mode === "audio" ? "output.mp3" : "output.mp4";
  const progressHandler = ({ progress }) => onProgress?.(0.1 + Math.max(0, Math.min(1, progress)) * 0.9);
  ffmpeg.on("progress", progressHandler);

  try {
    onStatus?.("Copying the source into temporary browser memory…");
    await ffmpeg.writeFile("input.media", new Uint8Array(await source.arrayBuffer()));
    onStatus?.(mode === "audio" ? "Extracting MP3 on this device…" : "Enhancing video on this device…");
    const exitCode = await ffmpeg.exec(buildLocalCommand(mode, filter), JOB_TIMEOUT_MS);
    if (exitCode !== 0) throw new Error(`Local FFmpeg stopped with exit code ${exitCode}.`);
    const output = await ffmpeg.readFile(outputName);
    const type = mode === "audio" ? "audio/mpeg" : "video/mp4";
    onProgress?.(1);
    return { blob: new Blob([output.buffer], { type }), extension: mode === "audio" ? "mp3" : "mp4" };
  } finally {
    ffmpeg.off("progress", progressHandler);
    await ffmpeg.deleteFile("input.media").catch(() => {});
    await ffmpeg.deleteFile(outputName).catch(() => {});
    running = false;
  }
}

export function terminateLocalProcessor() {
  engine?.terminate();
  engine = undefined;
  enginePromise = undefined;
  running = false;
}
