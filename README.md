# Video Enhancer

Download the best stream exposed by TikTok or Instagram, verify the saved
media, and optionally create enhanced copies with a local Python/FFmpeg app.

The original download path never filters or video-encodes the source. Upscaling
and generated 60/90 FPS output are always separate files. Everything runs
locally on your computer; the app has no cloud backend.

Release status: `v0.1.0` is an unpublished cross-platform Python beta candidate,
with self-contained macOS packages planned for both Apple Silicon and Intel
Macs. Public distribution remains blocked until Developer ID
signing/notarization, authorized real-source acceptance tests, and verified
operator details are in place.

## Features

- TikTok and Instagram HTTPS links
- Best-available original download with saved-file resolution/FPS verification
- 2x Lanczos or Bicubic upscaling
- Frame interpolation to 48, 60, 90, 144 FPS, or another target up to 240 FPS
- 1 FPS playback, calibrated frame stepping, and 1x-8x focal zoom/pan
- Physical browser downloads with byte-range video playback
- CPU encoders: `libx264`, `libx265`
- Dry-run mode that prints the exact FFmpeg command
- Local web UI for choosing, previewing, exporting, and downloading videos

## Requirements

- Python 3.10+
- FFmpeg in `PATH`; ffprobe is optional and used when available
- The CLI also accepts a custom FFmpeg executable through `--ffmpeg`
- `yt-dlp` (installed automatically with this package)

Install FFmpeg with the package manager for your operating system and verify it
is available with `ffmpeg -version`. For example, on macOS:

```bash
brew install ffmpeg
```

## Install

After the `v0.1.0` beta is published, install the same portable wheel on macOS,
Windows, or Linux in a virtual environment:

```bash
python -m venv .venv
. .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Then install the wheel:

```bash
python -m pip install "https://github.com/bjorkepoc/video-enhancer/releases/download/v0.1.0/video_enhancer-0.1.0-py3-none-any.whl"
```

## Web UI

```bash
video-enhancer-web --open
```

The server binds to `127.0.0.1`, accepts public TikTok or Instagram links,
previews original and derived files in the browser, and keeps working files in
a process-specific temporary directory. Use **Clear local files** to remove
them immediately; normal app shutdown also removes them. Starting a new source
replaces the previous working set, and starting a new enhancement replaces the
previous enhanced copy.

The printed local URL contains a random session key. Open it directly and do
not share it; the key expires when the process stops.

Paste a TikTok or Instagram link to download the best available source. Source
access is anonymous: the app never reads browser cookies or handles platform
login sessions.

The local UI loads no ad-network code, analytics, cookies, pixels, or remote
creative. It includes one static **Advertise here** project notice that opens a
public GitHub contact request. Video Enhancer does not track the impression or
click; GitHub receives the request after the visitor chooses its link. TikTok or
Instagram is contacted only after a link action. See
[the launch/privacy/security checklist](docs/launch-privacy-security.md).

Privacy and copyright contact: `bjorke.poc@gmail.com`. A verified legal
operator name and business address have not yet been published, so this contact
address alone does not clear the public consumer-release gate.

Advertising networks do not belong inside this localhost app. A paid direct
sponsor may later replace the project notice with clearly labelled, bundled
text or licensed artwork and a normal HTTPS link. Any ad-network advertising
must live on a separate public site and pass the platform, publisher-policy,
privacy, and consent gates in that checklist first.

## macOS App Build

The planned `v0.1.0` beta provides two self-contained native `.app` ZIPs: one
for Apple Silicon (`arm64`) and one for Intel (`x86_64`). Each bundles matching
builds of yt-dlp and FFmpeg, so recipients do not need Python, Homebrew, or a
separate FFmpeg install. Choose the ZIP matching the Mac's processor; these are
separate native artifacts rather than one universal binary.

Local ad-hoc build:

```bash
TARGET_ARCH="$(uname -m)" uv run --extra macos scripts/build_macos.sh
```

Developer ID signing and notarization use the same command after the signing
identity and notary credentials are installed. Public distribution requires an
Apple Developer Program account, a Developer ID Application certificate, and
successful Apple notarization; an ad-hoc local build is only for development:

```bash
xcrun notarytool store-credentials video-enhancer-notary --apple-id APPLE_ID --team-id TEAM_ID
CODESIGN_IDENTITY="Developer ID Application: NAME (TEAMID)" \
NOTARY_PROFILE=video-enhancer-notary \
uv run --extra macos scripts/build_macos.sh
```

The output ZIP and SHA-256 file are written to `dist/`. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before distributing it.

Tagged GitHub releases build, sign, notarize, and verify both native Mac
artifacts on matching GitHub-hosted runners. They also require repository
secrets for the Developer ID certificate (`MACOS_CERTIFICATE_BASE64`,
`MACOS_CERTIFICATE_PASSWORD`, and `MACOS_SIGNING_IDENTITY`) and notarization
(`APPLE_ID`, `APPLE_TEAM_ID`, and `APPLE_APP_PASSWORD`). A tag is not published
if signing or notarization fails.

The Python wheel and source archive remain the portable installation path for
other operating systems. On Windows or Linux, install the Python package,
provide FFmpeg in `PATH`, and run the same local web UI; the release workflow
does not currently publish self-contained Windows or Linux desktop bundles.
Source download and FFmpeg processing can still work when the operating
system's browser cannot preview the source video's codec.

Result labels are literal:

- `Original platform stream`: saved directly without video encoding.
- `Remuxed without video re-encoding`: video/audio streams were combined into
  one container without encoding the video.
- `Enhanced synthetic copy`: pixels or frames were generated by FFmpeg.

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

- The app cannot guarantee Full HD, a particular bitrate, or native high FPS.
  It can only save variants exposed anonymously for that post.
- Platform compression cannot be reversed. No downloader can recreate detail
  discarded before the platform served the file.
- Upscaling cannot recover detail that was never in the source.
- `minterpolate` can create artifacts around fast motion, hard cuts, text,
  hands, flashing lights, water, and motion blur.
- 90/144 FPS exports can be much slower than real time.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Pushing a tag that exactly matches the project version, such as `v0.1.0`, runs
tests, lint, and security checks; builds signed and notarized `arm64` and
`x86_64` Mac ZIPs plus the wheel and source archive; and creates the GitHub
release with SHA-256 checksums.

Run `video-enhancer --help` for every CLI option.

## License

MIT. See [LICENSE](LICENSE).
