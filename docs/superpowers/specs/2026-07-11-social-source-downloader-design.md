# Social Source Downloader Design

## Goal

Turn the existing local Mac web UI into one source-first workflow for TikTok and
Instagram: inspect every platform-provided variant, download the best untouched
stream, verify the saved media, and optionally create clearly labelled enhanced
copies.

## Product Contract

- `Original` downloads the best stream exposed to the current anonymous or
  explicitly selected browser session. It never applies a video filter or
  re-encodes the media.
- `Smooth 60 FPS`, `Smooth 90 FPS`, and `Upscaled` are separate derived files.
  The UI must never describe generated frames or pixels as original detail.
- Full HD and high FPS are not guaranteed. The result is limited by what the
  platform exposes for that post and session.
- Only HTTPS TikTok and Instagram video URLs are accepted.
- The user is responsible for downloading only media they own or may use.

## Architecture

`video-enhancer` is the canonical implementation. A focused `sources.py` module
owns social URL validation, yt-dlp inspection/download commands, format
normalisation, saved-file probing, keyframe extraction, and candidate
comparison. `web.py` exposes that module through the existing stdlib HTTP server
and sends downloaded files into the existing FFmpeg enhancement job path.

The old `/Users/po/dev/lossless-social-video` project remains an alternative
launcher, but does not retain a second downloader implementation. Its
`npm start` command starts the canonical Python web app on port 3100.

## Source Inspection

Inspection uses the installed `yt-dlp` executable and structured JSON output.
The dependency is installed with the Python package. The backend:

1. validates the URL host before starting a subprocess;
2. optionally passes one explicitly selected browser session (`chrome`,
   `safari`, or `firefox`) with `--cookies-from-browser`;
3. requests all metadata without downloading;
4. groups duplicate CDN mirrors by resolution, FPS, bitrate, codecs, and
   container;
5. returns format IDs and quality metadata, never signed source URLs or cookies.

Automatic selection uses yt-dlp's source-first `bv*+ba/b` selector. A user may
select another inspected format; the backend re-inspects the URL and rejects a
format ID that is no longer present.

## Download And Verification

Downloads are written below `outputs/web/<source-id>/` with restricted
filenames. Existing files are not overwritten. Failed partial files are
removed. The API returns only files inside the configured work directory.

The backend probes the saved file with `ffprobe` JSON when available. If this
Mac only has `ffmpeg`, it parses the first video stream from FFmpeg's own probe
output and labels fields that remain unknown. The result displays actual saved
resolution, FPS, video/audio codecs, duration, bitrate, size, selected format,
and whether the operation was direct, remuxed, or enhanced.

## Web Workflow

The first panel uses a segmented `Link` / `Local file` input control.

For a link, the flow is:

1. Paste TikTok or Instagram URL.
2. Optionally choose a browser session.
3. Inspect available source variants.
4. Choose `Best available` or a specific inspected variant.
5. Run `Download original`, `Original + 60 FPS`, `Original + 90 FPS`, or
   `Original + upscale`.
6. Preview and download both the untouched source and any derived copy.

The existing local-file enhancement flow remains available. Downloaded media is
passed to the existing job builder by filesystem path; it is not uploaded back
through the browser.

## Alternative And Repost Discovery

The app offers every practical discovery route without claiming certainty:

- all platform-provided CDN/codec/bitrate variants from yt-dlp;
- exact metadata search links built from post ID, title, and uploader;
- three local FFmpeg keyframes suitable for manual Google Lens or TinEye search;
- a candidate URL field that inspects another TikTok/Instagram link and compares
  sampled grayscale frame hashes locally.

Candidate comparison is advisory. It reports likely match, uncertain, or
different and shows duration/resolution differences. Cropping, overlays,
re-editing, and reordered clips can defeat the heuristic.

There is no zero-key, official cross-platform reverse-video API. The app does
not scrape Google, TikTok, Instagram, or Bing result pages. Google Lens remains
a user-initiated image upload. TinEye automation requires paid credentials and
is deferred until credentials exist; Bing Search APIs were retired in 2025.

## Safety And Failure Handling

- URL allowlisting prevents arbitrary downloader/SSRF targets.
- Browser cookies are used only for the selected request and are never returned,
  copied, or persisted by the app.
- Request bodies, subprocess output, download duration, and filenames are
  bounded.
- Signed CDN URLs are kept server-side because they expire and often require
  extractor headers.
- Instagram login/rate-limit and TikTok anti-bot failures return actionable
  messages that suggest an explicit browser session.
- Source and enhancement jobs have separate status/error states, so a failed
  derived copy never removes a successful original.

## Testing

- Unit tests cover URL validation, browser selection, format grouping, command
  construction, path containment, FFmpeg/ffprobe parsing, and candidate hashes.
- HTTP tests cover inspect, original download, source-file serving, and starting
  enhancement from a downloaded source with subprocesses mocked.
- Live smoke tests inspect and download the provided TikTok URL and inspect a
  public Instagram Reel anonymously.
- Browser QA covers Link and Local file flows at desktop and mobile widths,
  including an invalid URL and one successful source inspection.
- The complete existing Python test suite and `git diff --check` must pass.

## Success Criteria

- The provided TikTok link selects and saves its 1080x1920 HEVC source without
  video re-encoding and reports the saved 30 FPS stream.
- A public Instagram Reel exposes and downloads its highest available variant.
- Selecting 60 or 90 FPS produces a separate, explicitly synthetic result.
- Duplicate TikTok CDN links are shown as mirrors, not higher-quality choices.
- The old `npm start` entrypoint opens the same canonical app on port 3100.
- No raw signed media URL, browser cookie, or file outside the work directory is
  exposed through the API.
