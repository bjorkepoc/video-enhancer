from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_python_core_runs_on_linux_windows_and_macos() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    python_job = workflow.split("\n  python-test:\n", 1)[1].split("\n  security:\n", 1)[
        0
    ]

    assert '- runner: ubuntu-latest\n            python-version: "3.12"' in python_job
    assert '- runner: windows-2025\n            python-version: "3.12"' in python_job
    assert '- runner: macos-15\n            python-version: "3.12"' in python_job
    assert "python -m pytest" in python_job


def test_release_uses_the_hashed_lock_without_build_isolation() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    security_job, after_security = workflow.split("\n  security:\n", 1)[1].split(
        "\n  macos-package-test:\n", 1
    )
    _, release_jobs = after_security.split("\n  release-build:\n", 1)
    release_build, release_publish = release_jobs.split("\n  release-publish:\n", 1)

    assert "uv export --locked --no-dev --extra macos --group release" in security_job
    assert "--no-emit-project --format requirements-txt" in security_job
    assert "runs-on: macos-15" in security_job
    assert "pip-audit==2.10.1" in security_job
    assert "bandit==1.9.4" in security_job
    assert "pip freeze" not in security_job
    assert "pip install" not in security_job

    assert (
        "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in release_build
    )
    assert 'version: "0.11.21"' in release_build
    sync = "uv sync --locked --no-dev --extra macos --group release"
    assert f"{sync} --no-install-project" in release_build
    assert f"{sync} --no-build-isolation" in release_build
    assert release_build.index(
        "Install locked release dependencies"
    ) < release_build.index("Import Developer ID certificate")
    assert "pip install" not in release_build

    publish_sync = "uv sync --locked --no-dev --group release"
    assert f"{publish_sync} --no-install-project" in release_publish
    assert f"{publish_sync} --no-build-isolation" in release_publish
    assert "python -m build --no-isolation" in release_publish
    assert "--prerelease" in release_publish
    assert "pip install" not in release_publish

    requirements = re.findall(r'"([\w-]+)(?:\[[^]]+\])?[<>=!~]', project)
    lock = (ROOT / "uv.lock").read_text()
    assert set(requirements) <= set(
        re.findall(r'^name = "([\w-]+)"$', lock, re.MULTILINE)
    )

    artifacts = re.findall(r"^\s*(?:sdist = )?\{ url = .+$", lock, re.MULTILINE)
    assert artifacts and all('hash = "sha256:' in artifact for artifact in artifacts)


def test_pushes_and_pull_requests_build_both_native_macos_packages() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    package_job = workflow.split("\n  macos-package-test:\n", 1)[1].split(
        "\n  release-build:\n", 1
    )[0]

    assert "if: ${{ !startsWith(github.ref, 'refs/tags/v') }}" in package_job
    assert "- runner: macos-15\n            arch: arm64" in package_job
    assert "- runner: macos-15-intel\n            arch: x86_64" in package_job
    assert "uv sync --locked --no-dev --extra macos" in package_job
    assert "TARGET_ARCH: ${{ matrix.arch }}" in package_job
    assert "bash scripts/build_macos.sh" in package_job
    assert "shasum -a 256 -c" in package_job
    assert "CODESIGN_IDENTITY" not in package_job
    assert "NOTARY_PROFILE" not in package_job


def test_release_builds_native_arm64_and_intel_artifacts_before_publishing() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    release_build, release_publish = workflow.split("\n  release-build:\n", 1)[1].split(
        "\n  release-publish:\n", 1
    )

    assert "- runner: macos-15\n            arch: arm64" in release_build
    assert "- runner: macos-15-intel\n            arch: x86_64" in release_build
    assert "runs-on: ${{ matrix.runner }}" in release_build
    assert "TARGET_ARCH: ${{ matrix.arch }}" in release_build
    assert "name: macos-${{ matrix.arch }}" in release_build
    assert "macos-${{ matrix.arch }}.zip.sha256" in release_build
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        in release_build
    )
    assert "gh release create" not in release_build

    assert "needs: release-build" in release_publish
    assert (
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
        in release_publish
    )
    assert "merge-multiple: true" in release_publish
    assert "macos-arm64.zip" in release_publish
    assert "macos-x86_64.zip" in release_publish
    assert "gh release create" in release_publish


def test_macos_build_script_rejects_architecture_mismatches() -> None:
    script = (ROOT / "scripts/build_macos.sh").read_text()

    assert 'build_arch="${TARGET_ARCH:-$python_arch}"' in script
    assert "arm64)" in script
    assert "x86_64)" in script
    assert "--target-architecture arm64" not in script
    assert 'lipo "$2" -verify_arch "$build_arch"' in script
    assert 'verify_arch "FFmpeg" "$ffmpeg"' in script
    assert 'verify_arch "$name" "$vendor_dir/$name"' in script
    assert "for module in yt_dlp gallery_dl" in script
    assert '--collect-all "$module"' in script
    assert "--collect-all yt_dlp" in script
    assert "--collect-submodules gallery_dl.extractor" in script
    assert 'downloader_args+=(--codesign-identity "$CODESIGN_IDENTITY")' in script
    assert 'VIDEO_ENHANCER_SMOKE_TEST=1 "$app/Contents/MacOS/Video Enhancer"' in script
    assert '"$app/Contents/Frameworks/bin/gallery-dl" --version' in script
    assert 'verify_arch "Bundled gallery-dl"' in script
    assert 'verify_arch "App executable"' in script
    assert 'archive="Video-Enhancer-$version-macos-$build_arch.zip"' in script


def test_source_archive_manifest_contains_linked_release_files() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text().splitlines()

    assert "include THIRD_PARTY_NOTICES.md" in manifest
    assert "include assets/VideoEnhancer.icns" in manifest
    assert "include docs/launch-privacy-security.md" in manifest
    assert "include docs/snapdownloader-parity.md" in manifest
    assert "include scripts/build_macos.sh" in manifest


def test_local_page_assets_are_included_in_both_package_formats() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    script = (ROOT / "scripts/build_macos.sh").read_text()
    assert (
        'video_enhancer = ["web_assets/*.html", "web_assets/*.css", "web_assets/*.js"]'
        in project
    )
    assert "web_assets:video_enhancer/web_assets" in script
    for name in ("index.html", "style.css", "app.js"):
        assert (ROOT / "src/video_enhancer/web_assets" / name).is_file()


def test_every_installation_requires_fixed_urllib3_and_native_downloaders_share_it() -> (
    None
):
    project = (ROOT / "pyproject.toml").read_text()
    lock = (ROOT / "uv.lock").read_text()
    script = (ROOT / "scripts/build_macos.sh").read_text()
    floor = re.search(r'"urllib3>=(\d+)\.(\d+)\.(\d+)"', project)
    locked = re.search(r'name = "urllib3"\nversion = "(\d+)\.(\d+)\.(\d+)"', lock)
    assert floor and tuple(map(int, floor.groups())) >= (2, 8, 0)
    assert locked and tuple(map(int, locked.groups())) >= (2, 8, 0)
    assert 'Version(urllib3.__version__) < Version("2.8.0")' in script
    assert "releases/download/$yt_dlp_version/yt-dlp_macos" not in script
    assert '"$app/Contents/Frameworks/bin/yt-dlp" --version' in script


def test_updated_downloader_http_stack_streams_an_ordinary_chunked_response() -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import requests

    payload = "ordinary æøå response".encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in (payload[:10], payload[10:]):
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(
                f"http://127.0.0.1:{server.server_port}/", stream=True, timeout=2
            ) as response:
                response.raise_for_status()
                assert b"".join(response.iter_content(chunk_size=3)) == payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_native_security_floor_remains_enforced_with_python_optimization(
    tmp_path: Path,
) -> None:
    script = (ROOT / "scripts/build_macos.sh").read_text()
    guard = script.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    (tmp_path / "urllib3.py").write_text('__version__ = "2.7.0"\n')
    result = subprocess.run(
        [sys.executable, "-c", guard],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "PYTHONOPTIMIZE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "urllib3>=2.8.0 is required" in result.stderr
