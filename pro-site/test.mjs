import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

test("builds the browser-first Pro site", async () => {
  const [html, routes] = await Promise.all([
    readFile("dist/client/index.html", "utf8"),
    readFile("dist/client/_routes.json", "utf8"),
  ]);
  assert.match(html, /Media Downloader Pro/);
  assert.match(html, /Enhance it on your device/);
  assert.doesNotMatch(html, /Media Downloader Lite|Downloader Lite/);
  assert.deepEqual(JSON.parse(routes).include, ["/*"]);
  await Promise.all([
    access("dist/client/og.png"),
    access("dist/server/index.js"),
    access("dist/server/functions/api/resolve.js"),
  ]);
});
