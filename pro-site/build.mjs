import { cp, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";

const next = "dist.next";
const previous = "dist.previous";
await Promise.all([
  rm(next, { recursive: true, force: true }),
  rm(previous, { recursive: true, force: true }),
]);

try {
  await Promise.all([
    mkdir(`${next}/server`, { recursive: true }),
    mkdir(`${next}/.openai`, { recursive: true }),
  ]);
  await Promise.all([
    cp("../public-site", `${next}/client`, { recursive: true }),
    cp("../functions", `${next}/server/functions`, { recursive: true }),
    cp("../site-worker.js", `${next}/server/index.js`),
    cp(".openai/hosting.json", `${next}/.openai/hosting.json`),
  ]);

  let html = await readFile(`${next}/client/index.html`, "utf8");
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
  html = html.replaceAll("__SITE_ORIGIN__", "https://media-downloader-pro.bjorke-poc.chatgpt.site");

  await Promise.all([
    writeFile(`${next}/client/index.html`, html),
    cp("og.png", `${next}/client/og.png`),
  ]);

  let movedPrevious = false;
  try {
    await rename("dist", previous);
    movedPrevious = true;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  try {
    await rename(next, "dist");
  } catch (error) {
    if (movedPrevious) await rename(previous, "dist");
    throw error;
  }
  await rm(previous, { recursive: true, force: true });
} catch (error) {
  await rm(next, { recursive: true, force: true });
  throw error;
}
