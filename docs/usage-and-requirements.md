# Usage and Requirements

`video-enhancer` wraps FFmpeg scaling, optional interpolation, and CPU encoding.

## Workflow

1. Pick a source video.
2. Choose a preset, or override `--scale-factor` and `--fps`.
3. Dry-run if you want to inspect the FFmpeg command.
4. Run `video-enhancer input output`.
5. Keep the original file untouched and compare the export visually.

## FFmpeg

FFmpeg must be available on `PATH`, or passed directly:

```bash
video-enhancer input.mp4 output.mp4 --ffmpeg /opt/homebrew/bin/ffmpeg
```

Check your install:

```bash
ffmpeg -version
```

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
