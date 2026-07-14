from __future__ import annotations

import json
import re
import threading
import time
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import video_enhancer.web as web
from video_enhancer.presets import get_preset
from video_enhancer.web import (
    HTML,
    Handler,
    JOBS,
    MODES,
    SOURCES,
    Job,
    SourceJob,
    build_options,
    create_enhancement_job,
    safe_filename,
    source_payload,
)

TOKEN = "test-session-token"


@pytest.fixture(autouse=True)
def reset_job_state() -> Iterator[None]:
    JOBS.clear()
    SOURCES.clear()
    yield
    JOBS.clear()
    SOURCES.clear()


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
        'id="input-link"',
        'id="input-local"',
        'id="source-url"',
        'id="inspect-source"',
        'id="source-format"',
        'id="download-original"',
        'id="download-60"',
        'id="download-90"',
        'id="download-upscale"',
        'id="source-result"',
        'id="source-video"',
        'id="source-zoom"',
        'id="output-zoom"',
        'id="clear-session"',
        'id="privacy-dialog"',
    ):
        assert control in HTML
    assert "browser-session" not in HTML
    assert "cookies-from-browser" not in HTML
    assert "if (!response.ok) throw new Error(config.error" in HTML
    for label in (
        "Original platform stream",
        "Remuxed without video re-encoding",
        "Enhanced synthetic copy",
    ):
        assert label in HTML


def test_web_ui_contains_repost_discovery_controls() -> None:
    for control in (
        'id="search-web"',
        'id="search-tiktok"',
        'id="search-instagram"',
        'id="search-google-lens"',
        'id="search-tineye"',
        'id="keyframes"',
        'id="candidate-url"',
        'id="compare-candidate"',
        'id="comparison-result"',
    ):
        assert control in HTML


def test_web_ui_contains_frame_playback_controls() -> None:
    for player in ("source", "output"):
        for control in (
            f'id="{player}-frame-controls"',
            f'id="{player}-previous-frame"',
            f'id="{player}-one-fps"',
            f'id="{player}-next-frame"',
            f'id="{player}-frame-fps"',
        ):
            assert control in HTML
    for label in ("Forrige bilde", "Spill av ett bilde per sekund", "Neste bilde"):
        assert label in HTML


def test_web_ui_wires_focal_zoom_and_physical_downloads() -> None:
    for marker in (
        'id="source-stage"',
        'id="source-zoom-reset"',
        'id="output-stage"',
        'id="output-zoom-reset"',
        'stage.addEventListener("wheel"',
        'stage.addEventListener("pointermove"',
        'url.searchParams.set("download", "1")',
        "image.src = localFileUrl(url)",
    ):
        assert marker in HTML


def test_local_page_has_security_headers_and_no_cookie(tmp_path: Path) -> None:
    with running_server(tmp_path) as base:
        with urlopen(base) as response:
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
        with pytest.raises(ValueError, match="bare bindes"):
            web.run_server(host=host)


def test_serve_opens_token_in_a_url_fragment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeServer:
        daemon_threads = False

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

    web._serve("127.0.0.1", 8765, tmp_path, open_browser=True)

    url = f"http://127.0.0.1:8765/#token={TOKEN}"
    assert opened == [url]
    assert url in capsys.readouterr().out


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
    source = SourceJob("source1", "https://tiktok.com/x", {}, original.parent)
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
    source = SourceJob("source1", "https://tiktok.com/x", {}, original.parent)
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
    source = SourceJob("source1", "https://tiktok.com/x", {}, original.parent)
    source.original_path = original

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        with urlopen(
            f"{base}/files/sources/source1/original?token={TOKEN}&download=1"
        ) as response:
            assert response.status == 200
            assert response.headers["content-disposition"] == (
                'attachment; filename="original.mp4"'
            )
            assert response.read() == b"video"


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

    with pytest.raises(ValueError, match="aktive eksporten"):
        create_enhancement_job(source, source.name, {}, tmp_path)


def test_source_payload_never_contains_browser_or_signed_url(tmp_path: Path) -> None:
    job = SourceJob(
        id="source1",
        url="https://tiktok.com/x",
        info={
            "id": "123",
            "title": "Sample",
            "formats": [{"format_ids": ["best"], "url": "https://signed/x"}],
        },
        directory=tmp_path,
    )

    payload = source_payload(job)

    assert "browser" not in payload
    assert "signed" not in json.dumps(payload)


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

    def run(command: list[str], **kwargs: object) -> object:
        calls.append((command, kwargs))
        output.write_bytes(b"video")
        return web.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(web.subprocess, "run", run)
    job = Job("job1", tmp_path / "input.mp4", output, ["ffmpeg", "input"])

    web.run_job(job)

    assert job.status == "done"
    assert job.logs == ["Export started.", "Export finished."]
    assert calls[0][1] == {
        "stdout": web.subprocess.DEVNULL,
        "stderr": web.subprocess.DEVNULL,
        "check": False,
        "timeout": web.ENHANCEMENT_TIMEOUT_SECONDS,
    }


def test_run_job_removes_partial_output_after_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "output.mp4"

    def time_out(command: list[str], **kwargs: object) -> object:
        output.write_bytes(b"partial")
        raise web.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(web.subprocess, "run", time_out)
    job = Job("job1", tmp_path / "input.mp4", output, ["ffmpeg", "input"])

    web.run_job(job)

    assert job.status == "error"
    assert "seks timer" in job.error
    assert not output.exists()


def test_source_payload_includes_searches_keyframes_and_comparison(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frames" / "frame-1.jpg"
    job = SourceJob(
        id="source1",
        url="https://tiktok.com/x",
        info={"id": "123", "title": "Sample", "formats": []},
        directory=tmp_path,
    )
    job.keyframes = [frame]
    job.comparison_status = "done"
    job.comparison = {"result": "likely_match", "score": 0.9, "advisory": True}

    payload = source_payload(job)

    assert set(payload["searches"]) == {
        "web",
        "tiktok",
        "instagram",
        "google_lens",
        "tineye",
    }
    assert payload["keyframes"] == ["/files/sources/source1/frames/1"]
    assert payload["comparison_status"] == "done"
    assert payload["comparison"]["advisory"] is True


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


def test_inspect_source_http_route_stores_safe_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        web,
        "inspect_source",
        lambda url: {
            "id": "123",
            "platform": "tiktok",
            "title": "Sample",
            "formats": [{"format_ids": ["best"], "mirrors": 1}],
        },
    )

    with running_server(tmp_path) as base:
        status, payload = post_json(
            base,
            "/api/sources/inspect",
            {"url": "https://tiktok.com/@a/video/123"},
        )

    assert status == 200
    assert payload["status"] == "inspected"
    assert payload["info"]["platform"] == "tiktok"
    assert payload["id"] in SOURCES
    assert "browser" not in json.dumps(payload)


def test_source_json_body_is_bounded(tmp_path: Path) -> None:
    with running_server(tmp_path) as base:
        request = Request(
            f"{base}/api/sources/inspect",
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


def test_video_upload_body_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "MAX_VIDEO_BODY", 4)
    with running_server(tmp_path) as base:
        request = Request(
            f"{base}/api/jobs",
            data=b"12345",
            headers={
                "content-type": "application/octet-stream",
                "x-file-name": "video.mp4",
                "x-video-enhancer-token": TOKEN,
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)

    assert error.value.code == 400


def test_failed_upload_removes_partial_local_file(tmp_path: Path) -> None:
    class ShortBody:
        def read(self, size: int) -> bytes:
            return b"12" if size > 2 else b""

    handler = object.__new__(Handler)
    handler.work_dir = tmp_path
    handler.headers = {
        "content-type": "application/octet-stream",
        "content-length": "4",
        "x-file-name": "video.mp4",
    }
    handler.rfile = ShortBody()

    with pytest.raises(ValueError, match="full video"):
        handler.create_job({})

    assert list(tmp_path.iterdir()) == []


def test_clear_session_removes_completed_local_files(tmp_path: Path) -> None:
    directory = tmp_path / "source-source1"
    directory.mkdir()
    (directory / "video.mp4").write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", {}, directory)
    source.status = "done"

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        status, payload = post_json(base, "/api/session/clear", {})

        assert status == 200
        assert payload == {"cleared": True}
        assert list(tmp_path.iterdir()) == []
        assert SOURCES == {}


def test_source_download_route_runs_async_and_reports_saved_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(
        url: str, destination: Path, format_id: str = ""
    ) -> dict[str, object]:
        assert format_id == "1080"
        destination.mkdir(parents=True)
        path = destination / "source.mp4"
        path.write_bytes(b"video")
        return {
            "path": path,
            "media": {"width": 1080, "height": 1920, "fps": 30.0},
            "format_id": format_id,
            "operation": "direct",
        }

    monkeypatch.setattr(web, "download_source", fake_download)
    source = SourceJob(
        "source1",
        "https://tiktok.com/@a/video/123",
        {"formats": []},
        tmp_path / "source-source1",
    )
    SOURCES[source.id] = source

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        status, payload = post_json(
            base,
            "/api/sources/source1/download",
            {"format_id": "1080"},
        )
        assert status == 202
        assert payload["status"] in {"queued", "downloading", "done"}

        deadline = time.monotonic() + 2
        while True:
            _, payload = get_json(base, "/api/sources/source1")
            if payload["status"] == "done" or time.monotonic() >= deadline:
                break
            time.sleep(0.01)

    assert payload["status"] == "done"
    assert payload["media"]["width"] == 1080
    assert payload["original_url"] == "/files/sources/source1/original"


def test_source_file_route_serves_only_files_inside_work_dir(tmp_path: Path) -> None:
    inside = tmp_path / "source-source1" / "original.mp4"
    inside.parent.mkdir()
    inside.write_bytes(b"inside")
    source = SourceJob("source1", "https://tiktok.com/x", {}, inside.parent)
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


def test_source_frame_route_serves_only_registered_keyframes(tmp_path: Path) -> None:
    frame = tmp_path / "source-source1" / "frames" / "frame-1.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"jpeg")
    source = SourceJob("source1", "https://tiktok.com/x", {}, frame.parents[1])
    source.keyframes = [frame]

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        request = Request(
            f"{base}/files/sources/source1/frames/1",
            headers={"x-video-enhancer-token": TOKEN},
        )
        with urlopen(request) as response:
            assert response.status == 200
            assert response.headers["content-type"] == "image/jpeg"
            assert response.read() == b"jpeg"
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    f"{base}/files/sources/source1/frames/2",
                    headers={"x-video-enhancer-token": TOKEN},
                )
            )

    assert error.value.code == 404


def test_source_enhance_route_reuses_original_with_explicit_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", {}, original.parent)
    source.original_path = original
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
            base, "/api/sources/source1/enhance", {"mode": "60"}
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


def test_source_compare_route_runs_async_and_reports_advisory_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "source-source1" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"video")
    source = SourceJob("source1", "https://tiktok.com/x", {}, original.parent)
    source.original_path = original
    source.status = "done"

    monkeypatch.setattr(
        web,
        "compare_candidate",
        lambda job, url: {
            "result": "likely_match",
            "score": 0.91,
            "advisory": True,
        },
        raising=False,
    )

    with running_server(tmp_path) as base:
        SOURCES[source.id] = source
        status, payload = post_json(
            base,
            "/api/sources/source1/compare",
            {"url": "https://instagram.com/reel/candidate"},
        )
        assert status == 202
        assert payload["comparison_status"] in {"queued", "running", "done"}

        deadline = time.monotonic() + 2
        while True:
            _, payload = get_json(base, "/api/sources/source1")
            if payload["comparison_status"] == "done" or time.monotonic() >= deadline:
                break
            time.sleep(0.01)

    assert payload["comparison_status"] == "done"
    assert payload["comparison"] == {
        "result": "likely_match",
        "score": 0.91,
        "advisory": True,
    }


def test_compare_candidate_uses_lowest_360p_variant_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "source" / "original.mp4"
    original.parent.mkdir()
    original.write_bytes(b"original")
    source = SourceJob("source1", "https://tiktok.com/x", {}, original.parent)
    source.original_path = original
    source.media = {"width": 1080, "height": 1920, "duration": 10.0}
    downloaded_to: list[Path] = []

    monkeypatch.setattr(
        web,
        "inspect_source",
        lambda url: {
            "id": "candidate",
            "platform": "instagram",
            "formats": [
                {"width": 720, "height": 1280, "tbr": 1000, "format_ids": ["high"]},
                {"width": 360, "height": 640, "tbr": 400, "format_ids": ["low"]},
                {"width": 180, "height": 320, "tbr": 100, "format_ids": ["too-low"]},
            ],
        },
    )

    def fake_download(
        url: str, destination: Path, format_id: str = ""
    ) -> dict[str, object]:
        assert format_id == "low"
        downloaded_to.append(destination)
        path = destination / "candidate.mp4"
        path.write_bytes(b"candidate")
        return {
            "path": path,
            "media": {"width": 360, "height": 640, "duration": 9.5},
        }

    monkeypatch.setattr(web, "download_source", fake_download)
    monkeypatch.setattr(
        web,
        "sample_frame_hashes",
        lambda path: [0] if path == original else [(1 << 80) - 1],
    )

    result = web.compare_candidate(source, "https://instagram.com/reel/candidate")

    assert result["result"] == "uncertain"
    assert result["duration_difference"] == 0.5
    assert result["candidate_resolution"] == [360, 640]
    assert result["candidate_format_id"] == "low"
    assert downloaded_to and not downloaded_to[0].exists()
