import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import test from "node:test";

const run = promisify(execFile);

test("builds the browser-first Pro site", async () => {
  const [html, routes] = await Promise.all([
    readFile("dist/client/index.html", "utf8"),
    readFile("dist/client/_routes.json", "utf8"),
  ]);
  assert.match(html, /Media Downloader Pro/);
  assert.match(html, /Enhance it on your device/);
  assert.doesNotMatch(html, /Media Downloader Lite|Downloader Lite/);
  assert.match(html, /https:\/\/media-downloader-pro\.bjorke-poc\.chatgpt\.site/);
  assert.doesNotMatch(html, /__SITE_ORIGIN__/);
  assert.deepEqual(JSON.parse(routes).include, ["/api/*"]);
  await Promise.all([
    access("dist/client/og.png"),
    access("dist/server/index.js"),
    access("dist/server/functions/api/resolve.js"),
  ]);
});

test("failed builds preserve the previous dist", async () => {
  const root = await mkdtemp(join(tmpdir(), "media-downloader-pro-build-"));
  const project = join(root, "pro-site");
  try {
    await mkdir(join(project, ".openai"), { recursive: true });
    await Promise.all([
      cp(new URL("./build.mjs", import.meta.url), join(project, "build.mjs")),
      cp(new URL("../public-site", import.meta.url), join(root, "public-site"), { recursive: true }),
      cp(new URL("../functions", import.meta.url), join(root, "functions"), { recursive: true }),
      cp(new URL("../site-worker.js", import.meta.url), join(root, "site-worker.js")),
      cp(new URL("./.openai/hosting.json", import.meta.url), join(project, ".openai/hosting.json")),
      cp(new URL("./og.png", import.meta.url), join(project, "og.png")),
    ]);
    const htmlPath = join(root, "public-site/index.html");
    const html = await readFile(htmlPath, "utf8");
    await writeFile(htmlPath, html.replaceAll("Media Downloader Lite", "Broken source copy"));
    await mkdir(join(project, "dist"));
    await writeFile(join(project, "dist/sentinel.txt"), "previous build");

    await assert.rejects(run(process.execPath, ["build.mjs"], { cwd: project }));
    assert.equal(await readFile(join(project, "dist/sentinel.txt"), "utf8"), "previous build");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
