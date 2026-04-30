# Video Enhancer

Free, local, offline video enhancement powered by FFmpeg.

`video-enhancer` is a small Python CLI that turns one video into a sharper,
smoother export. It can upscale resolution, denoise lightly, sharpen, and
synthesize in-between frames for high-FPS output. Everything runs on your own
machine; no cloud upload, no account, no subscription.

> Honest GPU note: this project supports optional FFmpeg hardware **encoding**
> with NVIDIA NVENC, AMD AMF, and Intel Quick Sync. The heavy enhancement
> filters, especially `minterpolate` and `nlmeans`, are still CPU-heavy FFmpeg
> filters in this first version.

## Features

- Local/offline video enhancement
- 2x upscaling with Lanczos or Bicubic scaling
- Frame interpolation to 48, 60, 90, 144 FPS, or any positive FPS value
- Optional denoise and sharpening in the `ultra` preset
- CPU encoders: `libx264`, `libx265`
- Hardware encoder options: `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`,
  `h264_amf`, `hevc_amf`, `av1_amf`, `h264_qsv`, `hevc_qsv`, `av1_qsv`
- Dry-run mode that prints the exact FFmpeg command before running it
- Test-covered command construction

## Requirements

- Python 3.10+
- FFmpeg available in `PATH`, or passed with `--ffmpeg`

Install FFmpeg:

```bash
# Windows
winget install Gyan.FFmpeg

# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

Check FFmpeg:

```bash
ffmpeg -version
```

## Install

From the project folder:

```bash
python -m venv .venv
python -m pip install -U pip
python -m pip install -e .
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Quick Start

Balanced default:

```bash
video-enhancer input.mp4 output.mp4
```

High quality:

```bash
video-enhancer input.mp4 output-quality.mp4 --preset quality
```

Maximum FFmpeg-only enhancement:

```bash
video-enhancer input.mp4 output-ultra.mp4 --preset ultra
```

144 FPS experiment:

```bash
video-enhancer input.mp4 output-144.mp4 --preset ultra --fps 144
```

Preview the command without writing a video:

```bash
video-enhancer input.mp4 output.mp4 --preset ultra --dry-run
```

## Presets

| Preset | Output intent | Notes |
| --- | --- | --- |
| `fast` | quick test export | 2x Bicubic, 48 FPS, faster encode |
| `balanced` | general default | 2x Lanczos, 60 FPS |
| `quality` | slower, cleaner FFmpeg output | 2x Lanczos, 60 FPS, stronger interpolation |
| `ultra` | maximum FFmpeg-only pipeline | light denoise, 90 FPS, 2x Lanczos, sharpening, CRF 16 |

Override FPS and scale:

```bash
video-enhancer input.mp4 output-2x144.mp4 --preset ultra --fps 144 --scale-factor 2
```

Disable one part of the pipeline:

```bash
video-enhancer input.mp4 output-60fps.mp4 --fps 60 --no-upscale
video-enhancer input.mp4 output-2x.mp4 --scale-factor 2 --no-interpolate
```

## Hardware Encoding

Hardware encoding can make the final encode stage faster on supported GPUs and
FFmpeg builds.

List available codec names supported by the CLI:

```bash
video-enhancer --list-encoders
```

NVIDIA:

```bash
video-enhancer input.mp4 output-nvenc.mp4 --preset ultra --video-codec h264_nvenc --encoder-preset p6 --quality 18
```

AMD:

```bash
video-enhancer input.mp4 output-amf.mp4 --preset ultra --video-codec h264_amf --encoder-preset quality --quality 18
```

Intel Quick Sync:

```bash
video-enhancer input.mp4 output-qsv.mp4 --preset ultra --video-codec h264_qsv --encoder-preset slow --quality 18
```

Quality values use FFmpeg-style `0-51` scales where lower is generally higher
quality. The mapping depends on encoder family:

- CPU: `-crf`
- NVIDIA NVENC: `-cq:v`
- AMD AMF: `-qvbr_quality_level`
- Intel QSV: `-global_quality`

## Limitations

- Upscaling cannot recover true detail that was never in the source.
- Frame interpolation may create artifacts around fast motion, hard cuts, text,
  hands, wheels, water, flashing lights, or motion blur.
- 90/144 FPS exports can be much slower than real time.
- Hardware encoders accelerate encoding, not every filter in this project.
- For true AI super-resolution and AI frame interpolation, future backends such
  as Real-ESRGAN and RIFE are better candidates.

## Development

Install test dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run tests:

```bash
python -m pytest
```

## Documentation

- [Usage notes](docs/usage-and-requirements.md)
- [Command examples](examples/commands.md)
- [Future AI backends](docs/future-ai-backends.md)

## License

MIT. See [LICENSE](LICENSE).
