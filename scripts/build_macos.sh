#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build requires macOS." >&2
  exit 1
fi

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(dirname -- "$script_dir")"
python_bin="$(command -v "${PYTHON_BIN:-python3}")"
python_arch="$("$python_bin" -c 'import platform; print(platform.machine())')"
build_arch="${TARGET_ARCH:-$python_arch}"
case "$build_arch" in
  arm64)
    ffmpeg_sha256="6d175a4743ca50256e89a8cdd731100f9cee33bd79aeea46894d209410dc6617"
    ;;
  x86_64)
    ffmpeg_sha256="4a4a968b98859588e98500ae25973d80a5ca5eed0724222b9f76360dcb72a001"
    ;;
  *)
    echo "Unsupported macOS architecture: $build_arch" >&2
    exit 1
    ;;
esac
if [[ "$python_arch" != "$build_arch" ]]; then
  echo "TARGET_ARCH=$build_arch requires a native $build_arch Python (found $python_arch)." >&2
  exit 1
fi
vendor_dir="$project_dir/build/vendor"
yt_dlp="$vendor_dir/yt-dlp"
gallery_dl="$vendor_dir/gallery-dl"
ffmpeg="$vendor_dir/ffmpeg"
dist_dir="$project_dir/dist/macos"
app="$dist_dir/Video Enhancer.app"

verify_arch() {
  if ! lipo "$2" -verify_arch "$build_arch" >/dev/null 2>&1; then
    echo "$1 does not contain the required $build_arch architecture: $2" >&2
    exit 1
  fi
}

"$python_bin" -c "import gallery_dl, imageio_ffmpeg, PyInstaller" 2>/dev/null || {
  echo "Install the macOS build extra first: python -m pip install -e '.[macos]'" >&2
  exit 1
}
"$python_bin" - <<'PY'
import urllib3
from packaging.version import Version

if Version(urllib3.__version__) < Version("2.8.0"):
    raise SystemExit("Update the build environment: urllib3>=2.8.0 is required")
PY
version="$($python_bin -c 'from importlib.metadata import version; print(version("video-enhancer"))')"
mkdir -p "$vendor_dir" "$project_dir/build/pyinstaller"
ffmpeg_source="$($python_bin -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')"
printf '%s  %s\n' "$ffmpeg_sha256" "$ffmpeg_source" | shasum -a 256 -c -
cp "$ffmpeg_source" "$ffmpeg"
chmod 755 "$ffmpeg"
verify_arch "FFmpeg" "$ffmpeg"
# Build both downloaders from the same environment as the audited application.
for module in yt_dlp gallery_dl; do
  name="${module//_/-}"
  entry="$($python_bin -c "import importlib; print(importlib.import_module('$module.__main__').__file__)")"
  downloader_args=(
    --clean --noconfirm --onefile --console
    --name "$name"
    --collect-all "$module"
    --distpath "$vendor_dir"
    --workpath "$project_dir/build/$name"
    --specpath "$project_dir/build/$name"
  )
  if [[ "$module" == "gallery_dl" ]]; then
    downloader_args+=(--collect-all yt_dlp)
  fi
  if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
    downloader_args+=(--codesign-identity "$CODESIGN_IDENTITY")
  fi
  "$python_bin" -m PyInstaller "${downloader_args[@]}" "$entry"
  chmod 755 "$vendor_dir/$name"
  verify_arch "$name" "$vendor_dir/$name"
done

pyinstaller_args=(
  --clean
  --noconfirm
  --onedir
  --windowed
  --name "Video Enhancer"
  --icon "$project_dir/assets/VideoEnhancer.icns"
  --osx-bundle-identifier com.bjorkepoc.videoenhancer
  --paths "$project_dir/src"
  --collect-submodules gallery_dl.extractor
  --add-binary "$yt_dlp:bin"
  --add-binary "$gallery_dl:bin"
  --add-binary "$ffmpeg:bin"
  --add-data "$project_dir/src/video_enhancer/web_assets:video_enhancer/web_assets"
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
verify_arch "App executable" "$app/Contents/MacOS/Video Enhancer"
verify_arch "Bundled FFmpeg" "$app/Contents/Frameworks/bin/ffmpeg"
verify_arch "Bundled yt-dlp" "$app/Contents/Frameworks/bin/yt-dlp"
verify_arch "Bundled gallery-dl" "$app/Contents/Frameworks/bin/gallery-dl"

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
VIDEO_ENHANCER_SMOKE_TEST=1 "$app/Contents/MacOS/Video Enhancer"
"$app/Contents/Frameworks/bin/gallery-dl" --version >/dev/null
"$app/Contents/Frameworks/bin/yt-dlp" --version >/dev/null

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

archive="Video-Enhancer-$version-macos-$build_arch.zip"
(
  cd "$project_dir/dist"
  ditto -c -k --keepParent "macos/Video Enhancer.app" "$archive"
  shasum -a 256 "$archive" > "$archive.sha256"
)
echo "Built $project_dir/dist/$archive"
