import {
  TERMS_VERSION,
  UserFacingError,
  anonymousRateKey,
  checkRateLimit,
  json,
  readJSONBody,
  requestOriginIsAllowed,
  resolveSource,
} from "../_shared.js";

export async function onRequestPost({ request }) {
  if (!requestOriginIsAllowed(request)) return json({ error: "Cross-origin requests are not accepted." }, 403);
  if (!checkRateLimit(await anonymousRateKey(request, "resolve"))) return json({ error: "Too many requests. Wait a minute and try again." }, 429, { "retry-after": "60" });

  try {
    const body = await readJSONBody(request);
    if (body.termsAccepted !== true || body.termsVersion !== TERMS_VERSION) return json({ error: "Accept the current Terms of Use before resolving media." }, 400);
    return json(await resolveSource(body.url));
  } catch (error) {
    return json({ error: error instanceof UserFacingError ? error.message : "The source could not be resolved." }, 400);
  }
}

export function onRequest() {
  return json({ error: "Use POST for this endpoint." }, 405, { allow: "POST" });
}
