// Public embed parsing patterns are partially adapted from
// Vette1123/social-media-downloader (MIT, Copyright 2025 Mohamed Gado).

export const TERMS_VERSION = "2026-08-10.2";
export const MAX_JSON_BYTES = 4096;
export const MAX_PAGE_BYTES = 2_500_000;
export const MAX_MEDIA_BYTES = 1024 * 1024 * 1024;

const SOURCE_HOSTS = {
  tiktok: ["tiktok.com"],
  instagram: ["instagram.com", "instagr.am"],
  facebook: ["facebook.com", "fb.watch"],
  vsco: ["vsco.co"],
};

const MEDIA_HOSTS = {
  tiktok: ["tiktok.com", "tiktokcdn.com", "tiktokcdn-eu.com", "tiktokcdn-us.com", "tiktokv.com", "byteoversea.com", "ibytedtos.com", "muscdn.com", "bytecdn.cn"],
  instagram: ["instagram.com", "cdninstagram.com", "fbcdn.net"],
  facebook: ["facebook.com", "fbcdn.net"],
};

const BROWSER_HEADERS = {
  accept: "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.7",
  "accept-language": "en-US,en;q=0.8",
  "sec-fetch-dest": "document",
  "sec-fetch-mode": "navigate",
  "sec-fetch-site": "none",
  "upgrade-insecure-requests": "1",
  "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36",
};

const INSTAGRAM_HEADERS = {
  ...BROWSER_HEADERS,
  "user-agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
};

// ponytail: isolate-local limiting costs nothing; use Cloudflare Rate Limiting if real abuse outgrows it.
const rateWindows = new Map();
const RATE_SALT = "media-downloader-lite-rate-limit-v1";

export class UserFacingError extends Error {}

function hostMatches(hostname, allowed) {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  return allowed.some((suffix) => host === suffix || host.endsWith(`.${suffix}`));
}

function isIpLiteral(hostname) {
  return /^\d{1,3}(?:\.\d{1,3}){3}$/.test(hostname) || hostname.includes(":");
}

function cleanHttpsURL(value, maxLength) {
  if (typeof value !== "string" || !value.trim() || value.length > maxLength) throw new UserFacingError("The URL is invalid or too long.");
  let url;
  try {
    url = new URL(value.trim());
  } catch {
    throw new UserFacingError("Enter a complete HTTPS link.");
  }
  if (url.protocol !== "https:" || url.username || url.password || url.port || isIpLiteral(url.hostname)) {
    throw new UserFacingError("Only normal HTTPS links without credentials or custom ports are accepted.");
  }
  url.hash = "";
  return url;
}

export function validateSourceUrl(value) {
  const url = cleanHttpsURL(value, 2048);
  for (const [platform, hosts] of Object.entries(SOURCE_HOSTS)) {
    if (hostMatches(url.hostname, hosts)) return { platform, url };
  }
  throw new UserFacingError("Use a public VSCO, Instagram, TikTok, or Facebook link.");
}

export function validateMediaUrl(value, platform) {
  if (!Object.hasOwn(MEDIA_HOSTS, platform)) throw new Error("Unknown media platform.");
  const url = cleanHttpsURL(value, 8192);
  if (!hostMatches(url.hostname, MEDIA_HOSTS[platform])) throw new Error("The source returned media from an unapproved host.");
  return url;
}

export function checkRateLimit(key, now = Date.now(), maximum = 15) {
  const windowMs = 60_000;
  const current = rateWindows.get(key);
  if (!current || now - current.startedAt >= windowMs) {
    rateWindows.set(key, { startedAt: now, count: 1 });
    for (const [storedKey, value] of rateWindows) {
      if (now - value.startedAt >= windowMs) rateWindows.delete(storedKey);
    }
    while (rateWindows.size > 10_000) {
      rateWindows.delete(rateWindows.keys().next().value);
    }
    return true;
  }
  current.count += 1;
  return current.count <= maximum;
}

export async function anonymousRateKey(request, scope) {
  const address = request.headers.get("cf-connecting-ip") || "local";
  const input = new TextEncoder().encode(`${RATE_SALT}:${address}`);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", input));
  return `${scope}:${[...digest.slice(0, 12)].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function decodeCodePoint(code, original) {
  return Number.isInteger(code) && code >= 0 && code <= 0x10ffff ? String.fromCodePoint(code) : original;
}

function decodeEntities(value) {
  return String(value || "")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#x([0-9a-f]+);/gi, (match, code) => decodeCodePoint(parseInt(code, 16), match))
    .replace(/&#(\d+);/g, (match, code) => decodeCodePoint(Number(code), match));
}

function decodeEscaped(value) {
  try {
    return JSON.parse(`"${value}"`);
  } catch {
    return decodeEntities(String(value || "").replace(/\\u002F/gi, "/").replace(/\\\//g, "/").replace(/\\u0026/gi, "&").replace(/\\/g, ""));
  }
}

function parseTagAttributes(tag) {
  const attributes = {};
  for (const match of tag.matchAll(/([:\w-]+)\s*=\s*(["'])(.*?)\2/gs)) attributes[match[1].toLowerCase()] = decodeEntities(match[3]);
  return attributes;
}

export function parseMetaTags(html) {
  const meta = {};
  for (const match of String(html).matchAll(/<meta\b[^>]*>/gi)) {
    const attributes = parseTagAttributes(match[0]);
    const key = (attributes.property || attributes.name || "").toLowerCase();
    if (key && attributes.content && !meta[key]) meta[key] = attributes.content;
  }
  return meta;
}

function scriptById(html, id) {
  const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return String(html).match(new RegExp(`<script\\b[^>]*id=["']${escaped}["'][^>]*>([\\s\\S]*?)<\\/script>`, "i"))?.[1] || "";
}

function scriptContaining(html, marker) {
  for (const match of String(html).matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    if (match[1].includes(marker)) return match[1];
  }
  return "";
}

function deepObjects(root, limit = 20_000) {
  const found = [];
  const stack = [root];
  const seen = new Set();
  while (stack.length && found.length < limit) {
    const value = stack.pop();
    if (!value || typeof value !== "object" || seen.has(value)) continue;
    seen.add(value);
    found.push(value);
    for (const child of Array.isArray(value) ? value : Object.values(value)) stack.push(child);
  }
  return found;
}

function asAbsolute(value, base) {
  if (typeof value !== "string" || !value) return "";
  try {
    return new URL(decodeEntities(value), base).href;
  } catch {
    return "";
  }
}

function bestUrl(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.find((item) => typeof item === "string") || "";
  if (!value || typeof value !== "object") return "";
  return bestUrl(value.urlList || value.UrlList || value.urls || value.url || value.src);
}

function extensionFor(url, kind) {
  const fallback = { video: "mp4", image: "jpg", audio: "mp3" }[kind] || "bin";
  try {
    const extension = new URL(url).pathname.match(/\.([a-z0-9]{2,5})$/i)?.[1]?.toLowerCase();
    return extension && !new Set(["html", "php", "json"]).has(extension) ? extension : fallback;
  } catch {
    return fallback;
  }
}

function safeFilename(value, fallback) {
  const cleaned = String(value || fallback).normalize("NFKD").replace(/[^a-z0-9._-]+/gi, "-").replace(/^[.-]+|[.-]+$/g, "");
  return (cleaned || fallback).slice(0, 100);
}

function mediaItem(platform, kind, url, title, details = {}) {
  const validated = validateMediaUrl(asAbsolute(url, `https://www.${platform}.com/`) || url, platform);
  const extension = details.extension || extensionFor(validated.href, kind);
  const filename = `${safeFilename(details.filename || title, `${platform}-${kind}`)}.${extension}`;
  const query = new URLSearchParams({ platform, kind, url: validated.href, name: filename });
  if (details.sourceUrl) {
    const source = validateSourceUrl(details.sourceUrl);
    if (source.platform !== platform) throw new Error("The media source platform does not match.");
    query.set("source", source.url.href);
  }
  return {
    kind,
    directUrl: validated.href,
    previewUrl: `/api/media?${query}`,
    downloadUrl: `/api/media?${query}&download=1`,
    filename,
    extension,
    width: Number(details.width) || 0,
    height: Number(details.height) || 0,
    fps: Number(details.fps) || 0,
    bytes: Number(details.bytes) || 0,
  };
}

function optionalMediaItem(platform, kind, url, title, details = {}) {
  try {
    return mediaItem(platform, kind, url, title, details);
  } catch {
    return null;
  }
}

function dedupeMedia(media) {
  const seen = new Set();
  return media.filter((item) => {
    if (!item || seen.has(item.previewUrl)) return false;
    seen.add(item.previewUrl);
    return true;
  }).slice(0, 51);
}

function genericMetaResult(platform, html, sourceUrl) {
  const meta = parseMetaTags(html);
  const title = meta["og:title"] || meta["twitter:title"] || `${platform} media`;
  const author = meta["author"] || "";
  const videoUrl = meta["og:video:secure_url"] || meta["og:video:url"] || meta["og:video"] || meta["twitter:player:stream"];
  const imageUrl = meta["og:image:secure_url"] || meta["og:image"] || meta["twitter:image"];
  const media = [];
  if (videoUrl) media.push(mediaItem(platform, "video", videoUrl, title, {
    width: meta["og:video:width"],
    height: meta["og:video:height"],
  }));
  if (!videoUrl && imageUrl) media.push(mediaItem(platform, "image", imageUrl, title, {
    width: meta["og:image:width"],
    height: meta["og:image:height"],
  }));
  return { ok: true, platform, title, author, sourceUrl, media: dedupeMedia(media) };
}

function parseTikTokState(html) {
  const candidates = [
    scriptById(html, "__UNIVERSAL_DATA_FOR_REHYDRATION__"),
    scriptById(html, "SIGI_STATE"),
    scriptContaining(html, "webapp.video-detail"),
  ].filter(Boolean);
  for (const text of candidates) {
    try {
      return JSON.parse(text);
    } catch {
      // Some TikTok variants embed a non-JSON wrapper; regex fallback handles it.
    }
  }
  return null;
}

export function parseTikTok(html, sourceUrl) {
  const state = parseTikTokState(html);
  const objects = state ? deepObjects(state) : [];
  const item = objects.find((value) => value.video && (value.id || value.desc || value.author)) || {};
  const title = String(item.desc || parseMetaTags(html)["og:title"] || "TikTok media").slice(0, 120);
  const author = item.author?.uniqueId || item.author?.nickname || "";
  const video = item.video || {};
  const media = [];

  const rates = Array.isArray(video.bitRate) ? video.bitRate : Array.isArray(video.bitrateInfo) ? video.bitrateInfo : [];
  const ranked = rates.map((rate) => ({
    url: bestUrl(rate.playAddr || rate.PlayAddr || rate),
    score: Number(rate.bitRate || rate.Bitrate || 0) + Number(rate.width || rate.PlayAddr?.Width || 0) * Number(rate.height || rate.PlayAddr?.Height || 0),
    width: rate.width || rate.PlayAddr?.Width,
    height: rate.height || rate.PlayAddr?.Height,
  })).filter((rate) => rate.url).sort((a, b) => b.score - a.score);
  let videoUrl = ranked[0]?.url || bestUrl(video.playAddr || video.playApi || video.downloadAddr);
  if (!videoUrl) {
    const script = candidatesFromHtml(html);
    videoUrl = decodeEscaped(script.match(/"playAddr":"((?:\\.|[^"\\])+)"/)?.[1] || script.match(/"downloadAddr":"((?:\\.|[^"\\])+)"/)?.[1] || "");
  }
  if (videoUrl) media.push(mediaItem("tiktok", "video", videoUrl, title, {
    width: ranked[0]?.width || video.width,
    height: ranked[0]?.height || video.height,
    fps: video.fps,
    sourceUrl,
  }));

  const imagePost = item.imagePost || objects.find((value) => Array.isArray(value.images) && value.images.some((image) => image?.imageURL || image?.imageUrl));
  const images = imagePost?.images || [];
  images.forEach((image, index) => {
    const url = bestUrl(image.imageURL || image.imageUrl || image.displayImage);
    const item = url && optionalMediaItem("tiktok", "image", url, `${title}-${index + 1}`, {
      width: image.imageWidth || image.width,
      height: image.imageHeight || image.height,
      sourceUrl,
    });
    if (item) media.push(item);
  });

  const music = item.music || objects.find((value) => value.playUrl && (value.title || value.authorName));
  const musicUrl = bestUrl(music?.playUrl || music?.play_url);
  const audio = musicUrl && optionalMediaItem("tiktok", "audio", musicUrl, `${title}-audio`, { sourceUrl });
  if (audio) media.push(audio);

  if (!media.length) return genericMetaResult("tiktok", html, sourceUrl);
  return { ok: true, platform: "tiktok", title, author, sourceUrl, media: dedupeMedia(media) };
}

function candidatesFromHtml(html) {
  return scriptContaining(html, "playAddr") || String(html);
}

function instagramShortcode(url) {
  return new URL(url).pathname.match(/\/(?:p|reel|reels|tv)\/([\w-]+)/i)?.[1] || "";
}

function balancedObject(text, start) {
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (let index = start; index < text.length; index += 1) {
    const character = text[index];
    if (escaped) escaped = false;
    else if (character === "\\") escaped = true;
    else if (character === '"') quoted = !quoted;
    else if (!quoted && character === "{") depth += 1;
    else if (!quoted && character === "}" && --depth === 0) return text.slice(start, index + 1);
  }
  return "";
}

function instagramMediaGraph(html) {
  const contextKey = '"contextJSON":';
  let searchFrom = 0;
  while (true) {
    const index = html.indexOf(contextKey, searchFrom);
    if (index < 0) break;
    const quote = html.indexOf('"', index + contextKey.length);
    if (quote < 0) break;
    let cursor = quote + 1;
    let escaped = false;
    for (; cursor < html.length; cursor += 1) {
      const character = html[cursor];
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') break;
    }
    searchFrom = cursor + 1;
    try {
      const parsed = JSON.parse(JSON.parse(html.slice(quote, cursor + 1)));
      const media = parsed?.gql_data?.shortcode_media || parsed?.context?.media;
      if (media) return media;
    } catch {
      // Continue to the next contextJSON payload.
    }
  }

  const key = '"shortcode_media":';
  const index = html.indexOf(key);
  const brace = index < 0 ? -1 : html.indexOf("{", index + key.length);
  if (brace >= 0) {
    try {
      return JSON.parse(balancedObject(html, brace));
    } catch {
      return null;
    }
  }
  return null;
}

export function parseInstagram(html, sourceUrl) {
  const graph = instagramMediaGraph(html);
  if (!graph) return genericMetaResult("instagram", html, sourceUrl);
  const author = graph.owner?.username || "";
  const caption = graph.edge_media_to_caption?.edges?.[0]?.node?.text?.trim() || "";
  const title = (caption || `Instagram post${author ? ` by @${author}` : ""}`).slice(0, 120);
  const media = [];
  const children = graph.edge_sidecar_to_children?.edges?.map((edge) => edge?.node).filter(Boolean) || [graph];
  children.forEach((item, index) => {
    if (item.is_video && item.video_url) {
      const video = optionalMediaItem("instagram", "video", item.video_url, `${title}-${index + 1}`, {
      width: item.dimensions?.width,
      height: item.dimensions?.height,
      });
      if (video) media.push(video);
    } else if (!item.is_video && item.display_url) {
      const image = optionalMediaItem("instagram", "image", item.display_url, `${title}-${index + 1}`, {
      width: item.dimensions?.width,
      height: item.dimensions?.height,
      });
      if (image) media.push(image);
    }
  });
  return { ok: true, platform: "instagram", title, author, sourceUrl, media: dedupeMedia(media) };
}

function facebookString(html, key) {
  const value = String(html).match(new RegExp(`"${key}":"((?:\\\\.|[^"\\\\])*)"`))?.[1];
  return value ? decodeEscaped(value) : "";
}

export function parseFacebook(html, sourceUrl) {
  const keys = ["browser_native_hd_url", "playable_url_quality_hd", "hd_src_no_ratelimit", "hd_src", "browser_native_sd_url", "playable_url", "sd_src_no_ratelimit", "sd_src"];
  const videoUrl = keys.map((key) => facebookString(html, key)).find((value) => value.startsWith("https://"));
  if (!videoUrl) return genericMetaResult("facebook", html, sourceUrl);
  const meta = parseMetaTags(html);
  const title = (meta["og:title"] || meta["og:description"] || "Facebook video").slice(0, 120);
  return {
    ok: true,
    platform: "facebook",
    title,
    author: "Facebook",
    sourceUrl,
    media: [mediaItem("facebook", "video", videoUrl, title, {
      width: meta["og:video:width"],
      height: meta["og:video:height"],
    })],
  };
}

async function readTextLimited(response, maximum = MAX_PAGE_BYTES, deadlineController = null) {
  if (!response.body) return "";
  const declared = Number(response.headers.get("content-length")) || 0;
  if (declared > maximum) {
    await response.body.cancel();
    throw new Error("The source page was too large to inspect safely.");
  }
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    // Aborting the fetch signal errors this stream, bounding stalled bodies.
    const { done, value } = await Promise.race([
      reader.read(),
      deadlineController ? new Promise((_, reject) => deadlineController.addEventListener("abort", () => reject(new Error("The source page took too long to load.")), { once: true })) : null,
    ]);
    if (done) break;
    total += value.byteLength;
    if (total > maximum) {
      await reader.cancel();
      throw new Error("The source page was too large to inspect safely.");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

async function fetchWithTimeout(url, init, timeoutMs = 10_000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

function rememberResponseCookies(response, jar) {
  if (!jar) return;
  const values = [...(response.headers.getSetCookie?.() || [])];
  const combined = response.headers.get("set-cookie");
  if (combined) values.push(combined);
  for (const value of values) {
    const match = String(value).match(/^\s*([^=;,\s]+)=([^;]*)/);
    if (match) jar.set(match[1], `${match[1]}=${match[2]}`);
  }
}

async function fetchPage(startUrl, platform, maximumRedirects = 4, headers = BROWSER_HEADERS, cookieJar = new Map(), retryChallenge = true) {
  let current = validateSourceUrl(startUrl).url;
  for (let redirects = 0; redirects <= maximumRedirects; redirects += 1) {
    const requestHeaders = cookieJar?.size ? { ...headers, cookie: [...cookieJar.values()].join("; ") } : headers;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    let response;
    try {
      response = await fetch(current, { headers: requestHeaders, redirect: "manual", signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }
    rememberResponseCookies(response, cookieJar);
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      await response.body?.cancel();
      if (!location || redirects === maximumRedirects) throw new Error("The source redirected too many times.");
      const next = new URL(location, current);
      const validated = validateSourceUrl(next.href);
      if (validated.platform !== platform) throw new Error("The source redirected to an unsupported platform.");
      current = validated.url;
      continue;
    }
    if (!response.ok) {
      await response.body?.cancel();
      if (response.status === 403 && retryChallenge && cookieJar.size) {
        return fetchPage(current.href, platform, maximumRedirects - redirects, headers, cookieJar, false);
      }
      if (platform === "vsco" && response.status === 403) {
        throw new Error("VSCO currently blocks this free edge resolver. Try again later; no media was stored.");
      }
      throw new Error(`The source platform returned HTTP ${response.status}.`);
    }
    const bodyController = new AbortController();
    const bodyTimeout = setTimeout(() => bodyController.abort(), 15_000);
    try {
      return { url: current.href, html: await readTextLimited(response, MAX_PAGE_BYTES, bodyController) };
    } finally {
      clearTimeout(bodyTimeout);
    }
  }
  throw new Error("The source could not be resolved.");
}

async function instagramPage(sourceUrl, cookieJar) {
  let finalUrl = sourceUrl;
  let shortcode = instagramShortcode(finalUrl);
  if (!shortcode) {
    const resolved = await fetchPage(sourceUrl, "instagram", 4, BROWSER_HEADERS, cookieJar);
    finalUrl = resolved.url;
    shortcode = instagramShortcode(finalUrl);
  }
  if (!shortcode) throw new UserFacingError("Use an Instagram post, reel, or video link.");
  const embed = `https://www.instagram.com/p/${shortcode}/embed/captioned/`;
  const page = await fetchPage(embed, "instagram", 4, INSTAGRAM_HEADERS, cookieJar);
  return { url: finalUrl, html: page.html };
}

export async function resolveSource(input) {
  const { platform, url } = validateSourceUrl(input);
  if (platform === "vsco") {
    throw new UserFacingError("VSCO links are recognized, but automated resolution is paused. We do not bypass platform protections or automate access without permission.");
  }
  const cookieJar = new Map();
  let page;
  if (platform === "instagram") page = await instagramPage(url.href, cookieJar);
  else page = await fetchPage(url.href, platform, 4, BROWSER_HEADERS, cookieJar);

  let result;
  if (platform === "tiktok") result = parseTikTok(page.html, page.url);
  else if (platform === "instagram") result = parseInstagram(page.html, page.url);
  else if (platform === "facebook") {
    result = parseFacebook(page.html, page.url);
    if (!result.media.length) {
      const pluginUrl = `https://www.facebook.com/plugins/video.php?href=${encodeURIComponent(page.url)}`;
      const plugin = await fetchPage(pluginUrl, "facebook", 4, BROWSER_HEADERS, cookieJar);
      result = parseFacebook(plugin.html, page.url);
    }
  } else throw new Error("Unsupported source platform.");

  if (!result.media?.length) throw new UserFacingError("The public source did not expose a supported original file. It may be private, unavailable, or login-only.");
  if (result.media.every((item) => item.kind !== "video") && platform === "instagram") result.note = "Original image media ready. Reels that Instagram exposes only after login are intentionally not bypassed.";
  return result;
}

export function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "cache-control": "no-store",
      "content-type": "application/json; charset=utf-8",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
      ...extraHeaders,
    },
  });
}

export function requestOriginIsAllowed(request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}

export async function readJSONBody(request) {
  const declared = Number(request.headers.get("content-length")) || 0;
  if (declared > MAX_JSON_BYTES) throw new UserFacingError("The request body is too large.");
  const reader = request.body?.getReader();
  const chunks = [];
  let total = 0;
  while (reader) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_JSON_BYTES) {
      await reader.cancel();
      throw new UserFacingError("The request body is too large.");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const text = new TextDecoder().decode(bytes);
  try {
    return JSON.parse(text);
  } catch {
    throw new UserFacingError("Send a valid JSON request.");
  }
}

function mediaReferer(platform) {
  return {
    tiktok: "https://www.tiktok.com/",
    instagram: "https://www.instagram.com/",
    facebook: "https://www.facebook.com/",
  }[platform];
}

async function fetchMedia(startUrl, platform, range, maximumRedirects = 3, cookie = "") {
  let current = validateMediaUrl(startUrl, platform);
  for (let redirects = 0; redirects <= maximumRedirects; redirects += 1) {
    const headers = {
      accept: "video/*,audio/*,image/*,*/*;q=0.6",
      "accept-encoding": "identity",
      referer: mediaReferer(platform),
      "user-agent": BROWSER_HEADERS["user-agent"],
    };
    if (range) headers.range = range;
    if (cookie) headers.cookie = cookie;
    const response = await fetchWithTimeout(current, { headers, redirect: "manual" }, 15_000);
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      await response.body?.cancel();
      if (!location || redirects === maximumRedirects) throw new Error("The media redirected too many times.");
      current = validateMediaUrl(new URL(location, current).href, platform);
      continue;
    }
    return response;
  }
  throw new Error("The media could not be fetched.");
}

async function fetchTikTokSessionMedia(sourceUrl, kind, range) {
  const cookies = new Map();
  const page = await fetchPage(sourceUrl, "tiktok", 4, BROWSER_HEADERS, cookies);
  const item = parseTikTok(page.html, page.url).media.find((candidate) => candidate.kind === kind);
  if (!item) throw new Error("TikTok did not expose this media type in the fresh anonymous session.");
  return fetchMedia(item.directUrl, "tiktok", range, 3, [...cookies.values()].join("; "));
}

function limitedStream(body, maximum, abort) {
  if (!body) return null;
  const reader = body.getReader();
  let total = 0;
  return new ReadableStream({
    async pull(controller) {
      const { done, value } = await reader.read();
      if (done) return controller.close();
      total += value.byteLength;
      if (total > maximum) {
        abort?.();
        await reader.cancel();
        controller.error(new Error("Media exceeded the streaming limit."));
        return;
      }
      controller.enqueue(value);
    },
    cancel(reason) { return reader.cancel(reason); },
  });
}

function contentTypeFor(kind, upstream) {
  const type = upstream?.split(";", 1)[0]?.trim().toLowerCase() || "";
  const prefixes = { video: "video/", audio: "audio/", image: "image/" };
  if (!type) return { video: "video/mp4", audio: "audio/mpeg", image: "image/jpeg" }[kind];
  if (type.startsWith(prefixes[kind])) return type;
  if (kind === "audio" && type.startsWith("video/")) return type;
  throw new Error("The media host did not return the requested media type.");
}

export async function proxyMedia(request) {
  const requestUrl = new URL(request.url);
  const platform = requestUrl.searchParams.get("platform") || "";
  const kind = requestUrl.searchParams.get("kind") || "";
  const source = requestUrl.searchParams.get("url") || "";
  const sourcePage = requestUrl.searchParams.get("source") || "";
  if (!new Set(["video", "audio", "image"]).has(kind)) throw new Error("Unknown media type.");
  validateMediaUrl(source, platform);
  if (sourcePage && validateSourceUrl(sourcePage).platform !== platform) throw new Error("The media source platform does not match.");

  const range = request.headers.get("range");
  if (range) {
    const bounds = /^bytes=(\d{1,20})?-(\d{1,20})?$/.exec(range);
    if (!bounds || (!bounds[1] && !bounds[2])) return json({ error: "Invalid byte range." }, 416);
    if (bounds[1] !== undefined && bounds[2] !== undefined && Number(bounds[1]) > Number(bounds[2])) {
      return json({ error: "Invalid byte range." }, 416);
    }
  }
  let response = await fetchMedia(source, platform, range);
  if (response.status === 403 && platform === "tiktok" && sourcePage) {
    await response.body?.cancel();
    response = await fetchTikTokSessionMedia(sourcePage, kind, range);
  }
  if (!response.ok && response.status !== 206) {
    await response.body?.cancel();
    throw new Error(`The media host returned HTTP ${response.status}.`);
  }

  const declared = Number(response.headers.get("content-length")) || 0;
  if (declared > MAX_MEDIA_BYTES) {
    await response.body?.cancel();
    return json({ error: "This source file exceeds the public streaming limit." }, 413);
  }

  const filename = safeFilename(requestUrl.searchParams.get("name"), `source.${extensionFor(source, kind)}`);
  const disposition = requestUrl.searchParams.get("download") === "1" ? "attachment" : "inline";
  const headers = new Headers({
    "accept-ranges": "bytes",
    "access-control-allow-origin": new URL(request.url).origin,
    "cache-control": "private, no-store",
    "content-disposition": `${disposition}; filename="${filename}"`,
    "content-type": contentTypeFor(kind, response.headers.get("content-type")),
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
  });
  for (const name of ["content-length", "content-range", "etag", "last-modified"]) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (range && response.status === 206 && !headers.has("content-range") && declared) {
    const bounds = range.match(/^bytes=(\d+)?-(\d+)?$/);
    const start = bounds && bounds[1] !== undefined ? Number(bounds[1]) : NaN;
    if (Number.isSafeInteger(start)) headers.set("content-range", `bytes ${start}-${start + declared - 1}/*`);
  }
  headers.set("access-control-expose-headers", "content-length, content-range, content-disposition");

  if (request.method === "HEAD") {
    await response.body?.cancel();
    return new Response(null, { status: response.status, headers });
  }
  return new Response(limitedStream(response.body, MAX_MEDIA_BYTES), { status: response.status, headers });
}
