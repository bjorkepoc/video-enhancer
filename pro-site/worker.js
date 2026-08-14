import worker, { STATIC_HEADERS } from "./base-worker.js";
import { HTML } from "./app-html.js";

export default {
  fetch(request, env, context) {
    const url = new URL(request.url);
    if ((request.method === "GET" || request.method === "HEAD") && (url.pathname === "/" || url.pathname === "/index.html")) {
      const headers = new Headers(STATIC_HEADERS);
      headers.set("cache-control", "no-cache");
      headers.set("content-type", "text/html; charset=utf-8");
      const body = request.method === "HEAD" ? null : HTML.replaceAll("__SITE_ORIGIN__", url.origin);
      return new Response(body, { headers });
    }
    return worker.fetch(request, env, context);
  },
};
