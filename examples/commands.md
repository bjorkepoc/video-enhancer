# Command Examples

These examples use neutral placeholder videos only.

## Inspect Available Encoders

```bash
video-enhancer --list-encoders
```

## Balanced Default

```bash
video-enhancer samples/source.mp4 exports/source-balanced.mp4
```

## Fast Preview

```bash
video-enhancer samples/source.mp4 exports/source-fast.mp4 --preset fast
```

## High Quality CPU Export

```bash
video-enhancer samples/source.mp4 exports/source-quality.mp4 --preset quality
```

## Ultra 90 FPS

```bash
video-enhancer samples/source.mp4 exports/source-ultra-90.mp4 --preset ultra
```

## Ultra 144 FPS

```bash
video-enhancer samples/source.mp4 exports/source-ultra-144.mp4 --preset ultra --fps 144
```

## NVIDIA Hardware Encoding

```bash
video-enhancer samples/source.mp4 exports/source-nvenc.mp4 --preset ultra --video-codec h264_nvenc --encoder-preset p6 --quality 18
```

## AMD Hardware Encoding

```bash
video-enhancer samples/source.mp4 exports/source-amf.mp4 --preset ultra --video-codec h264_amf --encoder-preset quality --quality 18
```

## Intel Quick Sync Hardware Encoding

```bash
video-enhancer samples/source.mp4 exports/source-qsv.mp4 --preset ultra --video-codec h264_qsv --encoder-preset slow --quality 18
```

## Frame Interpolation Only

```bash
video-enhancer samples/source.mp4 exports/source-60fps.mp4 --fps 60 --no-upscale
```

## Upscale Only

```bash
video-enhancer samples/source.mp4 exports/source-2x.mp4 --scale-factor 2 --no-interpolate
```
