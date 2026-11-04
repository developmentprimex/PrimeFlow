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
| Taska - ndryshime të përgjithshme | My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, PX Notes, PX JAV, Weekly Planner, Monthly Planner, Open Tasks, Admin Tasks, Projects, Task Details, Realization, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Meeting Scheduler, WFC, Comments, Reviews, Kontrolli ditor RLZ, Weekly Planning Check |
| Taska - personale / R1 / BLL | My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, PX Notes, PX JAV, Weekly Planner, Monthly Planner, Open Tasks, Admin Tasks, Projects, Task Details, Realization, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Taska - sistemore / përsëritje | System Tasks, System Tasks Report, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Weekly Planner, Realization, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details |
| Taska - nga PX Notes | PX Notes, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Projects, Weekly Planner, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details |
| Taska - nga PX JAV | PX JAV, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Weekly Planner, Projects, PX JAV Kontrolli, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details |
| Taska - nga takimet | Meetings, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, System Tasks, Weekly Planner, Realization, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Department Views, Task Details |
| Projekte - ndryshime të përgjithshme | Projects, Department Views, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, PX Notes, PX JAV, Weekly Planner, Monthly Planner, Meeting Scheduler, Realization, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, Task Details, Open Tasks, Weekly Planning Check |
| Projekte - faza / checklista | Projects, Meetings, Common View, Department Views, My View, Exports, Task Details |
| Takime externe | Common View, My View, Department Views, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Meeting Scheduler, Projects, Admin Tasks, M1 / M2 / M3 |
| Takime interne | Common View, My View, Department Views, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Meeting Scheduler, Admin Tasks, M1 / M2 / M3 |
| Checklista takimesh | Projects, Meetings, Common View, Department Views, My View, Exports |
| PX Notes | PX Notes, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Projects, Weekly Planner, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| PX JAV | PX JAV, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, Weekly Planner, Projects, PX JAV Kontrolli, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Mungesa dhe pushime | Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Weekly Planner, PX JAV, Realization, Weekly Planning Check, M1 / M2 / M3 |
| WFC / Waiting Client | WFC, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, PX Notes, PX JAV, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Planifikim | Weekly Planner, Monthly Planner, PX JAV, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Realization, Weekly Planning Check, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Realization dhe Reviews | My View, Department Views, Finance View, Realization, Reviews, Common View, Weekly Planner, Kontrolli ditor RLZ, M3 PIKAT |
| Regjistrime dhe Mira | Regjistrimet, Mira, Meetings, PX Notes, Task Details |
| Takimet (shënimet e takimeve) | Takimet, Takimi (seancat), Historia e klientit, Regjistrimet (Shënim / Injoro / screenshot), PX Notes (Dërgo / Bashko në PX), Meeting Scheduler (Trajnim), Sidebar |
| Mira Host / takimet 1H | Mira (nisje/ndalim/status), Discord 1H (hyrja, prania, radha, audioja), PX Notes, Common View, 1H SHTYPI Today, 1H Reports (Done dhe strike), Task Details |
| Raporte / email / eksporte | Reports, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, PX JAV Kontrolli, Weekly Planning Check, Kontrolli ditor RLZ, Print Preview, Print, Email, Exports, History |
| Përdorues dhe përgjegjës | Users, My View, Department Views, Finance View, Projects, PX Notes, PX JAV, Common View, Weekly Planner, Monthly Planner, Meeting Scheduler, Reports |
| GA PERSONAL - grupet dhe filtrat | Pamja ditore dhe javore e GA PERSONAL, filtri i grupeve dhe etiketat e tabelave; klasifikimi i eventeve ndahet përmes `frontend/src/lib/ga-personal-week.ts`, përfshirë eventet e vjetra të volejbollit. Të dhënat e modulit mbeten të ndara nga detyrat dhe raportet e kompanisë. |

## Varësi që nuk duhen harruar

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
- Taskat përdoren edhe nga M1/M2/M3 dhe PIKAT PËR RAP. Mos i përjashto këto
  vetëm sepse ndryshimi fillon në My View ose Common View. Përfshirja e taskut
  varet nga kategoria, data, personi dhe filtrat e raportit.
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
- SHTYPI Today dhe Tomorrow ndajnë komponentin dhe gjeneruesin bazë, por kanë
  dallime në data, gjenerim dhe historik. 1H Reports ka gjenerues tjetër.
- PX Notes dhe PX JAV lidhen me taskat përmes origjinës së Note dhe paketave
  Note–Task. Kontrollo edhe taskat për secilin përgjegjës, afatet dhe markerat.
- Takimet externe/interne mund të kenë pjesëmarrës të përbashkët, përsëritje,
  statuse sipas datës dhe taska PARA/PAS ose përgatitjeje. Kontrollo këto lidhje
  edhe kur ndryshon ose anulohet takimi. 1H Reports preket nga taskat përkatëse,
  pa qenë domosdoshmërisht një tabelë e plotë takimesh.
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
  ose bashkohen; statusi i tyre lexohet nga taskat e Note-s PX (`ga_note_origin_id`).
  Ngjyrat e statusit duhet të mbeten të njëjta me PX Notes. Regjistrimi i lidhur
  me takim krijon shënim takimi edhe kur konfirmohet detyra nga propozimi AI.
- Shtyrja, mbyllja, strike-et dhe ndryshimet e afateve mund të ndikojnë te
  Realization, bazat e planit, numërimet dhe raportet, përveç paraqitjes së taskut.
- Kopjet historike/snapshot-et nuk krahasohen si të dhëna live. SHTYPI Today
  ka kopje të ngrirë në 16:00; ruaj historikun dhe dallimin para/pas cutoff-it.
- Notes nga Mira kanë rregulla të veçanta dukshmërie në raporte. Mos supozo se
  çdo Note duhet të dalë në çdo raport; dallo regjistrimin nga tasku i krijuar.
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
  gjeneruesit e raporteve. Afati pyetet vetëm kur mungon; përgjigjja e shkurtër
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

## Pikat kryesore në kod

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
