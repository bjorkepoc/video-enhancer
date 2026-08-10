# Launch, Privacy, And Security

Status: cross-platform Python `v0.1.0` Plus beta candidate. The separate Lite
repository is deployed at https://media-downloader-4y5.pages.dev/ and was
technically verified 2026-08-10. Deployment does not mean either product has
completed its commercial/legal launch gates. This is an engineering launch
gate, not legal advice or a promise of worldwide legal compliance.

## Product Boundary

The product family has two repositories. This Plus repository contains the
Python application with a browser UI on `127.0.0.1`; its core runs on macOS,
Windows, and Linux with local Python and FFmpeg. The public Lite repository at
https://github.com/bjorkepoc/media-downloader-lite contains the static
Cloudflare Pages site and its minimal resolver/range proxy.

| Property | Local application |
| --- | --- |
| Account or login | None |
| Application cloud backend | None |
| Operator database or media storage | None |
| Browser cookies, localStorage, or IndexedDB | None |
| Advertising | Static bundled project notice seeking a direct sponsor |
| Analytics, ad-network code, pixels, or remote scripts | None |
| Platform authentication | None; public anonymous links only |
| Working files | Process-specific operating-system temporary directory |
| User export | Explicit browser attachment download |
| Terms acceptance | Required, versioned, active checkbox before retrieval |
| Enhancement consent | Separate active confirmation before each local export |
| Privacy and copyright contact | `bjorke.poc@gmail.com` |
| Verified legal operator and business address | Not yet published |

| Property | Public Pages variant |
| --- | --- |
| Account, login, subscription, or payment | None |
| Backend | Pages Functions resolver and conditional range/download proxy |
| Server-side FFmpeg or media processing | None |
| Database or persistent application media storage | None |
| Browser cookies, localStorage, or IndexedDB | None |
| Advertising | Four static, labelled, tracking-free direct-sponsor placements |
| Analytics, pixels, personalized ads, or ad-network code | None |
| Platform authentication | None; public anonymous links only |
| Terms acceptance | Required active checkbox before each retrieval |
| Enhancement consent | Separate active checkbox; browser-only WebAssembly |
| Browser processing limit | 500 MiB source; six-hour job ceiling |
| Operator/contact verification | Not yet complete; public launch gate remains |

In the local application, the operator never receives the submitted URL or
media. The local process sends a user-initiated request directly from the user's
IP address to VSCO, Instagram, TikTok, or Facebook and their media CDNs. A file
explicitly downloaded through the browser persists wherever the user saves it.

Temporary source media, archives, audio, and enhanced copies are deleted by
**Clear local files** and on normal process shutdown. A new source replaces the
previous working set, and a new enhancement replaces the previous enhanced
copy, so the temporary session retains at most one source set and one output.
An operating-system crash, power loss, or forced termination can prevent normal
cleanup; the process directory is still inside the operating system's
temporary-file area and never becomes operator storage.

## Cookies And Privacy Notice

The local application has no cookie consent banner because it uses no cookies
or similar browser storage. If any analytics, ad tag, fingerprinting, embedded
media, consent preference, or other device storage is later added, this
conclusion must be reviewed before release.

The in-app privacy disclosure must remain accurate and say:

- files are temporary and local;
- there is no account, operator database, analytics, advertising technology,
  or browser storage;
- VSCO, Instagram, TikTok, or Facebook receives the user's direct request and
  IP address;
- a browser download is a persistent copy chosen by the user.

Any future analytics, ad-network advertising, browser storage, account system,
or changed business model requires a fresh privacy and legal review before release.

Terms acceptance and privacy information are separate. The user must actively
accept the current Terms of Use before a source request, and must separately
confirm local device processing before each enhancement. Privacy information is
provided for transparency and is not mislabeled as consent. Neither checkbox is
preselected or stored in a cookie, localStorage, or IndexedDB.

## Hosted Architecture Decision (separate Lite repository)

The public variant sends the submitted URL to a Pages Function only for the
duration of the resolver request. The Function accepts four strict platform
allowlists, validates every redirect and returned media hostname, and returns
short-lived source-CDN URLs. Preview uses the source CDN directly when possible;
the range-compatible Function proxy is the fallback for CORS, hotlink, preview,
or attachment behavior. Application code does not log or persist URLs or media.
Cloudflare and source platforms still process ordinary connection metadata, so
the production privacy notice must name those processors and the verified operator.
TikTok's signed video CDN additionally requires anonymous response cookies from
a fresh public page request; the fallback keeps them only in an in-memory map
inside that one request, sends them only to the allowlisted TikTok CDN, and
discards them without setting a browser cookie.

Optional enhancement is client-side only and starts after explicit confirmation.
The browser downloads a hash-verified, version-pinned FFmpeg WebAssembly core
from jsDelivr, then uses local CPU, memory, temporary browser storage, and
battery. Neither source nor enhanced output is uploaded to an operator-run
enhancement service. A file becomes persistent only when the visitor chooses a
download action.

The zero-cost target is a free `pages.dev` address. Static requests do not invoke
Functions because `_routes.json` includes only `/api/*`; resolver and proxy calls
share the Workers Free request allowance. The in-memory rate limit is deliberately
best-effort per isolate, while strict request, timeout, response, stream, and
hostname limits bound each request. Free-plan exhaustion can make requests fail;
it must not trigger an unreviewed paid-plan upgrade.

Earlier live edge verification succeeded for Instagram, TikTok, and a current
public Facebook example, including byte-range attachment responses. Lite now
pauses VSCO resolution before making an upstream request; its parser remains
tested for a future authorized mechanism. It does not impersonate a whitelisted
crawler, use login cookies, or send the link through an unreviewed third-party
reader.

## Advertising And Funding

The localhost application includes a static, clearly labelled house
advertisement seeking a direct sponsor. It is bundled with the application and
has no remote creative, impression request, cookie, identifier, pixel, or click
tracking. Its contact button opens the in-app contact information; the external
inquiry begins only after the visitor chooses a GitHub link.

A one-pixel bundled marker is checked locally to detect when an ad blocker hides
the placement. The resulting support message is dismissible, and the check has
no network request, identifier, or persistent storage.

Do not embed AdSense or another remote ad network in the app: doing so would
distribute advertising through desktop software, weaken the current CSP, and
make the no-tracking disclosure false.

The public Pages variant has four static, clearly labelled sponsor placements:
left rail, right rail, mobile in-flow, and bottom banner. CSS selects the
appropriate placements by viewport. There is no customer payment path and no
ad network, impression request, identifier, or click beacon. These are inventory
placeholders, not current revenue; replace their bundled text/link only after a
real sponsor, licensed creative, destination, campaign period, and operator
agreement exist.

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

A direct sponsor inside the app is the only technically local-first paid
option: fixed bundled text or artwork plus a normal HTTPS link, clearly
labelled, with no remote creative, pixel, identifier, or click beacon. Replace
the current house advertisement only when an actual sponsor, licensed creative,
destination, and campaign period exist.

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

- accepts only HTTPS VSCO, Instagram, TikTok, and Facebook hostnames;
- does not log in, read browser cookies, bypass private content, or defeat an
  access control;
- performs only the user's explicit local request;
- labels native source quality separately from synthetic upscale/interpolation;
- does not host, index, recommend, or redistribute media.

Platform-contract risk remains. A lower-risk official TikTok route requires a
registered app, Login Kit, Webhooks, approved Data Portability scopes, and user
authorization, which conflicts with the chosen no-login product boundary. A
commercial public launch should obtain platform permission or targeted legal
advice rather than representing the anonymous extractor as approved.

## Terms And Responsibility Boundary

The user is responsible for selecting content they own or are permitted to use,
following applicable law and third-party platform terms, and choosing whether
to run local enhancement. The interface states that availability, source
quality, synthetic output and uninterrupted operation are not guaranteed.

Do not claim that the operator has "no responsibility" without qualification.
The in-app limitation applies only to the fullest extent permitted by law and
preserves mandatory consumer rights and liability that cannot legally be
excluded. Norwegian Contracts Act sections 36 and 37 permit unreasonable
standard terms to be set aside or changed. Public launch still requires review
of the final operator, jurisdiction, paid/free model and hosted data flow by
qualified counsel; this checklist is not legal advice.

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
- `gallery-dl` ignores user configuration, uses an in-memory cache, never reads
  browser cookies, limits each request to 51 image/audio files, and has network,
  file-size, output, process-time, and total-download bounds.
- Subprocesses use argument arrays with `shell=False`; filenames are sanitized.
- Local HTTP clients have an idle timeout. Web-triggered FFmpeg exports discard
  raw diagnostics, enforce an 8 GiB output and six-hour ceiling, and remove
  failed partial files. Probe diagnostics are capped at 4 MiB.
- Enhancement inputs are limited to 2x scale and 240 FPS, and only one encoder
  job can be active at a time. Only one completed source set and enhanced copy
  are retained, bounding normal temporary media use to roughly 17 GiB.
- Only registered files contained by the process work directory are served;
  final file opens reject symbolic links.
- Jobs and source records live in memory and are cleared with their files.
- CI runs the full Python matrix, dependency vulnerability audit, and Bandit.
  Dependabot monitors Python and GitHub Actions dependencies.
- The public resolver accepts small same-origin JSON requests, requires current
  Terms acceptance, enforces per-isolate request throttling, and fetches only
  strict HTTPS platform allowlists with manual, revalidated redirects.
- Public media URLs are revalidated against platform-specific CDN allowlists;
  arbitrary hosts, credentials, custom ports, IP literals, invalid byte ranges,
  oversized pages, oversized request bodies, and media over the stream cap are
  rejected.
- Public static assets use restrictive CSP, framing, MIME, referrer, opener,
  resource, and permissions headers. Only `/api/*` invokes Pages Functions.
- Browser FFmpeg files are version-pinned and hash-verified before execution;
  processing requires separate consent and is limited to one in-memory job.

### Residual Risks

- A malicious process already running as the same operating-system user is
  inside this tool's trust boundary and can access loopback or local temporary
  files.
- `gallery-dl`, `yt-dlp`, FFmpeg, and optional ffprobe parse untrusted platform
  responses and media.
  Keep release pins current and verify bundled artifact digests.
- The platform controls redirects and CDN destinations after the initial strict
  hostname validation. This is acceptable for a user-run local tool but would
  require stronger egress isolation in a hosted backend.
- The 8 GiB source/export bounds and one-source/one-output working set limit normal
  operations but cannot guarantee free disk space or cleanup after forced
  termination, an operating-system crash, or power loss.
- Synthetic interpolation can create misleading frames and visual artifacts;
  generated output is explicitly labeled and never presented as native FPS.
- Platform changes can break extraction or change the best variant. No Full HD,
  bitrate, codec, or native frame-rate guarantee is possible.
- Browser preview depends on codec support in the user's browser and operating
  system. Download and FFmpeg processing can work even when an original HEVC or
  WebM stream cannot be previewed in the browser.
- The API token defends against browser-origin attacks, not a hostile local
  account. TLS adds no useful protection to this loopback-only deployment.

Never expose this server through a tunnel, reverse proxy, public bind, router
port forward, or container port publication. A hosted service is a different
architecture and needs authentication, tenancy isolation, quotas, malware
handling, abuse controls, egress filtering, durable deletion, incident
response, and a new privacy assessment.

## Release Checklist

Local application release:

- full tests pass on Python 3.12 across Linux, Windows, and macOS, with Python
  3.10-3.12 covered on Linux;
- native ad-hoc macOS package builds pass on both arm64 and x86_64;
- dependency audit reports no known vulnerabilities;
- static and deep security scans have no unresolved high-impact finding;
- authorized real VSCO, Instagram, TikTok, and Facebook public-link flows are
  checked without login;
- downloaded video resolution/FPS/codec and image/audio/archive outputs are
  verified from the saved files;
- attachment download, byte ranges, 1 FPS, frame stepping, zoom, pan, reset,
  clear-session, desktop, and mobile layouts pass browser QA;
- no cookies, browser storage, remote scripts, ad-network code, analytics, or
  non-loopback listeners are present; the bundled house advertisement has no
  remote request or tracking;
- security report path and dependency-update automation are enabled.

Public distribution release:

- the exact tagged commit passes CI and produces verified release artifacts;
- authorized VSCO, Instagram, TikTok, and Facebook flows owned by the tester or
  used with the rights holder's permission pass end to end;
- platform permission or targeted legal advice covers the chosen release;
- verified legal operator identity, public email and business address are
  published; the current advertising and security GitHub routes are not a
  substitute for these;
- the separate Apple Silicon (`arm64`) and Intel (`x86_64`) consumer Mac builds
  are Developer ID signed, notarized, and verified on their matching native
  runners, or the release is clearly limited to a technical Python-package
  audience;
- programmatic or personalized advertising remains disabled until its separate
  gates above pass; a static tracking-free house or direct sponsor ad is allowed.

## Primary Sources

- TikTok EEA terms: https://www.tiktok.com/legal/page/eea/terms-of-service/en
- TikTok Data Portability API: https://developers.tiktok.com/doc/data-portability-api-get-started
- Instagram terms: https://www.facebook.com/help/instagram/581066165581870
- Facebook terms: https://www.facebook.com/terms.php
- VSCO terms: https://www.vsco.co/about/terms-of-use
- Norway cookie guidance: https://www.datatilsynet.no/personvern-pa-ulike-omrader/internett-og-apper/bruk-av-informasjonskapsler-og-andre-sporingsteknologier/
- Norway transparency guidance: https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/informasjon-og-apenhet/
- Google AdSense desktop software policy: https://support.google.com/adsense/answer/1346295
- Google publisher download policy: https://support.google.com/publisherpolicies/answer/10436828
- Google European consent requirements: https://support.google.com/adsense/answer/13554116
