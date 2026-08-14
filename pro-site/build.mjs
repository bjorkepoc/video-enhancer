import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await Promise.all([
  mkdir("dist/server", { recursive: true }),
  mkdir("dist/.openai", { recursive: true }),
]);
await Promise.all([
  cp("../public-site", "dist/client", { recursive: true }),
  cp("../functions", "dist/server/functions", { recursive: true }),
  cp("../site-worker.js", "dist/server/base-worker.js"),
  cp("worker.js", "dist/server/index.js"),
  cp(".openai/hosting.json", "dist/.openai/hosting.json"),
]);

let html = await readFile("dist/client/index.html", "utf8");
for (const [from, to] of [
  ["Media Downloader Lite", "Media Downloader Pro"],
  ["Downloader Lite", "Downloader Pro"],
  ["Paste an image or video link. Keep the files.", "Download public media. Enhance it on your device."],
  [
    "Media Downloader Pro previews original public media from Instagram, TikTok, and Facebook, with optional enhancement performed locally in your browser.",
    "Media Downloader Pro downloads original public media and enhances video locally in your browser.",
  ],
  ["Preview original public media and enhance video locally on your own device.", "Download original public media and enhance video locally on your own device."],
]) {
  if (!html.includes(from)) throw new Error(`Missing source copy: ${from}`);
  html = html.replaceAll(from, to);
}

await Promise.all([
  writeFile("dist/server/app-html.js", `export const HTML = ${JSON.stringify(html)};\n`),
  rm("dist/client/index.html"),
  writeFile("dist/client/_routes.json", `${JSON.stringify({ version: 1, include: ["/", "/index.html", "/api/*"], exclude: [] }, null, 2)}\n`),
  cp("og.png", "dist/client/og.png"),
]);
