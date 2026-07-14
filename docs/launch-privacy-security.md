# Launch, Privacy, Ads, And Security

Status: implementation baseline verified 2026-07-13. This is an engineering
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
the user's IP address to TikTok or Instagram and their media CDNs. Search,
Lens, and TinEye links open only when the user chooses them. A file explicitly
downloaded through the browser persists wherever the user saves it.

Temporary source videos, keyframes, comparison candidates, and enhanced copies
are deleted by **Slett lokale arbeidsfiler** and on normal process shutdown.
An operating-system crash, power loss, or `SIGKILL` can prevent normal cleanup;
the process directory is still inside the Mac's temporary-file area and never
becomes operator storage.

## Cookies And Privacy Notice

The local application must not show a cookie consent banner because it uses no
cookies or similar browser storage. Norway's Data Protection Authority says a
site using only exempt, strictly necessary storage neither needs nor should use
a consent banner. If any analytics, ad tag, fingerprinting, embedded media,
consent preference, or other device storage is later added, this conclusion
must be reviewed before release.

The in-app privacy disclosure must remain accurate and say:

- files are temporary and local;
- there is no account, operator database, analytics, advertising, or browser
  storage;
- TikTok or Instagram receives the user's direct request and IP address;
- external searches happen only after a click;
- a browser download is a persistent copy chosen by the user.

A future public download or information website is a separate system. Its host
will ordinarily process IP addresses and access logs even if the app does not.
That site needs a privacy notice naming the legal operator and contact details,
the actual processors, purposes, legal bases, retention periods, transfers,
rights, complaint route, and security contacts before public launch.

## Advertising Decision

Advertising is intentionally excluded from the local UI. Remote ad code would
send device and page data to third parties, weaken the Content Security Policy,
and make the current no-cookie/no-tracking statement false.

Ads may be evaluated only on a separate public distribution site that never
receives video links or video files. Before the first ad request, all of these
gates must be complete:

- legal operator name, address or jurisdiction, and privacy contact published;
- domain, host, CDN, log retention, and processor contracts documented;
- ad provider and every downstream vendor inventoried;
- ads and nonessential tags blocked before valid consent where required;
- accept and reject offered with comparable prominence on the same layer;
- granular choices, withdrawal, and proof of consent implemented;
- Google ads in the EEA, UK, or Switzerland use a Google-certified CMP with
  IAB TCF 2.3; no Google ad tag is called without the required Purpose 1 signal;
- advertising is visibly identifiable and not disguised as an app command;
- children are not targeted and sensitive-video context is not used for ad
  profiling;
- the page honors applicable opt-out preference signals such as Global Privacy
  Control and provides required regional privacy links;
- accessibility, vendor failure, consent revocation, and tracker-blocking tests
  pass in every supported browser.

Choosing "non-personalized" ads does not automatically remove consent or
privacy obligations because ad delivery and measurement can still access a
device or process personal data.

## International Release Gates

| Market | Gate before a public site with ads or analytics |
| --- | --- |
| Norway and EEA | GDPR controller information and lawful bases; Ekomloven section 3-15 consent before nonessential storage/access; processor and transfer review; equal reject; easy withdrawal. |
| UK | UK GDPR plus current PECR storage/access guidance; consent or a documented statutory exception; child-access and online-advertising review. |
| Switzerland | Swiss privacy review plus the ad provider's Swiss consent requirements. Google requires its certified CMP flow for covered ad serving. |
| California | Determine CCPA applicability using current thresholds. If covered and selling/sharing data, publish required notices and rights methods, honor GPC/OOPS, and confirm the opt-out state. |
| Other US states | Build a state-law applicability matrix with the selected providers; implement sale/share/targeted-ad opt-outs and universal signals where required. |
| US children | Do not make the service child-directed. If COPPA applies or there is actual knowledge of a user under 13, stop data collection/ads until the notice, minimization, deletion, security, and verifiable parental-consent flow is reviewed. |
| Canada, Brazil, Australia, Japan, South Korea, India, South Africa, and other targeted markets | Obtain a jurisdiction-specific review of notices, consent/opt-out, children, cross-border transfers, retention, breach handling, and local representation before targeted promotion or ad activation. |

Do not claim "worldwide compliant." Re-run the matrix whenever the business
model, target markets, host, domain, CMP, ad provider, analytics, or processors
change.

## Content Rights And Platform Terms

Users must download only public content they own or have permission to use.
Local execution, one-at-a-time use, and a private-copy exception do not create
copyright permission, a commercial license, or platform approval.

TikTok's EEA terms, last updated August 2025, prohibit extracting platform data
or content with automated software not provided or approved by TikTok.
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
- does not host, index, recommend, or redistribute videos;
- treats repost search and frame hashes as advisory, not proof of ownership or
  identity.

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
- API JSON, upload size, HTTP range syntax, source hostname, format ID, and file
  containment are validated.
- `yt-dlp` ignores user configuration and cache, never reads browser cookies,
  disables plugins, external commands, and playlists, forces its native
  downloader, and has socket, retry, inspection, download, and source-size
  bounds. Output capture is bounded and download growth is stopped while the
  process is running, rather than checked only after completion.
- Subprocesses use argument arrays with `shell=False`; selected format IDs are
  allowlisted and filenames are sanitized.
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
- `yt-dlp`, FFmpeg, and ffprobe parse untrusted platform responses and media.
  Keep them current and install them only from trusted sources.
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
- no cookies, browser storage, remote scripts, ads, analytics, or non-loopback
  listeners are present;
- security report path and dependency-update automation are enabled.

Public distribution site release:

- operator identity, privacy contact, domain, host, processors, retention, and
  target markets are known;
- the privacy notice describes observed production behavior, including logs;
- ad/CMP gates above are complete, or the site launches without ads/analytics;
- terms, copyright/takedown contact, acceptable use, and security contact are
  published and operational;
- legal review addresses platform terms before commercial promotion.

## Primary Sources

- TikTok EEA terms: https://www.tiktok.com/legal/page/eea/terms-of-service/en
- TikTok Data Portability API: https://developers.tiktok.com/doc/data-portability-api-get-started
- Instagram terms: https://www.facebook.com/help/instagram/581066165581870
- Norway cookie guidance: https://www.datatilsynet.no/personvern-pa-ulike-omrader/internett-og-apper/bruk-av-informasjonskapsler-og-andre-sporingsteknologier/
- Norway transparency guidance: https://www.datatilsynet.no/rettigheter-og-plikter/virksomhetenes-plikter/informasjon-og-apenhet/
- UK storage/access guidance, updated 2026-04-29: https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-the-use-of-storage-and-access-technologies/
- Google certified CMP requirement: https://support.google.com/adsense/answer/13554020
- Google TCF 2.3 transition: https://support.google.com/adsense/answer/9804260
- California privacy FAQ and current thresholds: https://cppa.ca.gov/faq
- California GPC enforcement examples: https://oag.ca.gov/privacy/ccpa/enforcement
- FTC COPPA final-rule summary: https://www.ftc.gov/news-events/news/press-releases/2025/01/ftc-finalizes-changes-childrens-privacy-rule-limiting-companies-ability-monetize-kids-data
