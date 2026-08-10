# SnapDownloader-paritet for Media Downloader Plus

Sist kontrollert: 10. august 2026

Målet er funksjonell paritet der det er lovlig, sikkert og forenlig med den
lokale arkitekturen. Vi kopierer ikke SnapDownloaders navn, grafikk eller
design. Plus skal være gratis for brukeren i nåværende produktbeslutning, så
ingen betaling eller lisensserver er aktivert.

Offisielle sammenligningskilder:

- <https://snapdownloader.com/features>
- <https://snapdownloader.com/supported-sites>
- <https://snapdownloader.com/downloads>
- <https://snapdownloader.com/buy>

SnapDownloader oppgir per kontrolltidspunkt 1 000+ nettsteder, opptil 8K,
Windows 64-bit og macOS, ti video-/lydformater i tillegg til GIF, klipping,
lyduttrekk, kø, samtidige/bulk-/planlagte nedlastinger, metadata, undertekster,
YouTube-kapitler, søk, private videoer og proxy. Oppgitt pris er USD 7,99 per
måned, USD 29,99 per år eller USD 39,99 for én personlig livstidslisens.

## Statusmatrise

| Konkurrentfunksjon | Plus-status | Konkret status / neste minste steg |
| --- | --- | --- |
| Opptil 8K og valgfri kvalitetsgrense | Matchet | UI og `yt-dlp` velger best, 8K, 4K, 1440p, 1080p, 720p eller 480p uten oppskalering. Kilden må faktisk tilby kvaliteten. |
| MP4, MOV og AVI | Matchet | Separate lokale FFmpeg-eksporter; originalfilen forblir uendret. |
| MP3, AAC, M4A, WAV, AIFF, FLAC og WMA | Matchet | Lyd kan trekkes ut fra alle nedlastede videoer, ikke bare TikTok. |
| Video til GIF | Matchet | Lokal, palettbasert GIF-eksport. |
| Innebygd videoklipper | Matchet | Valgfri start/slutt i sekunder før lokal eksport. En visuell tidslinje er ikke bygget ennå. |
| Metadata i eksport | Matchet delvis | FFmpeg kopierer container-metadata; plattformspesifikke beskrivelser/cover art er ikke garantert. |
| Beste tilgjengelige hastighet | Matchet delvis | Ingen kunstig hastighetsgrense; én aktiv jobb beskytter disk, CPU og brukerens maskin. |
| 360/VR-original | Matchet delvis | Originalstrømmen beholdes når en støttet kilde tilbyr den; ingen egen YouTube-/VR-flyt ennå. |
| Enkel lime inn / velg / last ned-flyt | Matchet | Eksplisitt originalnedlasting, formatvalg og fysisk filhandling. Lokal behandling krever separat samtykke. |
| macOS | Matchet delvis | Apple Silicon- og Intel-pakker bygges; signering/notarisering og offentlig release gjenstår. |
| Windows 64-bit | Matchet delvis | Python-hjulet og testmatrisen støtter Windows; selvstendig installasjonspakke gjenstår. |
| Linux | Matchet delvis | Python-hjulet kan kjøres lokalt; ingen selvstendig pakke ennå. |
| 1 000+ nettsteder | Mangler | Plus har en streng fireplattform-allowlist. Hver ny plattform må få vilkårs-, sikkerhets- og reell kildeverifisering før den åpnes. |
| YouTube-spillelister og kanaler | Mangler | Krever egen tillatt YouTube-produktbeslutning og bounded playlist-modell. |
| Opptil 100 lenker / bulk | Mangler | Nå én kilde om gangen. Første forsvarlige versjon blir en lokal sekvensiell kø med lav grense. |
| Samtidige nedlastinger | Mangler | Bevisst én aktiv jobb nå; parallellitet legges først til etter målte ressursgrenser. |
| Nedlastingskø | Mangler | Lokal kø og pause/fortsett er ikke implementert. |
| Planlagte nedlastinger | Mangler | Krever en vedvarende lokal desktop-prosess og tydelig systemtillatelse. |
| Ett-klikksmodus | Mangler | Kan lagre lokale format-/kvalitetsvalg når personvern- og reset-flyten er bestemt. |
| YouTube-undertekster | Mangler | Ingen YouTube-støtte eller undertekstvelger ennå. |
| YouTube-kapitler som filer | Mangler | Ingen YouTube-støtte eller kapittelvelger ennå. |
| Innebygd YouTube-søk | Mangler | Ikke bygget; URL-flyt prioriteres fremfor en egen søkeindeks. |
| Desktop-varsler | Mangler | Kan bruke operativsystemets native varsel etter eksplisitt tillatelse. |
| Mørk modus | Mangler | Eksisterende lyse design beholdes til en komplett mørk visuell QA-pass er gjort. |
| 24/7 kundestøtte | Ekstern drift | Kan ikke løses i kode; krever bemanning og kontakt-SLA. |
| Privat innhold via innlogget nettleser | Skal ikke bygges | Produktgrensen er offentlige, utloggede lenker uten cookies eller kontotilgang. |
| Proxy for å omgå geografiske sperrer | Skal ikke bygges | Ingen omgåelse av tilgangskontroll, region-, innloggings- eller DRM-sperrer. |
| Betaling, lisensnøkler og prøveperiode | Ikke aktivert | Dagens beslutning er gratis/ad- eller sponsorfinansiert. Ingen kunde skal belastes nå. |

## Rekkefølge videre

1. Fullfør Windows 64-bit selvstendig pakke og verifiser faktisk installasjon.
2. Legg til en liten lokal, sekvensiell kø før bulk, samtidighet og planlegging.
3. Legg til undertekster, kapitler, varsler og ett-klikkvalg gjennom eksisterende
   `yt-dlp`- og operativsystemfunksjoner.
4. Utvid nettstedskatalogen bare plattform for plattform etter tillatelse,
   sikkerhetskontroll og vedlikeholdbare tester.

En funksjon regnes ikke som matchet bare fordi `yt-dlp` eller FFmpeg teknisk kan
gjøre den. Den må være eksponert i Plus, avgrenset, testet og distribuert på den
aktuelle plattformen.
