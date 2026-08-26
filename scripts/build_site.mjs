import { cp, mkdir, rm } from "node:fs/promises";

await Promise.all([
  rm("dist/client", { recursive: true, force: true }),
  rm("dist/server", { recursive: true, force: true }),
  rm("dist/.openai", { recursive: true, force: true }),
]);
await Promise.all([
  mkdir("dist/server", { recursive: true }),
  mkdir("dist/.openai", { recursive: true }),
]);
await Promise.all([
  cp("public-site", "dist/client", { recursive: true }),
  cp("functions", "dist/server/functions", { recursive: true }),
  cp("site-worker.js", "dist/server/index.js"),
  cp(".openai/hosting.json", "dist/.openai/hosting.json"),
]);
