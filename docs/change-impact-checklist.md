# Harta e ndikimit të ndryshimeve

Përditësuar: 04.11.2026. Kjo hartë ruan vendet që duhen marrë parasysh kur
ndryshon një funksion i projektit. Shërben si pikënisje për kontroll; varësitë
konfirmohen në kod për ndryshimin konkret.

## Si përdoret nga Codex

1. Përcakto kategorinë dhe objektin e ndryshimit: task, projekt, takim, Note,
   planifikim, realizim ose raport.
2. Ndiq fushën ose sjelljen nga formulari dhe API-ja te listat, paraqitjet,
   gjeneruesit e raporteve dhe eksportet që e përdorin. Lista më poshtë është
   kontroll i ndikimit, jo kërkesë që çdo faqe të ketë të njëjtën paraqitje.
3. Për çdo ndryshim funksional ose vizual, njofto përdoruesin për faqet dhe
   raportet e tjera të prekura pas analizës në kod, para përgjigjes përfundimtare.
   Kjo përfshin ngjyra, CSS, filtra, etiketa dhe printim. Nëse shtrirja në këto
   vende nuk është miratuar tashmë, emërtoji dhe pyet një herë:
   **“Ky ndryshim prek edhe [faqet]. Dëshiron ta zbatojmë edhe atje, apo t'i lëmë
   vetëm për kontroll?”** Mos e hiq pyetjen duke e quajtur ndryshimin “lokal”.
   Përmendja e Common View ose një faqeje tjetër të vetme nuk do të thotë
   automatikisht se vendet e lidhura përjashtohen. Nëse përdoruesi e kufizon
   shprehimisht punën ose e ka miratuar tashmë shtrirjen, respekto vendimin pa
   pyetur përsëri, por prapë trego ndikimin. Nëse nuk ka ndikim tjetër të
   identifikuar, thuaje shkurt pa pyetje shtesë. Përfundo punën e pavarur të
   autorizuar ndërsa pret përgjigjen për pjesën shtesë. Leximi ose përditësimi i
   këtij dokumenti nuk e zëvendëson këtë komunikim me përdoruesin.
4. Për “vetëm kontroll”, verifiko sjelljen dhe raporto mospërputhjet pa bërë
   ndryshime shtesë. Dallo verifikimin në kod nga prova reale në UI/API.
5. Përmbylle me një listë të shkurtër: implementuar, kontrolluar, mbetet për
   kontroll. Mos shëno si të përfunduar një kontroll që nuk është kryer.
6. Kur zbulohet një përdorues i ri i të dhënës ose ndryshon arkitektura,
   përditëso rreshtin përkatës këtu. Excel-i është kopje për kontroll manual;
   dokumenti në repository mban udhëzimin e qëndrueshëm.

Shembull: kur kërkohet ndryshimi i ngjyrës së BLL në Common View, kontrollo
1H SHTYPI Today/Tomorrow dhe raportet që shfaqin BLL. Nëse edhe ato paraqitje
preken, tregoji dhe pyet për shtrirjen. Stilet e veçanta nuk e heqin këtë
detyrim dhe nuk nënkuptojnë se ngjyra përditësohet automatikisht gjithkund.

## Emërtimet e grupuara

- **Department Views**: Development View, Graphic Design View, Product Content
  View. Janë implementime të veçanta; kontrollohen të tria kur preken.
- **My View**: mënyrë shfaqjeje brenda faqeve të departamenteve, krahas
  Department View; nuk është një implementim i vetëm për të gjitha departamentet.
- **Finance View**: implementim më vete. Human Resources aktualisht është
  “Coming soon”; shtoje në hartë kur të implementohet.
- **M1 / M2 / M3**: Morning Report, After Break Report dhe Meetings Report.
  Një kontroll i grupuar përfshin të tre, sipas seksionit dhe të dhënave që përdorin.
- **M1 PIKAT, M2 PIKAT, M3 PIKAT**: rrjedha të veçanta nga raportet e mësipërme.
- **Projects**: përfshin faqet e projektit të përgjithshëm, Development,
  Product Content dhe Graphic Design, sipas llojit të projektit.
- **Reports** dhe **Exports**: kontrollohen raporti/formati konkret që përdor
  të dhënën, jo automatikisht çdo raport në projekt.

## Lista e kontrolleve sipas kategorisë

| Ndryshime në… | Ku duhet të kontrollohen |
|---|---|
| Taska - ndryshime të përgjithshme | My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, PX Notes, PX JAV, Weekly Planner, Monthly Planner, Open Tasks, Admin Tasks, Projects, Task Details, Realization, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Meeting Scheduler, WFC INT, Comments, Reviews, Kontrolli ditor RLZ, Weekly Planning Check |
| Taska - personale / R1 / BLL | My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, PX Notes, PX JAV, Weekly Planner, Monthly Planner, Open Tasks, Admin Tasks, Projects, Task Details, Realization, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Taska - sistemore / përsëritje | System Tasks, System Tasks Report, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Weekly Planner, Realization, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details |
| Taska - nga PX Notes | PX Notes, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Projects, Weekly Planner, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details |
| Taska - nga PX JAV | PX JAV, PX Notes (edhe printimi dhe Excel), My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Weekly Planner, Projects, PX JAV Kontrolli, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details |
| Taska - nga takimet | Meetings, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, System Tasks, Weekly Planner, Realization, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Department Views, Task Details |
| Projekte - ndryshime të përgjithshme | Projects, Department Views, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, PX Notes, PX JAV, Weekly Planner, Monthly Planner, Meeting Scheduler, Realization, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details, Open Tasks, Weekly Planning Check |
| Projekte - faza / checklista | Projects, Meetings, Common View, Department Views, My View, Exports, Task Details |
| Takime externe | Common View, My View, Department Views, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Meeting Scheduler, Projects, Admin Tasks, M1 / M2 / M3 |
| Takime interne | Common View, My View, Department Views, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Meeting Scheduler, Admin Tasks, M1 / M2 / M3 |
| Checklista takimesh | Projects, Meetings, Common View, Department Views, My View, Exports |
| PX Notes | PX Notes, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Projects, Weekly Planner, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| PX JAV | PX JAV, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Weekly Planner, Projects, PX JAV Kontrolli, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Mungesa dhe pushime | Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow (edhe tabelat hyrëse), 1H Reports, Weekly Planner, PX JAV / PX JAV Kontrolli, Realization / Kontrolli ditor RLZ, Weekly Planning Check, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, End Week BZ, Reports / Daily Report, eksportet e detyrave, raportimi personal Discord 1H/M2/M3 |
| WFC INT / Waiting Client | WFC INT, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, PX Notes, PX JAV, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Planifikim | Weekly Planner, Monthly Planner, PX JAV, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Realization, Weekly Planning Check, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Realization dhe Reviews | My View, Department Views, Finance View, Realization, Reviews, Common View, Weekly Planner, Kontrolli ditor RLZ, M3 PIKAT |
| Regjistrime dhe Mira | Regjistrimet, Mira, Meetings, PX Notes, Task Details |
| Mira Notetaker / Smart Notes | Mira → Notetaker dhe API-ja e historikut shfaqin çdo takim të përpunuar për të gjithë përdoruesit e autentikuar të PrimeFlow, pavarësisht organizatorit ose kanalit të nisjes. Përmbledhja ruhet veç shënimeve dhe transkriptit. Kontrollo Discord (`/takimi`, Mira Zhvillim, `mira-kontrolli`, kanalet personale), Mira → Shënimet, PX Notes, lidhjet e transkriptit dhe përjashtimin ekzistues të Mira Notes nga 1H Reports, After Break Report dhe M1 PIKAT. |
| Nisja e botëve të regjistrimit | Boti kryesor i Discord-it dhe Mira Zhvillim përdorin të njëjtin format të shënimeve. Moduli `discord_voice_note_format.py` ndan etiketat dhe datën nga klienti OpenAI dhe router-at FastAPI. Kontrollo importin e të dy botëve në një proces të pastër dhe gatishmërinë në Discord pas deployment-it. |
| Ask MIRA | Komanda `/mira pyet`, përmendjet e botit kryesor, API-ja Discord dhe lidhjet te segmentet e Notetaker. Karta private shfaq pyetjen, përgjigjen dhe burimet e lidhura. Transkripti është burimi, kujtesa mban kontekstin dhe qasja verifikohet sërish para kthimit të burimeve. Kontrollo dërgimin privat, identitetin e revokuar, kufirin e pyetjeve, hapjen e lidhjeve dhe komandat e raportimit 1H që ndajnë grupin `/mira`. |
| Mira Notetaker / Kujtesa e takimit | Notetaker dhe Kujtesa shfaqin pikat, sqarimet, burimet dhe historikun për përdoruesit e autentikuar. Çdo përdorues mund të japë sqarim dhe historiku ruan autorin. Projekti lidhet nga një përputhje unike në departamentin e takimit. Kontrollo që një çështje e përsëritur të ruajë burimet edhe kur takimet u nisën nga dy persona dhe që sqarimet të ruhen veç transkriptit. Kontrollo regresionin te raportimi orar, PX Notes dhe dërgimi në Discord. |
| Mira Notetaker / Pamjet e takimit | Pikat e hapura dhe Historiku i takimeve hapen nga shiriti i pamjeve të takimit. Mbyllja nga rreshti përdor statusin dhe versionin e së njëjtës pikë në Kujtesë. Kontrollo listën e pikave të hapura, numrin në katalog, „Për t’u ndjekur“, autorin në Kujtesë dhe rifreskimin pas konfliktit. Historiku çon te takimi i mëparshëm. Lidhjet nga Kujtesa dhe Discord duhet të hapin takimin dhe të theksojnë segmentin burimor kur lidhja përmban ID-në e segmentit. |
| Mira → Takimet | Lista dhe detajet përdorin të njëjtin format të datës dhe orës së takimit. Në detaje, data dhe ora shfaqen pranë titullit. Titulli Discord shkurtohet kur data dhe ora vijnë edhe nga regjistrimi. Katalogu bashkon 1H Host dhe regjistrimin Discord nga `voice_meeting_id` ose nga sloti i regjistrimit automatik. Raportimi i stafit pa Host hapet brenda regjistrimit të po atij sloti kur ka një të tillë. Shënimet e vjetra pa takim të lidhur mbeten të arritshme brenda Takimeve. Kontrollo lidhjet e vjetra Notetaker dhe Shënimet, hapjen e pikave nga Kujtesa, lidhjen e shënimit nga PX Notes, panelet Discord dhe lidhjet e segmentit nga Ask MIRA. Transkripti Desktop kufizohet te pronari. 1H Reports, After Break Report dhe M1 PIKAT përdorin burimet dhe filtrat e tyre ekzistues. |
| Mira → Shënimet dhe transkripti | Pamja e përbashkët grupon segmentet radhazi sipas folësit për Discord dhe Host dhe ruan tekstin origjinal të shënimit. Për Discord, lidhjet e segmentit vazhdojnë të theksojnë fragmentin e saktë brenda bllokut. Kontrollo lidhjet nga Kujtesa dhe Ask MIRA, lidhjet e shënimit nga PX Notes dhe qasjen për transkriptin Desktop, ku regjistrimi nuk dallon folësit. Seksioni i përgjithshëm i takimit lidh detyrat dhe shënimet e krijuara nga Host ose nga diktimi Discord; Discord ruan ID-të me krijimin në të njëjtin transaksion. Kontrollo Task Details, PX Notes dhe riprovimin pa kopje. |
| Mira → Treguesit në listën e takimeve | Numrat pranë titullit numërojnë detyrat dhe shënimet ende të disponueshme, të lidhura me Host ose diktimin Discord. Kur Host dhe regjistrimi hapen bashkë, numrat shfaqen te rreshti i përbashkët. Mira Zhvillim përdor avatarin jeshil të Discord-it në listë. Kontrollo që numrat të përputhen me seksionin “Detyra dhe shënime nga takimi”. |
| Mira Notetaker / Diktimi i detyrës | “Mira, detyrë për [inicialet] … fund detyre” nga një folës i lidhur në Discord krijon një detyrë 1H pa slot të paracaktuar në kanalin 1H ose Mira Zhvillim dhe e cakton vetëm kur përputhet një punonjës aktiv. Verifiko My View, pamjen e departamentit, Open Tasks, Task Details, njoftimin e caktimit, filtrin e raportimit 1H dhe riprovimin pa kopje. |
| Mira Zhvillim / hyrja automatike | Discord Mira Zhvillim (orari, prania, regjistrimi), mira-kontrolli (paneli Mira Zhvillim), Mira / shënimet, PX Notes (shikimi dhe ruajtja). Orari dhe request_id `autoai-` janë të veçantë nga regjistruesi 1H (`auto1h-`) dhe Mira Host. Finalizuesi i përbashkët ruan automatikisht shënimet e `auto1h-` dhe të `autoai-` me recorder `ai_agent`; nisjet manuale mbeten me ruajtje manuale. Kontrollo deduplikimin, lidhjen me transkriptin, statusin Ruajtur dhe kthimin te ruajtja manuale pas dështimit. |
| Emri i takimeve ZHVILLIM dhe botit Mira Zhvillim | Mira → Takimet (filtri ZHVILLIM, lista, kërkimi, detajet dhe historiku), Discord (emri i botit, paneli, komandat dhe ftesat), PX Notes dhe printimi, Task Details, Common View, My View, Development, Graphic Design, Product Content, Finance dhe eksportet Excel që lexojnë burimin e diktimit. Kontrollo titujt e vjetër dhe shënimet e ruajtura me emrin e mëparshëm. |
| Takimet (shënimet e takimeve) | Takimet, Takimi (seancat), Historia e klientit, Regjistrimet (Shënim / Injoro / screenshot), PX Notes (Dërgo / Bashko në PX), Meeting Scheduler (Trajnim), Sidebar |
| Mira Host / takimet 1H | Mira (nisje/ndalim/status), Discord 1H (hyrja, prania, radha, audioja), PX Notes, Common View, 1H SHTYPI Today, 1H Reports (Done dhe strike), Task Details |
| Raporte / email / eksporte | Reports, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, PX JAV Kontrolli, Weekly Planning Check, Kontrolli ditor RLZ, Print Preview, Print, Email, Exports, History |
| Përdorues dhe përgjegjës | Users, My View, Department Views, Finance View, Projects, PX Notes, PX JAV, Common View, Weekly Planner, Monthly Planner, Meeting Scheduler, Reports |
| GA PERSONAL - grupet dhe filtrat | Pamja ditore dhe javore e GA PERSONAL, filtri i grupeve dhe etiketat e tabelave; klasifikimi i eventeve ndahet përmes `frontend/src/lib/ga-personal-week.ts`, përfshirë eventet e vjetra të volejbollit. Të dhënat e modulit mbeten të ndara nga detyrat dhe raportet e kompanisë. |

## Varësi që nuk duhen harruar

- **M1 / DET 08:00/DL AM** dhe **1H Reports 11:00/11:50** përdorin të
  njëjtën përzgjedhje sipas datës lokale të afatit, shenjës 08:00 dhe
  kombinimit `Deadline Important` me periudhën `AM`. M1 ruan përgjigjen
  manuale te **A KA RIORGANIZIM?** gjatë rigjenerimit. Kontrollo dy tabelat
  e M1, statuset dhe komentet në pamjen e rifreskuar të 1H dhe eksportet.
  Burimi i tabelave 1H përfshin edhe detyrat e kryera pa slot dhe detyrat
  e raportuara që më pas u zhvendosën. Discord pyet çdo ditë pune nga data
  e fillimit deri te afati, për 08:00 në 11:00 dhe për DL AM në 11:50.
  Pyet pse nuk është punuar kur statusi është TODO dhe pse nuk është kryer
  kur detyra mbetet e hapur në datën e afatit. Raportet e rifreskuara i
  lexojnë përgjigjet e ruajtura sipas datës, slotit, punonjësit dhe detyrës.
  Mira Host lexon detyrat shtesë
  në slotin përkatës. Emaili ruan gjendjen e momentit të dërgimit.

- 1H SHTYPI Today/Tomorrow dhe 1H Reports lexojnë Common View nga databaza
  brenda procesit të autorizuar. Kontrollo preview, printimin nga Common
  View, gjenerimin e raporteve, javët e njëpasnjëshme dhe arkivin e Today
  në 16:00. Kur arkivi mungon, printimi shfaq gabimin e API-së.

- Common View dhe 1H SHTYPI Today/Tomorrow përdorin `waitingConfirmation`
  për rreshtin WFC INT në ekran, printim dhe eksport. WFC INT ka ngjyrë
  mente, WFE të artë dhe detyrat personale vjollcë. Kontrollo legjendat, badge-in CON:,
  pamjet e departamenteve, PX Notes/PX JAV, planifikimin dhe M1/M2/M3. Kontrollo
  inicialet nga Confirm by, detyrat pa konfirmues, filtrin për person dhe
  javën e plotë. Në Common View jashtë mënyrës Short, rreshti mbetet i dukshëm
  me filtrin All ose WFC INT kur rezultati është bosh. Waiting Client dhe
  rreshtat e personalëve për KA/GENT vazhdojnë të përdorin klasifikimet e tyre.

- Development → Meetings → M1 dhe seksioni M1 Zhvillim në Export Excel përdorin
  të njëjtin raport ditor. Mungesat, vonesat, pushimet dhe takimet lexohen nga
  Common View. Takimet externe të ditës përfshijnë të gjitha departamentet.
  Pika “Takimet interne” lexon takimet e ditës nga të gjitha departamentet.
  M1, M2 dhe M3 e shfaqin checklistën në gjithë gjerësinë; tabelat e takimeve
  dhe paneli Microsoft Calendar shfaqen te Testimi i Agent.
  Në hyrje te Meetings në Development, ora e PrimeFlow zgjedh M1 para 11:00,
  M2 nga 11:00 deri para 14:00 dhe M3 nga 14:00 deri para 18:00. Pas 18:00
  ruhet skeda e zgjedhur dhe brenda Meetings zgjedhja manuale mbetet aktive.
  Kartat e takimeve në M1 përdorin të njëjtin renderim në Department dhe My View
  të Development. Kartat marrin ngjyrat, orën dhe shenjat CAL/MANUAL/PARA/PAS
  nga të dhënat dhe stilet e Common View. Takimet e anuluara kanë titull të
  vijëzuar me të kuqe. Excel përdor etiketat e plota dhe paletën e raporteve.
  Në ekran, kartat e takimeve vendosen krah për krah dhe rreshti lëviz
  horizontalisht kur kartat nuk zënë vend. Takimet e anuluara dalin në fund
  të rreshtit, sipas renditjes së Common View ditore.
  Në Development → Meetings → M1, Department dhe My View kanë një zgjedhës
  pranë orës për takimet interne dhe externe, me vlerat bosh, “Mbajtur” dhe
  “Anuluar”, si në Common View. Statusi ruhet për datën e kartës përmes API-së
  që përdor edhe Common View. Në printim, statusi shfaqet si etiketë.
  Dialogu i anulimit tregon efektin te taskat e gjeneruara dhe takimet interne
  të lidhura. Statusi lexohet edhe në Excel, Common View, Admin Tasks,
  1H SHTYPI Sot/Nesër dhe tabelat e statuseve në raportet M2 dhe M3.
  Tabelat ditore në Development, Graphic Design dhe Product Content shfaqin
  anulimin, përfshirë My View.
  Takimet interne me KA kufizohen te Zhvillimi. Detyrat ndjekin datat e
  planifikimit, caktimet dhe simbolet KA/GENT/F; detyrat personale përdorin
  prefikset KA/Genti të raporteve M1/M3.
  Në ekran, kartat e detyrave përdorin ngjyrën për statusin. Teksti i statusit
  mbetet i disponueshëm për lexuesit e ekranit dhe në Excel.
  Personat e caktuar në kartat e detyrave përdorin të njëjtin rregull inicialesh
  si Common View. Excel shfaq emrat e plotë.
  Kopjet me të njëjtin burim ose grup shfaqen në një rresht për pikë, me
  personat, simbolet dhe komentet e bashkuara edhe në Excel.
  Hapja e një përgjigjeje në M1 e shënon automatikisht pikën në checklistën
  ekzistuese, që lexohet edhe në Excel. Mbyllja e përgjigjes nuk e heq shenjën.
  Pikat e hapura rikthehen për datën e raportit dhe përdoruesin në të njëjtën
  skedë të shfletuesit, si në Department ashtu edhe në My View.
  Takimet interne me KA dhe pyetjet për KA/Gentin shfaqen nën të njëjtën
  pikë me një tick, edhe në Excel. Për checklistat ekzistuese përdoret
  tick-u i pikës së parë të çiftit sipas rendit të ruajtur.
  Kur të dyja listat e KA/Gentit janë bosh, “Nuk ka për sot.” shfaqet pranë
  pyetjes dhe pika shënohet direkt me ✓ në Department dhe My View.
  Excel vendos përgjigjen me ngjyra poshtë pyetjes përkatëse në të njëjtën
  checklistë. Ndryshimi i rendit dhe redaktimi i pyetjes ruajnë lidhjen me
  përgjigjen. Pikat për vizitorët FRG dhe diskutimin e detyrave AM/PM në M1
  shfaqen vetëm me titullin dhe kutinë e shënimit, në Department dhe My View.
  Te pikat e M1 pa panel, klikimi në gjithë rreshtin ndryshon shenjën ✓.
  Excel vazhdon të lexojë shenjën nga checklist-a dhe tekstin nga raporti.
  Në M1, “YES” (Diskutuar) dhe “Close” përdorin pamjen e butonave të PX Notes
  direkt te çdo shënim në Department dhe My View. Numërimi fillon te shënimet
  e zakonshme dhe vazhdon te grupi “Email-et”. “Close” ruan `status: CLOSED`
  dhe “YES” ruan `is_discussed: true` përmes API-së së PX Notes. Të dyja e heqin shënimin
  nga lista e PX Notes të padiskutuara. Kontrollo filtrat në M1 dhe M2 të
  Development, Export Excel, Morning Report, After Break Report, 1H Reports,
  1H SHTYPI Tomorrow dhe M1 PIKAT për importet Gmail. Chat-i i Teams Personal
  mbetet pikë manuale.
  Në Development M1, shënimet nga email-et mblidhen nën “Email-et” me grup
  fillimisht të mbyllur. Rreshtat e hapur shfaqin titullin e shkurtër dhe
  veprimet “YES” dhe “Close”. Excel përdor tekstin e raportit.

- Development → Meetings → M2 përdor të njëjtën checklistë në Department
  View, My View dhe Excel-in e takimeve të brendshme. Hapja e një pike e shënon
  automatikisht dhe paneli rikthehet për datën e raportit në të njëjtën skedë
  të shfletuesit. Për pikat pa panel, klikimi në gjithë rreshtin ndryshon ✓.
  Kur lista e dorëzimeve te GA është bosh, pika shfaq “Jo” pranë pyetjes dhe
  shënohet direkt në rresht. Hapja dhe rifreskimi i
  pikave lexojnë email-et nga kutia IT dhe PX Notes të padiskutuara nga
  08:00 deri në momentin e kontrollit, me kufi në 12:00. Leximi i email-eve
  ripërdor lidhjen e After Break Report. Subjekti i emailit hap tekstin
  brenda pikës në Department dhe My View.
  Nëse Outlook kthen URL-në, aty mund të hapet edhe emaili origjinal.
  Excel përdor subjektin, dërguesin dhe orën për pikën e inbox-it.
  Dorëzimet GA përdorin rregullin M2/M2_M3 të M2 PIKAT, të filtruar për
  Development. Pikat për punën e
  paradites, planin PM dhe pjesa e Teams plotësohen në takim. Veprimi
  “Shëno si të diskutuar” ofrohet edhe në My View të M2 dhe përdor
  statusin e përbashkët të PX Notes. Email-et e importuara si PX Notes
  grupohen nën “Email-et” me titujt e shkurtër, si në M1. Excel përdor
  tekstin e plotë të raportit.

- Development → Meetings → M3 dhe Export Excel përdorin raportin ditor të
  Development M3. Pika e punës së përfunduar dhe planit të nesërm plotësohet
  manualisht. PX Notes përdorin filtrin e shënimeve të padiskutuara të M1
  dhe në ekran kanë “YES” dhe “Close”. PV lexon Common View për dy ditët e
  ardhshme të punës, për ekipin Development dhe pushimet për të gjithë.
  Dorëzimet lexojnë detyrat e Development që mbulojnë ditën e raportit me
  `M3` ose `M2_M3`. Takimet për ditën e ardhshme të punës përdorin kartat e
  M1 dhe statusin sipas datës së takimit. Takimet interne dhe externe janë
  nga të gjitha departamentet. Titulli i vjetër i pikës 5 me GA/KA/Gent
  shfaqet si “A ka takime interne për nesër?” edhe në Excel. Kur nuk ka të
  dhëna, përgjigjja shfaqet pranë pyetjes dhe klikimi
  në rresht ndryshon ✓ në Department dhe My View. Meetings Report dhe
  M3 PIKAT përdorin rrjedhat e tyre.

- Arsyeja `PV` pranohet pa koment në raportin ditor RLZ, te shtyrjet e
  detyrave dhe në përgjigjet M2 që përdorin listën e arsyeve. Kontrollo
  Development, Graphic Design, Product Content (edhe My View), Finance,
  Task Details, Weekly Planner, PX Notes/PX JAV, Realization, Kontrollin
  ditor RLZ, M2 Post-Break, M2/M3 PIKAT, eksportet dhe Discord M2. Arsyeja
  ruhet në `task_daily_rlz_states` pas migrimit 0210. Mbyllja si DONE e detyrave
  që kërkojnë koment për rezultatin përdor një rregull më vete.

- **BZ M3** te **Reports & Control → Meetings** lexon simbolet M2, M3 dhe M2/3
  të detyrave të planifikuara për datën e raportit dhe lidhjet aktive
  PrimeFlow–Discord të punonjësve. Përdor historikun e simboleve për datat
  e kaluara kur është i disponueshëm. Lexon vetëm kanalin
  `#det-nga-stafi-per-ga` me botin e përmendjeve dhe kontrollon titullin
  dhe autorin deri në 12:15 për M2 dhe deri në 16:30 për M3. M2/3 kërkon dy
  postime, me ndarje në 12:15. Kontrollo mesazhet e vonuara, identitetet e
  palidhura, titujt e dyfishtë dhe mungesën e qasjes në historikun e kanalit.
  Tabelat e dorëzimeve në M1, M2 dhe M3 PIKAT përdorin të njëjtin kontroll
  të Discord për çdo përgjegjës. M1 dhe M2 përdorin M2 në 12:15, M3 përdor
  M3 në 16:30. Kontrollo faqet, pamjet paraprake, emailin dhe eksportet
  Word, PNG dhe Excel. Common View mbetet burimi i simboleve të detyrave.
  Raporti shfaq inicialet
  dhe departamentin e secilit përgjegjës, përdor renditjen e Weekly Planner
  dhe Common View, si dhe ngjyrat e tabelave M3 për statusin, deadline dhe
  theksimin e detyrave 08:00 (përfshirë EM të detyrave josistemore).
  Paraqet veçmas grupet M2, M2/3 dhe M3 në këtë rend. Çdo rresht hyn në një
  grup sipas afateve që kontrollohen dhe grupi M2/3 i shfaq të dyja kolonat.
  Kolonat automatike Po/Jo nxjerrin Jo pas afatit kur historiku është lexuar
  drejtpërdrejt. Në BZ M3, e gjithë qeliza është e gjelbër për Po dhe e kuqe
  për Jo. Dorëzimi i vonuar shënohet te teksti i qelizës. Kur leximi direkt
  mungon, arkivi ekzistues i kanalit mund të konfirmojë një postim të gjetur.
  Në BZ M3 dhe M1/M2/M3 PIKAT, “Shiko dorëzimin” hap tekstin e postimit të
  verifikuar për atë kolonë dhe liston skedarët. Parapamja, emaili dhe Word
  shfaqin lidhjet e skedarëve kur vijnë nga leximi direkt. Excel dhe PNG
  shfaqin tekstin, emrat e skedarëve dhe adresën e postimit, me lidhje
  të klikueshme në Excel. Nga arkivi shfaqen emrat dhe lidhja e postimit.
  Rreshtat e dorëzimeve përdorin datën e raportit për shenjën e pauzës.
  Titulli që krahasohet me postimin e Discord-it ruhet pa etiketën e pauzës.
  Komentet ruhen sipas datës, detyrës
  dhe përgjegjësit në `discord_task_delivery_comments` (migrimi 0209).
  Pika 2 i shfaq dallimet në slote dhe simbole në dy tabela të ndara, me një
  rresht për çdo detyrë brenda secilës tabelë. API-ja lidh kopjet e së njëjtës
  detyrë me identitetin e përbashkët që përdor kontrolli i zgjedhjeve.
  Personat me të njëjtën zgjedhje dhe hollësi të njëjta shfaqen së bashku.
  Kolona sipas personit përfshin edhe zgjedhjet e kolegëve që dalin vetëm te
  krahasimet. Komentet kanë kolonë më vete brenda rreshtit të detyrës.
  Raporti i sotëm krahason slotet aktuale për datën efektive të planifikimit.
  Për datat e kaluara tabela përdor slotin e fundit të disponueshëm në
  historik për secilin person. Simbolet e vendosura shfaqen me të kuqe.
  Titulli shfaqet një herë, me pjesën e mbetur pas kontrollit +/−.
  Tabelat ndjekin ngjyrat e statusit dhe renditjen e punonjësve nga Weekly Planner. Editorët
  e detyrave kërkojnë koment kur zgjedhja individuale ndryshon nga zgjedhjet
  e kolegëve. Ruhet vlera e mëparshme, zgjedhja, homologët dhe arsyeja në
  historikun e ndryshimeve. Për rreshtat e përbashkët zgjedhja individuale
  lexohet në My View, Common View, Task Details dhe te dorëzimet për M2/M3.
  Kontrollo edhe Development, Graphic Design, Product Content dhe Finance,
  "Për të gjithë" në Common View, 1H SHTYPI, 1H Reports, M1/M2/M3 PIKAT,
  PX Notes/PX JAV dhe Discord që përdorin burimet e tyre të raportimit.
  Pika 3 liston detyrat aktive 1H pa slot sipas datës dhe përgjegjësit.
  Kontrollon zgjedhjen individuale, slotin e ruajtur për datën dhe slotin
  bazë në këtë radhë. Data e slotit ndjek kalimin e Common View pas 16:00.
  Common View, 1H Reports dhe M3 End of Day kanë paraqitjet e tyre për 1H pa slot.
  Pika 4 liston punonjësit pa 1H në 10:00, pa detyrë personale me një person
  tjetër në AM dhe pa simbol F në AM, vetëm kur mungojnë të tria. Përdor
  datën e raportit për përzgjedhjet individuale, mungesat tërëditore dhe
  renditjen e Weekly Planner. Common View llogarit mbulimin e vet për 10:00.

- INFO PX dhe EM IT në pikën 5 të M1 lexojnë tekstin nga Inbox-et e Outlook-ut
  me Microsoft Graph `Mail.Read`. Çdo përdorues i kyçur që hap M1 mund ta
  shohë tabelën dhe vetëm administratori autorizon mailbox-in. Rifreskimi
  ruan nga një PX Note për çdo ID mesazhi dhe mailbox, me prefiksin
  `EM INFO PX:` ose `EM IT:`. Kontrollo pikën e shënimeve në M1,
  M2 Post-Break, M1 PIKAT, 1H Reports, SHTYPI Tomorrow dhe Excel të PX Notes,
  si edhe përjashtimin nga API-ja publike. Tabela e Outlook-ut në pikën 5
  lexohet veç përmbajtjes së draftit.

- EM PX EU lexon Inbox-in e Gmail për intervalin e M1 me `gmail.readonly`. Një
  administrator autorizon llogarinë `primex.eu@gmail.com`. Hapja ose rifreskimi
  i tabelës në pikën 5 ruan një PX Note për çdo mesazh me prefiksin `EM PX EU:`.
  Verifiko filtrin Email në PX Notes, shënimet
  në M1, M2 Post-Break, M1 PIKAT, 1H Reports, SHTYPI Tomorrow, Excel të PX Notes
  dhe përjashtimin nga API-ja publike. Tabela burimore shfaqet në ekranin e M1.

- M1 dhe M2 Post-Break përdorin të njëjtin lexim të Inbox-it për Gmail dhe
  Yandex. Për Gmail, kontrollo që rezultati bosh të vijë si JSON dhe të
  shfaqet si interval pa email. Për të dy ofruesit, kontrollo riprovën pas
  ndërprerjes dhe që një gabim i vazhdueshëm të mbetet i dukshëm.

- Pika 5 e M1 shfaq tabelat e kutive postare. Normalizimi heq tabelat e
  vjetra të detyrave EM nga draftet e ruajtura, pamja paraprake dhe
  përmbajtja e email-it dhe e eksporteve të M1. Kontrollo që tabela e
  mesazheve Gmail të mbetet e dukshme kur është e disponueshme.

- Tabelat e inbox-it INFO PX, IT, HF dhe PX EU në pikën 5 të M1 përdorin
  të njëjtin komponent. Rreshti shfaq prefiksin me orën, dërguesin dhe
  subjektin. Butoni `+` hap tekstin e plotë dhe `−` e mbyll. Kontrollo
  të katër kutitë, përfshirë email-et me tekst të gjatë. Importi i ri përdor
  konfigurimin OpenAI të PrimeFlow për të përmbledhur subjektin dhe tekstin e
  email-it. Shënimi ruhet me prefiksin, orën, klientin ose projektin (ose
  subjektin kur nuk identifikohet një emër), një përmbledhje dhe hapat e
  numëruar. Kontrollo filtrin Email, eksportin Excel, M1, M2 Post-Break,
  M1 PIKAT, 1H Reports dhe 1H SHTYPI Tomorrow. Importet ekzistuese ruhen
  me ID-në e tyre; vetëm përmbledhjet që dështojnë riprovohen me Rifresko.
  Listat e PX Notes, M1/M2, M1 PIKAT dhe preview-të e 1H Reports e SHTYPI
  Tomorrow shfaqin titullin për shënimet nga email-et. Butoni `+` hap
  përmbledhjen dhe hapat e ruajtur, ose detajet e shënimit manual. Lidhja
  «Hap emailin origjinal» hap email-in te ofruesi kur URL-ja është ruajtur.
  PX Notes, M1 Start of Day, M2 Post-Break dhe M1 PIKAT shfaqin etiketën
  Forward ose Reply nga prefiksi i subjektit origjinal. Për shënimet EM
  manuale përdoret prefiksi pas orës në kryerresht. Te prefikset e njëpasnjëshme
  etiketa ndjek prefiksin e parë.
  Importet e vjetra që kanë vetëm kopje të email-it shfaqin statusin se
  përmbledhja nuk është ruajtur. Hapja e tekstit te
  kutitë e M1 dhe te shënimet përdor scroll brenda një kutie me lartësi të
  kufizuar. Për
  titullin përdoret formati `EM INFO PX: 08:00 PURIS – HOME24`. Kur një
  shënim i tillë kthehet në detyrë, `08:00` është shenja e prioritetit dhe
  sloti i detyrës 1H është `10:00`. Ora e pranimit ruhet te koha e importit.
  Pika 9 e M1 thekson edhe kryerreshtin e shënimeve me titull EM të shkruar manualisht.
  M1, M2, M1 PIKAT, 1H Reports dhe 1H SHTYPI Tomorrow rendisin shënimet
  e email-eve pas shënimeve të tjera, me të njëjtin rend brenda secilit grup.
  Kontrollo numrat e rreshtave dhe lidhjet e email-it e të bashkëngjitjeve kur
  hapen draftet e ruajtura me renditjen e vjetër.
  Kur një import i vjetër do të shfaqte vetëm prefiksin dhe orën, titulli merr edhe
  subjektin me shkronja të mëdha. Ruhet veçmas subjekti origjinal.
  Për importet e vjetra, API-ja lexon kopjen burimore nga shënimi ose nga
  metadata e plotësuar në sinkronizimin pasues. Daljet statike të gjeneruara
  nga shënimet përdorin rreshtin e shkurtuar.

- Renditja e pikave në M1 Start of Day përdoret edhe nga preview-ja, teksti
  dhe emaili me bashkëngjitjet Word/PNG, në dërgimin manual dhe automatik.
  Tabela automatike «A KA KOMENTE NE PF?» qëndron mes reagimeve të GA dhe
  Notes. Gjenerimi merr ngjarjet e komentit te një simbol nga 16:30 e ditës
  së mëparshme deri në kohën e gjenerimit për datën e raportit. Ndryshimi
  vetëm i simbolit dhe komenti pa simbol nuk krijojnë rresht. Kontrollo që
  daljet e M1 përdorin tabelën e ruajtur, si edhe renditjen e pyetjeve të
  shtuara nga M1 ose Common View.
  Pyetja e fundit «A KA RIORGANIZIM?» ruan BZ M1 si checkbox PO/JO, komentin dhe përgjigjet
  PO/JO për nënngarkesë e mbingarkesë në draftin e datës. Një përgjigje PO
  ose një mungesë/vonesë nga tabelat e M1 hap pyetjen «SI BËHET RIORGANIZIMI?».
  Mungesa/vonesa hap edhe fushën e shkaktarit. Rigjenerimi ruan përgjigjet
  e datës dhe paraqitja në preview, email, Word dhe PNG ndjek të njëjtat kushte.

- Te M1 PIKAT PËR RAP, «8. A DUHET RIORGANIZIM?» është pika e fundit
  në ekran, preview, email dhe eksportet Word, PNG e Excel.

- Leximi i kutive postare të M1 dhe M2 ndan intervalin me përgjigjet e GA.
  M1 nis në 16:30 të ditës paraardhëse, ose të ditës së fundit të punës
  kur raporti është i së hënës. M2 nis në 08:00 të datës së raportit.
  Përdor orën e gjenerimit të ruajtur me përgjigjet e GA. Verifiko
  rifreskimin e M1 dhe pilotin Gmail, gjenerimin e M2, preview, email-in
  dhe eksportet kur përmbajnë tabela email-esh. Tabelat e inbox-it në M1
  dhe M2 hapin edhe lidhjen origjinale kur ajo vjen nga ofruesi.

- Pika «(GA) EMAILS TE REJA?» në M2 Post-Break përdor të njëjtat katër
  inbox-e si M1. Gjenerimi ruan email-et e mbërritura në datën e raportit
  nga 08:00 deri në çastin e gjenerimit, në zonën kohore të raporteve.
  Ekrani i M2 lejon hapjen e tekstit të plotë. Preview-ja, teksti dhe
  dërgimi manual/automatik me bashkëngjitje marrin dërguesin, subjektin
  dhe orën nga po ai gjenerim. Leximi i M2 nuk krijon PX Notes.
  Ekrani shfaq statusin e të katër kutive edhe para gjenerimit, përmes
  `/microsoft-mail/status`. Statusi lexon konfigurimin dhe autorizimet
  e ruajtura, ndërsa HOMEFACE verifikohet kur lexohet inbox-i.
  Kontrollo kufijtë e orarit dhe që pyetja e vjetër manuale të mos
  rikthehet përmes drafteve të ruajtura ose sinkronizimit me Common View.

- Pika «EMAILS TE REJA?» në M1 Start of Day ka edhe një pilot lokal për leximin e subjektit,
  dërguesit, orës dhe përmbajtjes
  nga etiketa `PrimeFlow-M1-Test` në Gmail. Tabela e pilotit hyn në ekranin
  M1, preview, dërgimin manual dhe automatik, tekstin dhe bashkëngjitjet e M1.
  Tabela rendit DËRGUESI, PËRMBAJTJA dhe ORA dhe përdor gjerësi të kufizuar
  për titullin dhe dërguesin në ekran dhe në formatet e raportit.
  Kontrollo gjenerimin, rifreskimin pa dublime dhe ruajtjen e historikut të
  raporteve të dërguara. Ekrani dhe preview i ditës aktuale rifreskojnë Gmail-in
  edhe pas dërgimit, pa shkruar mbi raportin e ruajtur. Tabela e Gmail nuk
  krijon detyra të PrimeFlow.

- Pika 5 e M1 Start of Day lexon inbox-in HOMEFACE (`info@homeface.de`)
  nga Yandex me IMAP në modalitet leximi. Vendos fjalëkalimin e aplikacionit
  te sekreti i deploy-it `HOMEFACE_MAIL_APP_PASSWORD`. Mesazhet e intervalit të
  raportit importohen në PX Notes si `HF_MAIL`, me ID të qëndrueshme nga
  UIDVALIDITY dhe UID. Kontrollo filtrin Email, PX Notes Excel, pikën 9 të
  M1, M2 Post-Break, M1 PIKAT, 1H Reports dhe 1H SHTYPI Tomorrow. API-ja
  publike i përjashton shënimet HOMEFACE. Tabela e inbox-it është në
  ekranin e M1; pamjet e raporteve që lexojnë PX Notes marrin shënimet.

- Importi lokal Gmail në PX Notes përdor etiketën `PrimeFlow-M1-Test` dhe
  një ID të qëndrueshme për çdo mesazh. Shënimet në pritje shfaqen te pika 9
  e M1, M2 Post-Break, M1 PIKAT, 1H Reports dhe 1H SHTYPI Tomorrow me
  filtrat e secilit raport. Eksporti Excel i PX Notes përfshin shënimet Gmail.
  Trupi i emailit lexohet me OAuth `gmail.readonly` dhe ruhet si tekst në
  vetë shënimin. Kontrollo tekstin në çdo dalje që lexon shënimin, si edhe
  titullin dhe përshkrimin e parambushur kur shënimi kthehet në detyrë.
  Kontrollo shënimin si të diskutuar, kthimin në detyrë dhe rifreskimin pa
  dublime. Para aktivizimit në një databazë të përbashkët, verifiko që çdo
  version aktiv i endpoint-it publik i përjashton shënimet Gmail.

- Bashkëngjitjet e PX Notes shfaqen në rreshtat përkatës te M1 Start of Day,
  M2 Post-Break, 1H SHTYPI Tomorrow dhe 1H Reports, edhe me filtrin Vetëm Notes.
  Kontrollo edhe pamjen paraprake në M1/M2. Hapja dhe shkarkimi përdorin API-në
  e autentikuar të PX Notes. Ngarkimet e reja ruajnë përmbajtjen dhe metadata-n
  në të njëjtin transaksion të databazës, që dy backend-e me disqe të veçanta
  të mund të hapin të njëjtin skedar. Kopja në disk mbetet për kompatibilitet
  dhe për skedarët e vjetër. Kontrollo preview, download dhe fshirjen e
  bashkëngjitjes pas migrimit `0199_ga_note_attachment_contents`.
  Draftet e M1/M2 dhe snapshot-et e reja të 1H SHTYPI
  Tomorrow mbajnë ID-në e Note-s. Raportet e vjetra përputhen me tekstin, inicialet
  dhe orën kur ka një burim të vetëm. Emaili, printimi dhe eksportet ruajnë formatin e tyre.

- Statusi i taskut: përveç API-së dhe pamjeve, kontrollo listat e vlerave të
  pranuara në `backend/mcp_server.py` dhe udhëzimet në `discord_task_tools.py`.
  Për taskat nga PX Notes kontrollo edhe kufizimin `ck_tasks_ga_note_status_valid`.
  Provo migrimin me detyra ekzistuese në `WAITING_CLIENT` dhe
  `WAITING_CONFIRMATION`, që të dyja statuset të ruhen gjatë kalimit.
  Për taskat me sasi produktesh, kontrollo rillogaritjen e statusit në `tasks.py`
  si gjatë ruajtjes, ashtu edhe gjatë leximit, dhe përparësinë e statusit ditor
  ndaj sasive në `planners.py`. Migrimi i `PAUSED` të vjetër rikthen statusin
  e punës nga auditi kur është i disponueshëm dhe mban datat e regjistruara
  të pauzës. Kontrollo etiketën në SHTYPI Today/Tomorrow, 1H Reports,
  M1/M2/M3, PIKAT, eksportin Open Tasks dhe klasifikimin ditor në Realization.
  Pauzat e reja ruhen te `tasks.pause_periods`, me datën e fillimit dhe të
  fundit të përfshirë. Formularët ruajnë `pause_days` veç statusit. Weekly
  Planner, Common View, 1H Reports dhe 1H SHTYPI Today/Tomorrow e lexojnë pauzën për
  datën e rreshtit. Monthly Planner, pamjet ditore të departamenteve dhe
  Realization përdorin të njëjtin interval. Open Tasks dhe eksporti i tij
  kontrollojnë datën aktuale. Tabelat ditore M1, M2 dhe M3 përdorin datën e
  raportit për treguesin e pauzës.
  Sfondi gri dhe etiketa `Pauzë` përdoren në My View dhe Department View
  (Development, Graphic Design, Product Content), Finance, Common View,
  Weekly/Monthly Planner, Realization, Open Tasks, Admin Tasks dhe faqet e
  projekteve. Daily Report merr intervalet nga `reports.py`. Kontrollo ekranin,
  printimin dhe Excel-in për datën e raportit, si edhe pamjen e ditës
  së ardhshme në Finance dhe Admin Tasks. Në PX Notes dhe PX JAV, një shënim
  me disa detyra shfaq numrin e detyrave në pauzë kur pauza vlen vetëm për
  një pjesë të tyre. Raportet 1H, M1/M2/M3 dhe M1/M2/M3 PIKAT, si edhe eksportet,
  përdorin paletën e printimit dhe e mbajnë etiketën në formatin tekst.
  Kontrollo një ditë, disa ditë, heqjen para
  kohe dhe një pauzë të dytë, që ditët e pauzës së parë të mbeten të dukshme.

- Përmbledhja e shpejtë përdoret si në Notetaker, ashtu edhe në Discord. Për
  takimet normale numërohen të pesë seksionet së bashku, me kufi 250 fjalë dhe
  me riprovim për shkurtim. Kontrollo përmbledhjet e reja, shënimet e plota në
  PX Notes dhe transkriptin. Përmbledhjet ekzistuese lexohen nga vlera e ruajtur.
  Regjistruesi 1H krijon përmbledhjen e Notetaker-it pas përfundimit të ruajtjes
  ekzistuese. Administratorët dhe menaxherët mund ta gjenerojnë për takime të
  ruajtura me transkript, përfshirë regjistrimet e pjesshme. Kontrollo që
  rigjenerimi të ndryshojë vetëm përmbledhjen e shpejtë, të mos dërgojë njoftim
  tjetër në Discord dhe të mos krijojë kopje në PX Notes.

- Asistentja e GA-së (MCP, `docs/mcp-assistant.md`): `app/services/ga_assistant.py` përsërit
  në Python rregullat e tabelës së parë të **Admin Tasks** (GA TASKS / BZ ME GA TASKS,
  `koha_bz`, dita e planifikuar), të **GA Time Table** për takimet (externe + interne manuale,
  Mbajtur/Anuluar) dhe të **M1 “FIZIKISHT ME GA?”** për simbolin `F`. Kur ndryshon ndonjë nga
  këto rregulla, kontrollo edhe `ga_agenda`, `ga_leftovers`, `ga_untimed_today` dhe testet
  `tests/test_ga_assistant*.py`. Identiteti i GA-së lexohet vetëm nga
  `app/services/ga_identity.py` (`GA_USER_EMAIL` / `GA_USERNAME`); mos shto konstante të reja
  `GA_EMAIL` / `GA_USERNAME` nëpër module.
  Agjenda lexon edhe **iPhone Sync** të GA Time Table (formati `REMINDER HH:MM: titulli` i
  `app/services/ga_icloud_sync.py` dhe dritarja sot−7 e Shortcut-it): kur ndryshon formati ose
  dritarja, ndrysho edhe `parse_reminder_content` / `IPHONE_SYNC_LOOKBACK_DAYS`.
  Importi zëvendëson hyrjet e Calendar dhe Reminders të lidhjes brenda të
  njëjtit interval. Kur zgjerohet dritarja e Shortcut-it, kontrollo që të dyja
  listat të mbulojnë intervalin dhe verifiko hyrjet e importuara në eksportin
  `ga-time.xlsx` dhe në tabelën GA të emailit 1H (HTML dhe PNG).
  Importi ruan `is_completed` për Reminders. GA Time Table dhe printimi ditor
  që përdor PDF-ja e NEWS-PX shfaqin `✓ Done`. Eksporti `ga-time.xlsx`,
  bashkëngjitjet GA të 1H dhe agjenda e Asistentes GA i përjashtojnë hyrjet e
  kryera. Verifiko të dyja gjendjet pas një sinkronizimi të përsëritur.
  `ga_item_done` vendos kërkesën e kryerjes së një `tt:` në pritje deri te
  konfirmimi i Shortcut-it. Verifiko që `ga_agenda` e shfaq në pritje dhe
  listat e punës së hapur e përjashtojnë. Hyrjet në pritje dhe të konfirmuara
  ruhen gjatë një importi të përsëritur. Pas konfirmimit, tabela ditore
  dhe eksportet lexojnë `is_completed` si për kryerjet nga iPhone.

- M1 dhe M2: kur leximi i Discord vonohet, shfaq mesazhet e verifikuara me orën
  e leximit të fundit. Një lexim i mëvonshëm mund të plotësojë tabelën brenda
  kufirit të gjenerimit. Kontrollo faqet, preview dhe emailin për të dy raportet.

- Claude Artifact lexon përmendjet direkte të GA-së përmes `ga_discord_mentions_feed`
  dhe `/api/ga-assistant/discord/mentions/feed`. Burimi është `ga_discord_mentions`,
  të cilin e lexojnë edhe agjenda e GA-së dhe mjeti ekzistues `ga_discord_mentions`.
  Filtri i listës së Artifact-it përdor `DISCORD_GA_REPLIES_CHANNEL_ID`, të njëjtin
  konfigurim kanali që përdorin rrjedhat e përgjigjeve dhe reagimeve të GA në M1/M2.
  Kur ndryshon ID-ja e kanalit, kontrollo burimin në të tria paraqitjet. Për listën
  e Artifact-it kontrollo mention-et direkte, përjashtimin e kanaleve të tjera,
  faqëzimin dhe rifreskimin pas shtimit ose heqjes së një reagimi.
  Lista shfaq emrat e bashkëngjitjeve nga `ga_discord_mentions`. Hapja nga
  Artifact-i përdor `ga_discord_mention_attachments` dhe botin e përmendjeve
  për të kërkuar linket e përkohshme nga Discord. Kontrollo hapjen nga një
  përmendje direkte dhe refuzimin për burimet jashtë listës së kanalit.
  `ga_discord_attachment_content` përdor të njëjtin verifikim për të shkarkuar
  skedarin nga CDN-ja e Discord-it dhe për ta kthyer si tabelë, tekst ose imazh
  MCP. Kontrollo emrin e saktë, ID-të e kontekstit dhe kufizimet e skedarëve.
  Arkivi `ga_discord_channel_messages` furnizon `context` në të dy mjetet e
  përmendjeve. Kontrollo kanalin dhe thread-et publike, dritaren dyminutëshe
  për autorin, reply-n origjinal, reagimet dhe skedarët për çdo ID të lidhur.
  Agjenda e GA-së vazhdon të lexojë tabelën e përmendjeve dhe M1/M2 përdorin
  evidencën e tyre për përgjigjet dhe reagimet.
  Shkrimet nga Artifact-i kalojnë te `ga_discord_reply` / `ga_discord_react`
  dhe përdorin identitetin e botit të përmendjeve. Kontrollo autorizimin si GA,
  ID-të e kontekstit, lidhjen e reply-t te përmendja, heqjen e reagimit të
  botit dhe që ai reagim të mos numërohet si aprovim i një kolegu.
  Në feed-in e ASIST GA – DET GA, `ga_replied` lexon përgjigjet e arkivuara të
  GA-së në kanal ose në thread-et publike të lidhura dhe përgjigjet nga
  veprimi i audituar i PrimeFlow.
  `ga_reacted` lexon reagimet aktive të GA-së dhe botit të përmendjeve.
  Emrat te `others_reacted_before_ga` kërkojnë që shtimi i reagimit aktiv të
  kolegut të jetë parë para reagimit të parë aktiv të GA-së ose botit në të
  njëjtin sesion të botit. Kontrollo shtimin, heqjen, pastrimin dhe lidhjen
  pas ndërprerjes. `others_reacted_before_ga_known` është false kur mungon
  evidenca për renditjen, përfshirë reagimet historike të lexuara vetëm me REST
  dhe mesazhet që kanë reagime të stafit por presin një reagim të GA-së.

- M2: **DT WFE** është një tabelë automatike. Kontrollo që draftet e vjetra dhe
  importi nga Common View të mos krijojnë kopje në grupin manual të M2.

- M3 PIKAT PER RAP: **NËNNGARKESË NESER?** merr stafin nga caktimet kryesore dhe
  shtesë të detyrave aktive që përmbajnë `NËNNGARKESË` në rreshtin e titullit
  për datën e raportit. Kontrollo titujt me tekst para dhe pas fjalës.
  Kontrollo faqen, pamjen paraprake, emailin dhe bashkëngjitjet HTML, Word dhe PNG.

- M3: **DET DONE TE HV** përdor kalimin në DONE të regjistruar nga Haxhere
  Spahiu gjatë datës së raportit. Përfshin detyrat sistemore dhe të zakonshme.
  Kontrollo gjenerimin e M3, pamjen paraprake, email-in dhe eksportet Word/PNG.

- M3: Tabela **DET 08:00** te pika e detyrave të nesërme ngjyros rreshtat
  sipas statusit në ekran, preview, email dhe bashkëngjitjet Word/PNG.

- M3: **A JEMI BRENDA MESATARES ME PROJEKTE?**, **PIKAT E DITES** dhe
  **(GA) ZHV: TIKETAT E STD?** përjashtohen nga draftet e
  ruajtura, rigjenerimi dhe importi i pyetjeve manuale. Kontrollo gjithashtu
  faqen M3, preview, emailin dhe bashkëngjitjet.

- M3 End of Day: **SHIKO DET ME SIMBOLE NE 1H SHTYPI NESER** përdor të dhënat,
  renditjen dhe tabelën e detyrave të SHTYPI Tomorrow për ditën tjetër të punës.
  Hapja dhe rifreskimi i raportit të sotëm marrin tabelën aktuale. Faqja krijon
  draftin e sotëm kur mungon. Raportet historike përdorin tabelën e ruajtur.
  Fshehja e tabelës dhe zgjedhja e simboleve në faqen M3 veprojnë vetëm në pamjen e faqes.
  Kontrollo filtrin për të gjitha simbolet, faqen M3, preview, emailin, Word dhe PNG.

- M2: **PROJEKTET: ATO QE KEMI PUNU DHE SKEMI PUNU** shfaq PO/JO për VS,
  VL, MST dhe TT sipas kodeve në titujt e detyrave të caktuara stafit PCM.
  MST dhe TT kërkojnë një detyrë të lidhur me projekt (`project_id`), ndërsa
  VS dhe VL llogarisin edhe detyrat pa projekt.
  Data e raportit duhet të bjerë brenda Start Date–Due Date. Kontrollo caktimet
  kryesore dhe shtesë, rigjenerimin, preview, emailin dhe bashkëngjitjet e M2.

- M2: **A JEMI BRENDA PLANIT ME PROJEKTE/DIZAJN?** dhe **PIKAT E BORDIT/DISKUTO
  APLIKANTAT** përjashtohen nga draftet e ruajtura, rigjenerimi dhe importi nga
  Common View. Kontrollo faqen M2, preview, emailin dhe bashkëngjitjet.

- M1: **FIZIKISHT ME GA?** përdor detyrat aktive me simbolin `F` dhe
  **A KA PYTJE/SQARIME ME KA/GENTIN** ato me `KA` ose `GENT`. Të dyja pikat
  pranojnë simbolet e kombinuara dhe përdorin intervalin Start Date–Due Date
  që mbulon datën lokale të raportit, sipas rregullit të Common View për
  planifikimin. Kopjet e lidhura me të njëjtën bashkësi
  simbolesh shfaqen në një rresht me përgjegjësit përkatës pas filtrit të
  mungesave. Kur janë disa përgjegjës, kolona KUSH i ndan me `/` dhe faqja M1
  e thekson vijën ndarëse. Kontrollo numrin e rreshtave dhe kolonën KUSH.
  Ruajtja e titullit, marrësve ose pyetjeve të tjera mban tabelat e simboleve
  që faqja ka rifreskuar, edhe nëse përgjigjja e ruajtjes kthen kopjen e vjetër.
  Generate dhe dërgimi automatik i M1 ruajnë identifikuesit e tabelave të
  gjeneruara dhe bashkojnë përgjigjet manuale nga drafti ekzistues.
  Të dyja pikat renditen pas përgjigjeve dhe reagimeve të GA nga Discord.
  Kontrollo gjenerimin, rifreskimin e draftit, preview, emailin manual dhe
  automatik dhe bashkëngjitjet Word/PNG. Titulli nga TAK BORD/GA ose nga një
  pyetje manuale e ruajtur nuk shtohet për herë të dytë në M1. Common View,
  M1 PIKAT PER RAP, M2 dhe M3 përdorin rrjedhat e tyre.

- M1 dhe M2: **(GA) A KA REACTION NGA GA TEK DETYRAT NGA STAFI PER GA?** vjen pas komenteve të GA dhe
  përdor të njëjtin kanal Discord, të njëjtin interval dhe të njëjtën kohë
  gjenerimi si komentet e raportit përkatës. Boti ruan kohën kur merr
  reagimin e GA ndaj një mesazhi nga stafi me lidhje aktive Discord.
  AUTORI shfaq inicialet. Kolona SKEDARËT hap miniaturat dhe pamjen e plotë
  në M1/M2 përmes mesazhit të reaguar, edhe në thread publik. Preview dhe
  emaili HTML lidhin mesazhin në Discord, ndërsa Word/PNG tregojnë numrin.
  Reagimet e vjetra marrin lidhjen kur snapshot-i i Discord-it ruan mesazhin
  dhe të dhënat e bashkëngjitjeve. API-ja pranon vetëm mesazhe me reagim
  brenda intervalit të atij raporti.
  Kontrollo reagimet ndaj mesazheve ekzistuese, kufirin e së premtes për M1
  të së hënës, kufirin 08:00 për M2, preview, emailin dhe Word/PNG.
  Hapja e draftit, preview dhe dërgimi manual rilexojnë reagimet e draftit
  deri në orën fillestare të gjenerimit, edhe kur boti i ka ruajtur me vonesë.
  Për draftet e vjetra të M2 pa orë gjenerimi, përgjigjet dhe reagimet
  rilexohen me të njëjtën orë kontrolli. Raportet e dërguara pa orë
  gjenerimi përdorin orën e dërgimit kur rikuperojnë reagimet.
  Një server raportimi pa ID të serverit Discord lexon evidencën e ruajtur
  nga kanali i konfiguruar. Raportet e dërguara me evidencë të padisponueshme
  mund ta shfaqin tabelën e rikuperuar me kufirin e gjenerimit të ruajtur.
  Reagimet historike pa orë të regjistruar nuk mund të futen në interval.
  M3 dhe sinkronizimi i reagimeve për përmendjet e GA kanë rrjedha të veçanta.

- M1: **GA/HV/DV TASKS** lexon përgjigjet e Discord-it nga
  `discord_m3_questions` me llojin `tomorrow_task`, sipas ID-së së detyrës,
  personit dhe datës së synuar. Për tabelën HV vlejnë personat e caktuar te
  detyrat e Finance. Kontrollo PO, JO, shtyrjen, komentin pa përgjigje dhe
  konfirmimin përmbledhës që plotëson përgjigjet individuale. Një detyrë
  e hapur e zhvendosur pas përgjigjes JO mbetet në raportin e datës së synuar.
  Ndryshimet manuale ruhen
  për secilën fushë në draftin e M1 dhe kanë përparësi mbi Discord-in.
  Te **Vazhdon?**, qeliza PO është e gjelbër, JO e kuqe dhe përgjigjja
  bosh ruan ngjyrën e rreshtit në ekran, email, Word dhe PNG.
  Në faqen M1 simboli zgjidhet direkt në qelizë dhe komenti ruhet
  kur fusha humb fokusin. Numri i rreshtit lidh kontrollin me ID-në e detyrës
  edhe kur filtri i mungesave heq rreshta nga tabela.
  Kontrollo rifreskimin, rigjenerimin, preview, emailin manual dhe automatik,
  Word/PNG dhe tekstin. M2, M3, Common View dhe 1H përdorin tabela të veçanta.
  Vetëm nën-tabela **GA TASKS** shton kolonën **BZ ME**, duke ndjekur rregullin
  e Admin Tasks për inicialet e ekzekutuesve. Përfshihen caktimet e detyrës
  dhe të shabllonit sistemor, duke përjashtuar personat e caktuar për koordinim.
  Kontrollo që inicialet të përdoren edhe në preview, email, tekst dhe Word/PNG.
  Tabela **BZ ME GA** te pika e takimeve përdor rrjedhën e saj.
  Në M2, **GA MBYLLJA E DET** përdor të njëjtin burim për kolonën **BZ ME**
  në çdo tabelë statusi. Kontrollo gjenerimin, preview, emailin dhe Word/PNG.
  Tabela HV dhe bashkëngjitja e 1H Reports përdorin paraqitjen e tyre.
  Pyetja **A prishet plani për sot?** ruhet për secilën tabelë HV, DV dhe GA
  dhe shfaqet edhe në preview, email dhe bashkëngjitjet e M1.
  Te pika 6 e M1 PIKAT PËR RAP shfaqen rreshtat me PO/JO ose koment
  nga përgjigjet GA/HV/DV të ruajtura në draftin M1 Start of Day të së
  njëjtës datë. Preview, email dhe Word/PNG/Excel përdorin të njëjtën
  përmbledhje. Lidhja në ekran hap draftin e datës për redaktim.

- Në tabelën **Finance Tasks**, filtri i datave përfshin çdo detyrë që
  mbivendoset me intervalin e zgjedhur, përfshirë kufijtë. Një datë e vetme
  kontrollon atë ditë. Filtri **People** përfshin përgjegjësit dhe personat
  e BZ. Për detyrat sistemore, personat dhe ora e BZ lexohen edhe nga
  shablloni. Kontrollo detyrat e një departamenti tjetër ku një punonjës
  Finance merr pjesë vetëm në BZ. Excel përdor rreshtat e filtruar dhe
  kolonat BZ ME, KOHA BZ dhe përgjegjësit, me rregullin e pranisë së eksportit.
  Kolona BZ ME paraqet inicialet në Finance dhe Excel.
  Eksporti Excel i Finance vendos **USER** menjëherë pas **BZ ME**. **Admin Tasks**
  përdor të njëjtën API për Excel dhe e ka kolonën **USER** në fund.
  Kolona Asg dhe Excel përfshijnë përgjegjësit e kopjeve aktive të lidhura
  në `/tasks?include_shared_assignees=true`. Filtrat dhe redaktimi përdorin
  caktimet e rreshtit përkatës, ndërsa BZ ME përdor pjesëmarrësit e BZ.

- Excel i **Open Tasks** shfaq **ASSIGNEES TË TJERË** menjëherë pas **BZ ME**,
  nga caktimet e rreshtit dhe kopjeve aktive të lidhura, duke përjashtuar
  personin e filtruar ose përgjegjësin kryesor. **BZ ME** bashkon inicialet
  nga detyra dhe shablloni sistemor. Kontrollo shkarkimin nga Open Tasks dhe
  MCP, si dhe importin e planifikimit me kolonat ekzistuese dhe TASK ID.

- Pamja **Nesër** te **Finance** për HV dhe **Admin Tasks** për GA përdor
  një buton të veçantë. Admin mund të redaktojë planin e HV kur zgjedh
  Haxhere Spahiun te **People**. Auditimi regjistron Admin-in si autor.
  Te **Admin Tasks**, përdoruesit e kyçur mund ta lexojnë planin e GA.
  GA dhe Admin mund të ruajnë përgjigjet e GA. Auditimi regjistron Admin-in
  si autor kur redakton në emër të GA.
  Butoni **Nesër** është pas **Sot** te **ALL TASKS**, edhe në ekran të ngushtë.
  Tabela e GA përdor kolonat e planifikimit të **ALL TASKS** dhe fushat
  **Vazhdon?** dhe **Koment** për datën e ardhshme të punës.
  Printimi dhe eksporti i **ALL TASKS** janë aktivë në pamjet e tjera të tabelës.
  Lista përdor përzgjedhjen e Discord-it për ditën e ardhshme të punës. API-ja pranon vetëm
  detyrat e caktuara te llogaria e kyçur dhe ruan përgjigjen sipas detyrës,
  përdoruesit dhe datës te `task_plan_feedback` (migrimi `0196_task_plan_feedback`).
  Kontrollo edhe fundjavën, detyrat e përbashkëta dhe ndryshimin e datës gjatë
  redaktimit. M1 i bashkon me përgjigjet nga Discord-i dhe ruan përparësinë e
  korrigjimit manual në M1. Excel i Finance dhe printimi i Admin Tasks përdorin pamjet e tyre.

- M1: **PIKAT E DITES SOT** dhe **EP: A ESHTE LESHUAR MIRA? (PARA TAK 1-2 MIN)**
  hiqen gjatë leximit të raporteve të ruajtura dhe përjashtohen nga pyetjet e
  importuara nga TAK BORD/GA dhe nga pyetjet manuale
  të ruajtura. Kontrollo faqen, preview, emailin dhe bashkëngjitjet e M1.

- M1 dhe M2: pyetja **A ka reply nga GA tek detyrat nga stafi për GA?** përdor
  evidencën ditore `discord_ga_reply_snapshots` nga kanali Discord
  `1572160944358953042`, përmes `discord_ga_replies.py` në bot dhe shërbimit
  përkatës të API-së. M1 nis nga 16:30 e ditës së kaluar. Të hënën nis nga
  e premtja në 16:30 dhe përfshin fundjavën. M2 nis nga 08:00 e datës së
  raportit. Kufiri i fundit është momenti i gjenerimit,
  sipas orës së raportit. Kur leximi i Discord-it ende nuk mbulon atë orë,
  hapja e draftit, preview dhe dërgimi manual e provojnë sërish me të njëjtin
  kufi. Tabelat e vjetra bosh të drafteve rikontrollohen po njësoj.
  Një tabelë e ruajtur bosh të hënën me rregullin e vjetër rilexohet me orën e
  gjenerimit fillestar, edhe kur raporti është dërguar.
  Evidenca prej 30 ditësh jep edhe kontekstin e mesazhit origjinal. Çdo rresht
  shfaq tekstin e GA, inicialet e autorit dhe fjalinë e parë të mesazhit të cilit
  iu përgjigj. URL-të hiqen nga teksti i komenteve. Komentet e pavarura brenda
  intervalit plotësojnë kolonën e përgjigjes. M1/M2 shfaqin datën dhe orën e
  postimit sipas zonës së raportit. Qeliza SKEDARËT lexon skedarët e mesazhit
  në Discord kur hapet nga faqja. Miniatura e hap fotografinë brenda raportit.
  Backend-i që shërben faqen kërkon `DISCORD_BOT_TOKEN` dhe qasje në kanalin
  e mesazhit. Kur token-i mungon, faqja e tregon dhe ofron lidhjen te Discord. Burimi ruan
  numrin e skedarëve dhe identifikuesit e mesazhit, ndërsa URL-të e përkohshme të
  skedarëve merren me kërkesë. Preview dhe emaili HTML lidhin mesazhin në
  Discord dhe Word/PNG shfaqin numrin e skedarëve. Raportet e ruajtura
  plotësohen nga evidenca e datës kur rreshti përputhet në mënyrë unike.
  Kur burimi konfirmon se s’ka mesazhe të GA-së në interval, tabela shfaq
  `Asnjë reply`. Raportet me komente, përgjigje ose skedarë të GA-së e heqin
  atë rresht edhe kur janë ruajtur më herët. Kontrollo
  gjenerimin, grupin Auto-filled në M1 dhe M2,
  rifreskimin, preview, emailin manual/automatik dhe Word/PNG/Text të secilit
  raport. Dështimet/lejet e pamjaftueshme, identiteti GA i revokuar, kufijtë e
  leximit dhe burimi i vjetruar duhen dalluar nga mungesa e përgjigjeve.
  Për raportet e ruajtura në formatin e vjetër, teksti merret vetëm për ID-të
  e përgjigjeve të referuara dhe nga evidenca e datës së raportit. Nëse
  raporti ka ruajtur gjendjen e padisponueshme, kontrollo rikuperimin nga
  evidenca e të njëjtit kanal dhe datë deri në orën e dërgimit. Pyetja e planit në M1, M1 PIKAT, M2 PIKAT, M3 dhe
  Common View nuk marrin këtë automatizim. Kërkohet migrimi `0190` dhe rinisja
  e API-së/botit; lejet e kanalit dhe Message Content kontrollohen veçmas.

- Discord: WFE (`WAITING_CLIENT`) trajtohet si Done vetëm për pyetjet. Host-i
  Mira nuk kërkon progres, vazhdim, afat ose `record_task_discussion` për WFE,
  përfshirë BLL dhe rishikimin PM. Pyetjet personale 1H dhe M2/M3 përjashtojnë
  WFE nga kandidatët; kartat e vjetra M2/M3 mbyllin kontrollet pas rifreskimit.
  Statusi real WFE, Common View, Department Views, Finance, SHTYPI, raportet
  M1/M2/M3 dhe llogaritjet e realizimit nuk kthehen në Done nga ky rregull.

- Simbolet e prioriteteve `!`, `!!`, `!!!`: PX Notes ka legjendë përmbledhëse
  dhe tabelë të detajuar; Common View ka legjendë në ekran dhe HTML të veçantë
  për printim. My View në Development, Graphic Design dhe Product Content
  përdor `task-one-h-marker-legend.tsx`; Finance përdor editorin e përbashkët.
  PX JAV, regjistrimet dhe SHTYPI Tomorrow kanë lista të veçanta simbolesh.
  Kontrollo validimet e Task/GaNote/PlanNote, `task_marker.py`,
  `primeflow_report.py` dhe `tomorrow_print_report.py` për raportet, printimin
  dhe Excel. `DOUBLE_EXCLAM` ruan `!!`; `CLIENT_URGENT` ruan `!!!` me kuptimin
  e ri të qëllimit të javës. Kodet ekzistuese ruhen për përputhshmëri.
  Përzgjedhja lejon deri në dy kode të ndryshme, të ndara me presje në
  `one_h_marker`; vlerat me një kod mbeten të vlefshme. `TaskMarkerSelect`
  përdoret në editorët React; preview 1H Today/Tomorrow ka përzgjedhës të vetin
  në iframe. Filtrat duhet të kontrollojnë secilin kod, përfshirë KA/GENT në
  Common View dhe M3/M2_M3 te M3 PIKAT. Kolonat e Task, GaNote, PlanNote,
  historisë dhe inbox-it kërkojnë migrimin `0189_two_task_markers` (32 shenja).
  Renditja në përzgjedhës, filtra, legjenda përmbledhëse/tabela dhe raportet
  e gjeneruara është `!`, `!!`, `!!!`, `?`, pastaj simbolet e tjera.

- Common View: tabela javore (`THIS WEEK` / `NEXT WEEK`) ka kontrolle −/+ për
  çdo rresht. Rreshtat e minimizuar mbajnë etiketën në ekran dhe përjashtohen
  tërësisht nga printimi javor, edhe nga printimi i shfletuesit. Gjendja ndahet
  mes dy javëve gjatë qëndrimit në faqe. Eksporti Excel dhe raportet e veçanta
  1H SHTYPI Today/Tomorrow nuk përdorin këtë gjendje minimizimi.

- Common View Short filtron detyrat e tabelës javore për This Week dhe Next
  Week para grupimit të kartave. Kontrollo kolonat e hënë–e premte, përfshirjen
  sipas secilit kriter dhe printimin e së njëjtës tabelë. WFC INT përfshin
  vetëm detyrat me deadline të shënuar, treguesin 08:00 ose simbolin `!!!`.
  Rreshti WFC INT fshihet kur asnjë detyrë e javës nuk plotëson kriteret.
  Brenda çdo dite në rreshtin 1H, grupi AM vjen para PM. Brenda secilit grup
  zbatohet renditja e departamenteve dhe e përdoruesve nga Weekly Planner.
  Për secilin përdorues rendi është 08:00, deadline i shënuar, pastaj `!!!`.
  Detyrat pa periudhë të caktuar futen te AM me etiketën AM/PM të kartës.
  API-ja Common View, eksporti Excel dhe raportet e veçanta SHTYPI nuk përdorin
  filtrin Short.

- Eksporti `/exports/checklists.xlsx` përdoret nga checklistat e Product Content
  dhe kontrollon edhe shabllonet globale sipas `group_key`: MST, TT dhe
  shabllonet e takimeve eksportohen nga ADMIN dhe MANAGER; STAFF mbetet i
  kufizuar. Checklistat e projektit/detyrës ruajnë kontrollin e departamentit.
  Ndryshimi i lejes së eksportit nuk ndryshon lejet e redaktimit të shablloneve
  dhe nuk shton butona eksporti në faqe që nuk e përdorin këtë endpoint.

- Butoni i zgjerimit të titullit (`CollapsibleTaskTitle`) rreshtohet në skajin
  e kolonës për My View te Development, Graphic Design dhe Product Content
  (WFC INT, Project Tasks, Fast Tasks, System Tasks), si dhe te
  tabela Finance. `alignToggle` kërkon mbështjellës `relative` me hapësirë `pr-8`;
  në pamjen Department të tri departamenteve rreshtimi i zakonshëm ruhet.
  Ky komponent nuk përdoret nga raportet ose eksportet.
  Tabelat My View përdorin `table-fixed` dhe `MyViewTaskColumns` për gjerësi
  të pavarura nga titulli i zgjeruar; Finance ka kolonat e veta fikse.
  Zgjerimi ndryshon lartësinë e rreshtit, pa rillogaritur gjerësitë e kolonave;
  butoni ruan pozicionin vertikal në ekran gjatë hapjes/mbylljes.

- Filtrat “Vetëm me strikes > 0” dhe “Vetëm Done” përdoren te 1H Reports
  (admin dhe staff, përfshirë BLL dhe SHTYPI brenda raportit) dhe SHTYPI Today.
  Aktivizimi i njërit çaktivizon tjetrin; filtrohen së bashku karta dhe datat,
  dhe fshihen grupet/rreshtat bosh. Statusi ruhet në HTML si `data-task-status`;
  raportet e vjetra të ngrira pa këtë fushë dallojnë Done nga ngjyra e kartës.
  SHTYPI Tomorrow nuk ka këta filtra. Filtrat veprojnë në preview; shkarkimet
  dhe email-et e gjeneruara në server ndjekin raportin e plotë, si për Strikes.

- Totali dhe filtri i strikes te 1H Reports llogariten nga 08:00 deri në fund të
  slotit të zgjedhur, edhe në SHTYPI të integruar në raportin e GA. Ngjyra e
  pikave në 1H Reports (përfshirë BLL) ndjek intervalin e slotit: kaltër për
  pikën e kryer në interval, gjelbër për pikën e kryer më herët po atë ditë,
  gri për ditët e mëparshme ose pa datë. Pikat e ditës nga
  detyrat që mungojnë në seksionet e slotit shfaqen te “STRIKES TË DITËS”.
  Kontrollo preview, filtrin Strikes, email, Word/PNG/Text dhe raportet
  historike. SHTYPI Today më vete dhe Mira Host përdorin dritaret e slotit.

- Përjashtimi i personave me mungesë gjithë ditën/PV në raporte ndahet te
  `backend/app/services/report_attendance.py`. Rregulli ndjek 1H Reports:
  mungesa/PV që mbulon 08:00–16:00 përjashton personin nga puna e raportuar;
  mungesa e pjesshme nuk e përjashton. Detyrat e përbashkëta ruhen vetëm për
  përgjegjësit e pranishëm, pa ndryshuar caktimet në databazë.
  Kontrollo M1/M2/M3, të tri PIKAT, tabelat hyrëse të SHTYPI Tomorrow,
  përmbledhjen F/GA/P/M2, inicialet e komenteve/takimeve, GA/HV, Daily Report,
  RLZ, End Week BZ, PX JAV Kontrolli, Weekly Planning Check dhe Discord.
  M3 përdor datën e raportit për punën e sotme dhe datën pasuese të punës për
  seksionet `N-`; tabelat hyrëse të SHTYPI Tomorrow përdorin ditën që mbyllet.
  Eksportet me interval përdorin ditët e punës të intervalit, jo mungesën e
  sotme për një raport të një periudhe tjetër; personi përjashtohet nga
  përmbledhja e periudhës kur është i padisponueshëm në të gjitha ato ditë.
  Pikat dhe tabelat e ruajtura filtrohen edhe gjatë leximit/preview/email/eksportit.
  Tabela PV në M1 tregon pushimet e ditës së raportit dhe tabela PV në M3
  pushimet e ditës pasuese të punës. Këto dy tabela ruajnë edhe personat me
  pushim tërëditor. Pika e parë Auto-filled në M1 rendit Vonesa, Mungesa dhe
  PV, pastaj shënimin manual për planin. Draftet e vjetra zhvendosin vetëm
  tabelën PV nga pika e festave dhe takimeve. Për raportet e sotme të ruajtura para korrigjimit, tabela
  PV rindërtohet nga Common View gjatë hapjes dhe preview-t. Kontrollo edhe
  emailin dhe bashkëngjitjet Word/PNG të gjeneruara nga M1 dhe M3.
  Snapshot-et aktuale të SHTYPI kanë `attendance_filter_version=2`; kopjet e
  vjetra aktualizohen para mbylljes. Arkivat e ngrira në 16:00 dhe skedarët e
  dërguar më parë mbeten dokumente historike dhe nuk rishkruhen me të dhëna të reja.
  Formulari Common View ka “All day” edhe për Mungese: ruan intervalin ekzistues
  `From: 08:00 - To: 23:00`, që lexohet nga pamja, printimi, eksportet dhe
  kontrollet e konflikteve pa fushë të re në API. Çaktivizimi rikthen orët e
  zgjedhura për mungesë të pjesshme; zgjedhja është e ndarë nga “All day” i PV.

- Mira regjistruese hyn në kanalin 1H edhe në 07:59 në ditët e punës, sipas
  `DISCORD_1H_AUTO_JOIN_TIMES` dhe `APP_TIMEZONE`. Kontrollo hyrjen në Discord,
  gjendjen te `mira-kontrolli` dhe ruajtjen te Mira → Shënimet dhe PX Notes.
  Mira Host dhe Mira Zhvillim kanë orare të veçanta.

- Hyrja automatike e Mira Zhvillim dërgon `request_id=autoai-YYYYMMDDHHMM`
  (tentativat pasuese shtojnë `-2` / `-3`). Skema `VoiceStart` te
  `backend/app/schemas/discord_voice_meeting.py` duhet t'i pranojë bashkë me
  `auto1h-` dhe ID-të numerike të nisjeve manuale; përndryshe API-ja e refuzon
  nisjen para krijimit të sesionit. Kontrollo endpoint-in `/voice-meetings/start`
  në të dy API-të aktive, panelin mira-kontrolli dhe ruajtjen te Mira/PX Notes.
  Testet me skema të izoluara të shënimeve duhet të krijojnë edhe `MeetingNote`,
  sepse leximi i `GaNote` ngarkon flamurin `from_meeting` përmes `meeting_notes`.

- Konfirmimi i klikimeve në Discord përdoret nga panelet 1H dhe Mira Zhvillim në
  `mira-kontrolli` dhe nga butonat e regjistrimit e të shënimeve në mesazhe.
  Kontrollo konfirmimin para thirrjeve në PrimeFlow, dukshmërinë në kanalin
  e kontrollit dhe në kanalet personale, si dhe ruajtjen te Mira / PX Notes.
  Kur Discord kthen `10062`, logu i botit tregon moshën e klikimit në hyrje
  dhe kohën e kërkesës së konfirmimit. Veprimi i skaduar nuk ekzekutohet.
- Deploy-et me ndryshime të verifikuara vetëm në API i mbajnë 1H dhe Mira Zhvillim
  aktivë. Të dy botët përdorin gateway-n lokal `18080` që ndjek API-në aktive.
  Kontrollo panelin `mira-kontrolli`, komandat personale, raportet Discord dhe
  njoftimin e përfundimit të `/push` me botin që vazhdon të punojë. Kur duhet
  rinisje, kontrolli i takimeve aktive vazhdon të zbatohet për të dy regjistruesit.
- Release-i i Mirës përgatit kodin, konfigurimin dhe varësitë në një dosje të
  izoluar. Pas ndërrimit verifikon lidhjen, leximin dhe përditësimin e panelit,
  butonin “Fillo” dhe lejet në kanalin zanor për secilin regjistrues. Nëse
  verifikimi dështon, deploy-i rikthen release-in e mëparshëm. Testo klikimin
  dhe hyrjen reale në Discord në një provë të veçantë. Kontrolli i deploy-it
  nuk nis një regjistrim. Ruaj radhën e rikuperimit të transkripteve të Mira Host
  në të njëjtën dosje, pavarësisht versionit të botit.
  Nisjet automatike të 1H dhe Mira Zhvillim nuk harxhojnë tentativa gjatë
  verifikimit. Ato rifillojnë brenda dritares ekzistuese prej katër minutash.

- Taskat e krijuara drejtpërdrejt nga Regjistrimet krijojnë PX Note me
  `knowledge_type=RECORDING` dhe lidhjen `ga_note_origin_id`. PX Notes shfaq
  etiketën `REC` pranë etiketave të tjera; printimi klonon të njëjtën tabelë
  dhe e përfshin etiketën. Kjo vlerë nuk është kategori Knowledge PX.
  Shënimet e dërguara nga Takimet identifikohen nga lidhja ekzistuese
  `MeetingNote.ga_note_id` dhe API-ja kthen `from_meeting=true` për
  etiketën `TAK`, edhe për shënimet e vjetra dhe të bashkuara. `RECORDING`
  ka përparësi kur ekziston; etiketat nuk ndryshojnë të dhënat e ruajtura.

- Development, Graphic Design dhe Product Content përdorin
  `CollapsibleTaskTitle` për titujt në listat All (WFC INT,
  Project Tasks, Fast Tasks dhe System Tasks), me rreshtin e parë dhe `+`/`-`
  vetëm në My View. Department View ruan tekstin e plotë. Finance përdor të
  njëjtin komponent në tabelën e vet. Daily Report, printimet e departamenteve
  dhe eksporti Excel i Finance kanë renderues të veçantë dhe ruajnë sjelljen
  ekzistuese.

- Regjistrimi i ekranit përdor `RecordingCapture` për nisjen te Regjistrimet
  dhe për “Ndaj ekranin përsëri” si në panel ashtu edhe në shiritin global të
  regjistrimit. Të dyja kërkesat `getDisplayMedia` përdorin
  `audioSelection: "preferred"` dhe `systemAudio: "include"` që shfletuesit që
  i mbështesin të parapëlqejnë ndarjen me audio. Këto janë preferenca: përdoruesi
  dhe shfletuesi vendosin përfundimisht çfarë ndahet. Kontrollo të dyja rrugët;
  kjo nuk ndryshon Mira/Discord, takimet, PX Notes, raportet apo regjistrimet
  e ruajtura më parë.
  Te detajet e regjistrimit, videoja hapet me “Shfaq videon”; fshehja e ndalon
  luajtjen. Klikimi i kohës së citimit e hap videon automatikisht dhe e çon te
  momenti përkatës. Kontrollo edhe screenshot-in te takimi dhe shkarkimin që
  mbetet i arritshëm kur videoja është e fshehur.
  “Ruaj në…” te detajet hap zgjedhjen e skedarit lokal dhe përdor të njëjtin
  shkarkim të autorizuar `/api/meeting-recordings/{id}/download`, duke dërguar
  videon drejtpërdrejt në disk. Anulimi i dialogut nuk nis shkarkim. Në shfletues
  pa `showSaveFilePicker`, mbetet butoni “Shkarko regjistrimin”. Kjo ruajtje nuk
  përdor File Access dhe nuk zhvendos ose fshin regjistrimin në server.

- “Vetëm audio” te Regjistrimet kap mikrofonin dhe ruhet në të njëjtin historik
  si regjistrimi i ekranit. Kontrollo parazgjedhjen dhe nisjen në iPhone/Android,
  lejet, ndërprerjet, ngarkimin me pjesë, dëgjimin dhe shkarkimin. Detajet e
  takimit, Historia e klientit dhe burimi i shënimeve të takimeve shfaqin llojin
  sipas MIME-it të regjistrimit. Citimet dhe lidhjet me sekonda hapin luajtësin
  përkatës. Screenshot-i kërkon video. Ruajtja private, arkiva FILES, analiza e
  regjistrimit dhe eksporti i kohëve të citimeve përdorin të njëjtën prapashtesë
  të skedarit; kontrollo WebM dhe M4A për audio dhe formatet ekzistuese për video.

- Radha IndexedDB dhe shiriti i regjistruesit në krye të aplikacionit përdoren
  nga Ekran dhe Vetëm audio. Ngarkimi i vonuar mbetet në sfond dhe riprovohet
  pas rilidhjes, edhe pas “Ndalo”, sa kohë skeda që nisi regjistrimin është hapur.
  Kontrollo që “Pauzë” / “Vazhdo” të veprojnë vetëm me kërkesë të përdoruesit
  dhe që historiku e detajet të dallojnë skedarin e plotë nga pjesa e ruajtur
  pas ndërprerjes së shfletuesit ose arritjes së kufirit të ruajtjes lokale.
  Gjatë kapjes, regjistruesi kërkon mbajtjen e ekranit ndezur në shfletuesit që
  e mbështesin. Pronari i një regjistrimi të dështuar me fragmente në server
  mund ta rikuperojë si pjesë nga historiku ose detajet. Nëse ka fragmente
  lokale, paneli i rikuperimit ka përparësi. Kontrollo finalizimin, luajtjen,
  arkivën FILES dhe analizën. Auditimi dallon dështimin e nisjes nga braktisja.

- Krijimi i detyrave të sistemit përjashton `User.is_active = false` në
  `system_task_instances.py`, rrugën e vjetër `system_task_occurrences.py` dhe
  detyrat sistemore të takimeve në `meeting_system_tasks.py`. Kontrollo scheduler-in,
  gjenerimin nga API-ja dhe rastin aktiv/joaktiv/riaktivizim; slotet konsumojnë
  ekzekutimet e kapërcyera që të mos gjenerohen prapa pas riaktivizimit.
  `inactive_system_tasks.py` fshin instancat ekzistuese të përdoruesve joaktivë
  në çdo status, gjatë çaktivizimit nga PATCH/DELETE Users dhe scheduler-it.
  Detyrat e përbashkëta ruhen për përgjegjësit aktivë; hiqen lidhjet joaktive.
  Skripti `cleanup_inactive_system_tasks.py` ofron preview dhe `--apply` me
  backup të rreshtave të prekur dhe kontroll pas fshirjes. Instancat e vjetra
  pastrohen vetëm kur tabela `system_task_occurrences` ekziston. Fshirja prek
  edhe historikun e detyrave dhe raportet që lexojnë drejtpërdrejt databazën;
  raportet/snapshot-et e arkivuara nuk rishkruhen. TAK INT 1H janë
  detyra të zakonshme 1H dhe përdorin rrugë tjetër. ZV1/ZV2 joaktivë përjashtohen
  edhe nga ricaktimi i instancave të reja gjatë pushimit të përgjegjësit.
  Pamjet dhe raportet që lexojnë
  detyrat sistemore trashëgojnë mungesën e instancave të fshira dhe të atyre
  që nuk krijohen; përkufizimet e modeleve/slotet ruhen për riaktivizim.

- Vijëzimet e pjesshme të ruajtura në PX JAV (`[[done]]`) duhen renderuar
  edhe në Preview gjatë redaktimit: butoni `Strike / Undo` te `Edit Note`
  përdor përzgjedhjen në textarea dhe `editDoneRanges`; vetëm `Save changes`
  ruan përmbajtjen me serializimin ekzistues. Cancel nuk dërgon ndryshimet.
  PATCH ekzistues i `plan_notes` sinkronizon titullin/markat e detyrave të
  lidhura dhe regjistron strike events, pa ndryshuar statusin e detyrës.
  Këto shenja duhen renderuar
  edhe në My View / Department Views për detyra që kanë nisur para ditës së
  zgjedhur, njësoj si PX Notes. Kontrollo veçmas Development, Graphic Design,
  Product Content, Finance dhe printimet: statusi Done nuk nënkupton vijëzim
  automatik të gjithë titullit. Common View, SHTYPI, 1H Reports dhe M1/M2/M3
  kanë renderues të veçantë të markave.
- Tabela Stafi në Realization ditor shfaq Due date / Deadline brenda listave të
  detyrave, pa kolonë afatesh: listat shfaqin vetëm titullin e detyrës; afatet e
  pambyllura kanë titull të kuq, pa etiketa, sfond apo vijë shtesë. `realization-table-items.ts`
  ruan edhe afatet që mungojnë te `realization_items`, duke i vendosur te statusi
  përkatës; ekstra të hapura shfaqen te Në progres / Të shtyra / Pa progres.
  Tabela ditore bashkon POSTPONED dhe NO_PROGRESS në kolonën Pa progres, duke
  ruajtur llojin origjinal dhe shënimin e theksuar `Shtyrë:` përpara titullit,
  të rreshtuar horizontalisht që shënimi të mos bjerë poshtë titullit. Tabela javore i
  bashkon numërimet e këtyre statuseve te plani dhe afatet me `combinePostponed`;
  shënimi shtyrë tregon nëngrupin. Kjo është paraqitje, pa ndryshuar metrikat,
  penalizimet apo konfirmimet. Hover-i Plan RLZ, detajet ditore dhe Excel-i
  ruajnë ndarjen origjinale; mos ndrysho `realizationTaskGroups` për bashkimin.
- Realization ditor shfaq detyrat sipas të njëjtave kategori si hover-i i Plan RLZ;
  kolonat pa detyra në personat e filtruar fshihen. Gjerësitë janë relative dhe
  komenti/vlerësimi përdorin pamje kompakte vetëm në këtë tabelë. Klikimi i
  detyrës hap datat Start/Due para dhe pas shtyrjes, autorin, arsyen dhe komentin;
  butoni i konfirmimit është brenda dritares. Datat Start rindërtohen nga auditimi
  për ditën e zgjedhur përmes API-së së historikut, pa rishkruar datat e detyrës.
  Konfirmimet për person/detyrë/ditë
  ruhen te `realization_task_confirmations`, me autorin, kohën dhe evidencën.
  Vetëm Laurent Hoxha dhe Diellza Veliu konfirmojnë ose heqin konfirmimin në API.
  Konfirmimi heq penalizimin, pa ndryshuar statusin, kreditet apo peshën e planit;
  ndryshimi i evidencës kërkon konfirmim të ri. Kontrollo edhe përqindjet ditore
  dhe javore, Kontrollin ditor RLZ, gjendjen pas mbylljes dhe Excel-in (fleta
  `Konfirmimet RLZ`). Aprovimi ekzistues i shtyrjes gjithashtu heq penalizimin.
- Te **M3 PIKAT**, për realizim nën 50% te DEV, GD dhe PCM, çdo përdorues
  me qasje në raport mund të shkruajë komentin. Fusha ruhet kur humb fokusin.
  API-ja verifikon përqindjen dhe ruan komentin sipas datës dhe departamentit.
  Nga 16:15, pyetjet e Discord shkojnë te Laurent Hoxha për DEV dhe Diellza
  Veliu për GD e PCM, në kanalet e tyre private të lidhura. Secili departament
  nën 50% me koment ende bosh ka pyetjen e vet. Përgjigjja në Discord plotëson
  të njëjtën fushë. Komenti i ruajtur mbetet i dukshëm edhe pas përditësimit
  të përqindjes. Kontrollo Discord M3, tabelën, pamjen e email-it dhe
  bashkëngjitjet HTML, Word, PNG dhe Excel.
- Taskat përdoren edhe nga M1/M2/M3 dhe PIKAT PËR RAP. Mos i përjashto këto
  vetëm sepse ndryshimi fillon në My View ose Common View. Përfshirja e taskut
  varet nga kategoria, data, personi dhe filtrat e raportit.
- M2 Post-Break shfaq **ARSYEJA** dhe **KOMENT** te **STATUSI I DET
  08:00/DEADLINE/DUE DATE SOT** nga Daily Report i My View për datën e raportit. Vlerat
  lidhen sipas ID-së së detyrës. Gjenerimi, preview-ja dhe daljet e dërgimit
  përdorin të njëjtën tabelë. M2 PIKAT ndan përzgjedhjen e detyrave dhe ka
  rrjedhën e vet për shpjegimet dhe komentet manuale.
  M2 Post-Break përfshin edhe shënimet e veçanta nga Discord dhe komentet e
  vazhdimit AM → PM. Ndryshimet manuale ruhen për secilën fushë në draftin
  e M2 Post-Break dhe kanë përparësi gjatë rifreskimit dhe rigjenerimit.
  Tabela Post-Break përfshin edhe detyrat 08:00 dhe Deadline Important AM
  nga data e fillimit deri në datën e afatit, përfshirë detyrat e kryera.
  Kolona PROGRESI shfaq statusin. Rreshtat 08:00 marrin ngjyrën e statusit
  dhe ruajnë kornizën e kuqe në M2 Post-Break dhe daljet e tij. Filtri në
  DUE DATE shfaq të gjitha detyrat, vetëm SOT ose datat e tjera së bashku.
  Vetëm qeliza DUE DATE me vlerën SOT ka sfond të kuq në M2 Post-Break
  dhe në daljet e së njëjtës tabelë. DISCORD 1H
  shfaq përgjigjet e 11:00 dhe 11:50 të datës së raportit për të njëjtën ID
  detyre dhe ruan ndarjen nga KOMENT. M2 PIKAT dhe pyetjet M2 në Discord
  vazhdojnë të përdorin përzgjedhjen e detyrave AM/AM-PM të pakryera me afat sot.
  Në ekran, Arsyeja ruhet nga lista brenda qelizës dhe Komenti kur fusha
  humb fokusin. Numri i rreshtit lidhet me ID-në e detyrës pas filtrit të
  mungesave. Preview-ja dhe dërgimi përdorin tekstin e ruajtur.
- M2 në Discord lidh kartën AM të pambyllur me përgjigjen PM për të njëjtën
  detyrë/person/ditë. Vazhdimi AM→PM nuk ndryshon periudhën apo datat e taskut;
  ruhet në pyetjen PM dhe shfaqet edhe në M2 PIKAT/email/eksport. Mbyllja kalon
  përmes komandës normale të taskut; shtyrja përmes konfirmimit të Diellzës.
  Butoni AM “Vazhdon në PM” kërkon koment të detyrueshëm para ruajtjes. Komenti
  ruhet bashkë me PO në një transaksion, te `unfinished_comment` (detyra AM)
  dhe `pm_comment` (vazhdimi PM), si dhe një herë te komenti personal i detyrës.
  Anulimi ose komenti bosh nuk konfirmon vazhdimin; shënimi AM nuk plotëson
  automatikisht arsyen apo gjendjen ditore RLZ. Kontrollo formularët e vjetër,
  ridërgimin pa dublime dhe email/eksportin e të dy seksioneve në M2 PIKAT.
  Butoni i veçantë Koment ruan shënimin te komenti personal dhe te fusha M2,
  pa plotësuar Po/Jo, arsye apo datën e përgjigjes; ruhet edhe pas përgjigjes së mëvonshme.
- Common View dhe SHTYPI përdorin burim të përbashkët të dhënash, por kanë
  paraqitje të veçanta. Një ndryshim në JSX/CSS të Common View nuk ndryshon
  automatikisht HTML-in, emailin apo bashkëngjitjet e SHTYPI.
  Ngjyrat BLL dhe COM në Common View kanë stile lokale për pamjen ditore/javore;
  COM përdor `TaskMarkerComment` edhe në faqe të tjera, ndaj ndryshimet lokale
  kalojnë përmes klasës `common-marker-comment`. Printimi i ditës së ardhshme
  nga Common View ka stil të veçantë `.print-marker-comment`.
- Simbolet dhe komentet (`/comments`) lexon `/marker-comments` për datën
  origjinale të shtimit të komentit, veç datës së përditësimit. Komentet e
  vjetra pa datë origjinale shfaqin datën e regjistruar si orientuese. Filtri
  “Çdo përdorues” te “Të gjitha” përputh autorin ose marrësin sipas ID-së.
  PX Notes lidh te “Të gjitha”; shiritat e njoftimeve dhe dialogu i përbashkët
  i komenteve përdorin gjendjen dhe datën e përditësimit të listës bazë.
  Raportet dhe eksportet lexojnë simbolin dhe tekstin nga të dhënat e detyrës.
- PrimeFlow MCP liston komentet personale dhe versionin aktual të komenteve
  te simbolet për detyrat 1H. Gjendja `new` ose `seen` ruhet për llogarinë
  e asistentit dhe për versionin e komentit. Kontrollo Task Details dhe
  Simbolet dhe komentet për të njëjtin tekst, si edhe njohjen e komenteve
  të redaktuara si të reja. Njoftimet dhe konfirmimet e përgjegjësve përdorin
  `task_marker_comment_inbox`. M1 «A KA KOMENTE NE PF?» përdor historikun
  `task_symbol_comment_events`. SHTYPI lexon komentin e detyrës.
- SHTYPI Today dhe Tomorrow ndajnë komponentin dhe gjeneruesin bazë, por kanë
  dallime në data, gjenerim dhe historik. 1H Reports ka gjenerues tjetër.
  Mungesa ose PV tërëditore (08:00–16:00) përjashton detyrat nga gjenerimi i ri
  i 1H Reports në çdo slot, preview, email dhe eksportet Word/PNG/TXT, përfshirë
  përmbledhjen DET ME GA. Detyrat e përbashkëta mbeten për përgjegjësit e
  pranishëm; mungesat e pjesshme nuk i fshehin. Kontrollo edhe fallback-un
  `tasks` kur `oneH` mbetet bosh. Snapshot-et historike ruajnë përmbajtjen
  e gjenerimit origjinal; Common View dhe të dhënat e taskut nuk ndryshojnë.
- PX Notes dhe PX JAV lidhen me taskat përmes origjinës së Note dhe paketave
  Note–Task. Kontrollo edhe taskat për secilin përgjegjës, afatet dhe markerat.
  PX Notes lexon `/plan-notes?converted_to_task_only=true`: përfshin shënimet
  me flamurin e konvertimit ose me detyrë aktive të lidhur, edhe kur flamuri
  është i pasaktë. `EXISTS` shmang përsëritjen për disa përgjegjës; nuk krijohet
  GaNote ose detyrë e dytë. Printimi përdor tabelën e PX Notes; Excel-i ka
  endpoint më vete (`/exports/ga-notes.xlsx`) dhe lexon edhe këto PX JAV përmes
  të njëjtit filtër në server. Lista e zakonshme e PX JAV dhe raportet e tjera
  ruajnë filtrat e tyre.
- Takimet externe/interne mund të kenë pjesëmarrës të përbashkët, përsëritje,
  statuse sipas datës dhe taska PARA/PAS ose përgatitjeje. Kontrollo këto lidhje
  edhe kur ndryshon ose anulohet takimi. 1H Reports preket nga taskat përkatëse,
  pa qenë domosdoshmërisht një tabelë e plotë takimesh.
- `ALL` te krijimi i TAK INT në Common View ruan departamentin e takimit dhe
  cakton stafin aktiv nga të gjitha departamentet si pjesëmarrës individualë.
  `all_participants` ruan zgjedhjen për shfaqje. Ndryshimi manual i listës e
  heq etiketën, ndërsa ndryshimi vetëm i kujtesës e ruan. Kontrollo Common View
  (lista, detajet, printimi dhe Excel), Takimet, Admin Tasks (GA Time Table,
  pamja javore dhe Excel), tabelat ditore të Development,
  Graphic Design dhe Product Content në Department dhe My View, raportet
  M1/M2/M3, BZ të fundit të javës dhe SHTYPI Today/Tomorrow. Filtrat dhe
  kujtesat përdorin ID-të individuale të pjesëmarrësve. Finance nuk përdor
  tabelën ditore të takimeve.
- Meeting Scheduler krijon TAK EXT manual përmes `POST /meetings`, me emër,
  interval, pjesëmarrës dhe link opsional, pa krijuar automatikisht event/ftesë
  Microsoft ose TAK INT. Vetëm kontrolli i këtij formulari dërgon
  `conflicts_as_warnings=true` te `/meeting-scheduler/validate`: mbivendosjet
  PrimeFlow, 1H dhe Microsoft paralajmërojnë dhe lejojnë “Shto gjithsesi”.
  Datat në të kaluarën dhe të dhënat e pavlefshme mbeten gabime. Common View
  nuk dërgon këtë opsion dhe ruan validimin e mëparshëm, ashtu si kërkesat me
  aprovim. Profilet e orarit janë opsionale dhe nuk përzgjidhen automatikisht.
- Intervali i planifikuar i takimeve externe nga kalendari formohet nga
  `calendar-meeting-time.ts` në frontend dhe `calendar_meeting_time.py` në backend.
  Kontrollo Common View (ditore/javore, lista/detaje, fallback dhe printim), të tri
  Department Views/My View dhe printimet e tyre, katër faqet Projects,
  Meeting Scheduler dhe Admin Tasks (tabela GA e merr nga API-ja Common View),
  tabelën `DailyReportMeetingsTable`, M1/M2/M3 dhe SHTYPI Today/Tomorrow
  (HTML, Excel, PDF dhe PNG). API-ja Common View dërgon intervalin në `time`;
  renditja dhe kontrollet e konfliktit vazhdojnë nga fillimi. Kur mungon mbarimi,
  ruhet vetëm fillimi. Shënimi i ditës `(+1d)` nuk shfaqet. Tabelat e takimeve
  në SHTYPI (HTML/Excel/Word/PNG), raportet M1/M2/M3 dhe tabela ditore e
  departamenteve kanë kolona `PREJ` dhe `DERI`, me vijë ndarëse; pa orë mbarimi,
  `DERI` mbetet `-`. Snapshot-et historike ruajnë përmbajtjen që kishin në gjenerim.
  Në SHTYPI, etiketat CAL/MANUAL vendosen te celula e emrit të takimit në HTML,
  Excel, Word dhe PNG. Mbajtur/Anuluar vendosen nën orën te PREJ; DERI mban
  vetëm orën e mbarimit. USER është kolona e fundit pas titullit. Tabela ditore në
  Department Views/My View e ka Personat në fund.
- Shënimet e takimeve (`meeting_notes`) dalin te PX Notes vetëm kur dërgohen
  ose bashkohen; statusi i tyre ruhet manualisht në `manual_status`, veçmas
  nga taskat e Note-s PX (`ga_note_origin_id`). Bashkimi në PX përdor numra
  `1.`, `2.`, `3.` sipas rendit të përzgjedhjes. Renderuesi i PX Notes ruan
  numrin e shkruar edhe kur përgjigjet ose rreshtat bosh ndërpresin listën.
  Përmbajtja e bashkuar më parë nuk rishkruhet. Regjistrimi i lidhur
  me takim krijon shënim takimi edhe kur konfirmohet detyra nga propozimi AI.
- Shënimi / pyetja dhe vendimi redaktohen direkt në `NotesTable`, si te seanca e takimit ashtu edhe
  te Historia e klientit, me Ruaj/Anulo. PATCH dërgon vetëm `content` ose `answer`;
  teksti i shënimit nuk mund të ruhet bosh dhe lloji Pyetje/Shënim ruhet. Vendimi
  përfshihet në dërgimin/bashkimin e ardhshëm në PX Notes, por ndryshimi nuk
  përditëson kopjen që është dërguar tashmë në PX Notes.
  Kolona shqip e `answer` quhet “PËRSHKRIMI / PËRGJIGJA”; formulari dhe fusha
  direkte përdorin të njëjtin emërtim. Anglishtja përdor “QUESTION / CASE” dhe “ANSWER”;
  teksti i dërgimit në PX mbetet më vete.
  `NotesTable` ka buton fshirjeje direkt në rresht, si te seanca ashtu edhe te
  Historia e klientit, me konfirmim dhe DELETE ekzistues të `meeting_notes`.
  Hiqet nga lista/përzgjedhja vetëm pas suksesit; gabimi ruan rreshtin.
  Bashkëngjitjet e shënimit fshihen sipas API-së ekzistuese; kopjet në PX Notes
  dhe detyrat e tyre nuk fshihen. Butoni shfaqet kur konsumatori ofron `onRemoved`.
- Ngjyrat dhe etiketat e statuseve te shënimet e takimeve kanë disa burime:
  Statusi i shënimit ruhet manualisht në `MeetingNote.manual_status` me PATCH
  të shënimit, edhe pa detyra të lidhura. Seanca, Historia e klientit, numëruesit
  e listës dhe filtrimi i shënimeve Done përdorin këtë fushë. Statuset e detyrave
  normale/PX Notes nuk ndryshohen dhe nuk përcaktojnë statusin e shënimit.
  `meeting-notes.ts` / `NotesTable` përdoren te seanca dhe Historia e klientit;
  `StatusLegend` përdoret edhe te lista. Lista ka `CountChip`, seanca numëruesit
  e vet dhe Historia e klientit `chips` më vete. Kontrollo secilin para ndryshimit
  të DONE ose WFE/WAITING; ndryshimi i një numëruesi nuk përhapet automatikisht.
  Këto stile nuk përdoren nga raportet ose eksportet e detyrave.
- Gjuha e takimeve lidhet me llojin: tab-i External te lista `/meetings`,
  detajet e takimit ekstern, shënimet, redaktimi, klienti dhe legjenda përdorin
  anglishten përmes `meeting-notes-language.ts`. Historia e klientit përdor
  anglishten për seksionet eksterne dhe për filtrat/titullin kur të gjitha
  takimet e historisë janë eksterne. Interne/trajnime ruajnë shqipen; titujt,
  klientët dhe përmbajtja e shkruar nuk përkthehen. Sidebar, Meeting Scheduler,
  Regjistrimet dhe teksti i dërgimit në PX janë ndërfaqe më vete, pa ndryshim
  gjuhe nga ky rregull; nuk ndryshojnë API-të, taskat, raportet ose eksportet.
- Detajet e takimit kanë krye kompakte me datat e plota të seancave direkt
  poshtë emrit të takimit dhe vetëm dropdown-in e klientit pranë titullit,
  pa etiketë/buton ruajtjeje.
  Në hapjen e një takimi EXTERNAL, `collapseForPage` në `SidebarProvider`
  mbyll sidebar-in vetëm për atë faqe. Sidebar dhe Topbar lexojnë të njëjtën
  gjendje; përdoruesi mund ta rihapë manualisht. Preferenca në localStorage
  mbetet e paprekur dhe gjendja e zakonshme rikthehet kur largohet nga faqja.
  Takimet interne, lista, Historia e klientit, Regjistrimet dhe raportet nuk
  e aktivizojnë këtë sjellje.
  Zgjedhja/heqja e klientit ruhet direkt me PATCH; klienti i ri ruhet në blur/Enter
  pasi shkruhet emri. Gjatë ruajtjes fusha çaktivizohet; dështimi i zgjedhjes
  rikthen vlerën e ruajtur. `MeetingClientPicker.onCommit` është opsional:
  Meeting Scheduler ruan sjelljen ekzistuese të ruajtjes gjatë krijimit të takimit.
  Regjistrimi është në të njëjtin rresht pas filtrave dhe opsionit për shënimet
  e mbyllura; në ekran të ngushtë mbështillet. Kur nuk ka regjistrim në seancë, lidhja
  paraqitet si buton kryesor “Nis regjistrimin” / “Start recording”, me mikrofon.
  Hap të njëjtën faqe Regjistrimet me `meeting_id`; lidhjet e regjistrimeve
  ekzistuese dhe Historia e klientit nuk e përdorin këtë buton.
  Seksioni “Meeting details” / “Detajet e takimit” dhe opsioni për të shënuar
  si trajnim janë hequr nga kjo faqe. Kjo nuk ndryshon `is_training` të takimeve
  ekzistuese, API-në përkatëse ose krijimin si trajnim te Meeting Scheduler.
  Data shfaqet te përzgjedhja e seancës. Numërimet e
  statuseve gjenden poshtë tabelës, pranë legjendës. Në seancë legjenda tregon
  vetëm burimin manual/regjistrim (`withStatuses={false}`); statuset shfaqen
  vetëm te numërimet me ngjyra, pa përsëritje dhe pa shtyrje në skajin e djathtë.
  Lista dhe Historia e klientit ruajnë legjendën ekzistuese. Kjo paraqitje vlen për
  interne dhe eksterne; Historia e klientit ndan vetëm etiketat/tabelën, jo
  këtë krye. Formulari i klientit ruan hapësirë për krijimin e klientit të ri
  dhe gabimet pa lartësi fikse.
  Formulari i shënimit të ri është direkt poshtë filtrave të burimit dhe sipër
  tabelës, si fushë më e madhe me disa rreshta, sfond të bardhë, pa etiketë të
  dukshme “Shënim i ri”; emri i qasshëm ruhet për lexuesit e ekranit.
  Kjo fushë krijimi është vetëm te seanca e takimit, jo te Historia e klientit.
  Opsioni “Shfaq edhe të mbyllurat” është buton toggle pranë filtrave të burimit
  në të njëjtin grup, pa rreshtim në skajin e djathtë të faqes. Gjendja aktive
  theksohet me variantin kryesor dhe `aria-pressed`; filtrimi mbetet i njëjtë.
- Në të njëjtën tabelë, KUSH ndryshohet me përzgjedhje personi dhe AFATI shkruhet
  manualisht (`DDMMYYYY` ose `DD.MM.YYYY`), me Ruaj/Anulo dhe validim date.
  API-ja merr datën ISO; bosh e heq afatin. PATCH ndryshon vetëm `assignee_user_id` ose `due_date`
  të shënimit të takimit. Këto fusha nuk transferohen te PX Notes dhe nuk
  ndryshojnë përgjegjësit apo afatet e taskave të lidhura.
- Klientët e takimeve ruhen te `meeting_clients`; një klient lidhet me shumë
  takime përmes `meetings.client_id`, vetëm për identifikim. `client_name` ruan
  emrin për payload-et ekzistuese. Emrat e njëjtë bashkohen sipas shkronjave të
  vogla dhe hapësirave; migrimi ruan/bashkon etiketat e mëparshme. Lista dhe
  krijimi janë te `/meeting-notes/clients`. Zgjidhen ose krijohen te Meeting
  Scheduler dhe detajet e takimit; lista Takimet ka filtër sipas klientit dhe
  emri në kolonën KLIENTI aktivizon atë filtër. Lidhja ndryshohet përmes
  `/meeting-notes/meetings/{id}/client` nga çdo përdorues
  i kyçur (ADMIN/MANAGER/STAFF), njësoj si shënimet e takimit, përfshirë takimet
  e importuara pa krijues. Nuk krijon lidhje me projektin, historinë
  e projektit, taskat ose PX Notes; nuk dërgohet në Microsoft Calendar.
  `project_id` mbetet lidhje më vete, e përdorur nga historia ekzistuese dhe PX.
- Shkurtesat e klientëve paraqiten përmes `meeting-client-label.ts` te kolona dhe
  filtri i Takimeve dhe te `MeetingClientPicker` (detajet dhe Meeting Scheduler).
  Emri i plotë shfaqet në hover; kërkimi në Takimet pranon emrin dhe shkurtesën.
  ID-ja dhe emri i ruajtur mbeten të njëjtë; klientët pa shkurtim të përcaktuar
  shfaqen me emrin e plotë. Kjo paraqitje nuk klasifikon takime PARA/PAS dhe nuk
  ndryshon historinë sipas projektit, raportet, PX Notes apo Microsoft Calendar.
- Kolonat Data / Ora, Pjesëmarrësit dhe Shënime të hapura te lista Takimet
  përdorin `starts_at`, `next_session`/`last_session`, `participant_ids` dhe
  `counts.open_notes` nga `/meeting-notes/overview`; inicialet/emrat lexohen nga
  `/users/lookup` përmes `useUsersMap`. Data e takimit njëherësh ruan datën lokale
  origjinale; përsëritjet shfaqin seancën e radhës me orën lokale të takimit.
  E radhës përdoret vetëm për përsëritjet. Numri i shënimeve të hapura përjashton
  shënimet e mbyllura dhe ato me detyra të krijuara (të cilat numërohen te Detyrat).
  Këto kolona nuk shtohen automatikisht te detajet, Historia e klientit,
  Regjistrimet ose raportet; API-ja dhe caktimet e pjesëmarrësve nuk ndryshojnë.
- Lista Takimet përjashton plotësisht interne PARA/PAS (lidhjet
  `pre_external_meeting_id` / `paired_external_meeting_id`), edhe nga kërkimi,
  numërimet. Eksterne fizike me tonin `outlook-blue` mbeten të fshehura në listë;
  opsioni për t'i përfshirë është hequr. Krijimi dhe të dhënat e
  interne PARA/PAS nuk ndryshojnë. Klasifikimi përdor `meeting-notes-overview.ts` dhe
  ngjyrat ekzistuese nga `meeting-tone.ts`. API-ja `/meeting-notes/overview`
  përdoret edhe për lidhjen e regjistrimit me takim te Regjistrimet: mos e
  filtro globalisht, sepse do të hiqte takime nga ajo përzgjedhje. Detajet,
  seancat dhe historia e klientit mbeten të arritshme për takimet e fshehura.
- Shtyrja, mbyllja, strike-et dhe ndryshimet e afateve mund të ndikojnë te
  Realization, bazat e planit, numërimet dhe raportet, përveç paraqitjes së taskut.
- Kopjet historike/snapshot-et nuk krahasohen si të dhëna live. SHTYPI Today
  ka kopje të ngrirë në 16:00; ruaj historikun dhe dallimin para/pas cutoff-it.
- Notes nga Mira kanë rregulla të veçanta dukshmërie në raporte. Mos supozo se
  çdo Note duhet të dalë në çdo raport; dallo regjistrimin nga tasku i krijuar.
- Regjistruesit Discord 1H dhe Mira Zhvillim ruajnë fillimisht tekstin e transkriptuar
  sipas folësit, pa kohë pranë replikave, pastaj një përmbledhje të shkurtër nga i njëjti takim.
  Kontrollo përmbajtjen te Mira → Shënimet, PX Notes dhe rezultati në Discord
  për ruajtje manuale. Pas dështimit përfundimtar të përmbledhjes, transkripti
  vazhdon të ruhet. Mira Host ka përmbledhje të veçantë te Mira → Takimet.
- “Mira, shëno … fund shënimi” nga një folës me llogari Discord të lidhur
  krijon një shënim më vete direkt te PX Notes. Kontrollo komandat e ndara
  në segmente, folësit që ndërhyjnë dhe riprovimet. Në All Tasks/Notes burimi
  shfaqet me tekst të thjeshtë. Diktimet nuk shtohen në listën Mira → Shënimet
  ose në listat e shënimeve të raporteve që përjashtojnë shënimet e Mirës.
- Për të dy regjistruesit, “fund titulli” ndan titullin me shkronja të mëdha
  nga teksti në rreshtin pasues. Pranohen edhe “fund titullit”, “fund titull”,
  “fund titulle”, “fund titullë” dhe format e bashkuara si “fundtitulli”.
  Kur ndarësi mungon ose nuk njihet,
  “fund shënimi” ruan gjithë tekstin e diktuar. Kontrollo rreshtat në PX Notes,
  Excel dhe shënimin e lidhur te Mira → Takimet.
- “Mira, planifiko … fund shënimi” krijon shënim direkt në PX JAV për të dy
  regjistruesit. Pranohen edhe “planfiko” dhe “planifko”, me ose pa `ë` ose
  `e` në fund, njësoj si “planifiko”.
  Përdor të njëjtat variante të “fund titulli” dhe ruan gjithë
  tekstin pa ndarës të njohur. Shënimi hyn në PX JAV dhe PX JAV Kontrolli
  me rregullat ekzistuese të një shënimi të hapur pa detyrë të krijuar.
- Të dy regjistruesit pranojnë edhe variantet e transkriptuara “Mira shëna”,
  “Mirëa shëno”, “Mirashënë”, “fund shënime”, “Mira detyr” dhe “fund detyra”.
  Në diktimin e detyrave, `EFA` përputhet
  edhe me profilin “Elsa Ferati”. Nëse përputhen dy profile aktive, detyra
  nuk krijohet.
- Diktimi i një detyre nga 1H ose Mira Zhvillim ruan në të njëjtin transaksion
  detyrën 1H dhe shënimin e lidhur në PX Notes. Pas inicialeve, “fund titulli”
  dhe variantet e tij e ruajnë pjesën e parë me shkronja të mëdha si titull të
  detyrës. Vazhdimi ruhet në rreshtin pasues të shënimit të lidhur. Pa ndarës
  të njohur, i gjithë diktimi pas inicialeve përdoret si titull, si më parë.
  Kontrollo që “Task Created”
  të hapë detyrën ekzistuese dhe që burimi të shfaqet te Task Details,
  Common View, My View, Development, Graphic Design, Product Content,
  Finance dhe eksportet përkatëse. Raportet që përjashtojnë shënimet e
  Mirës vazhdojnë ta përjashtojnë shënimin e lidhur.
- Kur diktimi i Mirës ka detyrë të lidhur, qeliza SHËNIMI në PX Notes merr
  ngjyrën sipas statusit të detyrës. Printimi kopjon ngjyrën nga tabela.
  Excel-i përdor hartën e vet të ngjyrave të statusit.
- Mira Host lexon Done/strike përmes filtrimit dhe snapshot-it të përbashkët me
  1H Reports; ndryshimet te këta ndihmës kontrollohen edhe te raportet/SHTYPI.
  Radha e raportimit ka përjashtime sipas slotit: LH, EH, EF dhe RA nuk marrin
  radhë në 11:50 dhe 16:00, përfshirë rishikimin PM në 11:50. Kontrollo ftesat,
  praninë, radhët e ruajtura/rinisjen dhe listën te Mira → Takimet; personat e
  përjashtuar nuk duhen shpallur mungesë. Ky rregull nuk filtron detyrat në
  Common View, SHTYPI ose 1H Reports dhe nuk ndryshon slotet e tjera.
  `turns_view` përdoret edhe nga përmbledhjet/Mira Notes dhe dërgimi në PX Notes;
  atje ruhen faktet dhe shënimet historike me `include_slot_excluded=True`,
  pa i rifutur personat në radhën ose statuset e raportimit.
  Hyrja zanore është Notes të reja → Done → Strikes; për kategori bosh lexohet
  shkurt se nuk ka të reja. Edhe këto fjali kërkojnë konfirmim audio, pa krijuar
  përmendje për detyra ose Notes që mungojnë. Ky rend i audios nuk ndryshon
  gjeneruesit e raporteve. Afati pyetet vetëm kur mungon; PËRGJIGJA e shkurtër
  ruhet siç u tha, pa diktuar zotime ose data. Pas konfirmimit të pjesës së fundit,
  kontrolluesi mund të kalojë në pritje të heshtur me `wait_for_staff` para orës
  zyrtare, pa një përgjigje tjetër të modelit. Kontrollo që audioja, reagimet
  automatike dhe rikuperimi i përgjigjes të mos e thyejnë këtë pritje, ndërsa
  konfigurimi i stafit/mbylljes dhe rezultatet e vonuara ruajnë fazën e saktë.
  `mira_host_speech` përgatit vetëm shqiptimin e Host (titujt, hyrjen dhe kodet):
  shkurtesat teknike dhe përqindjet lexohen shqip; adresat, skedarët dhe versionet
  ruhen si identifikues. Verifiko që titujt, argumentet e shkrimit dhe përmendjet
  e ruajtura mbeten burimi origjinal dhe që konfirmimi i audios përputhet me
  tekstin e përgatitur. Pyetjet e stafit/PM nuk duhet të rilexojnë lista ose
  etiketa teknike dhe kufiri i kohës nuk duhet të përdoret si minimum raportimi.
  Pas përgjigjes mjafton “Në rregull”/“Dakord” dhe direkt pyetja tjetër, pa
  njoftime kujtese ose ruajtjeje. Kontrollo udhëzimin bazë dhe rikuperimin zanor
  të worker-it, si në test ashtu edhe në takim real.
  Në 16:00 secili pyetet në fund për vazhdimin nesër sipas planit, edhe kur ka
  detyra të hapura/BLL; në rishikimin PM të 11:50 pyetet nëse vazhdon në PM
  sipas planit. Një “po” mjafton; për “jo” sqarohet vetëm ndryshimi. Mos pyet
  sërish kur personi e ka sqaruar tashmë. PM ruhet te `record_pm_review`, nesër
  te shënimi i shkurtër `summary` i radhës; kontrollo transkriptin, Mira → Takimet
  dhe shënimet e përmbledhura/dërguara në PX Notes pa ndryshuar planifikimin.
  Rikuperimi i përgjigjes duhet të ruajë udhëzimin e fazës aktive; nuk duhet
  të humbasë pyetjen e slotit ose të rrëfejë “po e mbaj shkurt/po vazhdoj”.
  “Po/jo” nga folësi aktual pas pyetjes kërkon vazhdim edhe nëse modeli e
  injoroi; reagimet gjatë audios së Mirës vazhdojnë të filtrohen.
  Përmendja e një PX Note nga Host nuk e bën atë Note të krijuar nga Mira.
  Përjashtimet e detyrave nga leximi i Host nuk duhet të ndryshojnë raportet e
  përgjithshme. Hyrja para takimit dhe fillimi zyrtar i stafit/pranisë janë hapa
  të veçantë; kontrollo edhe nisjen manuale dhe rishikimin PM në 11:50.
  Në 16:00 radha dhe njoftimi paraprak i Host përfshijnë edhe përgjegjësit që
  kanë vetëm BLL. Pas rilidhjes kontrollo rikthimin e radhëve të papërfunduara
  dhe ruajtjen e raportimeve/fakteve të mëparshme, përfshirë rishikimin PM.
- Në 11:50 radha e Host përfshin edhe përgjegjësit që kanë vetëm detyra të
  pambyllura nga slotet e mëparshme, pas personave të slotit aktual. Kontrollo
  edhe ftesën paraprake dhe shmangien e dublimeve/mungesave. Nisja PM duhet të
  kontrollojë burimin e freskët dhe radhën e ruajtur edhe kur snapshot-i i stafit
  nuk ka detyra PM. Mbyllja dhe skedarët e rikuperimit të Host mbajnë tentativën
  e lidhjes (`join_attempt`); një kërkesë e vjetër nuk duhet të mbyllë rinisjen.
  Pas upload-it të rikuperimit, fshi vetëm snapshot-in e rikuperuar: rinisja
  mund të ketë ruajtur një transkript më të ri në të njëjtin skedar ndërkohë.
  Skedarët e rinj ruhen veçmas për çdo tentativë; lexo edhe formatin e vjetër
  `<meeting_id>.json`. Rinisja dhe pastrimi i tentativës së vjetër nuk duhet të
  mbishkruajnë/fshijnë rreshtat, metrikat apo konfirmimet ende të padërguara.
  Anulimi i procesit regjistrohet si ndërprerje, jo si takim i përfunduar;
  ruaj identitetin e tentativës edhe kur ndalimi ndodh para lidhjes zanore.
  Nisja e dështuar gjatë përgatitjes së kredencialeve mbyll vetëm tentativën
  përkatëse; kontrollo përsëri gjendjen para kthimit të një sesioni të gatshëm.
  Në ndalim prit me kufi shkrimet që janë në punë para upload-it përfundimtar.
  Rikuperimi ka kufij kohe për kërkesat dhe kalon me radhë te skedarët e tjerë,
  që një skedar i dëmtuar ose kërkesë e bllokuar të mos pengojë takimet pasuese.
  Përmbledhjet dhe shënimet për person krijohen në sfond dhe shfaqen te Mira / PX
  Notes: kontrollo veçmas nëse një rezultat i vonuar i gjenerimit mbishkruan një
  transkript më të ri ose përmbledhjen pas rinisjes. Kjo varësi kërkon kontroll
  edhe kur takimi vetë është rikuperuar me sukses.
- Kur një kategori ka fushë gri në Excel, kjo pasqyron kontrollin e dakorduar
  për atë kategori. Nuk provon mungesën e çdo varësie të ardhshme: për një fushë
  ose sjellje të re, ndiq implementimin dhe rishiko hartën.
- Kontrollo rolet ADMIN/MANAGER/STAFF, filtrat e departamentit/personit/datës,
  cache-in dhe rifreskimin kur ato ndikojnë në sjelljen që po ndryshon.

## Kontrolli i deployment-it të frontend-it

`frontend/scripts/deploy-release.ps1` përgatit dy versione me varësi të veçanta
nën `PM2_HOME/primeflow-deploy/frontend-releases`. Kontrollo kandidatin në
`127.0.0.1:3301` para ndërrimit dhe commit-in që shërbehet në portën 3000 pas tij.
Ruaj versionin aktiv gjatë instalimit dhe build-it, si dhe versionin e mëparshëm
për rikthim nëse nisja në portën 3000 dështon.

Për aktivizimin e parë, instalo gateway-n me `deploy/install-gateway.ps1`
dhe Caddy për Windows në serverin ku punon lidhësi i Cloudflare Tunnel.
Ruaj adresat aktuale të origjinës në Cloudflare për rikthim. Nëse tuneli
ka lidhës në serverë të ndryshëm, verifiko arritshmërinë nga secili përpara
ndryshimit. Për lidhësin në serverin e PrimeFlow përdoren këto destinacione.

| Hostname | Shërbimi i tunelit | Prova publike para push-it |
| --- | --- | --- |
| `primeflow.primexeu.com` | `http://127.0.0.1:13000` | `GET /login` kthen 200 dhe header-in `X-PrimeFlow-Origin: 3000` |
| `api-flow.primexeu.com` | `http://127.0.0.1:18080` | `GET /health` kthen `status=ok` dhe `X-PrimeFlow-Origin: 8080` |

Gjatë deploy-it gateway lexon dy skedarë lokalë për të zgjedhur destinacionin
e çdo kërkese të re. Proceset në portat 3301 dhe 8000 marrin përkohësisht
trafikun përkatës pasi kalojnë kontrollin. Lidhjet e hapura përfundojnë te
procesi i vjetër. Pas verifikimit publik, lidhja e njoftimeve rilidhet te
origjina e zgjedhur. Kontrollo rikuperimin e njoftimeve të humbura gjatë
kalimit, numëruesin në shiritin e sipërm dhe komentet me shenjues.
Nëse një lidhje tjetër ose kërkesë e gjatë e mban procesin të zënë
për 20 minuta, workflow dështon para ndaljes së tij dhe lë trafikun në
destinacionin e verifikuar. Nëse deploy ndërpritet, kontrollo të dyja
origjinat dhe header-in publik përpara rinisjes. Testi në Windows përdor
`python deploy/test_gateway.py <caddy.exe>` me portat lokale të lira.

Përditësimet e DB-së dhe API-së duhet të funksionojnë edhe me versionin
që shërben gjatë kalimit. Ndaje heqjen e kolonave ose ndryshimin e kontratës
nga deploy-i që zhvendos lexuesit. Kontrollo hyrjen, një faqe të hapur që
ngarkon një chunk të vjetër dhe një kërkesë API në vazhdim. Para rinisjes
së botëve, `backend/scripts/wait_for_mira_deploy.py` pret mbylljen e seancave
1H dhe Mira Zhvillim, përfundimin e shënimeve dhe mbylljen e takimit Mira Host.

`.github/workflows/deploy.yml` përdor `frontend/scripts/wait-for-readiness.ps1`
për kandidatin, rikthimin e versionit të mëparshëm dhe kontrollin përfundimtar.
Ndryshimet e këtij kontrolli ndikojnë pranimin ose rollback-un e gjithë build-it,
përfshirë Common View, Department Views, Finance dhe faqet e raporteve; nuk
ndryshojnë renderuesit ose të dhënat e tyre. Kontrollo përgjigjen e vonuar,
gabimet HTTP dhe refuzimin e një faqeje HTTP 200 me commit të vjetër. Vetëm pas
kontrollit të commit-it të ri përditësohet shënuesi `frontend.sha`. Prova lokale
e kontrollit nuk zëvendëson verifikimin e deployment-it real në server.

## Pikat kryesore në kod

- ASIST GA – DET GA lidh M1 Start of Day, After Break, Meetings Report,
  M1/M2/M3 PIKAT dhe 1H SHTYPI Sot/Nesër me `?date=YYYY-MM-DD`.
  Për datat e arkivuara SHTYPI përdor snapshot-in e datës, edhe te Nesër.
  Ruajtja MCP e pikës «A duhet riorganizim?» përdor përgjigjen manuale të
  M1 PIKAT. Kontrollo edhe preview, email dhe eksportet e M1 PIKAT. Lista
  PX e afateve përdor përgjegjësin ose konfirmuesin GA si lista GA Tasks.
  Agjenda MCP lexon simbolet e ruajtura që përdorin Common View, 1H
  dhe raportet M1/M2/M3. Takimet lexojnë të njëjtën ditë dhe status si GA
  Time Table dhe shënimet e Takimeve. Shënimi «reacted» te GA Devices është
  gjendje e listës MCP. Përfundimi i detyrës kalon nga shërbimi ekzistues
  dhe pasqyrohet në Task Details, Common View, My View, Development,
  Graphic Design, Product Content, Finance dhe në raportet e lidhura.

- Tema Light / Dark / System: `frontend/src/lib/theme.ts` vendos klasën `dark`
  para renderimit dhe ruan `primex-theme` në localStorage; System ndjek ndryshimet
  e pajisjes dhe zgjedhja sinkronizohet mes skedave. `theme-switcher.tsx` në
  Topbar dhe njoftimet Sonner përdorin `use-theme.ts`. Variablat në `globals.css`
  dhe ngjyrat e vjetra në `theme-utilities.css` ndikojnë gjithë aplikacionin:
  Common View, My View, Development, Graphic Design, Product Content, Finance,
  planifikuesit, PX Notes/PX JAV dhe faqet M1/M2/M3. Kontrollo secilën pamje
  veçmas për ngjyra inline/arbitrare. Rregullat e temës vlejnë vetëm në ekran;
  printimi ruan variablat Light. Preview-t në iframe (1H Reports, SHTYPI dhe
  raportet që përdorin HTML të gjeneruar), email-et dhe eksportet kanë stile
  të veçanta dhe nuk trashëgojnë temën e faqes prind.

- Vendosja direkte e simboleve: Weekly Planner (kartat e projekteve, sistemore,
  të shpejta dhe kutia e planifikimit), Common View javore, Monthly Planner,
  Open Tasks, Admin Tasks, WFC INT, Projects, Task Details, PX JAV dhe preview i 1H Reports përdorin
  redaktuesin e përbashkët. Common View javore paraqet një kontroll për kartën
  me disa persona. Dialogu nis me “Për të gjithë” dhe ruan të njëjtat simbole
  në taskat e kartës, duke ruajtur komentet individuale. “Sipas personit” hap
  kontrollet e veçanta vetëm brenda dialogut. Kartat mbeten të bashkuara edhe
  kur simbolet ndryshojnë dhe kontrolli shfaq `⋯ ▾` me ngjyrë neutrale; hover-i
  tregon personat dhe simbolet e tyre. Kontrollet React dhe përzgjedhësi në
  preview SHTYPI Today/Tomorrow shfaqin dy simbolet si etiketa të ndara pa `+`.
  Teksti i printimit/raporteve ruan formatin e vet. Inicialet mbeten
  në kartë. Deduplikimi i raporteve të printimit mbetet sipas simboleve;
  printimi nga shfletuesi shfaq vlerat individuale pa kontrollet.
  Lista PX Notes shfaq vetëm etiketa të simboleve ekzistuese, pa kontrolle
  direkte dhe pa tregues bosh. Kjo vlen edhe për Notes me burim PX JAV brenda
  kësaj liste; simbolet ndryshohen në Edit Note. Faqja më vete PX JAV dhe
  Weekly Planner ruajnë kontrollet e tyre. Editori i përbashkët i komenteve
  përdor të njëjtin Edit Note dhe nuk merr kontrolle të reja.
  `task-marker-updates.ts` përditëson vetëm kopjet live të të njëjtit task dhe
  pastron cache-in Common View. Printimi përdor vlerën e ruajtur, pa butonat.
  M1/M2/M3 kanë panelin “Simbolet e detyrave” për detyrat aktuale të datës;
  teksti i raportit përditësohet me rifreskim/rigjenerim, jo nga përputhja e
  titujve. Historiku/snapshot-et mbeten të pandryshuara. My View dhe Department
  Views në Development, Graphic Design, Product Content, Finance dhe SHTYPI
  Today/Tomorrow kishin tashmë vendosjen direkte. Simboli i Note-s dhe simbolet
  e detyrave të personave ruhen veçmas; mos i përhap automatikisht te të tjerët.
  Task Details mban ndryshimet e simboleve veç draftit të formularit, që ruajtja
  e një simboli të mos fshijë redaktimet e paruajtura të titullit/përshkrimit.
  Redaktuesi sinkronizon props-at e ndryshuara para renderimit; një renderim
  me të njëjtat vlera të ruajtura nuk duhet të anulojë ndryshimin optimist.
  Ky kontroll vlen edhe për përdoruesit ekzistues të komponentit në My View,
  Department Views, Finance dhe SHTYPI Today/Tomorrow.

- 1H Reports: filtri “Vetëm Notes” përdor `notes_html` për preview dhe
  `notes_only=true` te `/admin/primeflow-1h-reports/preview` për Word/PNG/Text.
  Kopja përfshin vetëm Notes të padiskutuara me të njëjtat rregulla përzgjedhjeje
  si raporti i plotë; nuk shton burime Mira. Kontrollo mënyrat Admin dhe staf,
  çaktivizimin/kalimin te Done/Strikes, rigjenerimin dhe raportin pa Notes.
  Emaili manual/automatik, shkarkimet historike dhe SHTYPI Today/Tomorrow mbeten
  raportet e tyre të plota; ky filtër nuk i ndryshon.

- 1H Reports: shtesat GA (Time Table, GA/HV dhe SHTYPI i integruar) në preview
  JSON/HTML shfaqen vetëm për përdoruesin e autentikuar `gane.arifaj`, pavarësisht
  rolit dhe marrësve të konfiguruar. Kontrollo edhe llogaritë e tjera ADMIN,
  MANAGER dhe STAFF. Word/PNG/Text përdorin dokumentin bazë; emaili i GA ka
  ndarjen e vet sipas marrësit në `primeflow_report_delivery.py`. SHTYPI
  Today/Tomorrow dhe eksporti GA Time Table kanë rrjedha të veçanta.

- Njoftimi automatik i deployment-it në Discord përdor workflow-n dhe
  `backend/scripts/notify_discord_deploy.py`: lexon lidhjet aktive dhe dërgon
  paralajmërimin 7 minuta në kanalet personale para migrimeve/rinisjeve.
  Përfundimi njoftohet pas kontrolleve të deployment-it, dështimi veçmas;
  `/push` manual mbetet i ndarë. Nuk bllokon redaktimin në faqet e aplikacionit.
  Shih [njoftimet e deployment-it](discord-deployment-notices.md).

- Apliko migrimet në prodhim nga workflow `Primex Auto Deploy`, pasi skedari
  i migrimit të jetë në `main`. Për ndryshime të backend-it, `plan` lexon
  revizionet nga konfigurimi i databazës në runner dhe kontrollon rrugën e
  përditësimit për commit-in që publikohet. Kontrolli përsëritet me
  konfigurimin e deployment-it para `upgrade head`. Nëse revizioni aktiv
  mungon në Git, rikthe migrimin dhe verifiko skemën përpara një deployment-i
  të ri. Workflow i pull request-it kontrollon grafin pa lidhje me prodhimin.

- Integrimi i jashtëm NEWS-PX merr GA Time Table nga printimi ditor i Admin
  Tasks dhe `/api/exports/ga-time.xlsx` për email-et 07:00/21:00
  (Europe/Budapest). Ndryshimet në datë, kolonat, selektorët e printimit,
  autentikim ose rrugët e serverit kërkojnë kontroll të PDF/Excel në News.
  Binding-u dhe cache-i privat ruhen jashtë aplikacionit; zhvendosja e checkout-it
  nuk i zhvendos automatikisht. Shih
  [kontrollin dhe rikuperimin e integrimit](ga-news-integration-recovery.md).

| Zona | Skedarët kryesorë |
|---|---|
| Taska dhe modelet e të dhënave | <code>backend/app/api/routers/tasks.py</code>, <code>backend/app/schemas/task.py</code>, <code>frontend/src/lib/types.ts</code>, <code>frontend/src/components/task-edit-dialog.tsx</code> |
| My View dhe departamentet | <code>frontend/src/app/(app)/departments/{development,graphic-design,project-content-manager,finance}/department-kanban.tsx</code> |
| Common View | <code>frontend/src/app/(app)/common/page.tsx</code>, <code>backend/app/api/routers/common_view.py</code> |
| SHTYPI Today / Tomorrow | <code>frontend/src/app/(app)/today-print-report/page.tsx</code>, <code>frontend/src/app/(app)/tomorrow-print-report/page.tsx</code>, <code>backend/app/services/tomorrow_print_report.py</code>, <code>backend/app/services/today_print_report_freeze.py</code> |
| 1H Reports | <code>frontend/src/app/(app)/admin/1h-reports/page.tsx</code>, <code>backend/app/services/primeflow_report.py</code> |
| PX Notes dhe PX JAV | <code>frontend/src/components/px-notes-workspace.tsx</code>, <code>frontend/src/app/(app)/next-week-plan/page.tsx</code>, <code>backend/app/api/routers/ga_notes.py</code>, <code>backend/app/api/routers/plan_notes.py</code>, <code>backend/app/services/ga_note_task_instances.py</code> |
| Takimet | <code>backend/app/api/routers/meetings.py</code>, <code>backend/app/services/meeting_occurrence.py</code>, <code>backend/app/services/meeting_system_tasks.py</code>, <code>backend/app/services/meeting_cancellation.py</code>, <code>frontend/src/components/daily-report-meetings-table.tsx</code> |
| Takimet / shënimet | <code>backend/app/api/routers/meeting_notes.py</code>, <code>backend/app/models/meeting_note.py</code>, <code>frontend/src/app/(app)/meetings/</code>, <code>frontend/src/components/meeting-notes/</code>, <code>frontend/src/lib/meeting-notes.ts</code> |
| Projektet | <code>backend/app/api/routers/projects.py</code>, <code>frontend/src/app/(app)/projects/[id]/page.tsx</code>, <code>frontend/src/app/(app)/projects/{dev,pcm,design}/[id]/page.tsx</code> |
| M1 / M2 / M3 | <code>backend/app/services/morning_report.py</code>, <code>backend/app/services/after_break_report.py</code>, <code>backend/app/services/meetings_report.py</code> dhe faqet përkatëse në frontend |
| PIKAT PËR RAP | <code>backend/app/services/m1_reporting_points.py</code>, <code>backend/app/services/m2_reporting_points.py</code>, <code>backend/app/services/m3_reporting_points.py</code>, <code>frontend/src/components/m*-reporting-points-view.tsx</code> |
| Planifikimi dhe realizimi | <code>backend/app/api/routers/planners.py</code>, <code>backend/app/services/daily_report_logic.py</code>, <code>backend/app/services/daily_realization_live.py</code>, <code>frontend/src/app/(app)/weekly-planner/page.tsx</code>, <code>frontend/src/app/(app)/realization/</code> |
| Eksportet dhe dukshmëria e Notes | <code>backend/app/api/routers/exports.py</code>, gjeneruesi përkatës i raportit, <code>backend/app/services/report_note_visibility.py</code> |

Shtigjet me <code>{...}</code> ose <code>*</code> janë grupe skedarësh; zgjidh implementimin konkret
që prek ndryshimi. Mos u mbështet vetëm në këtë inventar nëse kodi ka ndryshuar.
