# Prosjektstatus og beslutningslogg

Sist oppdatert: 10. august 2026

Prosjekt: `video-enhancer` / Media Downloader

Arbeidskopi: `/Users/po/dev/video-enhancer`
Produksjon: <https://media-downloader-4y5.pages.dev/>

Dette er den samlede lokale fasiten for hva prosjektet var, hva som er gjort,
hva som er live, hvilke produktbeslutninger som gjelder, og hva som fortsatt
gjenstår. Oppdater dato og berørte avsnitt når arkitektur, kostnad, drift eller
produktgrense endres.

## Kortversjonen

Prosjektet består nå av to flater som skal leve videre samtidig:

1. Den eksisterende lokale Python-/FFmpeg-appen med hele funksjonssettet.
2. En offentlig, betalingsfri nettside på Cloudflare Pages med en minimal
   Pages Functions-resolver.

## Fysisk prosjektseparasjon

Fra 10. august 2026 er variantene også skilt i to lokale Git-prosjekter:

- **Media Downloader Lite:** `/Users/po/dev/media-downloader-lite`, commit
  `c3c86b2`, <https://github.com/bjorkepoc/media-downloader-lite>. Dette er den
  rene Cloudflare Pages/Functions-kilden og den aktive produksjonskilden.
- **Media Downloader Plus/Premium-base:** `/Users/po/dev/video-enhancer`.
  GitHub-prosjektet er <https://github.com/bjorkepoc/video-enhancer>. Dette er
  den eksisterende Python-, CLI-, desktop- og native FFmpeg-basen.

Ingen filer ble slettet fra den verdifulle Plus-arbeidskopien under utskillingen.
Pages/Functions-filene finnes derfor fortsatt som lokale, untracked kopier der,
men de inngår ikke i Plus-committen eller Plus-repoet på GitHub. Lite er pushet
til eget remote og er den sikre, reproduserbare kilden for disse filene.

Den offentlige siden lar brukeren lime inn en offentlig Instagram-, TikTok-
eller Facebook-lenke og hente det beste originale mediet kilden faktisk
eksponerer anonymt. VSCO-lenker gjenkjennes, men serveroppløsningen stanses før
noen upstream-request. Cloudflare skal ikke oppskalere, generere, interpolere
eller re-enkode mediet. Valgfri forbedring skjer i brukerens egen nettleser
etter et separat, aktivt samtykke.

Målet er 0 kr i fast driftskostnad nå. Siden har ingen kontoer, abonnement,
betaling, database, persistent medielagring eller betalt Cloudflare-produkt.
Brukerne skal ikke betale; inntektsmodellen er annonser/sponsorer. De fire
feltene åpner nå en strukturert sponsorhenvendelse i Lite-repoet, men gir fortsatt
0 kr i inntekt frem til en faktisk sponsoravtale finnes.

## Bindende produktbeslutninger

- Ingen eksisterende funksjonalitet skal slettes fra prosjektet.
- Originalmediet skal ikke re-enkodes når det hentes.
- Serveren skal aldri kjøre FFmpeg, oppskalering, bildegenerering,
  videoforbedring eller FPS-interpolering.
- 60/90 FPS, oppskalering, filtre og MP3-eksport kan fortsatt tilbys, men de
  skal kjøre på brukerens maskin og kreve uttrykkelig samtykke.
- Den lokale Python-/FFmpeg-appen og CLI-en skal bevares.
- Den offentlige siden skal være gratis for brukeren.
- Det skal ikke bygges abonnement, checkout, betalingskonto eller betalingsmur.
- Finansiering skal komme fra annonser eller direkte sponsorer, ikke kunder.
- Første offentlige versjon skal bruke en gratis `pages.dev`-adresse.
- Ingen database, kontoer, analyseverktøy eller persistent URL-/medielagring nå.
- Bare offentlige, utloggede innlegg støttes. Ingen private kontoer, innlogging,
  nettlesercookies, DRM-omgåelse eller omgåelse av tilgangskontroll.
- Direkte kilde-CDN brukes når mulig. En tynn Worker-proxy brukes bare når
  CORS, hotlink-beskyttelse, byte ranges eller `Content-Disposition` krever det.
- Offentlige Cobalt-instanser brukes ikke, og egen Cobalt-instans driftes ikke.
- Hvis beste video og lyd bare finnes som separate strømmer, leveres de separat
  på den offentlige siden. De slås ikke sammen på serveren.
- En bruker får ikke en fysisk fil i Downloads bare ved å lime inn en lenke.
  Nettverket og nettleserminne/cache brukes til oppløsning og forhåndsvisning;
  varig nedlasting skjer først når brukeren velger en nedlastingshandling.

## Hvordan prosjektet var før denne omleggingen

Den historiske Plus-basen før omleggingen var commit `e0156e0`. Der var
produktet i hovedsak en lokal Video Enhancer-beta:

- Brukeren måtte kjøre/installere en lokal Python-app eller planlagt macOS-pakke.
- En lokal HTTP-server kjørte bare på `127.0.0.1`.
- `yt-dlp` hentet offentlige TikTok- og Instagram-kilder.
- FFmpeg kjørte lokalt for oppskalering, interpolering og eksport.
- TikTok og Instagram var de opprinnelige lenkeplattformene.
- Det fantes CLI, lokale presets, frame stepping, zoom og encoder-valg.
- Originale strømmer og forbedrede, syntetiske kopier var separate.
- Ingen offentlig nettside eller cloud-backend var satt opp.
- Ingen kontoer, betaling eller analyseverktøy fantes.
- En statisk «Advertise here»-kontakt var den eneste annonseflaten og tjente
  ikke penger.
- macOS-utgivelse var teknisk forberedt, men offentlig distribusjon var fortsatt
  blokkert av signering/notarisering og andre lanseringskrav.

Den gamle lokale appen er ikke erstattet. Den er videreført og utvidet.

## Feiltolkningen som ble korrigert

I planleggingen ble «ingen videobehandling på serveren» først tolket som at
oppskalering, FPS, filtre, resultatvisning, CLI og MP3-eksport skulle fjernes
helt. Det var feil. Det finnes ikke en separat, generell bildegenerator i
nåværende kodebase; beslutningen er at eventuell fremtidig syntese heller ikke
skal kjøre på serveren.

Riktig tolkning er:

- Funksjonene skal fortsatt finnes.
- De skal kjøre lokalt hos brukeren.
- Brukeren skal informeres om CPU-, minne-, batteri- og lagringsbruk.
- Lokal behandling skal starte først etter et separat samtykke.
- Cloudflare skal bare finne og levere offentlig originalmedia.

Ingen deletion-first-migrering som fjerner enhancement-funksjonene ble derfor
gjennomført. Den lokale appen, CLI-en, presets og FFmpeg-koden er bevart.

## Dagens arkitektur

```text
Brukerens nettleser
  |
  |-- statisk HTML/CSS/JavaScript ---------------------- Cloudflare Pages
  |
  |-- POST /api/resolve med offentlig lenke ----------- Pages Function
  |      |-- streng plattform-/vertsallowlist
  |      |-- anonym henting og parsing av offentlig side
  |      `-- kortvarig JSON med kilde-CDN-lenker
  |
  |-- forhåndsvisning/nedlasting ----------------------- kilde-CDN direkte
  |      `-- /api/media bare ved CORS/range/download-problemer
  |
  `-- valgfri FFmpeg WebAssembly ----------------------- kun i nettleseren
         `-- separat samtykke før 60/90 FPS, 2x, filtre eller MP3
```

Cloudflare-resolveren leser plattformens offentlige HTML/JSON og velger det
beste enkeltmediet som er eksponert. Den lagrer ikke applikasjonsdata etter
requesten. Den tynne medieproxyen kan viderestrømme bytes, men prosesserer eller
lagrer dem ikke persistent.

## Det som er implementert

### Offentlig nettside

I det separate Lite-repoet inneholder `public-site/` statisk HTML, CSS og
JavaScript:

- lenkefelt for VSCO, Instagram, TikTok og Facebook;
- aktiv godkjenning av gjeldende brukervilkår før hver resolver-request;
- forhåndsvisning av bilde, video og lyd;
- eksplisitte nedlastingsknapper;
- støtte for karuseller/flere mediefiler;
- frame stepping, 1 FPS og zoom i visningen;
- lokal FFmpeg WebAssembly-behandling etter separat samtykke;
- Privacy- og Terms-dialoger;
- statiske, tydelig merkede sponsorflater;
- responsivt desktop-/mobiloppsett;
- ingen betalings- eller innloggingsflyt.

### Edge-resolver og medieproxy

I det separate Lite-repoet inneholder `functions/` to Pages Functions:

- `/api/resolve`: validerer lenken, krever vilkårssamtykke og parser den
  offentlige kilden.
- `/api/media`: viderestrømmer kun allowlistet kilde-CDN-media ved behov og
  støtter `GET`, `HEAD`, byte ranges, inline preview og sikre vedleggsnavn.

TikTok-, Instagram- og Facebook-mønstre er delvis tilpasset fra det minste
relevante uttrekket i MIT-prosjektet `Vette1123/social-media-downloader`.
Attribusjon finnes i Lite-kildekoden og Lite-repoets `THIRD_PARTY_NOTICES.md`;
hele prosjektet ble ikke importert. Lite gjenkjenner VSCO-lenker, men stanser
både resolver og proxy; Plus beholder sin separate lokale VSCO-implementasjon.

### Lokal behandling i den offentlige nettleseren

Lite-repoets `public-site/local-processor.js`:

- laster en versjonspinnet FFmpeg WebAssembly-core først etter samtykke;
- kontrollerer SHA-256 før den kjører;
- tilbyr 60 FPS, 90 FPS, 2x Lanczos-oppskalering, clean/sharpen-filtre og
  MP3-eksport;
- bruker brukerens CPU, minne, batteri og midlertidige nettleserminne;
- laster ikke kilde eller resultat opp til en enhancement-server;
- beholder originalen uendret og lager en separat syntetisk fil;
- begrenser kildefil til 500 MiB, én jobb om gangen og maksimalt seks timer.

### Bevart lokal Python-app

Den lokale appen og CLI-en er fortsatt prosjektets bredeste funksjonsflate:

- TikTok, Instagram, VSCO og Facebook;
- originale bilder, video, lyd og flerfilsposter;
- lokale ZIP-/lydresultater der det er relevant;
- presets `fast`, `balanced`, `quality` og `ultra`;
- 48, 60, 90, 144 eller egendefinert FPS opptil 240;
- 2x Lanczos/Bicubic;
- kildekvalitet som `best`, 8K, 4K, 1440p, 1080p, 720p eller 480p uten
  oppskalering av originalnedlastingen;
- lokal klipping og eksport til MP4, MOV, AVI, MP3, AAC, M4A, WAV, AIFF,
  FLAC, WMA eller GIF etter separat samtykke;
- `libx264`/`libx265`, dry-run og CLI;
- lokal midlertidig arbeidsmappe og eksplisitt opprydding.

Ingen eksisterende Plus-funksjon er fjernet, men Lite eksponerer foreløpig ikke
alle avanserte CLI-/desktopvalg. Eksempelvis ligger 48/144/custom FPS,
encoder-valg, dry-run og alle presets fortsatt bare i den lokale appen. Full
hosted UI-paritet er derfor et mulig senere arbeid, ikke en ferdig leveranse.

## Plattformstatus 10. august 2026

| Plattform | Offentlig Pages-resolver | Lokal app | Nåværende merknad |
| --- | --- | --- | --- |
| Instagram | Verifisert | Støttet | Offentlige eksempler og byte-range-nedlasting virket |
| TikTok | Verifisert | Støttet | Beste eksponerte video og separat lyd; fersk anonym sesjon brukes ved signerte CDN-lenker |
| Facebook | Verifisert på nåværende offentlig eksempel | Støttet | Uttrekk kan brekke når Facebook endrer offentlig HTML |
| VSCO | Resolver og proxy pauset før upstream-request | Støttet lokalt | Plus beholder VSCO; Lite automatiserer ikke tilgang uten tillatelse |

«Beste original» betyr beste variant plattformen faktisk eksponerer anonymt for
den aktuelle requesten. Det er ingen garanti for oppløsning, bitrate, kodek,
native FPS eller varig plattformstøtte.

## Sikkerhet og kostnadskontroll

Implementerte grenser omfatter:

- bare HTTPS og strenge kilde-/CDN-allowlists;
- ingen credentials, custom port eller IP-literal i brukerlenker;
- manuelle redirects som valideres på nytt;
- SSRF-beskyttelse på både kildesider og medier;
- maksimalt 4 KiB JSON-request, 2,5 MB kildeside og 1 GiB proxystrøm;
- 15 resolver-requests per minutt og 120 medierequests per minutt som
  best-effort, per Worker-isolat/pseudonymisert IP-nøkkel;
- korte nettverkstimeouts og begrenset antall redirects;
- same-origin-kontroll;
- restrictive CSP, framing-, MIME-, referrer- og permissions-headere;
- ingen arbitrær proxy-URL;
- `no-store` på API- og medieresponser;
- ingen applikasjonsdatabase, URL-logg eller persistent medielagring;
- bare `/api/*` aktiverer Functions; statiske sidekall gjør ikke det.

Ratebegrensningen er bevisst liten og enkel. Den er ikke en global, sterk kvote
på tvers av alle Cloudflare-isolater. Hvis misbruk eller trafikk blir et faktisk
problem, må sterkere kostnadsvern vurderes før noe betalt aktiveres.

## Personvern, vilkår og ansvar

Dagens juridiske produktgrense er:

- brukeren må aktivt godta versjonerte vilkår før hver kildeoppløsning;
- brukeren erklærer at innholdet kan åpnes og brukes lovlig;
- privat innhold, login, cookies, DRM og tilgangsomgåelse støttes ikke;
- lokal forbedring krever et separat aktivt samtykke;
- ingen samtykker lagres i cookies, `localStorage` eller `IndexedDB`;
- Cloudflare, kildeplattformen, CDN-en og nettleverandøren behandler ordinære
  forbindelsesdata selv om applikasjonen ikke lagrer lenken eller mediet;
- tjenesten leveres «as available», og brukeren er ansvarlig for valgt innhold
  og lovlig bruk;
- ansvar begrenses så langt loven tillater, men teksten lover ikke absolutt
  juridisk ansvarsfrihet og kan ikke fjerne ufravikelige rettigheter;
- verifisert juridisk operatørnavn og forretningsadresse er ikke publisert ennå.

Dette er teknisk dokumentasjon, ikke juridisk rådgivning. Gjennomgangen
10. august 2026 fant at gjeldende vilkår for VSCO, Instagram/Facebook og TikTok
begrenser automatisert uthenting; brukerens checkbox kurerer ikke operatørens
egen plattformbruk. Kommersiell markedsføring trenger derfor skriftlig
plattformtillatelse eller en godkjent mekanisme, verifisert operatørinformasjon,
privat rettighetskanal og ferdig personvern-/opphavsrettsvurdering.

## Annonser og inntekt

Beslutningen er at brukerne bare skal se annonser og ikke betale.

Abonnement rundt 99 kr/måned og tilhørende inntektseksempler ble tidligere
utforsket som et regnestykke, ikke implementert. Den senere produktbeslutningen
erstattet dette: ingen abonnement eller kundebetaling i dagens løsning.

Dagens faktiske situasjon:

- ingen abonnement;
- ingen betaling eller checkout;
- ingen konto;
- fire statiske sponsorplassholdere på den offentlige siden;
- ingen ad-network-kode, personalisering, cookies, visningspixel eller
  klikksporing;
- sponsorlenker går til en strukturert offentlig GitHub-forespørsel i Lite;
- annonseblokkerere kan skjule feltene;
- plassholderne gir 0 kr i inntekt frem til en reell sponsor eller godkjent
  annonseleverandør kobles til.

AdSense skal ikke legges inn nå: Google Publisher Policies begrenser annonser
på tjenester som muliggjør videonedlasting når innholdsleverandøren forbyr det.
Direkte, statiske sponsorer uten sporing er den nåværende tekniske retningen.
En fremtidig annonseintegrasjon må uansett avklares mot plattformregler,
publisher policy, personvern, samtykkeløsning, operatørinformasjon, `ads.txt` og
eventuelle EØS-krav.

## Cloudflare og kostnad nå

- Prosjekt: `media-downloader`.
- Produksjonsadresse: <https://media-downloader-4y5.pages.dev/>.
- Hosting: Cloudflare Pages med Pages Functions.
- Deploy: direkte Wrangler-upload, ikke automatisk Git-deploy.
- Wrangler OAuth er autorisert for kontoen og deploytilgang er verifisert.
- Siste verifiserte produksjonsdeploy: `fe327f34-5a06-4eb0-8942-9221b172178c`.
- Cloudflare viser Lite source commit `c3c86b2`.
- Eget domene er ikke kjøpt eller koblet til.
- Database, R2, KV, betalt Worker-plan og andre betalte produkter er ikke brukt.
- Fast kostnad i dagens oppsett: 0 kr per måned.

Tidlige estimater på omtrent 70–100 kr/måned for en liten server og rundt
350 kr/måned for en større VPS bygget på den feilaktige antakelsen om en
offentlig Python-/FFmpeg-server. De estimatene gjelder ikke den valgte
Pages/Functions-arkitekturen.

Gratisnivået er en grense, ikke uendelig kapasitet. Ved kvote-/plattformgrense
skal funksjonen heller feile enn at prosjektet oppgraderes til en betalt løsning
uten en ny, uttrykkelig beslutning. Cloudflare-priser og grenser må verifiseres
på nytt før lansering eller større trafikk.

Produksjonen kan nå gjenskapes fra Lite-committen `c3c86b2`, som finnes både
lokalt og på <https://github.com/bjorkepoc/media-downloader-lite>.
`video-enhancer`/`e0156e0` er ikke kilden til den aktive Pages-deployen.

## Layoutfeilen som ble rettet

Chrome-skjermbildet viste hovedinnholdet i en smal kolonne til venstre med stort
tomrom til høyre. Årsaken var at en annonseblokkerer skjulte venstre og høyre
annonserail. CSS Grid auto-plasserte da `<main>` i første 275 px-kolonne.

Rettelsen:

- `<main>` er eksplisitt låst til grid-kolonne 2 på desktop;
- venstre og høyre annonserail er låst til henholdsvis kolonne 1 og 3;
- under 1180 px brukes én sentrert kolonne og `<main>` går til kolonne 1;
- stylesheet-URL-en fikk versjonssuffiks for å bryte gammel nettlesercache;
- en regresjonstest kontrollerer den eksplisitte grid-plasseringen.

Produksjonsmålingen etter hard reload var 1800 px viewport, 960 px hovedfelt,
420 px venstrekant, grid-kolonne 2 og ingen horisontal overflow. Ingen
applikasjonsfeil ble registrert i konsollen.

## Endringer i arbeidskopien

Lite-områdene er nå kildekode i `/Users/po/dev/media-downloader-lite` og det
separate GitHub-repoet:

- `public-site/`: hosted frontend og lokal WebAssembly-behandling;
- `functions/`: resolver, extractors, SSRF-kontroller og range-proxy;
- `tests/public_site.test.js`: 16 fokuserte Worker-/UI-/sikkerhetstester;
- `wrangler.jsonc` og `package.json`: lokal Pages-utvikling, test og deploy.

Eksisterende områder som er videreutviklet:

- `src/video_enhancer/sources.py`: flere plattformer og medietyper;
- `src/video_enhancer/web.py`: utvidet lokal UI, vilkår, samtykke og medier;
- `src/video_enhancer/macos_app.py` og `scripts/build_macos.sh`: lokal
  distribusjon;
- Python-testene, release-testene, dokumentasjonen, tredjepartsnotiser og
  dependency lock.

Per 10. august 2026 er Plus-endringene lagt på branch `codex/plus-split` for
sikker review og GitHub-backup. De lokale Pages/Functions-kopiene er fortsatt
untracked og skal ikke stages i Plus. Det finnes ingen stash. `origin/main` står
fortsatt på `e0156e0`. En separat worktree finnes i
`/Users/po/dev/video-enhancer-task-1` på branch `task-1` og skal ikke endres eller
slettes uten egen kontroll.

Det separate `/Users/po/dev/media-downloader-lite`-prosjektet er rent på branch
`main` ved commit `c3c86b2` og tracker `origin/main` på GitHub.

## Verifisering 10. august 2026

- Python: 137 tester bestått.
- Ruff: alle kontroller bestått.
- Bandit: ingen funn etter eksplisitt HTTPS-/redirect-validering av tillatt
  Instagram-CDN.
- `pip-audit`: ingen kjente sårbarheter i låste avhengigheter.
- Faktisk lokal FFmpeg-kjøring: alle 11 eksportformatene opprettet gyldige
  resultatfiler fra en syntetisk testvideo.
- Node/Pages: 15 av 15 tester bestått.
- `git diff --check`: bestått.
- Produksjons-HTML, `Media Downloader Lite`-branding, VSCO-stopp og sponsorlenke
  verifisert direkte fra deploy `fe327f34-5a06-4eb0-8942-9221b172178c`.
- Chrome desktop- og mobil-QA: korrekt sideidentitet, meningsfull DOM, ingen
  framework overlay eller horisontal overflow, korrekt sentrering,
  kvalitetsvalg og Terms-dialog åpnet/lukket.
- Tidligere live offentlige eksempler: Instagram, TikTok og Facebook verifisert
  med resolver og byte-range-nedlasting. Nye VSCO-tester viser at både resolver
  og medieproxy stanser før nettverkskall; ingen omgåelse ble kjørt.

Teknisk grønt betyr ikke at alle kommersielle, juridiske eller
plattformspesifikke lanseringskrav er ferdige.

## Hva vi jobber med nå

Hovedmålet er å stabilisere en offentlig, gratis å drifte, annonsefinansiert
førsteversjon uten å miste lokal funksjonalitet.

Prioritert gjenstående arbeid:

1. Review og eventuelt merge Plus-branchen etter GitHub-backup.
2. Lage en selvstendig Windows 64-bit-pakke for Plus og verifisere installasjon.
3. Legge til en liten lokal kø, deretter undertekster, kapitler og native
   varsler gjennom eksisterende `yt-dlp`-/operativsystemfunksjoner.
4. Avklare skriftlig plattformtillatelse eller godkjent mekanisme før kommersiell
   markedsføring av Lite-resolveren.
5. Publisere verifisert operatørnavn, geografisk adresse, direkte e-post,
   organisasjons-/MVA-status og privat rettighetskanal.
6. Skaffe en reell direkte sponsor. Dagens plasser og henvendelsesflyt tjener
   ingenting uten en avtale.
7. Vedlikeholde tillatte extractors når plattformene endrer offentlig HTML.
8. Koble til eget domene bare når det ønskes og kostnaden er godkjent.

## Ting vi ikke skal gjøre uten en ny beslutning

- Aktivere betalt Cloudflare-plan eller annen betalt infrastruktur.
- Legge inn abonnement, betaling eller kundekontoer.
- Kjøre FFmpeg eller enhancement på serveren.
- Lagre brukerlenker eller medier persistent.
- Kreve eller bruke plattformlogin/cookies.
- Omgå private kontoer, DRM, bot challenge eller tilgangskontroll.
- Bruke en offentlig Cobalt-instans eller drifte Cobalt nå.
- Fjerne lokal app, CLI, presets eller eksisterende enhancement-funksjoner.
- Påstå at annonseplassholderne allerede gir inntekt.
- Påstå at tjenesten har absolutt juridisk ansvarsfrihet.
- Legge Lite-filene inn i Plus-repoet igjen.

## Nyttige kommandoer

```bash
# Python-app og test
.venv/bin/python -m pytest
.venv/bin/ruff check .

# Offentlig Pages-variant (kjøres fra /Users/po/dev/media-downloader-lite)
cd /Users/po/dev/media-downloader-lite
npm run test:web
npm run dev:web

# Deploy kun etter eksplisitt beslutning og kontroll av Cloudflare-konto
npm run deploy:web

# Kontroller lokal Git-tilstand før commit/deploy
git status --short --branch
git diff --stat
git worktree list
git stash list
```

## Relaterte dokumenter

- `README.md`: bruk, funksjoner, lokal Plus-app og lenke til separat Lite.
- `docs/launch-privacy-security.md`: detaljert launch-, personvern-, annonse-,
  plattform- og sikkerhetsgjennomgang.
- `docs/snapdownloader-parity.md`: verifisert funksjonsmatrise og prioritert
  Plus-gap mot SnapDownloader.
- `SECURITY.md`: sikkerhetspolicy og rapportering.
- `THIRD_PARTY_NOTICES.md`: dependency- og extractor-attribusjon.
