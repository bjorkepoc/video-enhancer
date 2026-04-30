# Usage and Requirements

This page documents the FFmpeg-only release of `video-enhancer`.

## Workflow

1. Pick a source video.
2. Choose a preset, or override `--scale-factor` and `--fps`.
3. Dry-run if you want to inspect the FFmpeg command.
4. Run `video-enhancer input output`.
5. Keep the original file untouched and compare the new export visually.

The tool builds an FFmpeg command around `scale` and, unless disabled,
`minterpolate`. The `ultra` preset adds mild `nlmeans` denoise before
interpolation, runs interpolation before scaling, and applies `unsharp` after
scaling.

## FFmpeg

FFmpeg must be available on `PATH`, or you can pass a specific executable:

```powershell
video-enhancer input.mp4 output.mp4 --ffmpeg C:\tools\ffmpeg\bin\ffmpeg.exe
```

Check your installation:

```powershell
ffmpeg -version
Get-Command ffmpeg
```

For hardware encoding, your FFmpeg build and GPU driver must support the chosen
encoder, such as `h264_nvenc`, `hevc_nvenc`, `h264_amf`, `hevc_amf`,
`h264_qsv`, or `hevc_qsv`.

## CLI

```powershell
video-enhancer input.mp4 output.mp4 [options]
```

| Option | Meaning |
| --- | --- |
| `--preset fast|balanced|quality|ultra` | Select speed and quality tuning. |
| `--scale-factor 2` | Override the upscale factor. |
| `--fps 60` | Override the interpolation target FPS. |
| `--no-upscale` | Guard scaling so output is never larger than input dimensions. |
| `--no-interpolate` | Disable generated intermediate frames. |
| `--video-codec CODEC` | Select a CPU or hardware FFmpeg video encoder. |
| `--encoder-preset PRESET` | Override the encoder-specific preset. |
| `--quality VALUE` | Set quality value `0-51`; lower is generally higher quality. |
| `--list-encoders` | Show codec names supported by this CLI. |
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

## Encoder Quality

Default CPU encoder tuning:

| Preset | x264 preset | CRF |
| --- | --- | --- |
| `fast` | `veryfast` | `23` |
| `balanced` | `medium` | `20` |
| `quality` | `slow` | `18` |
| `ultra` | `slow` | `16` |

Hardware encoder examples:

```powershell
video-enhancer input.mp4 output.mp4 --preset ultra --video-codec h264_nvenc --encoder-preset p6 --quality 18
video-enhancer input.mp4 output.mp4 --preset ultra --video-codec h264_amf --encoder-preset quality --quality 18
video-enhancer input.mp4 output.mp4 --preset ultra --video-codec h264_qsv --encoder-preset slow --quality 18
```

These flags are for encoding only. They do not mean the full filter chain is
GPU-accelerated.

## Quality Risks

Test short clips before committing to long videos. Interpolation works best on
smooth motion and can struggle with scene cuts, subtitles, blinking lights,
heavy compression artifacts, and motion blur. The `ultra` preset can be very
slow, especially for high-resolution input.
