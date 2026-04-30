# Future AI Backends

`video-enhancer` starts as a simple FFmpeg-based local tool, but the project can
support optional AI backends later without changing the main workflow too much.

The goal is to keep the current FFmpeg path free, offline, and dependable while
making heavier AI processing opt-in.

## Real-ESRGAN for Upscaling

Real-ESRGAN is a candidate for super-resolution because it can reconstruct more
natural detail than traditional scaling filters.

A practical pipeline:

1. Decode video to frames with FFmpeg.
2. Process frame batches with Real-ESRGAN.
3. Store output frames in a resumable cache with stable filenames.
4. Encode frames back to video and copy the original audio where possible.

Important choices:

- Model variant for photos, anime, or general video.
- Scale factor, commonly 2x or 4x.
- GPU memory, batch size, and tile size.
- Resume support for interrupted jobs.

## RIFE for Frame Interpolation

RIFE is a candidate for AI frame interpolation because it generates intermediate
frames with more motion understanding than classic FFmpeg interpolation.

A practical pipeline:

1. Decode video to frames.
2. Run RIFE between neighboring frames for the target FPS.
3. Keep timestamps consistent.
4. Encode the result and copy audio where possible.

Important choices:

- Target FPS, such as 50, 60, or 120.
- Scene-cut handling where interpolation should often be disabled.
- Constant versus variable frame-rate output.
- Artifact detection and fallback to original frames.

## Suggested Backend Contract

| Backend | Responsibility |
| --- | --- |
| `ffmpeg` | Scaling, denoise, sharpening, interpolation, and encoding without AI. |
| `realesrgan` | Super-resolution over decoded frames. |
| `rife` | AI frame interpolation. |
| `hybrid` | Real-ESRGAN plus RIFE plus FFmpeg encoding. |

Possible future commands:

```bash
video-enhancer input.mp4 output.mp4 --backend ffmpeg --preset balanced
video-enhancer input.mp4 output.mp4 --backend realesrgan --scale-factor 2
video-enhancer input.mp4 output.mp4 --backend rife --fps 60 --no-upscale
video-enhancer input.mp4 output.mp4 --backend hybrid --scale-factor 2 --fps 60
```

## Risks and Boundaries

- AI backends often require large model downloads and a capable GPU.
- CPU fallback can be extremely slow.
- Models can hallucinate plausible details that were not present in the source.
- Faces, text, patterns, and compression noise can produce visible artifacts.
- Model and weight licenses must be checked before distribution.

AI support should stay optional, clearly labeled, and easy to disable.
