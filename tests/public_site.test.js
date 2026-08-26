import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  anonymousRateKey,
  checkRateLimit,
  parseFacebook,
  parseInstagram,
  parseMetaTags,
  parseTikTok,
  proxyMedia,
  validateMediaUrl,
  validateSourceUrl,
} from "../functions/_shared.js";
import { onRequest as mediaRequest } from "../functions/api/media.js";
import { onRequestPost as resolveRequest } from "../functions/api/resolve.js";
import {
  buildLocalCommand,
  processLocally,
  terminateLocalProcessor,
} from "../public-site/local-processor.js";
import worker from "../site-worker.js";

test("source URL validation is HTTPS-only and platform allowlisted", () => {
  assert.equal(validateSourceUrl("https://www.tiktok.com/@a/video/1").platform, "tiktok");
  assert.equal(validateSourceUrl("https://www.instagram.com/p/abc/").platform, "instagram");
  assert.equal(validateSourceUrl("https://fb.watch/abc").platform, "facebook");
  assert.equal(validateSourceUrl("https://vsco.co/user/media/abc").platform, "vsco");

  for (const value of [
    "http://www.tiktok.com/@a/video/1",
    "https://tiktok.com.evil.test/video/1",
    "https://user:pass@tiktok.com/video/1",
    "https://instagram.com:444/p/a",
    "https://127.0.0.1/video/1",
    "https://example.com/video/1",
  ]) assert.throws(() => validateSourceUrl(value));
});

test("media URL validation blocks arbitrary proxy targets", () => {
  assert.equal(validateMediaUrl("https://v16.tiktokcdn.com/video.mp4", "tiktok").hostname, "v16.tiktokcdn.com");
  assert.equal(validateMediaUrl("https://scontent.cdninstagram.com/photo.jpg", "instagram").hostname, "scontent.cdninstagram.com");
  assert.throws(() => validateMediaUrl("https://im.vsco.co/photo.jpg", "vsco"));
  assert.throws(() => validateMediaUrl("https://169.254.169.254/latest/meta-data", "tiktok"));
  assert.throws(() => validateMediaUrl("https://tiktokcdn.com.attacker.test/video.mp4", "tiktok"));
  assert.throws(() => validateMediaUrl("https://example.com/video.mp4", "facebook"));
});

test("best-effort in-isolate rate limiting closes after the configured count", () => {
  const key = `test-${crypto.randomUUID()}`;
  assert.equal(checkRateLimit(key, 1_000, 2), true);
  assert.equal(checkRateLimit(key, 1_001, 2), true);
  assert.equal(checkRateLimit(key, 1_002, 2), false);
  assert.equal(checkRateLimit(key, 62_000, 2), true);
});

test("rate-limit keys do not retain the raw client address", async () => {
  const request = new Request("https://site.example/api/resolve", { headers: { "cf-connecting-ip": "192.0.2.42" } });
  const first = await anonymousRateKey(request, "resolve");
  assert.equal(first, await anonymousRateKey(request, "resolve"));
  assert.doesNotMatch(first, /192\.0\.2\.42/);
});

test("meta parser handles attribute order and entities", () => {
  const meta = parseMetaTags('<meta content="A &amp; B" property="og:title"><meta name="twitter:image" content="https://cdninstagram.com/x.jpg">');
  assert.equal(meta["og:title"], "A & B");
  assert.equal(meta["twitter:image"], "https://cdninstagram.com/x.jpg");
});

test("meta parser survives out-of-range numeric entities", () => {
  const meta = parseMetaTags('<meta content="bad &#1114112; &#x110000; &#65;" property="og:title">');
  assert.match(meta["og:title"], /bad .* A/u);
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
                { bitRate: 100, playAddr: { urlList: ["https://v16.tiktokcdn.com/low.mp4"] } },
                { bitRate: 500, playAddr: { urlList: ["https://v16.tiktokcdn.com/high.mp4"] } },
              ],
            },
            imagePost: { images: [{ imageURL: { urlList: ["https://p16.tiktokcdn.com/one.jpg"] } }] },
            music: { title: "Sound", playUrl: "https://sf16.tiktokcdn.com/sound.mp3" },
          },
        },
      },
    },
  };
  const result = parseTikTok(`<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">${JSON.stringify(state)}</script>`, "https://www.tiktok.com/@creator/video/123");
  assert.equal(result.author, "creator");
  assert.equal(result.media.length, 3);
  assert.match(result.media[0].previewUrl, /high\.mp4/);
  assert.deepEqual(result.media.map((item) => item.kind), ["video", "image", "audio"]);
});

test("Instagram embed parser preserves carousel images and video", () => {
  const graph = {
    owner: { username: "creator" },
    edge_media_to_caption: { edges: [{ node: { text: "A carousel" } }] },
    edge_sidecar_to_children: {
      edges: [
        { node: { is_video: false, display_url: "https://scontent.cdninstagram.com/a.jpg", dimensions: { width: 1000, height: 1000 } } },
        { node: { is_video: true, video_url: "https://video.fbcdn.net/b.mp4", dimensions: { width: 1080, height: 1920 } } },
      ],
    },
  };
  const inner = JSON.stringify({ gql_data: { shortcode_media: graph } });
  const html = `<script>{"contextJSON":${JSON.stringify(inner)}}</script>`;
  const result = parseInstagram(html, "https://www.instagram.com/p/abc/");
  assert.equal(result.title, "A carousel");
  assert.deepEqual(result.media.map((item) => item.kind), ["image", "video"]);
  assert.equal(result.media[0].directUrl, "https://scontent.cdninstagram.com/a.jpg");
});

test("Facebook parser prefers an HD source URL", () => {
  const html = '<meta property="og:title" content="Public clip"><script>{"browser_native_sd_url":"https:\\/\\/video.fbcdn.net/sd.mp4","browser_native_hd_url":"https:\\/\\/video.fbcdn.net/hd.mp4"}</script>';
  const result = parseFacebook(html, "https://www.facebook.com/reel/1");
  assert.equal(result.title, "Public clip");
  assert.match(result.media[0].previewUrl, /hd\.mp4/);
});

test("resolver endpoint requires current active Terms acceptance", async () => {
  const request = new Request("https://site.example/api/resolve", {
    method: "POST",
    headers: { "content-type": "application/json", origin: "https://site.example", "cf-connecting-ip": "192.0.2.20" },
    body: JSON.stringify({ url: "https://www.tiktok.com/@a/video/1" }),
  });
  const response = await resolveRequest({ request });
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /Terms of Use/);
});

test("resolver pauses VSCO without making an upstream request", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return new Response("unexpected"); };
  try {
    const request = new Request("https://site.example/api/resolve", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "https://site.example", "cf-connecting-ip": "192.0.2.21" },
      body: JSON.stringify({ url: "https://vsco.co/user/media/abc", termsAccepted: true, termsVersion: "2026-08-10.2" }),
    });
    const response = await resolveRequest({ request });
    assert.equal(response.status, 400);
    assert.match((await response.json()).error, /automated resolution is paused/);
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("resolver does not echo internal upstream failures", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("getaddrinfo ENOTFOUND internal-resolver-host");
  };
  try {
    const request = new Request("https://site.example/api/resolve", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "https://site.example", "cf-connecting-ip": "192.0.2.22" },
      body: JSON.stringify({ url: "https://www.tiktok.com/@a/video/1", termsAccepted: true, termsVersion: "2026-08-10.2" }),
    });
    const response = await resolveRequest({ request });
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { error: "The source could not be resolved." });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("resolver reads a delayed streamed response before its deadline", async () => {
  const originalFetch = globalThis.fetch;
  const state = { scope: { "webapp.video-detail": { itemInfo: { itemStruct: {
    id: "streamed",
    desc: "Streamed response",
    author: { uniqueId: "creator" },
    video: { playAddr: "https://v16.tiktokcdn.com/streamed.mp4" },
  } } } } };
  const html = `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">${JSON.stringify(state)}</script>`;
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      setTimeout(() => {
        controller.enqueue(new TextEncoder().encode(html));
        controller.close();
      }, 5);
    },
  }), { headers: { "content-type": "text/html" } });
  try {
    const request = new Request("https://site.example/api/resolve", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "https://site.example", "cf-connecting-ip": "192.0.2.23" },
      body: JSON.stringify({ url: "https://www.tiktok.com/@creator/video/streamed", termsAccepted: true, termsVersion: "2026-08-10.2" }),
    });
    const response = await resolveRequest({ request });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).media[0].directUrl, "https://v16.tiktokcdn.com/streamed.mp4");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("media endpoint reports upstream failures without echoing internals", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("getaddrinfo ENOTFOUND internal-upstream-host");
  };
  try {
    const params = new URLSearchParams({ platform: "tiktok", kind: "video", url: "https://v16.tiktokcdn.com/source.mp4" });
    const request = new Request(`https://site.example/api/media?${params}`, {
      headers: { origin: "https://site.example", "cf-connecting-ip": "192.0.2.77" },
    });
    const response = await mediaRequest({ request });
    assert.equal(response.status, 502);
    assert.equal(response.headers.get("retry-after"), "30");
    const body = await response.json();
    assert.doesNotMatch(body.error, /ENOTFOUND|internal-upstream-host/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("media endpoint returns 400 for permanent client validation errors", async () => {
  const params = new URLSearchParams({ platform: "tiktok", kind: "bogus", url: "https://v16.tiktokcdn.com/source.mp4" });
  const request = new Request(`https://site.example/api/media?${params}`, {
    headers: { origin: "https://site.example", "cf-connecting-ip": "198.51.100.211" },
  });
  const response = await mediaRequest({ request });
  assert.equal(response.status, 400);
  assert.equal(response.headers.get("retry-after"), null);
});

test("media proxy cancels an upstream body with the wrong MIME type", async () => {
  const originalFetch = globalThis.fetch;
  let cancelled = false;
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array([1])); },
    cancel() { cancelled = true; },
  }), { headers: { "content-type": "image/jpeg" } });
  try {
    const params = new URLSearchParams({ platform: "tiktok", kind: "video", url: "https://v16.tiktokcdn.com/source.mp4" });
    await assert.rejects(proxyMedia(new Request(`https://site.example/api/media?${params}`)), /requested media type/);
    assert.equal(cancelled, true);
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
    const params = new URLSearchParams({ platform: "tiktok", kind: "video", url: "https://v16.tiktokcdn.com/source.mp4", name: "safe.mp4", download: "1" });
    const response = await proxyMedia(new Request(`https://site.example/api/media?${params}`, { headers: { range: "bytes=2-5" } }));
    assert.equal(response.status, 206);
    assert.equal(upstreamRange, "bytes=2-5");
    assert.equal(response.headers.get("content-range"), "bytes 2-5/10");
    assert.equal(response.headers.get("content-disposition"), 'attachment; filename="safe.mp4"');
    assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [2, 3, 4, 5]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("range proxy restores a missing Content-Range for open-ended requests", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(new Uint8Array([7, 8, 9]), {
    status: 206,
    headers: { "content-type": "video/mp4", "content-length": "3" },
  });
  try {
    const params = new URLSearchParams({ platform: "instagram", kind: "video", url: "https://scontent.cdninstagram.com/source.mp4" });
    const response = await proxyMedia(new Request(`https://site.example/api/media?${params}`, { headers: { range: "bytes=10-" } }));
    assert.equal(response.headers.get("content-range"), "bytes 10-12/*");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("range proxy accepts suffix ranges and rejects inverted ones", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(new Uint8Array([8, 9]), {
    status: 206,
    headers: { "content-type": "video/mp4", "content-length": "2" },
  });
  try {
    const params = new URLSearchParams({ platform: "tiktok", kind: "video", url: "https://v16.tiktokcdn.com/source.mp4" });
    const suffix = await proxyMedia(new Request(`https://site.example/api/media?${params}`, { headers: { range: "bytes=-2" } }));
    assert.equal(suffix.status, 206);
    assert.equal(suffix.headers.get("content-range"), null);
    assert.equal([...new Uint8Array(await suffix.arrayBuffer())].length, 2);

    const inverted = await proxyMedia(new Request(`https://site.example/api/media?${params}`, { headers: { range: "bytes=100-50" } }));
    assert.equal(inverted.status, 416);

    const empty = await proxyMedia(new Request(`https://site.example/api/media?${params}`, { headers: { range: "bytes=-" } }));
    assert.equal(empty.status, 416);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("proxy filenames drop leading and trailing dots", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(new Uint8Array([1]), {
    status: 200,
    headers: { "content-type": "video/mp4", "content-length": "1" },
  });
  try {
    const params = new URLSearchParams({ platform: "tiktok", kind: "video", url: "https://v16.tiktokcdn.com/source.mp4", name: "..hidden..mp4" });
    const response = await proxyMedia(new Request(`https://site.example/api/media?${params}`));
    assert.equal(response.headers.get("content-disposition"), 'inline; filename="hidden..mp4"');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("TikTok proxy retries a signed video inside a fresh anonymous session", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const state = { scope: { "webapp.video-detail": { itemInfo: { itemStruct: {
    id: "123",
    desc: "Example",
    author: { uniqueId: "creator" },
    video: { playAddr: "https://v16.tiktokcdn.com/fresh.mp4" },
  } } } } };
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), cookie: init?.headers?.cookie || "" });
    if (calls.length === 1) return new Response("blocked", { status: 403 });
    if (calls.length === 2) return new Response(`<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">${JSON.stringify(state)}</script>`, {
      headers: { "content-type": "text/html", "set-cookie": "tt_chain_token=anonymous; Path=/; Secure" },
    });
    assert.equal(init.headers.cookie, "tt_chain_token=anonymous");
    return new Response(new Uint8Array([1]), {
      status: 206,
      headers: { "content-type": "video/mp4", "content-length": "1", "content-range": "bytes 0-0/1" },
    });
  };
  try {
    const params = new URLSearchParams({
      platform: "tiktok",
      kind: "video",
      url: "https://v16.tiktokcdn.com/stale.mp4",
      source: "https://www.tiktok.com/@creator/video/123",
    });
    const response = await proxyMedia(new Request(`https://site.example/api/media?${params}`, { headers: { range: "bytes=0-0" } }));
    assert.equal(response.status, 206);
    assert.equal(calls.length, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("local processor lock is released by failed loads and cleared only by the owning job", async () => {
  const source = await readFile(new URL("../public-site/local-processor.js", import.meta.url), "utf8");
  assert.match(source, /let ffmpeg;\n  try \{\n    ffmpeg = await loadLocalProcessor/);
  assert.match(source, /if \(token !== runToken\) throw new Error\("The local processing job was cancelled\."\);/);
  assert.match(source, /if \(token === runToken\) \{[\s\S]*?running = false;/);
  assert.match(source, /terminateLocalProcessor\(\)[\s\S]*?runToken \+= 1;\n  running = false;/);
});

test("stale local-processing callbacks cannot update a replacement source", async () => {
  const source = await readFile(new URL("../public-site/app.js", import.meta.url), "utf8");
  assert.match(source, /function resetMedia\(\) \{\n  terminateLocalProcessor\(\);/);
  assert.match(source, /onProgress: \(ratio\) => \{\n\s+if \(gen !== state\.gen\) return;/);
  assert.match(source, /onStatus: \(message\) => \{\n\s+if \(gen === state\.gen\)/);
  assert.match(source, /finally \{\n\s+if \(gen === state\.gen\)/);
});

test("local processing always releases its lock and temporary files", async () => {
  const originalFetch = globalThis.fetch;
  const originalWorker = globalThis.Worker;
  const originalDigest = crypto.subtle.digest;
  const hashes = [
    "67a48f11645f85439f3fde4f2119042c16b374b910206b7a7a24f342e28dcae3",
    "9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7",
  ];
  const exitCodes = [0, 1, 0];
  const deleted = [];
  let digestIndex = 0;

  class FakeWorker {
    onmessage;
    postMessage({ id, type, data }) {
      let result = true;
      if (type === "EXEC") result = exitCodes.shift();
      if (type === "READ_FILE") result = new Uint8Array([1, 2, 3]);
      if (type === "DELETE_FILE") deleted.push(data.path);
      queueMicrotask(() => this.onmessage?.({ data: { id, type, data: result } }));
    }
    terminate() {}
  }

  globalThis.Worker = FakeWorker;
  globalThis.fetch = async () => new Response(new Uint8Array([1]), { headers: { "content-length": "1" } });
  crypto.subtle.digest = async () => Uint8Array.from(Buffer.from(hashes[digestIndex++], "hex")).buffer;
  try {
    const source = new Blob([new Uint8Array([1])]);
    assert.equal((await processLocally(source, { mode: "audio" })).extension, "mp3");
    await assert.rejects(processLocally(source, { mode: "audio" }), /exit code 1/);
    assert.equal((await processLocally(source, { mode: "audio" })).extension, "mp3");
    assert.deepEqual(deleted, [
      "input.media", "output.mp3",
      "input.media", "output.mp3",
      "input.media", "output.mp3",
    ]);
  } finally {
    terminateLocalProcessor();
    globalThis.fetch = originalFetch;
    globalThis.Worker = originalWorker;
    crypto.subtle.digest = originalDigest;
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
    readFile(new URL("../public-site/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public-site/app.js", import.meta.url), "utf8"),
    readFile(new URL("../public-site/styles.css", import.meta.url), "utf8"),
    readFile(new URL("../public-site/_routes.json", import.meta.url), "utf8"),
  ]);
  assert.equal((html.match(/aria-label="Available advertisement"/g) || []).length, 4);
  assert.equal((html.match(/rel="sponsored noopener noreferrer"/g) || []).length, 4);
  assert.equal((html.match(/media-downloader-lite\/issues\/new\?template=sponsor\.yml/g) || []).length, 4);
  assert.match(html, /60 FPS/);
  assert.match(html, /90 FPS/);
  assert.match(html, /2× upscale/);
  assert.match(html, /Extract MP3/);
  assert.match(html, /Nothing is saved to Downloads until you choose it/);
  assert.match(html, /Media Downloader Lite/);
  assert.match(html, /No login, account, or payment/);
  assert.match(html, /mandatory rights under applicable law/);
  assert.match(html, /VSCO links are recognized, but automated resolution is paused/);
  assert.match(html, /<label for="terms-accepted">[^<]+<\/label>\s*<button[^>]+data-dialog="terms-dialog">Terms of Use<\/button>/);
  assert.doesNotMatch(`${html}\n${app}`, /Stripe|subscription|checkout|billing/i);
  assert.doesNotMatch(html, /300 × 600|970 × 90/);
  assert.doesNotMatch(app, /localStorage|indexedDB/i);
  assert.match(styles, /main\s*\{[^}]*grid-column:\s*2/s);
  assert.match(styles, /@media \(max-width: 720px\)/);
  assert.deepEqual(JSON.parse(routes).include, ["/api/*"]);
});

test("Sites worker routes APIs and emits host-correct social metadata with security headers", async () => {
  const html = await readFile(new URL("../public-site/index.html", import.meta.url), "utf8");
  const env = {
    ASSETS: {
      fetch: async () => new Response(html, { headers: { "content-type": "text/html; charset=utf-8" } }),
    },
  };
  const response = await worker.fetch(new Request("https://media.example/"), env, {});
  const rendered = await response.text();
  assert.match(rendered, /https:\/\/media\.example\/og\.png/);
  assert.doesNotMatch(rendered, /__SITE_ORIGIN__/);
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.equal(response.headers.get("cache-control"), "no-cache");

  const missing = await worker.fetch(new Request("https://media.example/api/missing"), env, {});
  assert.equal(missing.status, 404);
});
