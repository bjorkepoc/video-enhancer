import { json } from "./functions/_shared.js";
import { onRequest as mediaRequest } from "./functions/api/media.js";
import { onRequest as resolveRequest, onRequestPost } from "./functions/api/resolve.js";

const STATIC_HEADERS = {
  "content-security-policy": "default-src 'self'; base-uri 'none'; connect-src 'self' https://cdn.jsdelivr.net https://*.tiktok.com https://*.tiktokcdn.com https://*.tiktokcdn-eu.com https://*.tiktokcdn-us.com https://*.tiktokv.com https://*.byteoversea.com https://*.ibytedtos.com https://*.muscdn.com https://*.bytecdn.cn https://*.cdninstagram.com https://*.fbcdn.net; font-src 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' blob: data: https://*.tiktok.com https://*.tiktokcdn.com https://*.tiktokcdn-eu.com https://*.tiktokcdn-us.com https://*.tiktokv.com https://*.byteoversea.com https://*.ibytedtos.com https://*.muscdn.com https://*.bytecdn.cn https://*.cdninstagram.com https://*.fbcdn.net; media-src 'self' blob: https://*.tiktok.com https://*.tiktokcdn.com https://*.tiktokcdn-eu.com https://*.tiktokcdn-us.com https://*.tiktokv.com https://*.byteoversea.com https://*.ibytedtos.com https://*.muscdn.com https://*.bytecdn.cn https://*.cdninstagram.com https://*.fbcdn.net; object-src 'none'; script-src 'self'; style-src 'self'; worker-src 'self' blob:",
  "cross-origin-opener-policy": "same-origin",
  "cross-origin-resource-policy": "same-origin",
  "permissions-policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
};

async function serveStatic(request, env) {
  let response = await env.ASSETS.fetch(request);
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(STATIC_HEADERS)) headers.set(name, value);

  if (headers.get("content-type")?.includes("text/html")) {
    const body = (await response.text()).replaceAll("__SITE_ORIGIN__", new URL(request.url).origin);
    headers.delete("content-length");
    headers.set("cache-control", "no-cache");
    response = new Response(body, { status: response.status, statusText: response.statusText, headers });
  } else {
    response = new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  }
  return response;
}

export default {
  async fetch(request, env, context) {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/resolve") {
      return request.method === "POST"
        ? onRequestPost({ request, env, context })
        : resolveRequest({ request, env, context });
    }
    if (pathname === "/api/media") return mediaRequest({ request, env, context });
    if (pathname.startsWith("/api/")) return json({ error: "Not found." }, 404);
    return serveStatic(request, env);
  },
};
