#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This build currently targets Apple Silicon macOS only." >&2
  exit 1
fi

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(dirname -- "$script_dir")"
python_bin="$(command -v "${PYTHON_BIN:-python3}")"
yt_dlp_version="2026.07.04"
yt_dlp_sha256="498bd0dae17855c599d371d68ec5bafc439a9d8640e838be25c765a9792f261b"
ffmpeg_sha256="6d175a4743ca50256e89a8cdd731100f9cee33bd79aeea46894d209410dc6617"
vendor_dir="$project_dir/build/vendor"
yt_dlp="$vendor_dir/yt-dlp"
ffmpeg="$vendor_dir/ffmpeg"
dist_dir="$project_dir/dist/macos"
app="$dist_dir/Video Enhancer.app"

"$python_bin" -c "import imageio_ffmpeg, PyInstaller" 2>/dev/null || {
  echo "Install the macOS build extra first: python -m pip install -e '.[macos]'" >&2
  exit 1
}
version="$($python_bin -c 'from importlib.metadata import version; print(version("video-enhancer"))')"
mkdir -p "$vendor_dir" "$project_dir/build/pyinstaller"
ffmpeg_source="$($python_bin -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')"
printf '%s  %s\n' "$ffmpeg_sha256" "$ffmpeg_source" | shasum -a 256 -c -
cp "$ffmpeg_source" "$ffmpeg"
chmod 755 "$ffmpeg"
if [[ ! -f "$yt_dlp" ]] || ! printf '%s  %s\n' "$yt_dlp_sha256" "$yt_dlp" | shasum -a 256 -c - >/dev/null 2>&1; then
  download="$yt_dlp.download"
  curl --fail --location --silent --show-error \
    "https://github.com/yt-dlp/yt-dlp/releases/download/$yt_dlp_version/yt-dlp_macos" \
    --output "$download"
  printf '%s  %s\n' "$yt_dlp_sha256" "$download" | shasum -a 256 -c -
  mv "$download" "$yt_dlp"
fi
chmod 755 "$yt_dlp"

pyinstaller_args=(
  --clean
  --noconfirm
  --onedir
  --windowed
  --target-architecture arm64
  --name "Video Enhancer"
  --icon "$project_dir/assets/VideoEnhancer.icns"
  --osx-bundle-identifier com.bjorkepoc.videoenhancer
  --paths "$project_dir/src"
  --add-binary "$yt_dlp:bin"
  --add-binary "$ffmpeg:bin"
  --add-data "$project_dir/LICENSE:."
  --add-data "$project_dir/THIRD_PARTY_NOTICES.md:."
  --distpath "$dist_dir"
  --workpath "$project_dir/build/pyinstaller"
  --specpath "$project_dir/build/pyinstaller"
)
if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  pyinstaller_args+=(--codesign-identity "$CODESIGN_IDENTITY")
fi
pyinstaller_args+=("$project_dir/src/video_enhancer/macos_app.py")

"$python_bin" -m PyInstaller "${pyinstaller_args[@]}"

plist="$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" "$plist"
if ! /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $version" "$plist" 2>/dev/null; then
  /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $version" "$plist"
fi
signing_identity="${CODESIGN_IDENTITY:--}"
codesign_args=(--force --sign "$signing_identity")
if [[ "$signing_identity" != "-" ]]; then
  codesign_args+=(--options runtime --timestamp)
fi
codesign "${codesign_args[@]}" "$app"
codesign --verify --deep --strict --verbose=2 "$app"

if [[ -n "${NOTARY_PROFILE:-}" ]]; then
  if [[ -z "${CODESIGN_IDENTITY:-}" ]]; then
    echo "NOTARY_PROFILE requires CODESIGN_IDENTITY." >&2
    exit 1
  fi
  notary_zip="$project_dir/build/Video-Enhancer-notary.zip"
  ditto -c -k --keepParent "$app" "$notary_zip"
  xcrun notarytool submit "$notary_zip" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$app"
  xcrun stapler validate "$app"
  spctl -a -vv -t exec "$app"
fi

archive="Video-Enhancer-$version-macos-arm64.zip"
(
  cd "$project_dir/dist"
  ditto -c -k --keepParent "macos/Video Enhancer.app" "$archive"
  shasum -a 256 "$archive" > "$archive.sha256"
)
echo "Built $project_dir/dist/$archive"
