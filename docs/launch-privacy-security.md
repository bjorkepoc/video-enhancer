# Launch, Privacy, And Security

Status: implementation baseline reviewed 2026-08-06. This is an engineering
launch gate, not legal advice or a promise of worldwide legal compliance.

## Product Boundary

The product is a local Mac application with a browser UI on `127.0.0.1`.

| Property | Local application |
| --- | --- |
| Account or login | None |
| Application cloud backend | None |
| Operator database or media storage | None |
| Browser cookies, localStorage, or IndexedDB | None |
| Analytics, ads, pixels, or remote scripts | None |
| Platform authentication | None; public anonymous links only |
| Working files | Process-specific temporary directory on the user's Mac |
| User export | Explicit browser attachment download |

The operator never receives the submitted URL or video through this
architecture. The local process sends a user-initiated request directly from
the user's IP address to TikTok or Instagram and their media CDNs. A file
explicitly downloaded through the browser persists wherever the user saves it.

Temporary source videos and enhanced copies are deleted by **Clear local
files** and on normal process shutdown.
An operating-system crash, power loss, or `SIGKILL` can prevent normal cleanup;
the process directory is still inside the Mac's temporary-file area and never
becomes operator storage.

## Cookies And Privacy Notice

The local application has no cookie consent banner because it uses no cookies
or similar browser storage. If any analytics, ad tag, fingerprinting, embedded
media, consent preference, or other device storage is later added, this
conclusion must be reviewed before release.

The in-app privacy disclosure must remain accurate and say:

- files are temporary and local;
- there is no account, operator database, analytics, advertising technology,
  or browser storage;
- TikTok or Instagram receives the user's direct request and IP address;
- a browser download is a persistent copy chosen by the user.

Any future public website, analytics, live advertising, or changed business
model requires a fresh privacy and legal review before release.

## Advertising And Funding

The localhost application is intentionally ad-free. Do not embed AdSense or
another remote ad network in it: doing so would distribute advertising through
desktop software, weaken the current CSP, and make the no-tracking disclosure
false.

AdSense is not a launch option for this product until platform permission and
publisher-policy review are complete. Google's publisher policies restrict ads
on products that enable downloads when the content provider prohibits them.
If advertising is later approved, put it on a separate, crawlable HTTPS site
that never receives video URLs or files. That site needs its own operator and
contact details, privacy notice, consent/CMP flow where required, approved
publisher and slot IDs, and `ads.txt` entry.

For EEA, UK, and Swiss visitors, use a Google-certified CMP integrated with
TCF v2.3. Accept and reject must be equally prominent on the same layer,
withdrawal must be easy, and no non-essential storage or ad request may happen
before valid consent. See Google's European consent requirements below.

A direct sponsor inside the app is the only technically local-first option:
fixed bundled text or artwork plus a normal HTTPS link, clearly labelled, with
no remote creative, pixel, identifier, or click beacon. Add it only when an
actual sponsor, licensed creative, destination, and campaign period exist.

## Content Rights And Platform Terms

Users must download only public content they own or have permission to use.
Local execution, one-at-a-time use, and a private-copy exception do not create
copyright permission, a commercial license, or platform approval.

TikTok's EEA terms prohibit extracting platform data or content with automated
software not provided or approved by TikTok.
Instagram's terms effective 2025-01-01 prohibit automated access or collection
without express permission, including while logged out. Similar downloader
sites existing on the internet is not evidence that their operation complies
with contracts, copyright, privacy, advertising, or local law.

The current app therefore:

- accepts only HTTPS TikTok and Instagram hostnames;
- does not log in, read browser cookies, bypass private content, or defeat an
  access control;
- performs only the user's explicit local request;
- labels native source quality separately from synthetic upscale/interpolation;
- does not host, index, recommend, or redistribute videos.

Platform-contract risk remains. A lower-risk official TikTok route requires a
registered app, Login Kit, Webhooks, approved Data Portability scopes, and user
authorization, which conflicts with the chosen no-login product boundary. A
commercial public launch should obtain platform permission or targeted legal
advice rather than representing the anonymous extractor as approved.

## Threat Model And Controls

### Implemented Controls

- Loopback-only binding and rejection of non-local `Host` headers mitigate
  accidental network exposure and DNS rebinding.
- A random 256-bit process token protects API and file routes from blind
  cross-origin or local requests. The server never returns it from the
  bootstrap page: it arrives in a URL fragment that browsers do not send in
  HTTP requests or referrers. It is not a login or reusable credential and
  expires when the local process stops.
- Restrictive CSP, framing, MIME-sniffing, referrer, opener, resource, and
  permissions headers reduce browser attack surface.
- API JSON, HTTP range syntax, source hostname, and file containment are
  validated.
- `yt-dlp` ignores user configuration and cache, never reads browser cookies,
  disables plugins, external commands, and playlists, forces its native
  downloader, and has socket, retry, download, and source-size bounds. Output
  capture is bounded and download growth is stopped while the
  process is running, rather than checked only after completion.
- Subprocesses use argument arrays with `shell=False`; filenames are sanitized.
- Local HTTP clients have an idle timeout. Web-triggered FFmpeg exports discard
  raw diagnostics, enforce a six-hour ceiling, and remove failed partial files.
- Enhancement inputs are limited to 2x scale and 240 FPS, and only one encoder
  job can be active at a time.
- Only registered files contained by the process work directory are served;
  final file opens reject symbolic links.
- Jobs and source records live in memory and are cleared with their files.
- CI runs the full Python matrix, dependency vulnerability audit, and Bandit.
  Dependabot monitors Python and GitHub Actions dependencies.

### Residual Risks

- A malicious process already running as the same macOS user is inside this
  tool's trust boundary and can access loopback or local temporary files.
- `yt-dlp`, FFmpeg, and optional ffprobe parse untrusted platform responses and
  media.
  Keep release pins current and verify bundled artifact digests.
- The platform controls redirects and CDN destinations after the initial strict
  hostname validation. This is acceptable for a user-run local tool but would
  require stronger egress isolation in a hosted backend.
- The 8 GiB bound limits normal operations but cannot guarantee free disk space
  or cleanup after a forced process or system termination.
- Synthetic interpolation can create misleading frames and visual artifacts;
  generated output is explicitly labeled and never presented as native FPS.
- Platform changes can break extraction or change the best variant. No Full HD,
  bitrate, codec, or native frame-rate guarantee is possible.
- The API token defends against browser-origin attacks, not a hostile local
  account. TLS adds no useful protection to this loopback-only deployment.

Never expose this server through a tunnel, reverse proxy, public bind, router
port forward, or container port publication. A hosted service is a different
architecture and needs authentication, tenancy isolation, quotas, malware
handling, abuse controls, egress filtering, durable deletion, incident
response, and a new privacy assessment.

## Release Checklist

Local application release:

- full tests pass on Python 3.10-3.12;
- dependency audit reports no known vulnerabilities;
- static and deep security scans have no unresolved high-impact finding;
- real TikTok and Instagram public-link flows are checked without login;
- downloaded media resolution/FPS/codec are verified from the saved file;
- attachment download, byte ranges, 1 FPS, frame stepping, zoom, pan, reset,
  clear-session, desktop, and mobile layouts pass browser QA;
- no cookies, browser storage, remote scripts, ads, analytics, or
  non-loopback listeners are present;
- security report path and dependency-update automation are enabled.

Public distribution release:

- the exact tagged commit passes CI and produces verified release artifacts;
- authorized TikTok and Instagram flows pass end to end;
- platform permission or targeted legal advice covers the chosen release;
- operator identity and privacy, copyright, and security contacts are public;
- a consumer Mac build is Developer ID signed and notarized, or the release is
  clearly limited to a technical Python-package audience;
- any advertising remains disabled until its separate gates above pass.

## Primary Sources

- TikTok EEA terms: https://www.tiktok.com/legal/page/eea/terms-of-service/en
- TikTok Data Portability API: https://developers.tiktok.com/doc/data-portability-api-get-started
- Instagram terms: https://www.facebook.com/help/instagram/581066165581870
- Norway cookie guidance: https://www.datatilsynet.no/personvern-pa-ulike-omrader/internett-og-apper/bruk-av-informasjonskapsler-og-andre-sporingsteknologier/
- Norway transparency guidance: https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/informasjon-og-apenhet/
- Google AdSense desktop software policy: https://support.google.com/adsense/answer/1346295
- Google publisher download policy: https://support.google.com/publisherpolicies/answer/10436828
- Google European consent requirements: https://support.google.com/adsense/answer/13554116
