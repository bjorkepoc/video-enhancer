from __future__ import annotations

import json
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


@contextmanager
def running_server(work_dir: Path) -> Iterator[str]:
    Handler.work_dir = work_dir
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
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        return response.status, json.load(response)


def get_json(base: str, path: str) -> tuple[int, dict]:
    with urlopen(f"{base}{path}") as response:
        return response.status, json.load(response)


def test_safe_filename_removes_paths_and_unsafe_chars() -> None:
    assert safe_filename("../../my video!!.mp4") == "my_video_.mp4"


def test_web_ui_contains_source_first_controls() -> None:
    for control in (
        'id="input-link"',
        'id="input-local"',
        'id="source-url"',
        'id="browser-session"',
        'id="inspect-source"',
        'id="source-format"',
        'id="download-original"',
        'id="download-60"',
        'id="download-90"',
        'id="download-upscale"',
        'id="source-result"',
        'id="source-video"',
    ):
        assert control in HTML
    for label in (
        "Original platform stream",
        "Remuxed without video re-encoding",
        "Enhanced synthetic copy",
    ):
        assert label in HTML


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
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    job = create_enhancement_job(
        source, "source.mp4", {"preset": ["fast"]}, tmp_path
    )

    assert job.input_path == source
    assert job.output_path.name == "source-enhanced.mp4"


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
        lambda url, browser="": {
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
            {"url": "https://tiktok.com/@a/video/123", "browser": "chrome"},
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
            headers={"content-type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)

    assert error.value.code == 400


def test_source_download_route_runs_async_and_reports_saved_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_download(
        url: str, destination: Path, browser: str = "", format_id: str = ""
    ) -> dict[str, object]:
        assert browser == "safari"
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
            {"browser": "safari", "format_id": "1080"},
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
        with urlopen(f"{base}/files/sources/source1/original") as response:
            assert response.status == 200
            assert response.read() == b"inside"

        outside = tmp_path.parent / "outside.mp4"
        outside.write_bytes(b"outside")
        source.original_path = outside
        with pytest.raises(HTTPError) as error:
            urlopen(f"{base}/files/sources/source1/original")

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
