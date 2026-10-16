# Delegimi i detyrave te agjenti në Discord

## Qëllimi dhe kërkesat e konfirmuara

Përdoruesi delegon një detyrë ose një pikë të titullit/përshkrimit te një agjent
OpenAI për hulumtim ose përgatitje përmbajtjeje. Modeli është saktësisht
`gpt-6-luna`. Aplikacioni nuk vendos buxhet monetar, limit ditor shpenzimi apo
ndalim sipas kostos. Kufijtë e llogarisë dhe të API-së OpenAI vazhdojnë të zbatohen.

Ky version realizon rrjedhën e propozuar në bisedë: delegim, punë në sfond,
rezultat i ruajtur te detyra/pika dhe pranim nga përdoruesi. Organizimi automatik i
ditës mbetet punë e veçantë.

## Përvoja në Discord

1. Karta e detyrës merr butonin **Delegoja agjentit** dhe **Rezultatet AI**.
2. Përdoruesi zgjedh **Detyra e plotë**, një pikë titulli ose një pikë përshkrimi.
   Pikat kanë numrin dhe tekstin e shfaqur; listat përdorin faqe me deri 25 zgjedhje
   dhe ID unike për çdo komponent, përfshirë butonat e çaktivizuar.
3. Zgjedh mënyrën **Hulumtim në internet** ose **Përgatit tekst / analizë** dhe
   plotëson udhëzimin në formular. Formulari tregon objektivin e zgjedhur.
4. Boti konfirmon krijimin e punës dhe shfaq **Në radhë**, **Duke punuar**,
   **Gati për kontroll**, **Dështoi** ose **Anuluar**. Ekziston butoni **Anulo**.
5. Rezultati përmban tekstin, burimet e klikueshme, modelin dhe kohën e punës.
   Rezultatet e gjata ofrohen si skedar UTF-8 `.txt`, krahas përmbledhjes në kanal.
6. **Prano rezultatin** e regjistron pranimin. Për një pikë ekziston edhe
   **Prano dhe shëno pikën të kryer**. Për detyrën e plotë, mbyllja mbetet veprim
   i veçantë me validimet ekzistuese të PrimeFlow.
7. **Kërko ndryshime** hap formular dhe krijon punë të re që referon rezultatin
   paraardhës. Historiku ruhet; një rezultat i mëparshëm nuk mbishkruhet.

Formularët dhe kontrollet punojnë pa Message Content Intent. Përfundimet dërgohen
me identitetin normal të botit në kanal, që të funksionojnë edhe pasi skadon
interaction-i fillestar ose pasi riniset worker-i.

## Çfarë kryen versioni i parë

- Hulumtim në internet, krahasime, përmbledhje dhe raporte me burime.
- Draft ofertash, email-esh, tekstesh dhe analiza nga të dhënat e detyrës dhe
  udhëzimi i përdoruesit.
- Në mungesë informacioni, rezultati tregon pyetjet ose informacionin që duhet
  plotësuar, pa shpikur kryerjen e punës.
- Dërgimi real i email-eve, publikimi, blerjet, ekzekutimi i kodit dhe ndryshimet
  në sisteme të jashtme kërkojnë integrime të veçanta dhe nuk përfshihen këtu.
- Leximi i bashkëngjitjeve private dhe kërkimi në dokumente të kompanisë nuk
  përfshihen pa rrjedhë të posaçme të autorizimit dhe ngarkimit të skedarëve.

## Arkitektura

Përdoren FastAPI, PostgreSQL, Celery/Redis dhe worker-i Discord që ekzistojnë.
Një punë ruhet në databazë përpara ekzekutimit. Një tick Celery e nis përmes
Responses API në background dhe tick-et pasuese lexojnë gjendjen e response-it.
As API-ja e Discord-it dhe as procesi web nuk presin përfundimin e hulumtimit.
Celery beat kontrollon punët çdo 30 sekonda. Boti merr njoftimet e gatshme çdo
30 sekonda, kontrollon privatësinë e kanalit dhe regjistron mesazhin e dërguar.

Përdoret `model="gpt-6-luna"`, `background=true`, `store=true`, me reasoning
`medium`. Ruajtja në OpenAI mundëson marrjen e rezultatit pas rinisjeve; rezultati
ruhet edhe lokalisht në PostgreSQL. Nëse politika e projektit OpenAI nuk lejon
ruajtjen ose background mode, gabimi shfaqet qartë pa ndërruar modelin apo
mënyrën në heshtje. Mënyra e hulumtimit përdor
`web_search` dhe kërkon të paktën një kërkim real. Mënyra e draftit nuk aktivizon
web search. Nuk shtohet kufi aplikacioni për shpenzimin, tokenët ose numrin e
kërkimeve. Përfundimi i response-it dhe anulimi nga përdoruesi mbyllin punën.
Timeout-et e rrjetit dhe kufizimi i një procesimi konkurrues të së njëjtës punë
janë kontrolle teknike dhe nuk përdoren si kufij shpenzimi.

## Ruajtja dhe qëndrueshmëria

Një tabelë e re `discord_agent_runs` ruan: UUID, link/user/task, ID e kërkesës
Discord unike, mënyrën, udhëzimin, punën paraardhëse, modelin, snapshot-in e
kontekstit, fingerprint-in, fushën dhe identitetin e pikës, gjendjen,
OpenAI response ID, tekstin e rezultatit, burimet, usage-in nëse ofrohet,
gabimin publik, datat, lease-in e përpunimit/dërgimit, message ID dhe pranimin.
Pika identifikohet nga identiteti ekzistues i tekstit dhe shfaqja e saj origjinale,
jo vetëm nga numri që mund të ndryshojë me editimin e detyrës.

Gjendjet e brendshme: `QUEUED`, `SUBMITTING`, `RUNNING`, `READY`, `FAILED`,
`CANCEL_REQUESTED`, `CANCELLED`. Pranimi ruhet veçmas nga gjendja e ekzekutimit.
Pretendimi i punës bëhet atomik me row lock/lease që worker-at të mos nisin
dy response për të njëjtën kërkesë. Tick-et nuk mbajnë transaksion të hapur
gjatë thirrjeve në OpenAI ose Discord.

Nëse worker-i riniset me response ID të ruajtur, vazhdon leximi i atij response-i.
Nëse dërgimi në OpenAI ka rezultat të paqartë pa response ID, puna raportohet si
e dështuar/e paqartë; nuk niset automatikisht një response i dytë me pagesë.
Gabimet e leximit për response ekzistues mund të riprovohen pa e rikrijuar atë.
Anulimi në `QUEUED` nuk nis response; në `RUNNING` kërkon anulimin në OpenAI.
Në rast gare me përfundimin, databaza regjistron gjendjen reale pa pretenduar
se anulimi e ndaloi një response që tashmë kishte përfunduar.

## Identiteti dhe pranimi

Çdo krijim, lexim, anulim dhe pranim kontrollon identitetin ekzistues
Discord user/guild/channel, lidhjen aktive dhe caktimin aktual të detyrës.
Këto kontrolle përsëriten para nisjes dhe para dërgimit të rezultatit.
Revokimi i lidhjes ndalon nisjet/dërgimet dhe kërkon anulim për punët aktive.

Konteksti përfshin titullin, përshkrimin, objektivin dhe komentin e vetë
përdoruesit. Nuk dërgohen komente private të personave të tjerë, tokenë apo
sekrete. Teksti i detyrës dhe burimet e internetit trajtohen si të dhëna.
Agjenti prodhon rezultat; nuk ndryshon vetë statusin, tekstin ose strike-t.

Pranimi me strike kontrollon sërish fingerprint-in dhe identitetin e pikës.
Nëse detyra ndryshoi, rezultati mbetet i lexueshëm dhe strike automatik refuzohet
derisa përdoruesi të rishikojë objektivin aktual. Strike kalon përmes API-së
ekzistuese dhe auditimit. Kërkesat e përsëritura nuk e zbatojnë veprimin dy herë.
Pranimi i thjeshtë nuk kërkon ndryshimin e detyrës.

## Ndryshimet e parashikuara

- Model dhe migrim i ri për `discord_agent_runs`, pas head-it real të Alembic.
- Shërbim i veçantë për Responses API, state machine dhe serializimin e rezultateve.
- Router i veçantë për krijimin/listimin/leximin/anulimin/pranimin dhe njoftimet.
- Task Celery dhe schedule beat për procesimin e punëve të ruajtura.
- Modul i veçantë Discord për formularët, përzgjedhjen e pikave dhe rezultatet;
  lidhje të vogla në `discord_bot.py` dhe `discord_ui.py`.
- Konfigurim i veçantë `DISCORD_AGENT_MODEL=gpt-6-luna`, i përcjellë edhe nga
  deploy-i. Modeli i interpretimit të komandave ekzistuese mbetet i pavarur.
- Dokumentacion dhe teste të përfshira në kontrollin ekzistues të deploy-it.

## Verifikimi i nevojshëm

Testet mbulojnë detyrën e plotë dhe pikat e titullit/përshkrimit, përfshirë pika
me tekst të njëjtë dhe lista mbi 25 pika; ID komponentësh unike; përdorimin ekzakt
të `gpt-6-luna`; mungesën e kufijve të aplikacionit për shpenzim/tokenë/kërkime;
web search vetëm në mënyrën e hulumtimit; citimet; skedarët e rezultateve të gjata;
identitet të gabuar; revokim; rireshtim/ndryshim pikash; dërgime të dyfishta;
rinisje dhe timeout të paqartë; anulim gjatë procesimit; pranim të përsëritur;
kalimin e strike përmes API-së ekzistuese; dhe regresionet e botit aktual.

Testet lokale përdorin API të simuluar, pa shpenzim real OpenAI. Verifikimi real
me çelësin e serverit dhe migrimi në databazën reale raportohen veçmas.

## Burimet zyrtare

- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/background

## Statusi

Specifikimi është përgatitur për rishikim. Kodi i produktit nuk është ndryshuar.
