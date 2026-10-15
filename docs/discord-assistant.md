# Asistenti personal PrimeFlow në Discord

Secili përdorues lidh llogarinë e vet në faqen `/discord` të PrimeFlow. Kodi
njëpërdorimësh vlen 10 minuta dhe përdoret me `/lidh kodi:...` në serverin e ekipit.
Fjalëkalimet dhe tokenët PrimeFlow nuk vendosen në Discord. Një llogari Discord
lidhet me një llogari PrimeFlow; kodi i ri anulon kodin e mëparshëm.

## Aktivizimi fillestar

1. Krijo serverin e ekipit në Discord dhe një aplikacion/bot në
   [Discord Developer Portal](https://discord.com/developers/applications).
2. Ftoje aplikacionin në server me scopes `bot` dhe `applications.commands`.
   Lejo `View Channels`, `Send Messages`, `Read Message History` dhe `Manage Channels`.
   Nuk kërkohet leja `Administrator`. Mund të krijosh një kategori për kanalet personale.
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

## Biseda dhe dropdown

`/detyrat` shfaq detyrat e hapura për sot. Dropdown-i ndahet në faqe prej 25
detyrash. Pas përzgjedhjes shfaqen detajet, pikat e titullit/përshkrimit dhe një
dropdown me veprimet. Veprimi hap formularin e udhëzimit. `/pyet udhezimi:...`
punon edhe pa Message Content Intent. Pyetjet sqaruese ruhen për detyrën aktive.

Për mesazhe të zakonshme në kanal, aktivizo **Message Content Intent** në Bot
settings të Developer Portal dhe vendos `DISCORD_MESSAGE_CONTENT_ENABLED=true`.
Rinis worker-in. Lejet e Discord-it për aplikacionet e mëdha mund të kërkojnë
miratim për intent-in. Përdoruesit shkruajnë pasi kanë zgjedhur detyrën.

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

Përzgjedhja përdor dritaren ditore të API-së `/api/tasks`, assignee-n aktual dhe
vetëm detyrat aktive e të hapura. Sloti specifik i datës ka përparësi ndaj slotit
bazë. AM/PM përdor `finish_period`. Në 16:05 lexohet ende dita aktuale; ndryshimi
i slotit vazhdon të ndjekë rollover-in ekzistues në 16:00.

Worker-i kontrollon çdo 30 sekonda. Ka dritare rikuperimi 5 minuta, që një rinisje
e shkurtër të mos humbë kujtesën. Nuk ridërgohen kujtesat e vjetra pas kësaj
dritareje. Regjistri unik `link/day/bucket`, lease-i dhe nonce-t Discord shmangin
ridërgimin në retry-t e zakonshme. Nuk premtohet delivery exactly-once për
ndërprerje të gjata ose gabime të platformës.

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
mbulon 44 teste pa lidhje me Discord/OpenAI/databazën. Instalo varësitë opsionale
për të përfshirë testet e worker-it. `npm run build` dhe lint-i i faqes së re
kaluan. Kontrolli i plotë TypeScript dhe lint-i i sidebar-it raportojnë gabime
ekzistuese jashtë integrimit. Migrimi nuk është aplikuar në databazën reale;
hyrja me botin dhe rrjedha reale duhen verifikuar pas konfigurimit të Discord-it.

## Referenca teknike

- [Discord interactions](https://github.com/discord/discord-api-docs/blob/main/developers/interactions/receiving-and-responding.mdx)
- [Discord permissions](https://github.com/discord/discord-api-docs/blob/main/developers/topics/permissions.mdx)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
