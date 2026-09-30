import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { runInNewContext } from "node:vm";

import {
  anonymousRateKey,
  checkRateLimit,
  parseFacebook,
  parseInstagram,
  parseMetaTags,
  parseTikTok,
  proxyMedia,
  readJSONBody,
  validateMediaUrl,
  validateSourceUrl,
} from "../functions/_shared.js";
import { onRequestPost as resolveRequest } from "../functions/api/resolve.js";
import { buildLocalCommand } from "../public-site/local-processor.js";
import worker from "../site-worker.js";

test("source URL validation is HTTPS-only and platform allowlisted", () => {
  assert.equal(
    validateSourceUrl("https://www.tiktok.com/@a/video/1").platform,
    "tiktok",
  );
  assert.equal(
    validateSourceUrl("https://www.instagram.com/p/abc/").platform,
    "instagram",
  );
  assert.equal(validateSourceUrl("https://fb.watch/abc").platform, "facebook");
  assert.equal(
    validateSourceUrl("https://vsco.co/user/media/abc").platform,
    "vsco",
  );

  for (const value of [
    "http://www.tiktok.com/@a/video/1",
    "https://tiktok.com.evil.test/video/1",
    "https://user:pass@tiktok.com/video/1",
    "https://instagram.com:444/p/a",
    "https://127.0.0.1/video/1",
    "https://example.com/video/1",
  ])
    assert.throws(() => validateSourceUrl(value));
});

test("media URL validation blocks arbitrary proxy targets", () => {
  assert.equal(
    validateMediaUrl("https://v16.tiktokcdn.com/video.mp4", "tiktok").hostname,
    "v16.tiktokcdn.com",
  );
  assert.equal(
    validateMediaUrl("https://scontent.cdninstagram.com/photo.jpg", "instagram")
      .hostname,
    "scontent.cdninstagram.com",
  );
  assert.throws(() => validateMediaUrl("https://im.vsco.co/photo.jpg", "vsco"));
  assert.throws(() =>
    validateMediaUrl("https://169.254.169.254/latest/meta-data", "tiktok"),
  );
  assert.throws(() =>
    validateMediaUrl("https://tiktokcdn.com.attacker.test/video.mp4", "tiktok"),
  );
  assert.throws(() =>
    validateMediaUrl("https://example.com/video.mp4", "facebook"),
  );
});

test("best-effort in-isolate rate limiting closes after the configured count", () => {
  const key = `test-${crypto.randomUUID()}`;
  assert.equal(checkRateLimit(key, 1_000, 2), true);
  assert.equal(checkRateLimit(key, 1_001, 2), true);
  assert.equal(checkRateLimit(key, 1_002, 2), false);
  assert.equal(checkRateLimit(key, 62_000, 2), true);
});

test("rate-limit keys do not retain the raw client address", async () => {
  const request = new Request("https://site.example/api/resolve", {
    headers: { "cf-connecting-ip": "192.0.2.42" },
  });
  const first = await anonymousRateKey(request, "resolve");
  assert.equal(first, await anonymousRateKey(request, "resolve"));
  assert.doesNotMatch(first, /192\.0\.2\.42/);
});

test("meta parser handles attribute order and entities", () => {
  const meta = parseMetaTags(
    '<meta content="A &amp; B" property="og:title"><meta name="twitter:image" content="https://cdninstagram.com/x.jpg">',
  );
  assert.equal(meta["og:title"], "A & B");
  assert.equal(meta["twitter:image"], "https://cdninstagram.com/x.jpg");
});

test("TikTok parser chooses the highest exposed bitrate and includes photo audio", () => {
  const state = {
    scope: {
      "webapp.video-detail": {
        itemInfo: {
          itemStruct: {
            id: "123",
            desc: "Example",
            author: { uniqueId: "creator" },
            video: {
              width: 1080,
              height: 1920,
              bitRate: [
                {
                  bitRate: 100,
                  playAddr: { urlList: ["https://v16.tiktokcdn.com/low.mp4"] },
                },
                {
                  bitRate: 500,
                  playAddr: { urlList: ["https://v16.tiktokcdn.com/high.mp4"] },
                },
              ],
            },
            imagePost: {
              images: [
                {
                  imageURL: { urlList: ["https://p16.tiktokcdn.com/one.jpg"] },
                },
              ],
            },
            music: {
              title: "Sound",
              playUrl: "https://sf16.tiktokcdn.com/sound.mp3",
            },
          },
        },
      },
    },
  };
  const result = parseTikTok(
    `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">${JSON.stringify(state)}</script>`,
    "https://www.tiktok.com/@creator/video/123",
  );
  assert.equal(result.author, "creator");
  assert.equal(result.media.length, 3);
  assert.match(result.media[0].previewUrl, /high\.mp4/);
  assert.deepEqual(
    result.media.map((item) => item.kind),
    ["video", "image", "audio"],
  );
});

test("Instagram embed parser preserves carousel images and video", () => {
  const graph = {
    owner: { username: "creator" },
    edge_media_to_caption: { edges: [{ node: { text: "A carousel" } }] },
    edge_sidecar_to_children: {
      edges: [
        {
          node: {
            is_video: false,
            display_url: "https://scontent.cdninstagram.com/a.jpg",
            dimensions: { width: 1000, height: 1000 },
          },
        },
        {
          node: {
            is_video: true,
            video_url: "https://video.fbcdn.net/b.mp4",
            dimensions: { width: 1080, height: 1920 },
          },
        },
      ],
    },
  };
  const inner = JSON.stringify({ gql_data: { shortcode_media: graph } });
  const html = `<script>{"contextJSON":${JSON.stringify(inner)}}</script>`;
  const result = parseInstagram(html, "https://www.instagram.com/p/abc/");
  assert.equal(result.title, "A carousel");
  assert.deepEqual(
    result.media.map((item) => item.kind),
    ["image", "video"],
  );
  assert.equal(
    result.media[0].directUrl,
    "https://scontent.cdninstagram.com/a.jpg",
  );
});

test("Facebook parser prefers an HD source URL", () => {
  const html =
    '<meta property="og:title" content="Public clip"><script>{"browser_native_sd_url":"https:\\/\\/video.fbcdn.net/sd.mp4","browser_native_hd_url":"https:\\/\\/video.fbcdn.net/hd.mp4"}</script>';
  const result = parseFacebook(html, "https://www.facebook.com/reel/1");
  assert.equal(result.title, "Public clip");
  assert.match(result.media[0].previewUrl, /hd\.mp4/);
});

test("resolver endpoint requires current active Terms acceptance", async () => {
  const request = new Request("https://site.example/api/resolve", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "https://site.example",
      "cf-connecting-ip": "192.0.2.20",
    },
    body: JSON.stringify({ url: "https://www.tiktok.com/@a/video/1" }),
  });
  const response = await resolveRequest({ request });
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /Terms of Use/);
});

test("resolver pauses VSCO without making an upstream request", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response("unexpected");
  };
  try {
    const request = new Request("https://site.example/api/resolve", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "https://site.example",
        "cf-connecting-ip": "192.0.2.21",
      },
      body: JSON.stringify({
        url: "https://vsco.co/user/media/abc",
        termsAccepted: true,
        termsVersion: "2026-08-10.2",
      }),
    });
    const response = await resolveRequest({ request });
    assert.equal(response.status, 400);
    assert.match(
      (await response.json()).error,
      /automated resolution is paused/,
    );
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("range proxy forwards the byte range and emits a safe attachment", async () => {
  const originalFetch = globalThis.fetch;
  let upstreamRange;
  globalThis.fetch = async (_url, init) => {
    upstreamRange = init.headers.range;
    return new Response(new Uint8Array([2, 3, 4, 5]), {
      status: 206,
      headers: {
        "content-type": "video/mp4",
        "content-length": "4",
        "content-range": "bytes 2-5/10",
      },
    });
  };
  try {
    const params = new URLSearchParams({
      platform: "tiktok",
      kind: "video",
      url: "https://v16.tiktokcdn.com/source.mp4",
      name: "safe.mp4",
      download: "1",
    });
    const response = await proxyMedia(
      new Request(`https://site.example/api/media?${params}`, {
        headers: { range: "bytes=2-5" },
      }),
    );
    assert.equal(response.status, 206);
    assert.equal(upstreamRange, "bytes=2-5");
    assert.equal(response.headers.get("content-range"), "bytes 2-5/10");
    assert.equal(
      response.headers.get("content-disposition"),
      'attachment; filename="safe.mp4"',
    );
    assert.deepEqual(
      [...new Uint8Array(await response.arrayBuffer())],
      [2, 3, 4, 5],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("range proxy restores a missing Content-Range for open-ended requests", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(new Uint8Array([7, 8, 9]), {
      status: 206,
      headers: { "content-type": "video/mp4", "content-length": "3" },
    });
  try {
    const params = new URLSearchParams({
      platform: "instagram",
      kind: "video",
      url: "https://scontent.cdninstagram.com/source.mp4",
    });
    const response = await proxyMedia(
      new Request(`https://site.example/api/media?${params}`, {
        headers: { range: "bytes=10-" },
      }),
    );
    assert.equal(response.headers.get("content-range"), "bytes 10-12/*");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("TikTok proxy retries a signed video inside a fresh anonymous session", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const state = {
    scope: {
      "webapp.video-detail": {
        itemInfo: {
          itemStruct: {
            id: "123",
            desc: "Example",
            author: { uniqueId: "creator" },
            video: { playAddr: "https://v16.tiktokcdn.com/fresh.mp4" },
          },
        },
      },
    },
  };
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), cookie: init?.headers?.cookie || "" });
    if (calls.length === 1) return new Response("blocked", { status: 403 });
    if (calls.length === 2)
      return new Response(
        `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">${JSON.stringify(state)}</script>`,
        {
          headers: {
            "content-type": "text/html",
            "set-cookie": "tt_chain_token=anonymous; Path=/; Secure",
          },
        },
      );
    assert.equal(init.headers.cookie, "tt_chain_token=anonymous");
    return new Response(new Uint8Array([1]), {
      status: 206,
      headers: {
        "content-type": "video/mp4",
        "content-length": "1",
        "content-range": "bytes 0-0/1",
      },
    });
  };
  try {
    const params = new URLSearchParams({
      platform: "tiktok",
      kind: "video",
      url: "https://v16.tiktokcdn.com/stale.mp4",
      source: "https://www.tiktok.com/@creator/video/123",
    });
    const response = await proxyMedia(
      new Request(`https://site.example/api/media?${params}`, {
        headers: { range: "bytes=0-0" },
      }),
    );
    assert.equal(response.status, 206);
    assert.equal(calls.length, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("browser-local commands keep 60 FPS, 90 FPS, 2x upscale, filters, and MP3", () => {
  assert.match(buildLocalCommand("60").join(" "), /minterpolate=fps=60/);
  assert.match(buildLocalCommand("90").join(" "), /minterpolate=fps=90/);
  assert.match(buildLocalCommand("90").join(" "), /nlmeans/);
  assert.match(buildLocalCommand("upscale", "sharpen").join(" "), /iw\*2/);
  assert.match(buildLocalCommand("upscale", "sharpen").join(" "), /unsharp/);
  assert.match(buildLocalCommand("audio").join(" "), /libmp3lame/);
  assert.throws(() => buildLocalCommand("120"));
});

test("public UI is ad-funded, payment-free, consentful, and API-only on Functions", async () => {
  const [html, app, styles, routes] = await Promise.all([
    readFile(
      new URL("../public-site/index.html", import.meta.url),
      "utf8",
    ).then((html) => html.replace(/\s+/g, " ")),
    readFile(new URL("../public-site/app.js", import.meta.url), "utf8"),
    readFile(new URL("../public-site/styles.css", import.meta.url), "utf8"),
    readFile(new URL("../public-site/_routes.json", import.meta.url), "utf8"),
  ]);
  assert.equal(
    (html.match(/aria-label="Available advertisement"/g) || []).length,
    4,
  );
  assert.equal(
    (html.match(/rel="sponsored noopener noreferrer"/g) || []).length,
    4,
  );
  assert.equal(
    (
      html.match(
        /media-downloader-lite\/issues\/new\?template=sponsor\.yml/g,
      ) || []
    ).length,
    4,
  );
  assert.match(html, /60 FPS/);
  assert.match(html, /90 FPS/);
  assert.match(html, /2× upscale/);
  assert.match(html, /Extract MP3/);
  assert.match(html, /Nothing is saved to Downloads until you choose it/);
  assert.match(html, /Media Downloader Lite/);
  assert.match(html, /No login, account, or payment/);
  assert.match(html, /mandatory rights under applicable law/);
  assert.match(
    html,
    /VSCO links are recognized, but automated resolution is paused/,
  );
  assert.doesNotMatch(
    `${html}\n${app}`,
    /Stripe|subscription|checkout|billing/i,
  );
  assert.doesNotMatch(html, /300 × 600|970 × 90/);
  assert.doesNotMatch(app, /localStorage|indexedDB/i);
  assert.match(styles, /main\s*\{[^}]*grid-column:\s*2/s);
  assert.match(styles, /@media \(max-width: 720px\)/);
  assert.deepEqual(JSON.parse(routes).include, ["/api/*"]);
});

test("Sites worker routes APIs and emits host-correct social metadata with security headers", async () => {
  const html = await readFile(
    new URL("../public-site/index.html", import.meta.url),
    "utf8",
  );
  const env = {
    ASSETS: {
      fetch: async () =>
        new Response(html, {
          headers: { "content-type": "text/html; charset=utf-8" },
        }),
    },
  };
  const response = await worker.fetch(
    new Request("https://media.example/"),
    env,
    {},
  );
  const rendered = await response.text();
  assert.match(rendered, /https:\/\/media\.example\/og\.png/);
  assert.doesNotMatch(rendered, /__SITE_ORIGIN__/);
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.equal(response.headers.get("cache-control"), "no-cache");

  const missing = await worker.fetch(
    new Request("https://media.example/api/missing"),
    env,
    {},
  );
  assert.equal(missing.status, 404);
});

test("JSON ingestion counts actual stream bytes, cancels overflow and preserves UTF-8", async () => {
  const bytes = new TextEncoder().encode(JSON.stringify({ name: "æøå" }));
  const split = bytes.indexOf(195) + 1;
  const normal = new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(bytes.slice(0, split));
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    }),
  );
  assert.deepEqual(await readJSONBody(normal), { name: "æøå" });
  assert.equal(normal.body.locked, false);

  for (const length of [null, "4"]) {
    let reads = 0;
    let cancelled = false;
    const body = new ReadableStream(
      {
        pull(controller) {
          reads += 1;
          controller.enqueue(new Uint8Array(reads < 3 ? 2048 : 1).fill(32));
        },
        cancel() {
          cancelled = true;
        },
      },
      { highWaterMark: 0 },
    );
    const response = new Response(body, {
      headers: length ? { "content-length": length } : {},
    });
    await assert.rejects(readJSONBody(response), /request body is too large/);
    assert.equal(reads, 3);
    assert.equal(cancelled, true);
    assert.equal(body.locked, false);
  }
  let cancelled = false;
  const declared = new Response(
    new ReadableStream({
      cancel() {
        cancelled = true;
      },
    }),
    {
      headers: { "content-length": "4097" },
    },
  );
  await assert.rejects(readJSONBody(declared), /request body is too large/);
  assert.equal(cancelled, true);
  await assert.rejects(
    readJSONBody(
      new Request("https://unit.test", { method: "POST", body: "{" }),
    ),
    /Send a valid JSON request/,
  );
});

test("failed processor initialization remains retryable", async () => {
  const { processLocally, terminateLocalProcessor } =
    await import("../public-site/local-processor.js");
  const previous = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts += 1;
    throw new Error("Synthetic engine failure");
  };
  try {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await assert.rejects(
        processLocally(new Blob(["tiny"]), { mode: "60" }),
        /Synthetic engine failure/,
      );
    }
    assert.equal(attempts, 2);
  } finally {
    terminateLocalProcessor();
    globalThis.fetch = previous;
  }
});

test("only the processing worker permits verified blob scripts and WASM", async () => {
  const env = {
    ASSETS: {
      fetch: async () =>
        new Response("worker", {
          headers: { "content-type": "text/javascript" },
        }),
    },
  };
  const page = await worker.fetch(
    new Request("https://site.example/"),
    env,
    {},
  );
  const processor = await worker.fetch(
    new Request("https://site.example/vendor/ffmpeg/worker.js"),
    env,
    {},
  );
  assert.match(
    page.headers.get("content-security-policy"),
    /script-src 'self';/,
  );
  assert.doesNotMatch(
    page.headers.get("content-security-policy"),
    /wasm-unsafe-eval/,
  );
  assert.match(
    processor.headers.get("content-security-policy"),
    /script-src 'self' blob: 'wasm-unsafe-eval'/,
  );
  assert.match(
    processor.headers.get("content-security-policy"),
    /connect-src 'self' blob:/,
  );
});

test("source and output stay paired while processing and controls recover on failure", async () => {
  const source = await readFile(
    new URL("../public-site/app.js", import.meta.url),
    "utf8",
  );
  class Element {
    handlers = {};
    style = { setProperty() {} };
    value = "";
    checked = false;
    disabled = false;
    dataset = {};
    addEventListener(name, handler) {
      this.handlers[name] = handler;
    }
    replaceChildren() {}
    append() {}
    pause() {}
    load() {}
    focus() {}
    removeAttribute() {}
    setAttribute() {}
    reportValidity() {
      return true;
    }
  }
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const button = new Element();
  button.dataset.mode = "60";
  element("source-form").elements = [
    element("source-url"),
    element("terms-accepted"),
  ];
  const pending = Promise.withResolvers();
  let resolutions = 0;
  let fail = false;
  runInNewContext(source.replace(/^import[\s\S]*?;\n/, ""), {
    document: {
      getElementById: element,
      createElement: () => new Element(),
      querySelector: () => null,
      querySelectorAll: (selector) =>
        selector === "[data-mode]" ? [button] : [],
    },
    window: { addEventListener() {} },
    URL,
    Blob,
    AbortController,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    terminateLocalProcessor() {},
    processLocally: async () => {
      if (fail) throw new Error("job failed");
      return pending.promise;
    },
    fetch: async (url) => {
      if (url !== "/api/resolve") return new Response(new Blob(["source A"]));
      resolutions++;
      return Response.json({
        title: "Source A",
        media: [{ kind: "video", previewUrl: "/a", extension: "mp4" }],
      });
    },
  });
  element("terms-accepted").checked = true;
  element("source-url").value = "https://www.tiktok.com/@a/video/1";
  const submit = () =>
    element("source-form").handlers.submit({ preventDefault() {} });
  await submit();
  element("processing-accepted").checked = true;
  const job = button.handlers.click();
  assert.equal(element("source-url").disabled, true);
  assert.equal(button.disabled, true);
  element("source-url").value = "https://www.tiktok.com/@b/video/2";
  await submit();
  assert.equal(resolutions, 1);
  pending.resolve({ blob: new Blob(["result A"]), extension: "mp4" });
  await job;
  assert.equal(element("enhanced-download").download, "Source-A-60fps.mp4");
  assert.equal(element("source-url").disabled, false);
  assert.equal(button.disabled, false);
  fail = true;
  await button.handlers.click();
  assert.equal(element("enhance-status").textContent, "job failed");
  assert.equal(element("source-url").disabled, false);
});

test("a worker script error rejects initialization and allows another processing attempt", async () => {
  const { processLocally, terminateLocalProcessor } =
    await import("../public-site/local-processor.js");
  const previousFetch = globalThis.fetch;
  const previousWorker = globalThis.Worker;
  const previousDigest = crypto.subtle.digest;
  let workers = 0;
  let terminated = 0;
  globalThis.Worker = class {
    constructor() {
      workers++;
    }
    postMessage() {
      queueMicrotask(() =>
        this.onerror?.({ message: "Worker script unavailable" }),
      );
    }
    terminate() {
      terminated++;
    }
  };
  globalThis.fetch = async (url) =>
    new Response(new Uint8Array([String(url).endsWith(".wasm") ? 2 : 1]));
  crypto.subtle.digest = async (_algorithm, bytes) =>
    new Uint8Array(
      Buffer.from(
        bytes[0] === 1
          ? "67a48f11645f85439f3fde4f2119042c16b374b910206b7a7a24f342e28dcae3"
          : "9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7",
        "hex",
      ),
    ).buffer;
  try {
    terminateLocalProcessor();
    for (let attempt = 0; attempt < 2; attempt++) {
      await assert.rejects(
        processLocally(new Blob(["tiny"]), { mode: "60" }),
        /Worker script unavailable/,
      );
    }
    assert.equal(workers, 2);
    assert.equal(terminated, 2);
  } finally {
    terminateLocalProcessor();
    globalThis.fetch = previousFetch;
    globalThis.Worker = previousWorker;
    crypto.subtle.digest = previousDigest;
  }
});
