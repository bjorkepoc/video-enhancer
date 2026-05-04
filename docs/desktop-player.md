# Desktop Player

`Video Enhancer Player` is the native Windows GUI for this project. It lives in
`desktop/VideoEnhancer.Player` and uses the C# core library in
`desktop/VideoEnhancer.Core`.

## Capabilities

- Local UHD video playback through WinUI `MediaPlayerElement`
- Play, pause, seek, frame forward, and frame-back seek fallback
- Step-viewing at 1, 2, 5, or 10 frames per second
- Local library with FFmpeg metadata and thumbnails
- GUI access to the same enhancement choices as the CLI
- FFmpeg dry-run preview, progress, cancel, and export history
- Settings stored in `%LOCALAPPDATA%\VideoEnhancerPlayer`

## Build

Windows with the .NET SDK, Windows App SDK, and FFmpeg:

```powershell
dotnet build desktop\VideoEnhancer.Player\VideoEnhancer.Player.csproj -p:Platform=ARM64
```

For x64:

```powershell
dotnet build desktop\VideoEnhancer.Player\VideoEnhancer.Player.csproj -p:Platform=x64
```

## Test

```powershell
dotnet test desktop\VideoEnhancer.Core.Tests\VideoEnhancer.Core.Tests.csproj
python -m pytest -p no:cacheprovider
```

## Notes

- The app is unpackaged, so it can be launched directly from its build output.
- FFmpeg and ffprobe are found from `PATH`, a configured setting, or the Gyan
  FFmpeg WinGet package location.
- GPU filters and hardware encoders depend on the local FFmpeg build and GPU
  driver. Frame interpolation with `minterpolate` remains CPU-based.
