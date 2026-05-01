# Video Enhancer

Free, local, offline video enhancement powered by FFmpeg.

`video-enhancer` is a small Python CLI that turns one video into a sharper,
smoother export. It can upscale resolution, denoise lightly, sharpen, and
synthesize in-between frames for high-FPS output. Everything runs on your own
machine; no cloud upload, no account, no subscription.

> Honest GPU note: this project supports optional GPU **filter backends** for
> parts of the enhancement pipeline and optional GPU **hardware encoding** for
> the final export. FFmpeg motion interpolation with `minterpolate` still runs
> on CPU; true GPU/AI interpolation belongs in a future RIFE-style backend.

## Features

- Local/offline video enhancement
- 2x upscaling with Lanczos or Bicubic scaling
- Frame interpolation to 48, 60, 90, 144 FPS, or any positive FPS value
- Optional denoise and sharpening in the `ultra` preset
- GPU filter backends: `cuda`, `opencl`, `vulkan`, plus `auto`
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

Use GPU enhancement filters when your FFmpeg build and drivers support them:

```bash
video-enhancer input.mp4 output-gpu.mp4 --preset ultra --gpu
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

## GPU Filters and Hardware Encoding

There are two separate GPU features:

- `--filter-backend` controls enhancement filters such as denoise, upscale, and
  sharpening.
- `--video-codec` controls the final video encoder.

Inspect local FFmpeg filter support:

```bash
video-enhancer --list-filter-backends
```

This performs a tiny runtime probe. A backend can be compiled into FFmpeg but
still fail if the GPU driver or runtime is missing.

GPU filter examples:

```bash
# Pick an available GPU filter backend automatically.
video-enhancer input.mp4 output-gpu.mp4 --preset ultra --gpu

# Cross-vendor GPU denoise/upscale via Vulkan/libplacebo.
video-enhancer input.mp4 output-vulkan.mp4 --preset ultra --filter-backend vulkan

# NVIDIA CUDA denoise/upscale.
video-enhancer input.mp4 output-cuda.mp4 --preset ultra --filter-backend cuda

# OpenCL denoise/sharpen.
video-enhancer input.mp4 output-opencl.mp4 --preset ultra --filter-backend opencl
```

If you have multiple GPU devices, pass a selector:

```bash
video-enhancer input.mp4 output-gpu1.mp4 --preset ultra --filter-backend vulkan --filter-device 1
```

OpenCL device names can be platform/device pairs such as `0.0`:

```bash
video-enhancer input.mp4 output-opencl.mp4 --preset ultra --filter-backend opencl --filter-device 0.0
```

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

NVIDIA GPU filters plus NVIDIA hardware encoding:

```bash
video-enhancer input.mp4 output-nvidia.mp4 --preset ultra --filter-backend cuda --video-codec h264_nvenc --encoder-preset p6 --quality 18
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
- `minterpolate` frame interpolation remains CPU-based in the FFmpeg backend.
- GPU filter backends accelerate only the stages they support; unsupported
  stages stay on CPU.
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
- [GitHub Codex automation](docs/github-codex-automation.md)

## Maintainer Automation

This repo includes optional Codex-powered GitHub Actions for issue triage and
draft PR creation. Add an `OPENAI_API_KEY` Actions secret to enable them.

- Maintainer-created issues can receive automatic Codex triage.
- Public issues from unknown users are label-gated before Codex runs.
- Maintainers can comment `/codex fix` on an issue to ask Codex to draft a PR.

See [GitHub Codex automation](docs/github-codex-automation.md) for setup and
safety details.

## License

MIT. See [LICENSE](LICENSE).
