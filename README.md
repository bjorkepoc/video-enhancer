# Video Enhancer

Local FFmpeg video enhancement with a Python CLI and a small browser UI.

It can upscale, lightly denoise/sharpen with the `ultra` preset, and generate
higher-FPS output with FFmpeg `minterpolate`. Everything runs on your machine;
there is no cloud upload.

## Features

- Local/offline processing
- 2x Lanczos or Bicubic upscaling
- Frame interpolation to 48, 60, 90, 144 FPS, or any positive FPS value
- CPU encoders: `libx264`, `libx265`
- Dry-run mode that prints the exact FFmpeg command
- Local web UI for choosing, previewing, exporting, and downloading videos

## Requirements

- Python 3.10+
- FFmpeg in `PATH`, or passed with `--ffmpeg`

On macOS:

```bash
brew install ffmpeg
```

## Install

```bash
python -m venv .venv
python -m pip install -U pip
python -m pip install -e .
```

## Web UI

```bash
video-enhancer-web --open
```

The server binds to `127.0.0.1`, previews input/output in the browser, and
writes exports under `outputs/web/`.

## CLI

Balanced default:

```bash
video-enhancer input.mp4 output.mp4
```

High quality:

```bash
video-enhancer input.mp4 output-quality.mp4 --preset quality
```

Maximum FFmpeg-only preset:

```bash
video-enhancer input.mp4 output-ultra.mp4 --preset ultra
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

List codecs:

```bash
video-enhancer --list-encoders
```

## Limits

- Upscaling cannot recover detail that was never in the source.
- `minterpolate` can create artifacts around fast motion, hard cuts, text,
  hands, flashing lights, water, and motion blur.
- 90/144 FPS exports can be much slower than real time.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

More CLI detail: [docs/usage-and-requirements.md](docs/usage-and-requirements.md).

## License

MIT. See [LICENSE](LICENSE).
