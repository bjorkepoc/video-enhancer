import { anonymousRateKey, checkRateLimit, json, proxyMedia, requestOriginIsAllowed } from "../_shared.js";

export async function onRequest({ request }) {
  if (!new Set(["GET", "HEAD"]).has(request.method)) return json({ error: "Use GET or HEAD for this endpoint." }, 405, { allow: "GET, HEAD" });
  if (!requestOriginIsAllowed(request)) return json({ error: "Cross-origin requests are not accepted." }, 403);
  if (!checkRateLimit(await anonymousRateKey(request, "media"), Date.now(), 120)) return json({ error: "Too many media requests. Wait a minute and try again." }, 429, { "retry-after": "60" });

  try {
    return await proxyMedia(request);
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : "The media could not be streamed." }, 400);
  }
}
