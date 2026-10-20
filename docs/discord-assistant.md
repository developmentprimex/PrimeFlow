# Asistenti personal PrimeFlow në Discord

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

Mbahet një takim në një kohë për server. Pas ndalimit, Mira del nga voice
channel menjëherë; radha lokale e transkriptimit përfundon përpara se të nisë
një takim i ri. Shënimet e ruajtura kanë lejet normale të PX Notes. Teksti i
takimit nuk zbatohet si komandë për detyra. Përmbledhja nuk postohet në kanalin
e përbashkët. Audioja nuk arkivohet; ruhen segmentet e transkriptuara dhe drafti.

Në shkëputje ose gabim të audios njoftohet organizuesi. Shënimet e pjesshme
etiketohen qartë. Pas një rinisjeje nuk rifillon dëgjimi automatikisht; sesioni
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
| 09:50 | Sloti 10:00 |
| 10:50 | Sloti 11:00 |
| 11:40 | Sloti 11:50 |
| 11:50 | AM |
| 14:10 | Sloti 14:20 |
| 15:50 | Sloti 16:00 |
| 16:05 | PM |

Kujtesa e përmend personin (@) dhe liston detyrat e slotit. Te slotet 1H (jo AM/PM)
shton "Takimi 1H fillon në …" dhe butonin **🎧 Kyçu në takimin 1H**, që hap kanalin zanor
`DISCORD_1H_VOICE_CHANNEL_ID` (parazgjedhje: kanali 1H i serverit). Vetëm personat që kanë
detyra në atë slot e marrin. **📝 Fillo raportimin**
kalon detyrë pas detyre në të njëjtin mesazh me **✅ U krye / 🔵 Vazhdon / ⏸ WFE /
⏭ Kalo** dhe në fund lë përmbledhjen. **✅ Shëno të kryerat** mbyll disa detyra
njëherësh. Validimet e PrimeFlow mbeten: nëse mbyllja kërkon koment ose konfirmim,
boti e thotë privatisht dhe **📂 Hap detyrën** hap kartën e plotë. Kur personi
nuk ka detyra për slotin, nuk dërgohet asnjë mesazh. Kur vjen kujtesa tjetër,
një raportim i mëparshëm i papërfunduar kthehet në "pa raportuar", pa butona.
Butonat e raportimit punojnë vetëm brenda ditës së kujtesës.

Përzgjedhja përdor dritaren ditore të API-së `/api/tasks`, assignee-n aktual dhe
vetëm detyrat aktive e të hapura. Sloti specifik i datës ka përparësi ndaj slotit
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

- [Discord interactions](https://github.com/discord/discord-api-docs/blob/main/developers/interactions/receiving-and-responding.mdx)
- [Discord permissions](https://github.com/discord/discord-api-docs/blob/main/developers/topics/permissions.mdx)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
