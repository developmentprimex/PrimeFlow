# Asistenti personal PrimeFlow në Discord

Kanalet personale përdorin emrin e personit të lidhur: `primeflow-rinesa`,
`primeflow-elsa`, etj. Nëse emri është zënë, shtohet mbiemri ose një prapashtesë.
Lidhja me llogarinë identifikohet nga ID-ja dhe topic-u i kanalit, pavarësisht emrit.

## Raportet me komandë

Në kanalin personal të krijuar nga `/lidh`, `/m2` dhe `/m3` hapin raportin
personal të ditës, edhe jashtë orarit të njoftimeve automatike. Çdo pyetje vjen
drejtpërdrejt në mesazhin e vet, me të njëjtin tekst dhe butona si dërgimi
automatik M2/M3. Nuk kërkohet zgjedhja e detyrës nga një listë paraprake.
**Raporti M2/M3** hap listën ndihmëse, ku **Rifresko** merr gjendjen aktuale.
Përgjigjet ruhen në të njëjtat pyetje të ditës dhe
hapja manuale nuk konsumon njoftimin automatik. `/m3` sjell bashkë pyetjet M3
të orës 15:50 dhe planifikimin e nesërm të orës 16:10: detyrat, slotet dhe
konfirmimin përfundimtar të planit. Orari automatik vazhdon të funksionojë.

Kërkohet rinisja e API-ve dhe botit që regjistron komandat; nuk ka migrim të ri.

## Pyetjet M2 në 11:45

**Hap detyrën** shfaq kartën e plotë në të njëjtin mesazh M2: statusin, slotin,
afatin, të gjitha pikat, komentet dhe veprimet e detyrës. Teksti i gjatë shfletohet
me faqe pa mesazhe shtesë. **Kthehu te M2** rikthen pyetjen me përgjigjen aktuale.
Butoni mbetet i përdorshëm edhe kur përgjigjja është plotësuar në PrimeFlow ose
shtyrja është konfirmuar.

### Përgjigjet e plotësuara në PrimeFlow

Punëtori kontrollon edhe jashtë orarit M2 nëse pyetjet e dërguara kanë marrë
përgjigje në platformë. Statusi Mbajtur/Anuluar i takimit, Po/Jo dhe komentet
e përgjigjeve M2, arsyet/komentet e realizimit dhe përfundimi i detyrës përditësojnë
mesazhin ekzistues Discord pa dërguar mesazh të ri. Butonat e përgjigjes hiqen
kur pyetja është plotësuar; komentet nuk publikohen në kanalin e kërkuesit.
Ndryshimi i statusit përditëson përsëri mesazhin, ndërsa pastrimi i një përgjigjeje
manuale M2 ose statusi takimi rikthen pyetjen. **Koment manual** i shtyrjeve
mbetet shënim i pavarur dhe nuk llogaritet si përgjigjja e punonjësit.

Kërkohet `0168_discord_answer_sync`. Gjurmët e përditësimit dhe marrjes së
konfirmimit ruhen në databazë dhe riprovohen pas dështimit të përkohshëm të Discord-it.
Mesazhet që përdoruesi i ka fshirë nuk krijohen përsëri. Lidhjet e revokuara
ndalen dhe identiteti rishikohet para çdo përditësimi. Sinkronizimi bëhet
zakonisht brenda ciklit 30 sekonda, sipas radhës së mesazheve.

Takimet interne dhe externe të AM që kanë përfunduar dhe nuk kanë ende status
Mbajtur/Anuluar marrin pyetjen **M2 · A u mbajt takimi?** gjatë mbledhjes 11:45–12:00.
Pyetja shkon te personat e caktuar manualisht në takim me lidhje aktive Discord.
Kur takimi nuk ka persona të caktuar, i shkon Diellza Veliut (`diellza.veliu`).
Një person i caktuar pa Discord nuk e kthen takimin në rast pa përgjegjës.
Kjo pyetje nuk varet nga aktivizimi i kujtesës para takimit dhe nuk pyet për
takime ende në zhvillim. Përgjigjja ruan statusin e të njëjtës datë në Common View,
përditëson pyetjet e pjesëmarrësve dhe nuk mbishkruan një status tashmë të plotësuar.

Boti ekzistues kontrollon çdo 30 sekonda nga 11:45 deri para 12:00, të hënën–të
premten, sipas zonës kohore të raporteve. Në kanalin personal të secilit përdorues
të lidhur me `/lidh`, dërgon pyetje me përmendje për detyrat e caktuara atij:

- Detyrat AM/AM-PM të pakryera me Due Date sot, përfshirë 08:00 dhe Deadline,
  duke përdorur pikërisht përzgjedhjen e raportit M2.
- Shtyrjet SOT/SOT ose Deadline dhe shtyrjet e sotme para pauzës. Pyetja dallon
  Start + Due, vetëm Start dhe vetëm Due, dhe tregon datat para/pas ndryshimit.
  Një shtyrje që ka tashmë arsyen dhe komentin për ndryshimin nuk pyetet përsëri.
  Nëse e njëjta shtyrje është në të dyja tabelat, dërgohet vetëm një pyetje.
- Progresi për detyrat e hapura AM/AM-PM me F, GA ose personale me GA.
- Dorëzimi për secilën detyrë M2 ose M2/3: PO/JO; JO kërkon koment.
  PO ruhet me një klikim dhe hap direkt formularin e komentit opsional.
  Mbyllja pa koment nuk e anulon PO; komenti mund të ndryshohet edhe më vonë.
  Ruajtja përditëson të njëjtën pyetje në Discord pa mesazhe të reja konfirmimi.
  Teksti i komentit ruhet në PrimeFlow dhe nuk afishohet poshtë pyetjes në Discord.

Për arsyet përdoret lista e njëjtë si te shtyrjet/My View në PrimeFlow. Zgjedhja
hap formularin e komentit; ruajtja bëhet me dërgimin e formularit. Komenti ruhet
si përgjigje M2 me autor, shtohet te komenti personal i detyrës pa fshirë tekstin
e mëparshëm, dhe arsyeja/komenti operacional ruhen te gjendja ditore e detyrës.
Për shtyrjet, përgjigjja e Discord-it shfaqet vetëm te kolona **Komenti**;
**Koment manual** mbetet fushë e pavarur për shënimet nga faqja e raportit.
Dorëzimi ruhet në raport dhe te komenti i detyrës; PO nuk e mbyll detyrën.
Raporti përditëson kolonat e përgjigjeve dhe numëruesin SA/TOTALI. Për detyrat me
disa përgjegjës, secili përgjigjet veçmas: një JO e bën rezultatin JO; PO shfaqet
kur të gjithë marrësit e pyetjes janë përgjigjur PO.

Pyetjet/përgjigjet ruhen në `discord_m2_questions` dhe i mbijetojnë rinisjes.
Klikimi i përsëritur nuk shton dy komente.
Përgjigjja mund të ndryshohet gjatë së njëjtës ditë: p.sh. JO me koment, pastaj
PO kur dorëzohet. Raporti tregon përgjigjen e fundit; komentet e mëparshme dhe
auditimi mbeten si historik. Një formular i vjetër nuk mbishkruan një përgjigje
të ndryshuar ndërkohë. Revokimi i lidhjes, heqja e caktimit,
dita e kaluar ose një shtyrje e re refuzojnë përgjigjen e vjetër. Nuk kërkohet AI
ose Message Content Intent për këta formularë. Nuk dërgohen pyetje për personat
që ende nuk e kanë lidhur Discord-in.

Aktivizimi kërkon migrimin `0162_discord_m2_questions`, deploy të API-së dhe
frontend-it, dhe rinisjen e procesit `primeflow-discord`. Nuk ka dërgim provë
automatik gjatë testeve. Testet e PostgreSQL mund të ekzekutohen me
`M2_TEST_DATABASE_URL` dhe `python -m pytest tests/test_discord_m2_database.py`;
krijojnë dhe fshijnë vetëm një skemë të përkohshme me emër unik.

Shënimet e takimeve përdorin `DISCORD_MEETING_TRANSCRIBE_MODEL=gpt-transcribe`
për audion. Përmbledhjet përdorin `DISCORD_AI_MODEL`; në server është vendosur
`gpt-6-luna`.

## Mira në takimet zanore: vetëm dëgjim

Mira mund të hyjë me identitetin e botit ekzistues në një voice channel të
zakonshëm dhe të marrë shënime pa folur. Aktivizo GitHub Actions variable
`DISCORD_MEETING_NOTES_ENABLED=true` dhe bëj deploy; si parazgjedhje është
`false`. Përdoren token-i i botit dhe `OPENAI_API_KEY` ekzistues. Nuk duhet bot i
dytë. Variabla opsionale `DISCORD_VOICE_NODE_BINARY` zgjedh executable-n e Node;
parazgjedhja është `node`. Kërkohet Node >=22.12.

1. Lidhe llogarinë me `/lidh`, pastaj hyr në voice channel-in e stafit.
2. Në kanalin tënd personal përdor `/takimi fillo`. Titulli është opsional.
   Departamenti merret nga llogaria; admin/manager mund të japë UUID-në e një
   departamenti tjetër me parametrin opsional `departamenti`.
3. Mira poston njoftim në chat-in e voice channel-it përpara se të dëgjojë.
   Kërkon `View Channel`, `Connect` dhe `Send Messages` në atë kanal. Nuk
   kërkon lejen `Speak` dhe nuk transmeton audio. Në mungesë të njoftimit ose
   lidhjes së audios, takimi nuk nis si “Po dëgjoj”.
4. Përdor `/takimi mbaro` ose **Përfundo takimin** në kanalin personal.
   Organizuesi mund ta ndalë; admin/manager tjetër duhet të jetë në të njëjtin
   voice channel dhe të përdorë kanalin e vet personal. Komandat përfundohen
   edhe kur përgatitja e shënimeve vazhdon në sfond.
5. Shënimet vijnë në kanalin personal: përmbledhje, vendime, veprime me
   përgjegjës/afat kur janë përmendur dhe paqartësi. Për shënime të gjata
   dërgohet skedar UTF-8. Përdor **Shiko shënimet**, pastaj **Ruaj në PX Notes**.
   Dy klikime nuk krijojnë dy Notes. **Hap PX Notes** hap listën për redaktim.

Takimet 1H: nga e hëna në të premte Mira hyn vetë në kanalin 1H 2 minuta para
çdo sloti (`DISCORD_1H_AUTO_JOIN_TIMES`, parazgjedhje 09:58, 10:58, 11:48, 14:18,
15:58), në emër të `DISCORD_1H_AUTO_OWNER_DISCORD_ID`. Del me `/takimi mbaro`,
30 sekonda pasi del personi i fundit, ose pas 10 minutash nëse s'vjen askush.
Shënimet e këtyre takimeve ruhen direkt në PX Notes dhe nuk dërgohen në Discord.

Mbahet një takim në një kohë për server. Pas ndalimit, Mira del nga voice
channel menjëherë; radha lokale e transkriptimit përfundon përpara se të nisë
një takim i ri. Shënimet e ruajtura kanë lejet normale të PX Notes. Teksti i
takimit nuk zbatohet si komandë për detyra. Përmbledhja nuk postohet në kanalin
e përbashkët. Audioja nuk arkivohet; ruhen segmentet e transkriptuara dhe drafti.

Shkëputjet e shkurtra të Discord-it, paketat e audios që nuk dekodohen nga një
folës dhe një segment i vetëm që dështon në transkriptim nuk e ndalin takimin:
Mira rilidhet ose rinis vetëm atë folës; takimi shënohet i pjesshëm në PrimeFlow, pa etiketë në tekstin e shënimeve.
Organizuesi njoftohet dhe dëgjimi ndalet vetëm kur rilidhja dështon (rreth 25 s),
kur askush nuk dekodohet për 30 s, ose kur 3 segmente rresht apo 3 heartbeat-e
rresht dështojnë. Pas një rinisjeje nuk rifillon dëgjimi automatikisht; sesioni
i vjetër shënohet i ndërprerë dhe teksti i marrë mund të përmblidhet. Celery
worker/beat përpunojnë sesionet çdo 30 sekonda; boti dërgon rezultatet private.
Në dështim të përmbledhjes, transkripti mbetet në DB për rikuperim teknik.

Deploy-i përdor migrimin `0152_discord_voice_meetings`, instalimin e kyçur në
`backend/discord-voice` dhe `python scripts/check_discord_voice.py --install`.
Ky kontroll verifikon DAVE/Opus dhe testet lokale pa hyrë në Discord. Mund të
ekzekutosh `python scripts/check_discord_voice.py` vetëm për kontroll importesh.
Node child nuk trashëgon çelësat, token-in e botit apo kredencialet e databazës.

Para përdorimit të rregullt, bëni një takim prove të nisur qëllimisht me dy
folës në shqip: flisni njëkohësisht, njëri të dalë e të rikthehet, ndaleni,
kontrolloni shënimet dhe klikoni ruajtjen dy herë. Kjo verifikon marrjen reale
të audios dhe ndryshimet DAVE; testet me mock nuk e zëvendësojnë këtë provë.

Secili përdorues lidh llogarinë e vet në faqen `/discord` të PrimeFlow. Kodi
njëpërdorimësh vlen 10 minuta dhe përdoret me `/lidh kodi:...` në serverin e ekipit.
Fjalëkalimet dhe tokenët PrimeFlow nuk vendosen në Discord. Një llogari Discord
lidhet me një llogari PrimeFlow; kodi i ri anulon kodin e mëparshëm.

## Kujtesa e Mira-s

Pas çdo takimi Mira përditëson një regjistër të vetëm të gjallë me atë që u tha:
detyrat dhe premtimet, temat e hapura, vendimet dhe informacionet që mund të duhen
më vonë. Regjistri nxirret nga transkripti i plotë, jo nga shënimet. Kur shkruan
shënimet e takimit të radhës, Mira e lexon regjistrin dhe e lidh takimin me të
kaluarën vetëm kur është qartë e njëjta çështje, p.sh. "(1H, 21.10 09:58)".

- Aktivizimi: GitHub Actions variable `MIRA_MEMORY_ENABLED=true`, pastaj deploy.
  Si parazgjedhje është `false`, dhe shënimet punojnë saktësisht si më parë.
- Hyjnë të gjitha takimet, edhe ato të `/takimi fillo` që nuk u ruajtën në PX Notes.
  Takimet para aktivizimit nuk përfshihen; regjistri nis bosh.
- Tabi **Kujtesa** te faqja **Mira** (`/mira?tab=kujtesa`) e tregon regjistrin për të gjithë
  stafin. Çdokush mund ta korrigjojë një pikë, ta mbyllë, ta rihapë ose ta shënojë si
  të gabuar. Korrigjimi i një personi ka përparësi; asgjë nuk fshihet nga historiku.
- Shënimet nuk e presin kurrë kujtesën. Një përditësim që dështon provohet deri në 5
  herë; pastaj takimi shfaqet në fund të faqes si "nuk u përfshi" dhe një admin ose
  menaxher mund ta provojë sërish.
- `gh workflow run mira-diagnostics.yml --ref main` tregon `memory_status` për
  takimet e fundit dhe rreshtat `MIRA_DIAGNOSTIC memory` nga Celery worker, pa
  përmbajtje takimesh.

## Mira mban vetë takimet 1H (test)

Mira mund ta mbajë vetë 1H-në. Thërret njerëzit, flet me ta, pyet dhe krijon detyra nga PX Notes.
Në mënyrë parazgjedhëse është joaktive dhe niset vetëm me komandë. Dëgjimi i heshtur më lart
nuk ndryshon: ai vazhdon të transkriptojë si më parë, edhe kur Mira e mban takimin.

**Si funksionon.** Zëri i Mira-s është një bot i dytë Discord, "Mira Host", me token të vetin,
sepse një bot mund të jetë vetëm në një voice channel për server. Mira Host hyn në kanalin 1H dhe
flet përmes OpenAI Realtime (`VOICE_ASSISTANT_MODEL`). Kur dikush flet më shumë se një "aha" ose "po", ajo ndalet
dhe dëgjon; nuk flet përmbi askënd dhe pret kur dikush ndalet në mes të fjalisë.
Mesazhet me shkrim i dërgon boti ekzistues PrimeFlow në kanalet private të `/lidh`.

| Kur | Çka ndodh |
|---|---|
| 5 min para (11:00, 11:50, 14:20, 16:00; jo 10:00) | Secili me detyra 1H në atë slot merr protokollin, detyrat e slotit dhe detyrat në proces / pa progres nga sloti paraprak |
| 6 min para | Mira Host hyn në kanal dhe pret në heshtje (nuk dëgjon dhe nuk flet). Nëse lidhja dështon, provon sërish deri në 3 herë |
| 2 min para | Thirren në 1H Diellza, Gane dhe Elza; Olsa, nëse Elza mungon sot ose s'është kyçur në fillim të slotit. Mira fillon të flasë |
| 2 min para, faza GA | 1) "A ka reply nga GA te detyrat për GA?" (detyrat me simbolin GA, sipas personave). 2) "Notes të reja?": për secilin note "A krijojmë detyrë për dikë?"; kur thonë për kë, detyra 1H krijohet menjëherë. 3) Done dhe Strike të bëra në intervalin e 1H Reports për atë slot (p.sh. 11:00 = 10:00–11:00, nga çdo slot), sipas personave në renditjen e 1H SHTYPI, pa përsëritur çka është lexuar më herët sot. Stafi fillon kur mbaron GA (jo para orës së slotit, e shumta 8 min pas saj) |
| Gjatë gjithë takimit | "Mira, shënoje në PX Notes…": Mira e ruan menjëherë në PX Notes me avatarin e Mira-s dhe e shënon te takimi |
| Stafi | Një nga një sipas renditjes së Common View: së pari detyrat e slotit paraprak në proces / pa progres (në 11:50 të të gjitha sloteve paraprake), pastaj ato të slotit. Pyetja sipas ngjyrës: e verdhë "A ke me vazhdu, kur pritet me u kry?", rozë "Pse s'ke vazhdu, kur vazhdon?", e gjelbër (kur janë kryer të gjitha) "Me çka vazhdon në slotin tjetër?". Në 16:00 edhe detyrat BLLOK. Mira thërret të radhës pak para se të mbarojë personi aktual |
| 11:50, në fund | Rishikimi PM: për secilin detyrat PM të hapura: a vazhdon, a shtyhet ndonjë (për nesër / datë tjetër) dhe pse. Shtyrjet ruhen si shënime të takimit; Mira nuk i ndryshon detyrat |
| Fundi | Transkripti dhe përmbledhja ruhen te faqja **Mira → Takimet 1H** |

**Komandat** (vetëm admin/menaxher; edhe nga faqja **Mira → Cilësimet**):

| Komanda | Çka bën |
|---|---|
| `/mira mbaj-takimet [deri_ne_ore]` | Mira i mban 1H-të sot, deri në orën e dhënë ose deri në 16:45 |
| `/mira ndalo` | Mira ndalet menjëherë |
| `/mira statusi` | Tregon a është aktive dhe kush është në radhë tani |

**Aktivizimi në server**

1. Krijo në Discord Developer Portal një aplikacion të ri "Mira Host". Në tab-in Bot merr token-in.
   Nuk duhen privileged intents.
2. Fto botin në server me lejet View Channel, Connect dhe Speak në kanalin 1H.
3. Shto Actions secret `MIRA_HOST_BOT_TOKEN` dhe variable `MIRA_HOST_ENABLED=true`, pastaj deploy.
   Migrimi `0157_mira_host` krijon tabelat.
4. Sigurohu që Diellza, Gane, Elza, Olsa dhe stafi kanë bërë `/lidh`; kush s'e ka bërë nuk merr mesazhe.
   Emrat e ekipit GA, protokolli dhe minutat për person ndryshohen te **Mira → Cilësimet**.
5. **Knowledge** (Mira → Knowledge): shto strukturën e Primex, rregulloret dhe definimet si tekst
   ose si skedar `.txt`, `.md`, `.csv`, `.json` ose `.docx`. Për PDF, ngjit tekstin manualisht.
   Dokumentet aktive i lexon para çdo takimi brenda kufirit të shenjave; pjesën tjetër e kërkon
   vetëm kur pyetet. Pikat e hapura të Kujtesës hyjnë gjithashtu, kur `MIRA_MEMORY_ENABLED=true`.

## Aktivizimi fillestar

1. Krijo serverin e ekipit në Discord dhe një aplikacion/bot në
   [Discord Developer Portal](https://discord.com/developers/applications).
2. Ftoje aplikacionin në server me scopes `bot` dhe `applications.commands`.
   Lejo `View Channels`, `Send Messages`, `Read Message History`, `Embed Links`
   (për kartat e detyrave) dhe `Manage Channels`.
   Nuk kërkohet leja `Administrator`. Mund të krijosh një kategori për kanalet personale.
   Nëse ndryshohen lejet e një kanali ekzistues, riparimi automatik kërkon
   `Manage Roles`; pa të, boti ndalon dërgimin në atë kanal dhe kërkon korrigjim.
   Leximi normal i detyrave nuk rishkruan lejet që janë tashmë të sakta.
3. Kopjo server ID (Developer Mode në Discord). Ruaj bot token vetëm në
   `backend/.env` të serverit ose në menaxherin e sekreteve; mos e commit-o.
4. Vendos në mjedisin e API-së dhe worker-it:

   ```dotenv
   DISCORD_ASSISTANT_ENABLED=true
   DISCORD_BRIDGE_SECRET=<sekret i rastësishëm, të paktën 32 byte>
   DISCORD_BOT_TOKEN=<bot token>
   DISCORD_GUILD_ID=<server ID>
   DISCORD_CATEGORY_ID=<kategori ID, opsionale>
   DISCORD_AI_MODEL=gpt-5.4-mini
   DISCORD_AGENT_MODEL=gpt-6-luna
   OPENAI_API_KEY=<çelësi OpenAI>
   PRIMEFLOW_API_BASE_URL=http://127.0.0.1:8000
   FRONTEND_URL=https://primeflow.primexeu.com
   APP_TIMEZONE=Europe/Budapest
   ```

   Për sekretin mund të përdorësh `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Backend-i refuzon të gjitha thirrjet e botit kur integrimi është i çaktivizuar.
   Header-i `X-Primeflow-Discord-Secret` përdoret vetëm midis botit dhe API-së.
   Nëse API-ja ndodhet në kompjuter tjetër, përdor HTTPS.

5. Në folderin `backend`, instalo `python -m pip install -r requirements-discord.txt`.
   Apliko migrimet me `alembic upgrade head`, pastaj rinis API-në dhe ndërto frontend-in.
   Migrimi i ri është `0148_discord_assistant`; nuk i ndryshon tabelat e detyrave.
6. Nise worker-in nga folderi `backend`: `python discord_bot.py`.
   Për PM2 në Windows, me mjedisin e backend-it të konfiguruar:

   ```powershell
   pm2 start discord_bot.py --name primeflow-discord --interpreter python --cwd C:\path\to\Primex-TaskManager\backend
   pm2 save
   ```

   Worker-i është proces më vete; nuk nis nga API-ja. GitHub Actions e
   konfiguron dhe e nis automatikisht pasi API-ja të jetë gati, kur ekzistojnë
   Repository secrets `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` dhe
   `DISCORD_BRIDGE_SECRET`. Kërkohet edhe `OPENAI_API_KEY`.
   Biseda e lirë aktivizohet si parazgjedhje: aktivizo Message Content Intent
   edhe në Developer Portal. Deploy-i pret lidhjen reale dhe regjistrimin e komandave.
   Për ndryshime sekretesh, përdor Actions → Primex Auto Deploy → Run workflow
   pasi ky version i workflow-it të jetë publikuar. Variable opsionale
   `DISCORD_ASSISTANT_ENABLED=false` e çaktivizon asistentin në deploy-in vijues;
   `DISCORD_MESSAGE_CONTENT_ENABLED=false` e kufizon në dropdown dhe /pyet.
   Përdor vetëm një worker. API-ja mund të ketë disa procese.
7. Hape `/discord`, gjenero kodin, pastaj përdor `/lidh` në Discord. Rifresko
   faqen për ta parë lidhjen dhe për ta hapur kanalin personal.

## Navigimi: një mesazh, pak klikime

`/detyrat` shfaq titujt e numëruar dhe një buton për secilin numër (20 për faqe).
Klikimi e kthen të njëjtin mesazh në kartën e detyrës; kanali nuk mbushet me
mesazhe të reja. Karta tregon statusin, slotin, afatin dhe sa pika janë kryer në një rresht,
pastaj të gjitha pikat: ✅ ~~të bëra strike~~ (me orën e strike-it) dhe ⬜ të hapura. Teksti i plotë hapet privatisht te
**Më shumë → 📄 Teksti i plotë**.

Butonat kryesorë ndjekin statusin: To Do → **▶ Fillo / ✅ Mbylle**, Në progres →
**✅ Mbylle / ⏸ WFE**, WFE → **▶ Vazhdo / ✅ Mbylle**; gjithmonë **☑ Pikat** dhe
**Hap PrimeFlow**. Menuja **Më shumë** ka Edito, Koment, Mbylle me koment,
Slot/AM–PM, Konfirmim, statuset e tjera, udhëzimin AI, agjentin dhe Rifresko.
**◀ ↩ Lista ▶** lëvizin mes detyrave të ditës. Pas mbylljes hapet vetë detyra
tjetër; nëse PrimeFlow e refuzon mbylljen, karta tregon arsyen.
Pikat, Sloti dhe Konfirmimi hapen në të njëjtën kartë me **← Kthehu**.
Kartat e postuara para këtij ndryshimi vazhdojnë të funksionojnë.

Statuset, formularët dhe zgjedhja e pikave nuk kërkojnë interpretim AI: ndryshimi
i saktë kalon në të njëjtat kontrolle të API-së, versionit të detyrës dhe auditimit.
Te ☑ Pikat mund të zgjidhen disa pika njëherësh për strike ose heqje strike;
listat e gjata kanë faqe prej 25 pikash. Konfirmimi zgjedh personin nga përdoruesit
aktivë. Edito hap titullin, përshkrimin, afatin dhe AM/PM; shënimet e
strike-ve ruhen për tekstin e pandryshuar. Pas ruajtjes përditësohet karta aktive.
Për detyrat me origjinë PX Notes/PX JAV, pikat merren nga shënimi burimor dhe
strike ruhet përmes `PATCH /ga-notes/{id}` ose `PATCH /plan-notes/{id}`, njësoj si
strike manual. Këto rrugë sinkronizojnë detyrat e lidhura dhe historikun e strike-ve.
Përshkrimet e veçanta dhe detyrat pa shënim ruajnë ndryshimet te detyra.
Versioni përfshin tekstin e shënimit; menuja e pikave rifreskohet pas çdo ndryshimi.
Mbyllja (butoni, teksti "mbylle" ose "U krye" te raportimi) bën strike të gjitha pikat
e hapura dhe, kur detyra nuk ka koment, shton komentin "Kryer". Për koment tjetër
përdor **Më shumë → 📝 Mbylle me koment** ose shkruaje te mesazhi. Backend-i zbaton
kushtet e tjera (p.sh. personi i konfirmimit).

**Më shumë → 🤖 Udhëzim për AI**, mesazhet në kanal dhe `/pyet udhezimi:...` mbeten
për kërkesa të lira. `/pyet` punon edhe pa Message Content Intent. Pyetjet sqaruese ruhen
për detyrën aktive. Tekstet shumë të gjata kanë link për hapje në PrimeFlow;
zgjedhja e pikave vazhdon të përfshijë të gjitha pikat përmes faqeve.

Për mesazhe të zakonshme në kanal, aktivizo **Message Content Intent** në Bot
settings të Developer Portal dhe vendos `DISCORD_MESSAGE_CONTENT_ENABLED=true`.
Rinis worker-in. Lejet e Discord-it për aplikacionet e mëdha mund të kërkojnë
miratim për intent-in.

Përdoruesit mund të shkruajnë direkt, pa klikuar më parë. Detyra gjendet nga ajo që
shohin: mesazhi i botit ku bëjnë Reply, përndryshe mesazhi i fundit i botit me detyra
(lista, kujtesa e slotit ose karta), pastaj detyrat e tjera të ditës. "Këtë detyrë"
është detyra e vetme e shfaqur; "detyra 2" ndjek numrat e listës; një fjalë nga titulli
zgjedh detyrën. Kur nuk është e qartë, boti pyet dhe përgjigjja e shkurtër ("e dyta")
e plotëson kërkesën. Rezultati shfaqet si karta e përditësuar e detyrës.

Shembuj:

- `Te përshkrimi bëji strike pikat 1, 3 dhe 5, lëre në progres.`
- `Hiq strike nga pika 2 e titullit.`
- `Bëje WFE dhe shto komentin: Presim përgjigjen e klientit.`
- `Dërgoje për konfirmim te LH.`
- `Ndrysho afatin në nesër ora 11:00 dhe periudhën AM.`

Numrat e pikave referojnë listën që shfaq boti. Nëse titulli dhe përshkrimi kanë
numra të njëjtë, asistenti kërkon të sqarohet fusha. `WFE` përdor statusin real
`WAITING_CLIENT`. Mbyllja përdor `DONE`; validimet ekzistuese mund të kërkojnë
koment përfundimi ose person konfirmimi. Asistenti nuk kalon këto validime.

Përveç statuseve dhe strike-ve, mjetet mbulojnë fushat e editimit të detyrës,
komentin personal, checklist items që janë të aksesueshme, slotin sipas datës,
markerët, heqjen nga dita, deaktivizimin dhe fshirjen. Veprimet që kërkojnë rol
manager/admin refuzohen për staff, njësoj si në PrimeFlow. Nuk krijohen dokumente,
nuk ekzekutohet kod dhe nuk thirren endpoint-e arbitrare nga modeli.

## Delegimi te agjenti: hulumtim dhe përgatitje materialesh

Në kartën e detyrës, **Delegoja agjentit** hap zgjedhjen e detyrës së plotë ose
të një pike nga titulli/përshkrimi. Zgjidh **Hulumtim në internet** për rezultate
me burime ose **Përgatit tekst / analizë** për draft nga konteksti i detyrës.
Plotëso udhëzimin dhe rezultatin që pret. Formularët punojnë edhe pa Message
Content Intent. Përzgjedhësit e pikave kanë faqe me deri 25 zgjedhje.

Shembull: zgjidh pikën “Hulumto konkurrentët”, pastaj kërko “Krahaso 5 kompani
në Gjermani, me shërbimet kryesore dhe linket e burimeve”. Për draft mund të
kërkosh “Përgatit tekstin e ofertës nga kërkesat e përshkrimit; listo veçmas
informacionin që ende mungon”.

Punët ruhen në `discord_agent_runs` dhe shfaqin gjendjen aktuale: në radhë,
duke punuar, gati për kontroll, dështoi ose anuluar. **Rezultatet AI** në kartë
hap historikun, edhe pas rinisjes së botit. **Rifresko rezultatin** lexon gjendjen
nga databaza. Rezultatet e gjata dhe lista e plotë e burimeve bashkëngjiten si
skedar `.txt`; burimet shfaqen edhe si linke të klikueshme në Discord.

**Prano rezultatin** ruan pranimin. **Prano dhe shëno pikën të kryer** përdor API-në
ekzistuese të detyrës për strike dhe auditim. Nëse detyra/pika ndryshoi ndërkohë,
shënimi refuzohet dhe rezultati mbetet për kontroll. Pranimi i punës së një
detyre të plotë nuk e mbyll detyrën; përdor **Mbylle** me validimet normale.
**Kërko ndryshime** krijon një punë të re me rezultatin paraardhës si kontekst.
**Anulo** kërkon ndalimin; nëse OpenAI kishte përfunduar ndërkohë, ruhet rezultati
real. Boti nuk pretendon anulim të një pune tashmë të përfunduar.

Modeli i agjentit është `DISCORD_AGENT_MODEL=gpt-6-luna`, i pavarur nga modeli i
interpretimit të komandave. Aplikacioni nuk vendos kufi monetar, limit ditor,
kufi tokenësh ose numri kërkimesh. Vazhdon të zbatohet konfigurimi dhe aksesi i
llogarisë OpenAI. Nuk ka kalim automatik në një model tjetër kur mungon aksesi.
GitHub Actions pranon variable `DISCORD_AGENT_MODEL`; pa të përdor `gpt-6-luna`.

Kërkohet migrimi `0149_discord_agent_runs`, API-ja, Celery worker, Celery beat
dhe një worker Discord. Celery kontrollon punët çdo 30 sekonda dhe boti kontrollon
rezultatet çdo 30 sekonda. Ekzekutimi përdor OpenAI Responses në background me
`store=true`: konteksti/rezultati ruhen nga OpenAI sipas politikës së projektit,
dhe rezultati ruhet gjithashtu në PostgreSQL. Dërgimi në Discord përdor tokenin
e botit, jo interaction-in që mund të ketë skaduar.

Revokimi i lidhjes ose heqja e caktimit ndalon aksesin/dorëzimin dhe kërkon
anulimin e punëve aktive. Rinisja vazhdon leximin e OpenAI response ID ekzistues.
Nëse nisja mbetet e paqartë pas timeout-it pa response ID të ruajtur, puna nuk
përsëritet automatikisht: kontrollo aktivitetin e projektit OpenAI para se të
nisësh një punë të re. Kjo shmang kërkesa të dyfishta me pagesë. ID-të që mbërrijnë
vonë ruhen për anulim të riprovueshëm. Celery duhet të ketë akses shkrimi në
`backend/.discord-agent-recovery/`; kjo dosje ruan vetëm ID rikuperimi dhe duhet
të ruhet gjatë rinisjeve/deploy-it, që ndërprerjet e databazës të mos humbin ID-të.
Dorëzimi përdor
nonce dhe marker të qëndrueshëm në mesazhet e botit për rikuperimin pas ACK të
humbur; nuk premtohet exactly-once në çdo gabim platforme.

Versioni i parë hulumton dhe përgatit përmbajtje. Dërgimi real i email-eve,
publikimi, blerjet, ekzekutimi i kodit dhe leximi i bashkëngjitjeve/dokumenteve
private të kompanisë kërkojnë integrime të tjera. Konteksti përmban vetëm
titullin, përshkrimin, objektivin dhe komentin e vetë përdoruesit.

Për verifikim pa shpenzim OpenAI përdor testet e simuluara:
`python -m unittest discover -s tests -p "test_discord*.py" -v` dhe
`python -m unittest tests.test_migration_graph -v`, nga `backend`.

## Orari dhe përzgjedhja

Nga e hëna në të premte, në `APP_TIMEZONE`:

| Ora e pyetjes | Detyrat |
|---|---|
| 10:00 | Sloti 10:00 |
| 11:00 | Sloti 11:00 |
| 11:50 | Sloti 11:50 |
| 11:50 | AM |
| 14:20 | Sloti 14:20 |
| 16:00 | Sloti 16:00 |
| 16:05 | PM |

Në fillim të secilit slot 1H, çdo staf aktiv me Discord të lidhur dhe kanal personal
merr pyetjet që vlejnë për detyrat e atij sloti, pavarësisht pranisë në kanalin zanor
dhe nga aktivizimi i Mira Host. Mesazhi ruan @personin, orën, ngjyrën, titullin dhe
butonin **🎧 Kyçu në takimin 1H** (`DISCORD_1H_VOICE_CHANNEL_ID`). Plani i slotit ruhet
kur përgatitet dërgimi: detyrat e një sloti tjetër nuk shtohen automatikisht.

Ka vetëm tri pyetje automatike:
- IN_PROGRESS: “A ke me vazhdu me [detyrën]? Kur pritet me u kry?”
- TODO: “Pse s’ke vazhdu me [detyrën]? Kur vazhdon?”
- Kur të gjitha detyrat e planifikuara janë DONE: “Me çka ke me vazhdu në slotin tjetër?”

Pa detyra ose pa pyetje të nevojshme, nuk dërgohet mesazh. **Përgjigju** hap formularin
për përgjigjen dhe kohën e vazhdimit/përfundimit. Edhe Reply te karta ruan përgjigjen
si raportim; shkrimi i një date në përgjigje nuk ndryshon afatin e detyrës.
**Progres / strike**, **Koment**, **U krye** dhe **Shtyje** përdorin veprimet ekzistuese.
Shtyrjet ndjekin formularin dhe konfirmimin ekzistues të Diellzës. Mesazhi **Rifresko**
lexon gjendjen e fundit; **Rishiko / ndrysho përgjigjen** ruan edhe historikun origjinal.
**Kalo** e lë pyetjen pa përgjigje. Kartat 1H mbeten të përdorshme gjatë ditës.

Te **Mira → Takimet 1H**, përgjigjet shfaqen sipas datës, slotit, personit dhe detyrës:
gjendja në fillim/aktuale, përgjigjja, koha e pritshme, historiku i veprimeve dhe shtyrjet
në pritje/konfirmuara/refuzuara. Slotet shfaqen edhe kur nuk ka takim të udhëhequr me zë.
Migrimi `0170_discord_one_h_reports` shton arkivin JSONB në `discord_reminders`.

AM/PM vazhdon me **Fillo raportimin**, **U krye / Vazhdon / WFE / Kalo** dhe mbylljen
e disa detyrave njëherësh. Validimet e statusit, komentit dhe konfirmimit mbeten në API.

Përzgjedhja përdor dritaren ditore të API-së `/api/tasks`, assignee-n aktual dhe
detyrat aktive (edhe të kryerat për pyetjen e slotit tjetër). Sloti specifik i datës ka përparësi ndaj slotit
bazë. AM/PM përdor `finish_period`. Në 16:05 lexohet ende dita aktuale; ndryshimi
i slotit vazhdon të ndjekë rollover-in ekzistues në 16:00.

Worker-i kontrollon çdo 30 sekonda. Ka dritare rikuperimi 5 minuta, që një rinisje
e shkurtër të mos humbë kujtesën. Nuk ridërgohen kujtesat e vjetra pas kësaj
dritareje. Regjistri unik `link/day/bucket`, lease-i dhe nonce-t Discord shmangin
ridërgimin në retry-t e zakonshme. Nuk premtohet delivery exactly-once për
ndërprerje të gjata ose gabime të platformës.

## Kujtesat e takimeve

Pjesëmarrësit e zgjedhur te **Participants & reminder** në PrimeFlow marrin kujtesën
edhe në kanalin e tyre personal në Discord, me përmendje (@) që Discord-i të bjerë
si njoftim në telefon/desktop. Vlen koha e kujtesës së takimit (p.sh. 15 minuta
para), si dhe anulimet dhe përsëritjet, njësoj si njoftimet në shfletues.

- **Takim i jashtëm:** "🔔 Takim pas N min", me butonin **🔗 Hap takimin** kur
  takimi ka link.
- **Takim i brendshëm:** kujtesa para takimit dhe, kur fillon, "🔴 Takimi po fillon
  tani" për secilin pjesëmarrës, me **🎧 Hyr në kanalin zanor**. Kanali zanor është
  `DISCORD_MEETING_VOICE_CHANNEL_ID` (GitHub Actions variable, opsionale); pa të
  përdoret kanali i parë zanor i serverit.
- **Pas takimit:** kur mbaron takimi (sipas orës së përfundimit; pa të, 30 min pas fillimit)
  secili pjesëmarrës merr "❓ A u mbajt takimi?" me **✅ Mbajtur / ✖ Anuluar**. Zgjedhja ruhet
  njësoj si kolona Mbajtur/Anuluar te Common View, dhe pyetja te pjesëmarrësit e tjerë
  përditësohet me përgjigjen dhe emrin e personit që e shënoi. Nëse statusi është vendosur
  tashmë në Common View, pyetja nuk dërgohet. Pyetja dërgohet brenda 2 orëve pas përfundimit.
- Kujtesa liston edhe pjesëmarrësit e tjerë. Personat pa llogari Discord të lidhur
  marrin vetëm njoftimin në PrimeFlow.

**Krijimi nga chat-i:** p.sh. "krijo tak int për nesër ora 15 me unë, endi, rinesa, gane".
Boti kupton llojin (TAK INT / TAK EXT), datën dhe orën, pjesëmarrësit (emri, mbiemri ose
username; "unë" = vetë personi), titullin, platformën dhe linkun kur jepen. Kur mungon ora,
lloji ose një emër nuk është unik, pyet; përgjigjja e shkurtër vazhdon draftin. Para ruajtjes
shfaqet karta me **✅ Krijo takimin / ✖ Anulo**. Takimi krijohet përmes `POST /api/meetings`
me lejet e personit, në departamentin e tij. Nëse orari përputhet me 1H, boti i tregon
përplasjet dhe ofron **Krijo gjithsesi**. Kujtesa standarde (15 min) vlen menjëherë.

Discord nuk lejon që një bot të nisë thirrje telefonike/zanore; "thirrja" është
përmendja me njoftim dhe butoni për t'u futur në kanalin zanor. Kërkohet migrimi
`0150_discord_meeting_alerts`. Pa të, kujtesat e takimeve nuk dërgohen, por
kujtesat e detyrave vazhdojnë normalisht.

## Njoftimi për push: `/push`

Kushdo me llogari të lidhur shkruan `/push` (opsionale `minuta`, parazgjedhje 5, dhe `shenim`)
para se të publikojë PrimeFlow. Të gjithë të tjerët marrin në kanalin personal, me përmendje,
një njoftim se PrimeFlow po përditësohet dhe se ndryshimet gjatë asaj kohe mund të mos ruhen.
Kur deploy-i e rinis botin me version të ri (`APP_BUILD_SHA` ndryshon) brenda 45 minutave,
të gjithë marrin automatikisht "✅ PrimeFlow u përditësua" (një herë, edhe pas disa `/push`).
Çdo `/push` dërgon njoftimin, pa kufi kohe. Njoftimet ruhen te `discord_actions`.

## Identiteti, lejet dhe historiku

API-ja kontrollon serverin, Discord user ID dhe channel ID bashkë. Detyra duhet
t'i jetë caktuar përdoruesit dhe të jetë aktive. Boti kontrollon dhe riparon
lejet e kanalit para dërgimit. Pronari dhe administratorët e serverit mund t'i
shohin kanalet sipas modelit të lejeve të Discord-it.

API-ja ekzekuton mjetet me identitetin aktual PrimeFlow dhe përmes endpoint-eve
ekzistuese. Strike-t regjistrohen nga mekanizmi ekzistues, përfshirë datën dhe
aktorin; nuk shkruhen drejtpërdrejt në tabelat e detyrave. Teksti i detyrave
trajtohet si të dhëna në prompt dhe mjetet kanë lista të kufizuara veprimesh.

`discord_actions` ruan ID-në e komandës, përdoruesin e lidhur, detyrën,
udhëzimin, gjendjen para veprimit dhe rezultatin. Një ID Discord nuk ekzekutohet
dy herë. Komandat e ndërprera në `PROCESSING` duhen kontrolluar në PrimeFlow
përpara se të dërgohet komandë e re. Komandat me disa endpoint-e nuk janë një
transaksion i vetëm: kur një veprim i mëvonshëm dështon, boti raporton pjesën e
zbatuar dhe gabimin. Nuk pretendon rollback.

Përdoruesi mund ta revokojë lidhjen menjëherë në `/discord`. Kujtesat ndalen dhe
komandat refuzohen. Revokimi nuk fshin mesazhet historike në Discord.

## Verifikimi lokal

`python -m unittest discover -s tests -p "test_discord*.py" -v`, nga `backend`,
mbulon testet e botit, kartave, veprimeve direkte dhe deploy-it pa lidhje me
Discord/OpenAI/databazën. Instalo varësitë opsionale
për të përfshirë testet e worker-it. `npm run build` dhe lint-i i faqes së re
kaluan. Kontrolli i plotë TypeScript dhe lint-i i sidebar-it raportojnë gabime
ekzistuese jashtë integrimit. Migrimi nuk është aplikuar në databazën reale;
hyrja me botin dhe rrjedha reale duhen verifikuar pas konfigurimit të Discord-it.

## Referenca teknike

### M2: vazhdimi në PM dhe kërkesat për shtyrje

Butoni **Kërko shtyrje** gjendet edhe te kartat e zakonshme të detyrave të hapura
nga `/detyrat`, në çdo orar dhe për AM/PM. Këto kërkesa nuk varen nga pyetja M2:
zgjedhja e datave, arsyeja dhe komenti kalojnë te e njëjta Diellza Veliu për
konfirmim. Vendimi njoftohet një herë në kanalin personal, pa publikuar komentin.
Kërkohet edhe migrimi `0167_discord_task_postponements`. Historiku i kërkesave M2 ruhet.
Pas zgjedhjes së arsyes, formulari hap Start dhe Due me datat aktuale dhe komentin
e detyrueshëm, pa pyetje për llojin e datës. Gjendja në pritje përditëson të njëjtin mesazh
të detyrës. **Kthehu te detyra**
rikthen kartën pa krijuar mesazh tjetër. Emri dhe datat aktuale mbeten të dukshme
gjatë procesit; komenti i dërguar nuk publikohet në mesazhin e kërkuesit.

Në ditët e punës, nga 11:45 deri në 12:00, pyetja **A vazhdon në PM?**
dërgohet për çdo detyrë të hapur të planifikuar për PM (përfshirë AM/PM)
brenda intervalit Start–Due të ditës. Përfshihen edhe detyrat **None (all day)**,
që ruhen me AM/PM bosh, si TODO ashtu edhe në progres. Detyrat vetëm AM nuk përfshihen në këtë pyetje.
Përgjigjet PO/JO dhe komentet ruhen veçmas nga dorëzimi M2, në seksionin 7 të raportit.
PO hap një koment opsional; JO kërkon shpjegim. Mesazhi ekzistues përditësohet pa
publikuar komentet e punonjësit në kanal.

**Kërko shtyrje** lejon ndryshimin e Start, Due, ose të dyjave në të njëjtin formular;
fushat e pandryshuara ruhen siç janë. Komenti është i detyrueshëm dhe arsyeja
zgjidhet nga kodet standarde të platformës. Propozimi ruhet në pritje; detyra ende
nuk ndryshon. Diellza Veliu (`diellza.veliu`), në kanalin e saj personal Discord,
merr datat aktuale, datat e propozuara, arsyen dhe komentin, me butonat e konfirmimit/refuzimit.
Vetëm konfirmimi i saj e zbaton ndryshimin përmes rrjedhës normale të detyrave,
me auditimin dhe arsyen/komentin e shtyrjes. Refuzimi i lë datat të pandryshuara.
Nëse datat, përgjegjësit ose grupi ndryshojnë ndërkohë, kërkesa vjetrohet dhe nuk
mbishkruan ndryshimet e reja. Konfirmimi dhe datat ruhen në të njëjtin transaksion.

Kërkohet migrimi `0163_discord_m2_approvals`. Njoftimet e konfirmimit vazhdojnë
edhe jashtë intervalit të mbledhjes së pyetjeve. Tabela `discord_m2_postponements`
ruan propozimin, vendimin dhe marrjen e njoftimeve, që rinisja e botit të mos
humbasë kërkesat në pritje. Komenti i shtyrjes shfaqet në kolonën **Komenti**;
**Koment manual** mbetet i pavarur.

- [Discord interactions](https://github.com/discord/discord-api-docs/blob/main/developers/interactions/receiving-and-responding.mdx)
- [Discord permissions](https://github.com/discord/discord-api-docs/blob/main/developers/topics/permissions.mdx)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
