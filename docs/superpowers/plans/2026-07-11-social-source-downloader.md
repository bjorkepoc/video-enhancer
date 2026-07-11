# Social Source Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source-first TikTok and Instagram inspection, original download, verified media metadata, optional enhancement, and practical repost discovery to the existing local Mac web app.

**Architecture:** Put all downloader logic in one new `sources.py` module backed by the installed yt-dlp and FFmpeg executables. Keep `web.py` as the HTTP/UI boundary, reuse its existing enhancement job builder for downloaded files, and turn the old Node prototype into a launcher for the canonical Python app.

**Tech Stack:** Python 3.10+, stdlib HTTP server/subprocess/dataclasses, yt-dlp, FFmpeg/ffprobe, pytest, browser QA.

## Global Constraints

- Work directly on `main`; preserve unrelated files and push immediately after every successful commit.
- `Original` must never apply video filters or invoke a video encoder.
- Only HTTPS TikTok and Instagram hosts are accepted before any network subprocess starts.
- Never return signed media URLs or browser cookies through the HTTP API.
- Browser cookies are opt-in per request and limited to `chrome`, `safari`, or `firefox`.
- Derived 60/90 FPS and upscale files must be labelled synthetic or enhanced.
- Use existing yt-dlp and FFmpeg capabilities; add no downloader, image, or web framework dependency.
- Each task follows red-green-refactor and leaves the full suite green.

---

### Task 1: Social URL And Format Inspection Core

**Files:**
- Create: `src/video_enhancer/sources.py`
- Create: `tests/test_sources.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `SourceError`
- Produces: `validate_social_url(raw: str) -> str`
- Produces: `browser_args(browser: str) -> list[str]`
- Produces: `group_formats(formats: list[dict[str, Any]]) -> list[dict[str, Any]]`
- Produces: `inspect_source(url: str, browser: str = "", *, yt_dlp: str = "yt-dlp") -> dict[str, Any]`

- [ ] **Step 1: Add failing URL, browser, grouping, and subprocess tests**

```python
def completed_json(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["yt-dlp"], 0, json.dumps(payload), "")


def test_validate_social_url_allows_only_supported_https_hosts() -> None:
    assert validate_social_url("https://vm.tiktok.com/abc") == "tiktok"
    assert validate_social_url("https://www.instagram.com/reel/abc/") == "instagram"
    for url in ("http://tiktok.com/a", "https://tiktok.com.evil.test/a", "https://example.com/a"):
        with pytest.raises(SourceError):
            validate_social_url(url)


def test_group_formats_collapses_cdn_mirrors() -> None:
    grouped = group_formats([
        {"format_id": "1080-0", "width": 1080, "height": 1920, "fps": 30,
         "tbr": 767, "vcodec": "h265", "acodec": "aac", "ext": "mp4"},
        {"format_id": "1080-1", "width": 1080, "height": 1920, "fps": 30,
         "tbr": 767, "vcodec": "h265", "acodec": "aac", "ext": "mp4"},
    ])
    assert grouped[0]["format_ids"] == ["1080-0", "1080-1"]
    assert grouped[0]["mirrors"] == 2


def test_inspect_source_never_returns_signed_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = completed_json({
        "id": "123", "title": "Sample", "webpage_url": "https://tiktok.com/x",
        "formats": [{"format_id": "best", "url": "https://signed.example/token",
                     "width": 1080, "height": 1920, "vcodec": "h265", "acodec": "aac"}],
    })
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)
    result = inspect_source("https://www.tiktok.com/@a/video/123")
    assert "signed.example" not in json.dumps(result)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_sources.py -q`

Expected: import failure because `video_enhancer.sources` does not exist.

- [ ] **Step 3: Implement the minimal inspection module**

```python
SUPPORTED_HOSTS = {"tiktok.com": "tiktok", "instagram.com": "instagram"}
SUPPORTED_BROWSERS = {"", "chrome", "safari", "firefox"}


def validate_social_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise SourceError("Use an HTTPS TikTok or Instagram video URL.")
    host = parsed.hostname.lower().rstrip(".")
    for domain, platform in SUPPORTED_HOSTS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    raise SourceError("Only TikTok and Instagram video URLs are supported.")


def browser_args(browser: str) -> list[str]:
    if browser not in SUPPORTED_BROWSERS:
        raise SourceError("Browser session must be none, chrome, safari, or firefox.")
    return ["--cookies-from-browser", browser] if browser else []
```

`inspect_source` runs `yt-dlp --no-playlist --skip-download --dump-single-json`, parses JSON, removes every raw format URL, groups mirrors, sorts highest resolution/FPS/bitrate first, and returns `id`, `platform`, `title`, `uploader`, `duration`, `thumbnail`, `webpage_url`, and `formats`.

- [ ] **Step 4: Add yt-dlp as the single runtime dependency**

```toml
dependencies = ["yt-dlp>=2026.7.4"]
```

- [ ] **Step 5: Run focused and full tests**

Run: `.venv/bin/python -m pip install -e '.[dev]'`

Run: `.venv/bin/python -m pytest tests/test_sources.py -q`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add pyproject.toml src/video_enhancer/sources.py tests/test_sources.py
git commit -m "feat: inspect social video source formats"
git push origin main
```

### Task 2: Original Download And Saved-File Probe

**Files:**
- Modify: `src/video_enhancer/sources.py`
- Modify: `tests/test_sources.py`

**Interfaces:**
- Consumes: `validate_social_url`, `browser_args`, `inspect_source`
- Produces: `build_download_command(url: str, destination: Path, browser: str = "", format_id: str = "") -> list[str]`
- Produces: `parse_ffprobe(payload: dict[str, Any]) -> dict[str, Any]`
- Produces: `download_source(url: str, destination: Path, browser: str = "", format_id: str = "", *, yt_dlp: str = "yt-dlp") -> dict[str, Any]`
- Produces: `probe_media(path: Path, *, ffprobe: str = "ffprobe", ffmpeg: str = "ffmpeg") -> dict[str, Any]`

- [ ] **Step 1: Add failing command, format validation, and probe parser tests**

```python
def test_download_command_is_source_first_and_has_no_recode_flags(tmp_path: Path) -> None:
    command = build_download_command("https://tiktok.com/x", tmp_path, "", "")
    assert command[command.index("-f") + 1] == "bv*+ba/b"
    assert "--recode-video" not in command
    assert "--remux-video" not in command


def test_parse_ffprobe_reports_saved_stream() -> None:
    media = parse_ffprobe({"streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1080,
         "height": 1920, "avg_frame_rate": "30/1", "bit_rate": "664000"},
        {"codec_type": "audio", "codec_name": "aac"},
    ], "format": {"duration": "105.03", "size": "10076075", "bit_rate": "767000"}})
    assert media["fps"] == 30.0
    assert media["video_codec"] == "hevc"
    assert (media["width"], media["height"]) == (1080, 1920)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_sources.py -q`

Expected: missing download/probe functions.

- [ ] **Step 3: Implement source-first download with bounded output**

```python
BEST_FORMAT = "bv*+ba/b"


def selected_format(format_id: str) -> str:
    if not format_id:
        return BEST_FORMAT
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", format_id):
        raise SourceError("Invalid source format.")
    return f"{format_id}+ba/{format_id}"
```

Before download, re-inspect and require the selected ID in the current format list. Run yt-dlp with `--no-playlist`, `--no-overwrites`, a restricted output template, and `--print after_move:FILE:%(filepath)s`. Resolve the printed path and require it to be inside `destination`. Delete `.part` files after a failed process. Mark the result `direct` unless yt-dlp selected separate video/audio formats, in which case mark it `remuxed`.

- [ ] **Step 4: Implement ffprobe JSON with an FFmpeg fallback**

Use `ffprobe -v error -show_streams -show_format -of json`. If unavailable, run `ffmpeg -hide_banner -i <file> -map 0:v:0 -frames:v 1 -f null -` and parse codec, dimensions, FPS, duration, and total bitrate from stderr. Always add actual file size from `Path.stat()`.

- [ ] **Step 5: Verify RED-GREEN and the full suite**

Run: `.venv/bin/python -m pytest tests/test_sources.py -q`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add src/video_enhancer/sources.py tests/test_sources.py
git commit -m "feat: download and verify original social video"
git push origin main
```

### Task 3: Social Source HTTP API And Existing Enhancer Reuse

**Files:**
- Modify: `src/video_enhancer/web.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: `inspect_source`, `download_source`, `probe_media`, existing `Job`, `run_job`, `build_options`
- Produces: `SourceJob`, `source_payload`, `create_enhancement_job(input_path, original_name, params)`
- Produces HTTP: `POST /api/sources/inspect`, `POST /api/sources/<id>/download`, `GET /api/sources/<id>`, `POST /api/sources/<id>/enhance`, `GET /files/sources/<id>/original`

- [ ] **Step 1: Add failing helper and HTTP tests**

```python
def test_enhancement_from_source_reuses_file_without_upload(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    job = create_enhancement_job(source, "source.mp4", {"preset": ["fast"]}, tmp_path)
    assert job.input_path == source
    assert job.output_path.name == "source-enhanced.mp4"


def test_source_payload_never_contains_browser_or_signed_url() -> None:
    job = SourceJob(
        id="source1",
        url="https://tiktok.com/x",
        info={"formats": [{"format_id": "best"}]},
        directory=Path("outputs/web/source1"),
    )
    payload = source_payload(job)
    assert "browser" not in payload
    assert "signed" not in json.dumps(payload)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_web.py -q`

Expected: missing source-job helpers.

- [ ] **Step 3: Add a minimal in-memory source job table**

```python
@dataclass
class SourceJob:
    id: str
    url: str
    info: dict[str, Any]
    directory: Path
    status: str = "inspected"
    original_path: Path | None = None
    media: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    logs: list[str] = field(default_factory=list)
```

Use the existing global lock and the same deliberate in-memory ceiling as enhancement jobs. Run downloads in daemon threads so the HTTP request returns immediately.

- [ ] **Step 4: Add bounded JSON parsing and source routes**

Read at most 20 KB JSON. Validate route IDs against the source table. The inspect response stores no browser choice. The download request carries browser/format selection again. File serving checks `Path.resolve().is_relative_to(work_dir.resolve())` before opening the file.

- [ ] **Step 5: Refactor upload job creation through one shared path helper**

Move command/job/thread creation into `create_enhancement_job`. The existing upload route writes its file then calls it. The source enhancement route calls it directly with `SourceJob.original_path` and applies these mode overrides:

```python
MODES = {
    "60": {"fps": ["60"], "scale": ["1"], "preset": ["quality"]},
    "90": {"fps": ["90"], "scale": ["1"], "preset": ["ultra"]},
    "upscale": {"no_interpolate": ["1"], "scale": ["2"], "preset": ["quality"]},
}
```

- [ ] **Step 6: Run focused and full tests**

Run: `.venv/bin/python -m pytest tests/test_web.py -q`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 7: Commit and push**

```bash
git add src/video_enhancer/web.py tests/test_web.py
git commit -m "feat: add social source web api"
git push origin main
```

### Task 4: Link-First Web Workflow

**Files:**
- Modify: `src/video_enhancer/web.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: source HTTP endpoints from Task 3
- Produces UI: Link/Local file segmented input, source variants, original/enhanced actions, source polling and preview

- [ ] **Step 1: Add failing static UI contract tests**

```python
def test_web_ui_contains_source_first_controls() -> None:
    for control in (
        'id="input-link"', 'id="input-local"', 'id="source-url"',
        'id="browser-session"', 'id="inspect-source"', 'id="source-format"',
        'id="download-original"', 'id="download-60"', 'id="download-90"',
        'id="download-upscale"',
    ):
        assert control in HTML
```

- [ ] **Step 2: Run the UI contract test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_web.py::test_web_ui_contains_source_first_controls -q`

Expected: missing controls.

- [ ] **Step 3: Implement the compact source workflow in the existing HTML**

Use native buttons/selects/table and existing colours. The initial state shows Link mode. Inspect fills a source summary and a `<select>` whose first option is `Best available`; each grouped option shows resolution, FPS when known, codec, bitrate, and mirror count. Download actions poll the source job, then set the input preview to the original file. Derived actions call the enhancement route and reuse existing enhancement polling.

Keep all fixed controls stable with explicit grid tracks and switch to one column below 980 px. Do not put panels inside panels.

- [ ] **Step 4: Add browser-side validation and honest labels**

Reject empty URLs before fetch. Show `Original platform stream`, `Remuxed without video re-encoding`, or `Enhanced synthetic copy` from API state. Keep 60/90/upscale buttons disabled until the original download is complete.

- [ ] **Step 5: Run focused and full tests**

Run: `.venv/bin/python -m pytest tests/test_web.py -q`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add src/video_enhancer/web.py tests/test_web.py
git commit -m "feat: add link-first downloader workflow"
git push origin main
```

### Task 5: Repost Discovery And Candidate Comparison

**Files:**
- Modify: `src/video_enhancer/sources.py`
- Modify: `src/video_enhancer/web.py`
- Modify: `tests/test_sources.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Produces: `search_links(info: dict[str, Any]) -> dict[str, str]`
- Produces: `extract_keyframes(path: Path, destination: Path, *, ffmpeg: str = "ffmpeg") -> list[Path]`
- Produces: `frame_hash(raw: bytes, width: int = 17, height: int = 16) -> int`
- Produces: `compare_hashes(left: list[int], right: list[int]) -> dict[str, Any]`
- Produces HTTP: frame files and `POST /api/sources/<id>/compare`

- [ ] **Step 1: Add failing metadata-link and hash tests**

```python
def test_search_links_cover_metadata_and_both_platforms() -> None:
    links = search_links({"id": "123", "title": "Closet Cleanout", "uploader": "aurora"})
    assert set(links) == {"web", "tiktok", "instagram", "google_lens", "tineye"}
    assert "Closet+Cleanout" in links["web"]


def test_compare_hashes_classifies_match_uncertain_and_different() -> None:
    assert compare_hashes([0], [0])["result"] == "likely_match"
    assert compare_hashes([0], [(1 << 80) - 1])["result"] == "uncertain"
    assert compare_hashes([0], [(1 << 256) - 1])["result"] == "different"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_sources.py tests/test_web.py -q`

Expected: missing discovery functions/routes.

- [ ] **Step 3: Implement zero-key search links and three keyframes**

Build percent-encoded exact-title/uploader searches for the open web, `site:tiktok.com`, and `site:instagram.com`. Link to `https://lens.google.com/` and `https://tineye.com/`. Extract JPEG frames at 25%, 50%, and 75% of probed duration, capped to 960 px wide.

- [ ] **Step 4: Implement local candidate comparison**

Download the explicitly submitted candidate URL into a temporary source directory using the lowest variant at least 360 px high, extract five evenly spaced `17x16` grayscale frames through FFmpeg rawvideo, compute horizontal difference hashes, and compare median Hamming similarity. Return `likely_match` at `>= 0.85`, `uncertain` at `>= 0.65`, otherwise `different`. Always label the result advisory.

- [ ] **Step 5: Add source-result UI for keyframes, searches, and candidate URL**

Show three downloadable keyframe thumbnails, five search buttons, one candidate URL input, and one compare button. Render result, score, duration difference, and resolution difference. Do not auto-upload frames to any third party.

- [ ] **Step 6: Run focused and full tests**

Run: `.venv/bin/python -m pytest tests/test_sources.py tests/test_web.py -q`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 7: Commit and push**

```bash
git add src/video_enhancer/sources.py src/video_enhancer/web.py tests/test_sources.py tests/test_web.py
git commit -m "feat: add repost discovery tools"
git push origin main
```

### Task 6: Legacy Launcher And Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/usage-and-requirements.md`
- Modify: `/Users/po/dev/lossless-social-video/package.json`
- Delete: `/Users/po/dev/lossless-social-video/server.js`
- Delete: `/Users/po/dev/lossless-social-video/public/index.html`

**Interfaces:**
- Consumes: installed `video-enhancer-web` script
- Produces: `npm run setup`, `npm start`, and `npm run check` compatibility commands

- [ ] **Step 1: Replace the prototype scripts with the canonical launcher**

```json
{
  "name": "lossless-social-video",
  "version": "0.2.0",
  "private": true,
  "scripts": {
    "setup": "python3 -m venv .venv && .venv/bin/python -m pip install -U -e ../video-enhancer",
    "start": ".venv/bin/video-enhancer-web --port 3100 --work-dir ../video-enhancer/outputs/web",
    "check": ".venv/bin/video-enhancer --list-encoders"
  }
}
```

Delete the now-unused Node server and duplicate HTML. Keep existing downloaded media untouched.

- [ ] **Step 2: Document source and enhancement semantics**

Document setup, both launch commands, supported URL hosts, browser-session privacy, source inspection, original/remuxed/enhanced labels, 60/90 FPS limits, keyframe search, and candidate comparison ceilings. State that platform compression cannot be reversed.

- [ ] **Step 3: Verify both entrypoints**

Run: `.venv/bin/video-enhancer-web --help`

Run from `/Users/po/dev/lossless-social-video`: `npm run setup && npm run check`

Expected: both commands exit 0.

- [ ] **Step 4: Commit and push the tracked repo changes**

```bash
git add README.md docs/usage-and-requirements.md
git commit -m "docs: explain social source workflow"
git push origin main
```

The launcher directory is not a Git repository, so report its local-only state explicitly.

### Task 7: Live Source, API, And Browser Verification

**Files:**
- Modify only if verification exposes a defect in files from Tasks 1-6.

**Interfaces:**
- Verifies all prior task outputs end to end.

- [ ] **Step 1: Run static and unit gates**

Run: `.venv/bin/python -m py_compile src/video_enhancer/*.py`

Run: `.venv/bin/python -m pytest`

Run: `git diff --check`

Expected: all exit 0.

- [ ] **Step 2: Run live source inspection**

Inspect `https://vm.tiktok.com/ZNREU73wW/` and require a grouped 1080x1920 HEVC variant with two mirrors. Inspect `https://www.instagram.com/reel/Chunk8-jurw/` anonymously and require at least one video variant.

- [ ] **Step 3: Download and probe the provided TikTok source**

Require the saved original to report 1080x1920, HEVC/H.265, 30 FPS, and no enhancement command. Decode one frame with FFmpeg.

- [ ] **Step 4: Smoke one derived 60 FPS output**

Use a short generated or trimmed local clip so verification completes quickly. Require a separate output file that FFmpeg decodes and reports 60 FPS.

- [ ] **Step 5: Run Browser-plugin QA**

The flow under test is: app loads -> inspect TikTok link -> source variants render -> download original -> original preview appears -> start 60 FPS derivative -> separate result appears.

Check page identity, nonblank DOM, no error overlay, console warnings/errors, desktop screenshot, mobile screenshot, invalid URL state, and the full interaction path.

- [ ] **Step 6: Verify clean pushed state**

Run: `git status --short --branch`

Run: `git log -7 --oneline --decorate`

Expected: `main...origin/main` with no local changes. If a verification fix was needed, commit it, rerun all gates, and push immediately.
