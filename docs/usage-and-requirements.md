# Usage and Requirements

`video-enhancer` combines source-first TikTok/Instagram downloading with FFmpeg
scaling, optional interpolation, and CPU encoding.

## Workflow

For a social link:

1. Paste an HTTPS TikTok or Instagram post URL.
2. Optionally select Chrome, Safari, or Firefox when anonymous access fails.
3. Inspect and select `Best available` or one listed source variant.
4. Download the original, then optionally make a 60 FPS, 90 FPS, or 2x copy.
5. Compare the verified saved metadata and preview the separate files.

For a local file, choose `Local file` in the web app or use the CLI below.

## FFmpeg

FFmpeg must be available on `PATH`, or passed directly:

```bash
video-enhancer input.mp4 output.mp4 --ffmpeg /opt/homebrew/bin/ffmpeg
```

Check your install:

```bash
ffmpeg -version
```

## Social Sources

Only HTTPS hosts at `tiktok.com` and `instagram.com`, including their
subdomains, are accepted. Inspection uses yt-dlp structured metadata and never
returns signed CDN URLs or browser cookies through the HTTP API. Duplicate
formats with the same dimensions, FPS, bitrate, codecs, and container are shown
as mirrors rather than separate quality levels.

`Best available` uses yt-dlp's source-first `bv*+ba/b` selection. Choosing a
specific variant triggers a fresh inspection before download. The file is
written with a restricted filename and probed after saving to report actual
resolution, FPS, codecs, duration, bitrate, and size.

An `Original platform stream` has not passed through a video encoder. A
`Remuxed without video re-encoding` result only combines separate source
streams. Any 60/90 FPS or 2x result is an `Enhanced synthetic copy`; it cannot
be treated as native platform quality.

Browser sessions are opt-in per inspect/download/compare request. yt-dlp reads
the selected local browser's cookies directly. The app does not copy, persist,
or include those cookies in responses.

## Alternative Sources

After inspection, the app creates exact metadata searches for the open web,
TikTok, and Instagram. After download, it extracts three local JPEG keyframes
for manual Google Lens or TinEye use. It does not upload those images.

You can submit another TikTok or Instagram URL as a candidate. The app
downloads a temporary low-resolution comparison copy, samples five grayscale
frames locally, compares 256-bit difference hashes, and removes the candidate
file. The result is advisory: crops, captions, overlays, reordered scenes, and
re-encoding can produce false or uncertain results.

## CLI

```bash
video-enhancer input.mp4 output.mp4 [options]
```

| Option | Meaning |
| --- | --- |
| `--preset fast|balanced|quality|ultra` | Select speed and quality tuning. |
| `--scale-factor 2` | Override the upscale factor. |
| `--fps 60` | Override the interpolation target FPS. |
| `--no-upscale` | Guard scaling so output is never larger than input dimensions. |
| `--no-interpolate` | Disable generated intermediate frames. |
| `--video-codec libx264|libx265` | Select the CPU video encoder. |
| `--encoder-preset PRESET` | Override the encoder preset. |
| `--quality VALUE` | Set CRF `0-51`; lower is generally higher quality. |
| `--list-encoders` | Show supported codec names. |
| `--overwrite` | Replace an existing output file. |
| `--dry-run` | Print the FFmpeg command without running it. |
| `--ffmpeg PATH` | Use a specific FFmpeg binary. |

## Presets

| Preset | When to use it | Notes |
| --- | --- | --- |
| `fast` | Quick previews and slower machines | 2x bicubic scaling, 48 FPS blend interpolation, faster x264 encode. |
| `balanced` | Normal use | 2x Lanczos scaling, 60 FPS motion interpolation, medium x264 encode. |
| `quality` | Better output with slower processing | 2x Lanczos scaling, stronger 60 FPS interpolation, slow x264 encode. |
| `ultra` | Best FFmpeg-only output | Mild denoise, 90 FPS interpolation, 2x Lanczos scaling, sharpening, low-CRF encode. |

Default encoder tuning:

| Preset | x264 preset | CRF |
| --- | --- | --- |
| `fast` | `veryfast` | `23` |
| `balanced` | `medium` | `20` |
| `quality` | `slow` | `18` |
| `ultra` | `slow` | `16` |

## Quality Risks

Test short clips before committing to long videos. Interpolation works best on
smooth motion and can struggle with scene cuts, subtitles, blinking lights,
heavy compression artifacts, and motion blur. The `ultra` preset can be slow,
especially for high-resolution input.

The source platform may expose only a compressed, low-resolution, or 30 FPS
variant. Upscaling cannot restore discarded detail, and interpolation generates
new frames rather than revealing a hidden higher-FPS original.
