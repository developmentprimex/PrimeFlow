# Mira: shënime të takimeve në Discord

Status: dizajn për shqyrtim; implementimi nuk ka filluar.

## Qëllimi i konfirmuar

Stafi takohet në një voice channel të serverit ekzistues Discord. Mira hyn
si boti ekzistues, dëgjon dhe merr shënime. Nuk përshëndet me zë, nuk përgjigjet
me zë dhe nuk ndërpret takimin. Në fund përgatit përmbledhjen, vendimet dhe
veprimet e përmendura, për kontroll dhe ruajtje në PX Notes.

Përdoret OPENAI_API_KEY ekzistues në backend. Nuk kërkohet llogari apo bot i ri.
Krijimi automatik i detyrave dhe ndryshimi i detyrave nga fjalët e takimit nuk
përfshihen: përgjegjësit dhe afatet paraqiten si shënime për kontroll.

## Përvoja e përdoruesit

1. Përdoruesi i lidhur me PrimeFlow hyn në voice channel dhe përdor
   `/takimi fillo` në kanalin e tij personal të botit. Komanda mund të marrë një
   titull opsional; përndryshe përdoret emri i kanalit dhe data e takimit.
2. Boti kontrollon llogarinë, kanalin, lejet dhe shërbimin e audios. Poston një
   njoftim të dukshëm në chat-in e voice channel-it përpara nisjes së dëgjimit.
   Nëse njoftimi nuk mund të postohet, dëgjimi nuk fillon.
3. Mira hyn e heshtur (`selfMute=true`, `selfDeaf=false`). Nuk ka gjenerim apo
   transmetim audioje nga aplikacioni. Kanali personal tregon gjendjen dhe
   butonin **Përfundo takimin**; `/takimi mbaro` bën të njëjtin veprim.
4. Përfundimi lejohet nga organizuesi ose nga një admin/manager i autorizuar
   i PrimeFlow në të njëjtin voice channel. Kontrolli nuk mbështetet vetëm te
   dukshmëria e butonit. Komandat përdorin përgjigje të shkurtra shqip.
5. Boti ndërpret marrjen e audios, del nga voice channel, përpunon segmentet e
   mbetura dhe njofton organizuesin në kanalin e tij personal kur shënimet janë gati.
6. Organizuesi shikon shënimet dhe përdor **Ruaj në PX Notes**. Rezultati ka
   përmbledhje, vendime, veprime me përgjegjës/afate kur janë shprehur dhe pika
   të paqarta. Teksti i gjatë ofrohet si skedar UTF-8 në kanalin personal.
   **Hap PX Notes** shfaqet pas ruajtjes. Ruajtja dy herë kthen të njëjtin Note.

Versioni i parë mban vetëm një takim aktiv për server, sipas kufizimit të një
lidhjeje zanore të të njëjtit bot për server. Kanale Stage, ekranet e ndara dhe
transkriptimi i videos nuk përfshihen. Hyrja/dalja e pjesëmarrësve në voice
channel nuk e nis dhe nuk e ndal automatikisht takimin e stafit.

## Alternativat dhe zgjedhja teknike

- Zgjerimi Python `discord-ext-voice-recv` përshtatet drejtpërdrejt me botin,
  por mbështetja për deshifrimin DAVE vazhdon të jetë në pull requests të
  pashkrira. Nuk zgjidhet si varësi e parazgjedhur për këtë implementim.
- Një bot i veçantë Node është më i izoluar, por shton token, ftesë në server
  dhe identitet të dytë që përdoruesi nuk e ka kërkuar.
- **Zgjedhja:** boti Python ekzistues kontrollon një proces lokal Node për
  transportin e audios, përmes adapterit të mbështetur nga `@discordjs/voice`.
  Ka vetëm një lidhje kryesore Discord Gateway dhe përdoret identiteti aktual.

Paketa e publikuar `@discordjs/voice@0.19.2` deklaron Node >=22.12 dhe varësinë
DAVE `@snazzah/davey`; Node lokal është 24.13.0. Varësitë dhe versionet fiksohen
në një package-lock të veçantë për komponentin e audios. Instalimi dhe importi
i varësive native në Windows verifikohen para aktivizimit.

Audio receive nuk garantohet si API e qëndrueshme nga Discord. Prandaj marrja
reale e audios dhe ndryshimi i çelësave kur hyjnë/dalin persona janë kritere
pranimi, jo supozime që i mbulojnë testet me mock.

## Kufijtë e komponentëve

### Boti dhe procesi i audios

`discord_bot.py` regjistron grupin `/takimi`, kontrollet dhe njoftimet. Një modul
i veçantë menaxhon jetën e procesit Node. Python përcjell vetëm eventet përkatëse
VOICE_STATE_UPDATE/VOICE_SERVER_UPDATE te adapteri. Kërkesat e adapterit për
Gateway pranohen vetëm si operacioni voice-state i serverit dhe kanalit aktiv;
nuk ekzekutohet JSON arbitrar i ardhur nga procesi fëmijë.

Komunikimi bëhet me stdin/stdout të procesit lokal, me mesazhe të kufizuara,
ID sesioni dhe konfirmime. Tokens e lidhjes zanore nuk regjistrohen në log.
Procesi Node nuk merr OPENAI_API_KEY dhe nuk hap një server HTTP publik.
Ndërprerja e Gateway ose vdekja e procesit fëmijë mbyll dëgjimin dhe shënon
takimin si të ndërprerë; nuk rifillon regjistrimi në heshtje.

### Audio dhe transkriptimi

Audioja ndahet sipas Discord user ID që në marrje, për të ruajtur se kush foli
edhe kur dy persona flasin njëkohësisht. Çdo segment ka ID unike, kohën relative
të nisjes/mbarimit dhe identitetin e folësit. Opus dekodohet në PCM/WAV në
segmente të shkurtra me buffer dhe radhë të kufizuar. Transporti nuk mbështetet
te grumbullimi i gjithë audios së takimit në RAM.

Backend-i merr segmentet përmes bridge-it ekzistues të autentikuar, verifikon
sesionin, identitetin e worker-it, formatin, madhësinë dhe numrin rendor dhe i
transkripton me konfigurimin ekzistues për shqipen. Segmentet ruhen një herë
në DB; riprovimet nuk shtojnë të njëjtin tekst dy herë. Audioja është e
përkohshme dhe lirohet pas përpunimit; nuk krijohet arkiv audioje i takimeve.

Teksti i transkriptuar trajtohet si material takimi, pa tools ose veprime mbi
detyrat. Modeli i përmbledhjes përdoret vetëm për strukturimin e shënimeve.
Për takime të gjata përdoret përmbledhje me pjesë duke ruajtur burimet e
vendimeve/veprimeve; nuk pritet teksti në heshtje te kufiri i kontekstit.

### Gjendja dhe ruajtja

Një migrim shton sesionet dhe segmentet e transkriptuara. Sesioni ruan
organizuesin/link-un, serverin, kanalin zanor, destinacionin e Note-it, titullin,
kohët, gjendjen, gabimin e sigurt, draftin dhe saved_note_id.

Gjendjet: STARTING, LISTENING, FINALIZING, READY, SAVED, INTERRUPTED, FAILED.
Rezervimi i sesionit aktiv dhe kalimet e gjendjes serializohen në DB.
Nisja/përfundimi/ruajtja janë idempotente. Sesionet e mbetura aktive pas një
rinisjeje bëhen INTERRUPTED; transkriptet e marra mbeten për rikuperim.

Ruajtja e Note-it kalon kontrollet ekzistuese të rolit dhe departamentit.
Destinacioni përcaktohet nga organizuesi i autorizuar; një përdorues nuk merr
qasje te departament i ri duke nisur takim në Discord. Krijimi i GaNote dhe
regjistrimi i saved_note_id bëhen në një transaksion me lock të sesionit, që
një përgjigje e humbur të mos krijojë dy Notes. Përmbledhja nuk postohet
automatikisht në kanalin e përbashkët të takimit.

## Gabimet dhe funksionimi

Nuk tregohet “Po dëgjoj” përpara se lidhja e audios të jetë gati. Nëse dikush
flet por nuk merret audio e dekodueshme, njoftohet organizuesi. Radhë e
tejmbushur, humbje e transportit, gabime transkriptimi apo pjesë që mungojnë
shfaqen qartë; një përmbledhje e pjesshme etiketohet si e tillë.

`/takimi mbaro` e ndal menjëherë kapjen. Segmentet tashmë të kapura përfundojnë
në sfond; dështimi i OpenAI nuk e mban botin në voice channel. Shënimet bosh
nuk krijohen kur nuk ka të folur të kuptueshëm. Lejet kontrollohen përsëri
gjatë ruajtjes dhe njoftimit privat.

Aktivizimi përdor një flag të veçantë, kontroll varësish dhe dokumentim deploy-i.
Komandat ekzistuese të detyrave vazhdojnë të punojnë kur audioja është e
çaktivizuar. Çelësat dhe përmbajtja e takimit nuk shfaqen në log-et e deploy-it.

## Verifikimi dhe kriteret e pranimit

- Teste për lejet, serverin e gabuar, përdoruesin e palidhur, dy nisje paralele,
  përfundim të dyfishtë, segmente të përsëritura, renditje dhe ruajtje të dyfishtë.
- Teste transporti për adapterin, mbylljen e procesit, kufijtë e buffer-it,
  ndalimin gjatë ngarkimit dhe mungesën e çdo rruge të transmetimit audio.
- Teste me OpenAI të zëvendësuar për heshtje, dështime, shqip, folës të
  mbivendosur, përmbledhje të pjesshme dhe përgjegjës/afate të papërmendura.
- Teste regresioni të botit, deploy-it dhe krijimit normal të PX Notes.
- Provë reale në server: dy njerëz flasin shqip, njëri del dhe rikthehet,
  Mira mbetet e heshtur, kap audio dhe identitetet, del me komandë, prodhon
  shënime dhe ruan vetëm një Note. Pa këtë provë funksioni raportohet si i
  implementuar me testim real ende të pambyllur, jo si i verifikuar në prodhim.

## Burimet e kontrolluara më 2026-10-20

- https://discordjs.dev/docs/packages/voice/main
- https://discordjs.dev/docs/packages/voice/main/VoiceReceiver:Class
- https://discordjs.dev/docs/packages/voice/main/DiscordGatewayAdapterImplementerMethods:Interface
- https://discordjs.dev/docs/packages/voice/main/DiscordGatewayAdapterLibraryMethods:Interface
- https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/65
- https://developers.openai.com/api/docs/guides/speech-to-text
- Metadata e paketës në npm: `npm view @discordjs/voice version engines dependencies --json`.
