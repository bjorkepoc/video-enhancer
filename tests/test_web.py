from __future__ import annotations

import json
import re
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from video_enhancer import sources, web
from video_enhancer.presets import get_preset
from video_enhancer.web import (
    HTML,
    JOBS,
    MODES,
    SOURCES,
    Handler,
    Job,
    SourceJob,
    build_options,
    create_enhancement_job,
    create_export_job,
    safe_filename,
    source_payload,
)

TOKEN = "test-session-token"
ACCEPTED_TERMS = {
    "terms_accepted": True,
    "terms_version": web.TERMS_VERSION,
}
LOCAL_PROCESSING_ACCEPTED = {"local_processing_accepted": True}


@pytest.fixture(autouse=True)
def reset_job_state() -> Iterator[None]:
    JOBS.clear()
    SOURCES.clear()
    web.DOWNLOAD_TOKENS.clear()
    yield
    JOBS.clear()
    SOURCES.clear()
    web.DOWNLOAD_TOKENS.clear()


@contextmanager
def running_server(work_dir: Path) -> Iterator[str]:
    Handler.work_dir = work_dir
    Handler.session_token = TOKEN
    JOBS.clear()
    SOURCES.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post_json(base: str, path: str, payload: dict[str, object]) -> tuple[int, dict]:
    request = Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "content-type": "application/json",
            "x-video-enhancer-token": TOKEN,
        },
        method="POST",
    )
    with urlopen(request) as response:
        return response.status, json.load(response)


def get_json(base: str, path: str) -> tuple[int, dict]:
    request = Request(f"{base}{path}", headers={"x-video-enhancer-token": TOKEN})
    with urlopen(request) as response:
        return response.status, json.load(response)


def test_safe_filename_removes_paths_and_unsafe_chars() -> None:
    assert safe_filename("../../my video!!.mp4") == "my_video_.mp4"


def test_web_ui_contains_source_first_controls() -> None:
    for control in (
        'id="source-form"',
        'id="source-url"',
        'id="download-original"',
        'id="download-60"',
        'id="download-90"',
        'id="download-upscale"',
        'id="source-quality-select"',
        'id="export-format"',
        'id="clip-start"',
        'id="clip-end"',
        'id="create-export"',
        'id="source-result"',
        'id="source-video"',
        'id="source-image"',
        'id="source-audio"',
        'id="source-zoom"',
        'id="output-zoom"',
        'id="clear-session"',
        'id="adblock-dialog"',
        'id="contact-dialog"',
        'id="privacy-dialog"',
        'id="terms-dialog"',
        'id="terms-accepted"',
        'id="local-processing-dialog"',
        'id="local-processing-accepted"',
    ):
        assert control in HTML
    assert '<html lang="en">' in HTML
    assert 'id="input-local"' not in HTML
    assert 'id="local-controls"' not in HTML
    assert 'type="file"' not in HTML
    assert 'tabindex="0"' not in HTML
    assert 'apiFetch(`/api/jobs?' not in HTML
    assert "browser-session" not in HTML
    assert "cookies-from-browser" not in HTML
    assert "if (!response.ok) throw new Error(config.error" in HTML
    assert 'id="output-image"' in HTML
    assert 'id="output-advanced"' in HTML
    assert "if (state.localJobActive) return;" in HTML
    assert "setLocalJobActive(true);" in HTML
    assert HTML.index('const source = await postJSON("/api/sources/download"') < HTML.index(
        "showSourceLoading();"
    )
    assert 'const gif = extension === "gif";' in HTML
    for label in (
        "Original platform stream",
        "Remuxed without video re-encoding",
        "Enhanced synthetic copy",
    ):
        assert label in HTML
    for label in ("Privacy at a glance", "Terms of use"):
        assert label in HTML
    for label in (
        'aria-label="Advertisement"',
        "Sponsor Media Downloader",
        "Advertise here",
        "Open advertising inquiry",
        "public advertising inquiry",
        'href="mailto:bjorke.poc@gmail.com"',
        "Last updated August 10, 2026",
        "Report security privately",
        "static project notice",
        "VSCO, Instagram, TikTok, and Facebook",
        "It looks like ads are being blocked",
        "Continue without ads",
        "Optional enhancement runs locally only after confirmation",
        "Nothing in these terms limits mandatory consumer rights",
    ):
        assert label in HTML
    class ResourceAuditParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.remote_resources: list[tuple[str, str, str]] = []
            self.external_links: list[dict[str, str | None]] = []
            self.ping_tags: list[str] = []

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            values = dict(attrs)
            if "ping" in values:
                self.ping_tags.append(tag)
            for name in (
                "src",
                "srcset",
                "href",
                "xlink:href",
                "poster",
                "data",
                "action",
                "formaction",
            ):
                value = values.get(name) or ""
                remote = value.lstrip().lower().startswith(
                    ("http://", "https://", "//")
                )
                if not remote:
                    continue
                if tag == "a" and name == "href":
                    self.external_links.append(values)
                else:
                    self.remote_resources.append((tag, name, value))

    audit = ResourceAuditParser()
    audit.feed(HTML)
    assert not audit.remote_resources
    assert not audit.ping_tags
    assert audit.external_links
    for link in audit.external_links:
        assert (link["href"] or "").lower().startswith("https://")
        assert (link.get("target") or "").lower() == "_blank"
        rel = set((link.get("rel") or "").lower().split())
        assert {"noopener", "noreferrer"} <= rel
    assert not re.findall(
        r'''(?:url\(\s*|@import\s+(?:url\(\s*)?)["']?(?:https?:)?//''',
        HTML,
        re.IGNORECASE,
    )
    assert 'postJSON("/api/sources/download", {' in HTML
    assert "terms_accepted: true" in HTML
    assert 'quality: $("source-quality-select").value' in HTML
    assert "local_processing_accepted: true" in HTML
    assert "Video source quality" in HTML
    assert "Images stay at the original resolution" in HTML
    assert '$("output-meta").textContent = "Error";' in HTML
    assert '$("output-empty").textContent = error.message;' in HTML
    assert HTML.count("showPollingError(error);") >= 3
    assert '`/api/sources/${state.sourceId}/export`' in HTML
    assert "inspect-source" not in HTML
    assert "compare-candidate" not in HTML
    for marker in (
        "Image &amp; video downloader",
        "Download media",
        'aria-describedby="url-help source-error"',
        'class="workspace-layout"',
        'id="output-player" hidden',
        "Technical details",
    ):
        assert marker in HTML
    assert "How it works" not in HTML
    assert 'id="ad-bait"' in HTML
    assert '$("adblock-dialog").showModal()' in HTML
    assert '$("retry-adblock").addEventListener("click"' in HTML
    assert HTML.index('id="source-error"') < HTML.index('id="url-help"')
    assert HTML.index('class="house-ad') > HTML.index('id="workspace-active"')


def test_web_ui_contains_frame_playback_controls() -> None:
    for player in ("source", "output"):
        shell = HTML.index(f'id="{player}-shell"')
        frame_controls = HTML.index(f'id="{player}-frame-controls"')
        zoom_label = "original" if player == "source" else "enhanced copy"
        zoom_controls = HTML.index(f'aria-label="Zoom controls for {zoom_label}"')
        assert shell < frame_controls < zoom_controls
        assert f'<video id="{player}-video" preload="metadata" playsinline controls>' in HTML
        assert f'id="{player}-play"' not in HTML
        for control in (
            f'id="{player}-frame-controls"',
            f'id="{player}-previous-frame"',
            f'id="{player}-one-fps"',
            f'id="{player}-next-frame"',
            f'id="{player}-frame-fps"',
        ):
            assert control in HTML
    for label in ("Previous frame", "Play one frame per second", "Next frame"):
        assert label in HTML
    assert ".player-shell:fullscreen .frame-controls" in HTML


def test_web_ui_wires_focal_zoom_and_physical_downloads() -> None:
    for marker in (
        'id="source-stage"',
        'id="source-zoom-reset"',
        'id="output-stage"',
        'id="output-zoom-reset"',
        'stage.addEventListener("wheel"',
        'stage.addEventListener("pointermove"',
        'url.searchParams.set("download", "1")',
    ):
        assert marker in HTML


def test_local_page_has_security_headers_and_no_cookie(tmp_path: Path) -> None:
    with running_server(tmp_path) as base, urlopen(base) as response:
        body = response.read().decode()
        content_security_policy = response.headers["content-security-policy"]
        assert TOKEN not in body
        assert "window.location.hash" in body
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in content_security_policy
        assert "unsafe-inline" not in content_security_policy
        nonce = re.search(r'<script nonce="([^"]+)">', body)
        assert nonce and f"'nonce-{nonce.group(1)}'" in content_security_policy
        assert response.headers.get("set-cookie") is None


def test_favicon_request_does_not_log_a_404(tmp_path: Path) -> None:
    with running_server(tmp_path) as base, urlopen(f"{base}/favicon.ico") as response:
        assert response.status == 204
        assert response.read() == b""


def test_api_rejects_missing_token_and_nonlocal_host(tmp_path: Path) -> None:
    with running_server(tmp_path) as base:
        with pytest.raises(HTTPError) as missing_token:
            urlopen(f"{base}/api/config")
        with pytest.raises(HTTPError) as invalid_host:
            urlopen(Request(base, headers={"Host": "attacker.example"}))

    assert missing_token.value.code == 403
    assert invalid_host.value.code == 421


def test_run_server_uses_only_a_process_temporary_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_serve(
        host: str, port: int, work_dir: Path, *, open_browser: bool = False
    ) -> None:
        captured.update(host=host, port=port, work_dir=work_dir)
        assert work_dir.is_dir()

    monkeypatch.setattr(web, "_serve", fake_serve)

    web.run_server(port=4321)

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 4321
    assert not Path(captured["work_dir"]).exists()
    for host in ("0.0.0.0", "::1", "example.com"):
        with pytest.raises(ValueError, match="only bind"):
            web.run_server(host=host)


def test_serve_opens_token_in_a_url_fragment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeServer:
        daemon_threads = False
        server_port = 54321

        def __init__(self, address: tuple[str, int], handler: type[Handler]) -> None:
            pass

        def serve_forever(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    opened: list[str] = []
    monkeypatch.setattr(web, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(web.secrets, "token_hex", lambda size: TOKEN)
    monkeypatch.setattr(web.webbrowser, "open", opened.append)

    web._serve("127.0.0.1", 0, tmp_path, open_browser=True)

    url = f"http://127.0.0.1:54321/#token={TOKEN}"
    assert opened == [url]
    assert url in capsys.readouterr().out


def test_serve_treats_sigterm_as_a_clean_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signal_calls: list[tuple[int, object]] = []
    events: list[str] = []
    previous = object()

    class FakeServer:
        server_port = 54321

        def __init__(self, address: tuple[str, int], handler: type[Handler]) -> None:
            pass

        def serve_forever(self) -> None:
            handler = next(
                handler
                for signum, handler in signal_calls
                if signum == signal.SIGTERM
            )
            assert callable(handler)
            handler(signal.SIGTERM, None)

        def server_close(self) -> None:
            events.append("server closed")

    monkeypatch.setattr(web, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(web.signal, "getsignal", lambda signum: previous)
    monkeypatch.setattr(
        web.signal,
        "signal",
        lambda signum, handler: signal_calls.append((signum, handler)),
    )
    monkeypatch.setattr(
        web,
        "clear_session",
        lambda work_dir, *, force=False: events.append(f"cleared {force}"),
    )

    web._serve("127.0.0.1", 0, tmp_path)

    assert events == ["server closed", "cleared True"]
    term_handlers = [
        handler for signum, handler in signal_calls if signum == signal.SIGTERM
    ]
    assert callable(term_handlers[0])
    assert term_handlers[-2:] == [signal.SIG_IGN, previous]


def test_serve_waits_for_in_flight_requests_before_job_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    request_started = threading.Event()
    finish_request = threading.Event()

    class FakeServer:
        daemon_threads = True
        server_port = 54321

        def __init__(self, address: tuple[str, int], handler: type[Handler]) -> None:
            self.request_thread: threading.Thread | None = None

        def serve_forever(self) -> None:
            def handle_request() -> None:
                events.append("request started")
                request_started.set()
                finish_request.wait()
                events.append("request finished")

            self.request_thread = threading.Thread(
                target=handle_request,
                daemon=self.daemon_threads,
            )
            self.request_thread.start()
            request_started.wait()
            raise KeyboardInterrupt

        def server_close(self) -> None:
            assert self.daemon_threads is False
            assert self.request_thread is not None
            finish_request.set()
            self.request_thread.join()
            events.append("server closed")

    monkeypatch.setattr(web, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(
        web,
        "clear_session",
        lambda work_dir, *, force=False: events.append(f"cleared {force}"),
    )

    web._serve("127.0.0.1", 0, tmp_path)

    assert events == [
        "request started",
        "request finished",
        "server closed",
        "cleared True",
    ]


def test_serve_file_ignores_client_disconnect(tmp_path: Path) -> None:
    class DisconnectedClient:
        def write(self, _data: bytes) -> None:
            raise BrokenPipeError

    file = tmp_path / "video.mp4"
    file.write_bytes(b"video")
    handler = object.__new__(Handler)
    handler.headers = {}
    handler.wfile = DisconnectedClient()
    handler.send_response = lambda status: None
    handler.send_header = lambda name, value: None
    handler.end_headers = lambda: None

    handler.serve_file(file, "video/mp4")


@pytest.mark.skipif(not hasattr(web.os, "O_NOFOLLOW"), reason="requires O_NOFOLLOW")
def test_serve_file_rejects_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.mp4"
    target.write_bytes(b"video")
    link = tmp_path / "link.mp4"
    link.symlink_to(target)
    errors: list[int] = []
    handler = object.__new__(Handler)
    handler.send_error = errors.append

    handler.serve_file(link, "video/mp4")

    assert errors == [404]


def test_video_files_support_byte_ranges(tmp_path: Path) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"0123456789")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        request = Request(
            f"{base}/files/sources/source1/original",
            headers={
                "Range": "bytes=2-5",
                "x-video-enhancer-token": TOKEN,
            },
        )
        with urlopen(request) as response:
            assert response.status == 206
            assert response.headers["accept-ranges"] == "bytes"
            assert response.headers["content-range"] == "bytes 2-5/10"
            assert response.headers["content-length"] == "4"
            assert response.read() == b"2345"


def test_video_files_reject_unbounded_range_numbers(tmp_path: Path) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"0123456789")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        request = Request(
            f"{base}/files/sources/source1/original",
            headers={
                "Range": f"bytes={'1' * 21}-",
                "x-video-enhancer-token": TOKEN,
            },
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)

    assert error.value.code == 416


def test_download_query_serves_a_physical_attachment(tmp_path: Path) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        _, payload = post_json(
            base,
            "/api/files/token",
            {"path": "/files/sources/source1/original"},
        )
        with urlopen(
            f"{base}/files/sources/source1/original"
            f"?token={payload['token']}&download=1"
        ) as response:
            assert response.status == 200
            assert response.headers["content-disposition"] == (
                'attachment; filename="original.mp4"'
            )
            assert response.read() == b"video"

        with pytest.raises(HTTPError) as error:
            urlopen(f"{base}/files/sources/source1/original?token={TOKEN}")

    assert error.value.code == 403


def test_media_token_survives_a_delayed_range_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"0123456789")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original
    clock = [100.0]
    monkeypatch.setattr(web.time, "monotonic", lambda: clock[0])

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        _, payload = post_json(
            base,
            "/api/files/token",
            {"path": "/files/sources/source1/original"},
        )
        clock[0] += 301
        request = Request(
            f"{base}/files/sources/source1/original?token={payload['token']}",
            headers={"Range": "bytes=5-"},
        )
        with urlopen(request) as response:
            assert response.status == 206
            assert response.read() == b"56789"


def test_source_routes_encode_unicode_filenames(tmp_path: Path) -> None:
    file = tmp_path / "source-source1" / "🔥.jpg"
    file.parent.mkdir()
    file.write_bytes(b"image")
    source = SourceJob("source1", "https://tiktok.com/photo/1", file.parent)
    source.original_path = file
    source.preview_path = file

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        for kind, disposition in (("preview", "inline"), ("original", "attachment")):
            _, payload = post_json(
                base,
                "/api/files/token",
                {"path": f"/files/sources/source1/{kind}"},
            )
            request = Request(
                f"{base}/files/sources/source1/{kind}"
                f"?token={payload['token']}&download={int(kind == 'original')}"
            )
            with urlopen(request) as response:
                assert response.headers["content-disposition"] == (
                    f'{disposition}; filename="download.jpg"; '
                    "filename*=UTF-8''%F0%9F%94%A5.jpg"
                )
                assert response.read() == b"image"


def test_source_routes_serve_image_preview_and_tiktok_audio_types(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "source-source1"
    directory.mkdir()
    archive = directory / "images.zip"
    preview = directory / "image.jpg"
    audio = directory / "sound.mp3"
    archive.write_bytes(b"zip")
    preview.write_bytes(b"image")
    audio.write_bytes(b"audio")
    source = SourceJob("source1", "https://tiktok.com/photo/1", directory)
    source.original_path = archive
    source.preview_path = preview
    source.audio_path = audio

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        for kind, content_type, body in (
            ("preview", "image/jpeg", b"image"),
            ("audio", "audio/mpeg", b"audio"),
        ):
            request = Request(
                f"{base}/files/sources/source1/{kind}",
                headers={"x-video-enhancer-token": TOKEN},
            )
            with urlopen(request) as response:
                assert response.headers["content-type"] == content_type
                assert response.read() == body


def test_job_route_serves_export_media_types(tmp_path: Path) -> None:
    with running_server(tmp_path) as base:
        for extension, content_type in (
            ("gif", "image/gif"),
            ("mov", "video/quicktime"),
            ("avi", "video/x-msvideo"),
        ):
            output = tmp_path / f"output.{extension}"
            output.write_bytes(extension.encode())
            job = Job(extension, tmp_path / "input.mp4", output, ["ffmpeg"])
            job.status = "done"
            JOBS[job.id] = job
            request = Request(
                f"{base}/files/{job.id}/output",
                headers={"x-video-enhancer-token": TOKEN},
            )
            with urlopen(request) as response:
                assert response.headers["content-type"] == content_type
                assert response.read() == extension.encode()


def test_build_options_uses_existing_preset_and_toggles() -> None:
    options = build_options(
        {
            "preset": ["fast"],
            "scale": ["1.5"],
            "fps": ["48"],
            "no_upscale": ["1"],
            "no_interpolate": ["true"],
            "codec": ["libx265"],
        }
    )

    assert options.preset == get_preset("fast")
    assert options.scale_factor == 1.5
    assert options.fps == 48
    assert options.no_upscale is True
    assert options.no_interpolate is True
    assert options.video_codec == "libx265"


def test_enhancement_from_source_reuses_file_without_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoopThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr(web.threading, "Thread", NoopThread)
    monkeypatch.setattr(web, "build_ffmpeg_command", lambda *args, **kwargs: ["ffmpeg"])
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    job = create_enhancement_job(source, "source.mp4", {"preset": ["fast"]}, tmp_path)

    assert job.input_path == source
    assert job.output_path.name == "source-enhanced.mp4"


def test_export_from_source_reuses_file_with_format_and_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoopThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    captured: dict[str, object] = {}

    def build(input_path: Path, output_path: Path, output_format: str, **kwargs: object) -> list[str]:
        captured.update(
            input=input_path,
            output=output_path,
            format=output_format,
            **kwargs,
        )
        return ["ffmpeg"]

    monkeypatch.setattr(web.threading, "Thread", NoopThread)
    monkeypatch.setattr(web, "build_export_command", build)

    job = create_export_job(
        source,
        source.name,
        {"format": "mp3", "start": "1.5", "end": "3"},
        tmp_path,
    )

    assert job.kind == "audio-export"
    assert job.output_path.name == "source-export.mp3"
    assert captured["input"] == source
    assert captured["start_seconds"] == 1.5
    assert captured["end_seconds"] == 3.0


def test_failed_enhancement_setup_removes_job_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        web,
        "build_ffmpeg_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("invalid")),
    )

    with pytest.raises(ValueError, match="invalid"):
        create_enhancement_job(source, source.name, {}, tmp_path)

    assert list(tmp_path.iterdir()) == [source]


def test_only_one_enhancement_can_be_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoopThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(web.threading, "Thread", NoopThread)
    monkeypatch.setattr(web, "build_ffmpeg_command", lambda *args, **kwargs: ["ffmpeg"])

    create_enhancement_job(source, source.name, {}, tmp_path)

    with pytest.raises(ValueError, match="active export"):
        create_enhancement_job(source, source.name, {}, tmp_path)


def test_completed_enhancement_is_replaced_to_bound_session_disk_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source" / "video.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    old_output = tmp_path / "old-job" / "output.mp4"
    old_output.parent.mkdir()
    old_output.write_bytes(b"old")
    old_job = Job("old", source, old_output, ["ffmpeg"])
    old_job.status = "done"
    JOBS[old_job.id] = old_job
    monkeypatch.setattr(web, "build_ffmpeg_command", lambda *args, **kwargs: ["ffmpeg"])
    monkeypatch.setattr(web, "run_job", lambda job: None)

    new_job = create_enhancement_job(source, source.name, {}, tmp_path)
    assert new_job.id in JOBS
    assert list(JOBS) == [new_job.id]
    assert not old_output.parent.exists()
    assert source.exists()


def test_source_payload_does_not_expose_url_or_local_path(tmp_path: Path) -> None:
    job = SourceJob(
        id="source1",
        url="https://tiktok.com/private-source",
        directory=tmp_path,
    )

    payload = source_payload(job)

    assert "url" not in payload
    assert str(tmp_path) not in json.dumps(payload)


def test_job_payload_does_not_expose_local_paths(tmp_path: Path) -> None:
    job = Job(
        "job1",
        tmp_path / "private" / "input.mp4",
        tmp_path / "private" / "output.mp4",
        ["ffmpeg"],
    )

    payload = web.job_payload(job)

    assert "output_path" not in payload
    assert "command" not in payload
    assert str(tmp_path) not in json.dumps(payload)


def test_run_job_discards_ffmpeg_output_and_has_a_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "output.mp4"
    calls = []

    process = object()

    def run(command: list[str], **kwargs: object) -> object:
        calls.append((command, kwargs))
        callback = kwargs["process_callback"]
        callback(process)
        assert job.process is process
        output.write_bytes(b"video")
        callback(None)
        return web.subprocess.CompletedProcess(command, 0)

    job = Job("job1", tmp_path / "input.mp4", output, ["ffmpeg", "input"])
    monkeypatch.setattr(web, "run_bounded_process", run)

    web.run_job(job)

    assert job.status == "done"
    assert job.logs == ["Export started.", "Export finished."]
    options = calls[0][1]
    assert options["timeout"] == web.ENHANCEMENT_TIMEOUT_SECONDS
    assert options["max_output_bytes"] == web.MAX_PROCESS_OUTPUT_BYTES
    assert options["destination"] == tmp_path
    assert options["max_directory_growth_bytes"] == web.MAX_SOURCE_BYTES
    assert options["capture_output"] is False


def test_run_job_removes_partial_output_after_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "output.mp4"

    def time_out(command: list[str], **kwargs: object) -> object:
        output.write_bytes(b"partial")
        raise web.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(web, "run_bounded_process", time_out)
    job = Job("job1", tmp_path / "input.mp4", output, ["ffmpeg", "input"])

    web.run_job(job)

    assert job.status == "error"
    assert "six-hour" in job.error
    assert not output.exists()


def test_source_modes_are_explicit_synthetic_derivatives() -> None:
    assert MODES == {
        "60": {"fps": ["60"], "scale": ["1"], "preset": ["quality"]},
        "90": {"fps": ["90"], "scale": ["1"], "preset": ["ultra"]},
        "upscale": {
            "no_interpolate": ["1"],
            "scale": ["2"],
            "preset": ["quality"],
        },
    }


def test_source_json_body_is_bounded(tmp_path: Path) -> None:
    with running_server(tmp_path) as base:
        request = Request(
            f"{base}/api/sources/download",
            data=json.dumps({"url": "x" * 21_000}).encode(),
            headers={
                "content-type": "application/json",
                "x-video-enhancer-token": TOKEN,
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)

    assert error.value.code == 400


def test_web_rejects_local_file_uploads(tmp_path: Path) -> None:
    with running_server(tmp_path) as base:
        request = Request(
            f"{base}/api/jobs",
            data=b"video",
            headers={
                "content-type": "application/octet-stream",
                "x-file-name": "video.mp4",
                "x-video-enhancer-token": TOKEN,
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)

    assert error.value.code == 404


def test_clear_session_removes_completed_local_files(tmp_path: Path) -> None:
    directory = tmp_path / "source-source1"
    directory.mkdir()
    (directory / "video.mp4").write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", directory)
    source.status = "done"

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        status, payload = post_json(base, "/api/session/clear", {})

        assert status == 200
        assert payload == {"cleared": True}
        assert list(tmp_path.iterdir()) == []
        assert SOURCES == {}


def test_clear_session_finishes_deleting_before_a_new_job_can_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_directory = tmp_path / "old-source"
    old_directory.mkdir()
    (old_directory / "video.mp4").write_bytes(b"video")
    old_source = SourceJob("old", "https://tiktok.com/x", old_directory)
    old_source.status = "done"
    SOURCES[old_source.id] = old_source
    deletion_started = threading.Event()
    finish_deletion = threading.Event()
    job_created = threading.Event()
    original_rmtree = web.shutil.rmtree

    def blocked_rmtree(path: Path, **kwargs: object) -> None:
        deletion_started.set()
        finish_deletion.wait()
        original_rmtree(path, **kwargs)

    monkeypatch.setattr(web.shutil, "rmtree", blocked_rmtree)
    monkeypatch.setattr(web, "build_ffmpeg_command", lambda *args, **kwargs: ["ffmpeg"])
    monkeypatch.setattr(web, "run_job", lambda job: None)
    clear_thread = threading.Thread(target=web.clear_session, args=(tmp_path,))
    clear_thread.start()
    assert deletion_started.wait(1)

    def create_job() -> None:
        create_enhancement_job(tmp_path / "input.mp4", "input.mp4", {}, tmp_path)
        job_created.set()

    create_thread = threading.Thread(target=create_job)
    create_thread.start()
    assert not job_created.wait(0.05)
    finish_deletion.set()
    clear_thread.join()
    create_thread.join()

    assert job_created.is_set()
    assert not old_directory.exists()


def test_forced_clear_stops_owned_process_before_removing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    directory = tmp_path / "job1"
    directory.mkdir()
    output = directory / "output.mp4"
    output.write_bytes(b"partial")
    job = Job("job1", tmp_path / "input.mp4", output, ["ffmpeg"])
    job.status = "running"
    job.process = object()

    class Worker:
        def join(self, *, timeout: float | None = None) -> None:
            assert timeout == web.REQUEST_TIMEOUT_SECONDS
            events.append("joined")

    job.thread = Worker()
    JOBS[job.id] = job
    remove = web.shutil.rmtree
    monkeypatch.setattr(web, "stop_process", lambda process: events.append("stopped"))

    def remove_after_stop(path: Path, **kwargs: object) -> None:
        events.append("removed")
        remove(path, **kwargs)

    monkeypatch.setattr(web.shutil, "rmtree", remove_after_stop)

    web.clear_session(tmp_path, force=True)

    assert events == ["stopped", "joined", "removed"]
    assert job.cancelled is True
    assert JOBS == {}


def test_source_download_route_runs_async_and_reports_saved_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(
        url: str, destination: Path, **kwargs: object
    ) -> dict[str, object]:
        assert url == "https://tiktok.com/@a/video/123"
        assert kwargs["quality"] == "4k"
        assert kwargs["cancel_callback"]() is False
        callback = kwargs["process_callback"]
        process = object()
        callback(process)
        assert any(source.process is process for source in SOURCES.values())
        callback(None)
        destination.mkdir(parents=True)
        path = destination / "source.mp4"
        path.write_bytes(b"video")
        return {
            "path": path,
            "preview_path": path,
            "audio_path": None,
            "platform": "tiktok",
            "media_type": "video",
            "preview_type": "video",
            "item_count": 1,
            "media": {"width": 1080, "height": 1920, "fps": 30.0},
            "format_id": "best",
            "operation": "direct",
        }

    monkeypatch.setattr(web, "download_source", fake_download)

    with running_server(tmp_path) as base:
        status, payload = post_json(
            base,
            "/api/sources/download",
            {
                "url": "https://tiktok.com/@a/video/123",
                "quality": "4k",
                **ACCEPTED_TERMS,
            },
        )
        assert status == 202
        assert payload["status"] in {"queued", "downloading", "done"}
        source_id = payload["id"]

        deadline = time.monotonic() + 2
        while True:
            _, payload = get_json(base, f"/api/sources/{source_id}")
            if payload["status"] == "done" or time.monotonic() >= deadline:
                break
            time.sleep(0.01)

    assert payload["status"] == "done"
    assert payload["quality"] == "4k"
    assert payload["preview_type"] == "video"
    assert payload["media"]["width"] == 1080
    assert payload["original_url"] == f"/files/sources/{source_id}/original"


def test_nullable_instagram_metadata_leaves_source_job_in_terminal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"entries": [{"id": "image", "formats": [], "thumbnails": None}]}
    monkeypatch.setattr(
        sources,
        "_run_gallery_dl",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    monkeypatch.setattr(
        sources,
        "_run_yt_dlp",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0 if "--dump-single-json" in command else 1,
            json.dumps(payload) if "--dump-single-json" in command else "",
            "",
        ),
    )
    job = SourceJob(
        "source1",
        "https://www.instagram.com/p/example/",
        tmp_path / "source-source1",
    )

    web.run_source_download(job)

    assert job.status == "error"
    assert "did not provide public media" in job.error
    assert not job.directory.exists()


def test_completed_source_is_replaced_to_bound_session_disk_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_directory = tmp_path / "source-old"
    old_directory.mkdir()
    (old_directory / "old.mp4").write_bytes(b"old")
    old_source = SourceJob("old", "https://tiktok.com/old", old_directory)
    old_source.status = "done"
    SOURCES[old_source.id] = old_source
    monkeypatch.setattr(web, "run_source_download", lambda source: None)
    handler = object.__new__(Handler)
    handler.work_dir = tmp_path

    payload = handler.create_source_job(
        {"url": "https://instagram.com/reel/ABC123/", **ACCEPTED_TERMS}
    )

    assert list(SOURCES) == [payload["id"]]
    assert not old_directory.exists()


def test_source_download_route_rejects_parallel_downloads(tmp_path: Path) -> None:
    with running_server(tmp_path) as base:
        SOURCES["active"] = SourceJob(
            "active", "https://tiktok.com/@a/video/123", tmp_path / "active"
        )
        with pytest.raises(HTTPError) as error:
            post_json(
                base,
                "/api/sources/download",
                {"url": "https://instagram.com/reel/ABC123/", **ACCEPTED_TERMS},
            )

    assert error.value.code == 400
    assert json.load(error.value) == {
        "error": "Wait for the active source download to finish."
    }


def test_source_download_requires_current_terms_acceptance(tmp_path: Path) -> None:
    with running_server(tmp_path) as base, pytest.raises(HTTPError) as error:
        post_json(
            base,
            "/api/sources/download",
            {"url": "https://tiktok.com/@a/video/123"},
        )

    assert error.value.code == 400
    assert json.load(error.value) == {
        "error": "Accept the current Terms of Use before downloading media."
    }


def test_source_file_route_serves_only_files_inside_work_dir(tmp_path: Path) -> None:
    inside = tmp_path / "source-source1" / "original.mp4"
    inside.parent.mkdir()
    inside.write_bytes(b"inside")
    source = SourceJob("source1", "https://tiktok.com/x", inside.parent)
    source.original_path = inside

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        request = Request(
            f"{base}/files/sources/source1/original",
            headers={"x-video-enhancer-token": TOKEN},
        )
        with urlopen(request) as response:
            assert response.status == 200
            assert response.read() == b"inside"

        outside = tmp_path.parent / "outside.mp4"
        outside.write_bytes(b"outside")
        source.original_path = outside
        with pytest.raises(HTTPError) as error:
            urlopen(request)

    assert error.value.code == 404


def test_source_enhance_route_reuses_original_with_explicit_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original
    source.media_type = "video"
    source.status = "done"
    captured: dict[str, object] = {}

    def fake_create(
        input_path: Path,
        original_name: str,
        params: dict[str, list[str]],
        work_dir: Path,
    ) -> Job:
        captured.update(
            input_path=input_path,
            original_name=original_name,
            params=params,
            work_dir=work_dir,
        )
        return Job("job1", input_path, tmp_path / "derived.mp4", ["ffmpeg"])

    monkeypatch.setattr(web, "create_enhancement_job", fake_create)

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        status, payload = post_json(
            base,
            "/api/sources/source1/enhance",
            {"mode": "60", **LOCAL_PROCESSING_ACCEPTED},
        )

    assert status == 202
    assert payload["id"] == "job1"
    assert captured["input_path"] == original
    assert captured["params"] == {
        "fps": ["60"],
        "scale": ["1"],
        "preset": ["quality"],
        "output": ["original-60fps.mp4"],
    }


def test_source_enhance_route_rejects_images(tmp_path: Path) -> None:
    original = tmp_path / "source-source1" / "image.jpg"
    original.parent.mkdir()
    original.write_bytes(b"image")
    source = SourceJob("source1", "https://vsco.co/u/media/1", original.parent)
    source.original_path = original
    source.media_type = "image"
    source.status = "done"

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        with pytest.raises(HTTPError) as error:
            post_json(
                base,
                "/api/sources/source1/enhance",
                {"mode": "60", **LOCAL_PROCESSING_ACCEPTED},
            )

    assert error.value.code == 400
    assert json.load(error.value) == {"error": "Only downloaded videos can be enhanced."}


def test_source_enhance_requires_local_processing_confirmation(tmp_path: Path) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original
    source.media_type = "video"
    source.status = "done"

    with running_server(tmp_path) as base, pytest.raises(HTTPError) as error:
        SOURCES[source.id] = source
        post_json(base, "/api/sources/source1/enhance", {"mode": "60"})

    assert error.value.code == 400
    assert json.load(error.value) == {
        "error": "Confirm local device processing before enhancing."
    }


def test_source_export_route_reuses_original_with_explicit_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original
    source.media_type = "video"
    source.status = "done"
    captured: dict[str, object] = {}

    def fake_create(
        input_path: Path,
        original_name: str,
        body: dict[str, object],
        work_dir: Path,
    ) -> Job:
        captured.update(
            input_path=input_path,
            original_name=original_name,
            body=body,
            work_dir=work_dir,
        )
        return Job(
            "job1",
            input_path,
            tmp_path / "derived.mp3",
            ["ffmpeg"],
            kind="audio-export",
        )

    monkeypatch.setattr(web, "create_export_job", fake_create)

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        status, payload = post_json(
            base,
            "/api/sources/source1/export",
            {
                "format": "mp3",
                "start": "4",
                "end": "9",
                **LOCAL_PROCESSING_ACCEPTED,
            },
        )

    assert status == 202
    assert payload["kind"] == "audio-export"
    assert captured["input_path"] == original
    assert captured["body"] == {
        "format": "mp3",
        "start": "4",
        "end": "9",
        **LOCAL_PROCESSING_ACCEPTED,
    }


def test_source_export_requires_local_processing_confirmation(tmp_path: Path) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", original.parent)
    source.original_path = original
    source.media_type = "video"
    source.status = "done"

    with running_server(tmp_path) as base, pytest.raises(HTTPError) as error:
        SOURCES[source.id] = source
        post_json(base, "/api/sources/source1/export", {"format": "mp3"})

    assert error.value.code == 400
    assert json.load(error.value) == {
        "error": "Confirm local device processing before exporting."
    }
