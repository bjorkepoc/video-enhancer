# Local-First Launch Design

## Product Contract

Video Enhancer remains a local Mac application served only on `127.0.0.1`.
It has no accounts, remote application backend, database, analytics, cookies, or
cloud media storage. TikTok and Instagram requests are anonymous and limited to
public URLs. Temporary source, frame, and output files exist only while the
local process is running and can be cleared immediately from the UI.

## Video Workflow

Both video players support 1x-8x zoom around the pointer or touch midpoint,
drag-to-pan, pinch/trackpad zoom, a slider, and reset. Zoom changes viewing only;
downloaded media is never cropped or re-encoded by the viewer.

Every result has a real attachment download response so the browser saves a
physical file. Playback continues to use byte-range responses from the same
temporary local file.

## Privacy And Ads

The local application loads no third-party scripts and writes no browser
storage, so it must not show a consent banner. Its privacy disclosure states
which user-initiated requests leave the Mac and that temporary files are local.

Ads are excluded from the local application. Monetisation belongs on a separate
public distribution page because ad networks require a public approved origin
and introduce tracking, controller identity, consent, and international transfer
obligations. That page must not receive video URLs or files. Before ads are
enabled there, the operator must select a provider, publish its legal identity
and contact details, and use the provider-required certified consent platform in
the affected jurisdictions.

## Security Boundary

- Bind the application only to loopback and reject non-loopback Host headers.
- Require a random per-process token for API mutations and file access without
  using cookies.
- Remove browser-cookie extraction and all authenticated-source options.
- Bound request bodies, subprocess inspection time, and served paths.
- Send restrictive browser security headers and no-referrer policy.
- Clear in-memory job records and local temporary files on demand and at normal
  process shutdown.

The application does not bypass private-content, login, or technical access
controls. Platform terms and content-rights risk remain documented because
local processing does not remove those independent obligations.

## Verification

Automated tests cover focal-point zoom wiring, attachment downloads, local API
token enforcement, Host validation, upload limits, path containment, anonymous
source commands, and cleanup. Final verification includes the complete Python
suite, dependency/security checks, and desktop/mobile browser QA against the
running local app.
