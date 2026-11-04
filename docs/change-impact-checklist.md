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
| Mira Host / takimet 1H | Mira (nisje/ndalim/status), Discord 1H (hyrja, prania, radha, audioja), PX Notes, Common View, 1H SHTYPI Today, 1H Reports (Done dhe strike), Task Details |
| Raporte / email / eksporte | Reports, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, PX JAV Kontrolli, Weekly Planning Check, Kontrolli ditor RLZ, Print Preview, Print, Email, Exports, History |
| Përdorues dhe përgjegjës | Users, My View, Department Views, Finance View, Projects, PX Notes, PX JAV, Common View, Weekly Planner, Monthly Planner, Meeting Scheduler, Reports |
| GA PERSONAL - grupet dhe filtrat | Pamja ditore dhe javore e GA PERSONAL, filtri i grupeve dhe etiketat e tabelave; klasifikimi i eventeve ndahet përmes `frontend/src/lib/ga-personal-week.ts`, përfshirë eventet e vjetra të volejbollit. Të dhënat e modulit mbeten të ndara nga detyrat dhe raportet e kompanisë. |

## Varësi që nuk duhen harruar

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
- Shtyrja, mbyllja, strike-et dhe ndryshimet e afateve mund të ndikojnë te
  Realization, bazat e planit, numërimet dhe raportet, përveç paraqitjes së taskut.
- Kopjet historike/snapshot-et nuk krahasohen si të dhëna live. SHTYPI Today
  ka kopje të ngrirë në 16:00; ruaj historikun dhe dallimin para/pas cutoff-it.
- Notes nga Mira kanë rregulla të veçanta dukshmërie në raporte. Mos supozo se
  çdo Note duhet të dalë në çdo raport; dallo regjistrimin nga tasku i krijuar.
- Mira Host lexon Done/strike përmes filtrimit dhe snapshot-it të përbashkët me
  1H Reports; ndryshimet te këta ndihmës kontrollohen edhe te raportet/SHTYPI.
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
| Projektet | <code>backend/app/api/routers/projects.py</code>, <code>frontend/src/app/(app)/projects/[id]/page.tsx</code>, <code>frontend/src/app/(app)/projects/{dev,pcm,design}/[id]/page.tsx</code> |
| M1 / M2 / M3 | <code>backend/app/services/morning_report.py</code>, <code>backend/app/services/after_break_report.py</code>, <code>backend/app/services/meetings_report.py</code> dhe faqet përkatëse në frontend |
| PIKAT PËR RAP | <code>backend/app/services/m1_reporting_points.py</code>, <code>backend/app/services/m2_reporting_points.py</code>, <code>backend/app/services/m3_reporting_points.py</code>, <code>frontend/src/components/m*-reporting-points-view.tsx</code> |
| Planifikimi dhe realizimi | <code>backend/app/api/routers/planners.py</code>, <code>backend/app/services/daily_report_logic.py</code>, <code>backend/app/services/daily_realization_live.py</code>, <code>frontend/src/app/(app)/weekly-planner/page.tsx</code>, <code>frontend/src/app/(app)/realization/</code> |
| Eksportet dhe dukshmëria e Notes | <code>backend/app/api/routers/exports.py</code>, gjeneruesi përkatës i raportit, <code>backend/app/services/report_note_visibility.py</code> |

Shtigjet me <code>{...}</code> ose <code>*</code> janë grupe skedarësh; zgjidh implementimin konkret
që prek ndryshimi. Mos u mbështet vetëm në këtë inventar nëse kodi ka ndryshuar.
