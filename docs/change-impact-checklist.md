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
| WFC / Waiting Client | WFC, My View, Department Views, Finance View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, PX Notes, PX JAV, Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Planifikim | Weekly Planner, Monthly Planner, PX JAV, My View, Common View, 1H SHTYPI Today, 1H SHTYPI Tomorrow, Realization, Weekly Planning Check, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT |
| Realization dhe Reviews | My View, Department Views, Finance View, Realization, Reviews, Common View, Weekly Planner, Kontrolli ditor RLZ, M3 PIKAT |
| Regjistrime dhe Mira | Regjistrimet, Mira, Meetings, PX Notes, Task Details |
| Mira AI Agent / hyrja automatike | Discord AI Agent (orari, prania, regjistrimi), mira-kontrolli (paneli AI Agent), Mira / shënimet, PX Notes (shikimi dhe ruajtja). Orari dhe request_id `autoai-` janë të veçantë nga regjistruesi 1H (`auto1h-`) dhe Mira Host. Finalizuesi i përbashkët ruan automatikisht shënimet e `auto1h-` dhe të `autoai-` me recorder `ai_agent`; nisjet manuale mbeten me ruajtje manuale. Kontrollo deduplikimin, lidhjen me transkriptin, statusin Ruajtur dhe kthimin te ruajtja manuale pas dështimit. |
| Takimet (shënimet e takimeve) | Takimet, Takimi (seancat), Historia e klientit, Regjistrimet (Shënim / Injoro / screenshot), PX Notes (Dërgo / Bashko në PX), Meeting Scheduler (Trajnim), Sidebar |
| Mira Host / takimet 1H | Mira (nisje/ndalim/status), Discord 1H (hyrja, prania, radha, audioja), PX Notes, Common View, 1H SHTYPI Today, 1H Reports (Done dhe strike), Task Details |
| Raporte / email / eksporte | Reports, 1H SHTYPI Today, 1H SHTYPI Tomorrow, 1H Reports, M1 / M2 / M3, M1 PIKAT, M2 PIKAT, M3 PIKAT, PX JAV Kontrolli, Weekly Planning Check, Kontrolli ditor RLZ, Print Preview, Print, Email, Exports, History |
| Përdorues dhe përgjegjës | Users, My View, Department Views, Finance View, Projects, PX Notes, PX JAV, Common View, Weekly Planner, Monthly Planner, Meeting Scheduler, Reports |
| GA PERSONAL - grupet dhe filtrat | Pamja ditore dhe javore e GA PERSONAL, filtri i grupeve dhe etiketat e tabelave; klasifikimi i eventeve ndahet përmes `frontend/src/lib/ga-personal-week.ts`, përfshirë eventet e vjetra të volejbollit. Të dhënat e modulit mbeten të ndara nga detyrat dhe raportet e kompanisë. |

## Varësi që nuk duhen harruar

- Butoni i zgjerimit të titullit (`CollapsibleTaskTitle`) rreshtohet në skajin
  e kolonës për My View te Development, Graphic Design dhe Product Content
  (Waiting Confirmation, Project Tasks, Fast Tasks, System Tasks), si dhe te
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
  Snapshot-et aktuale të SHTYPI kanë `attendance_filter_version=2`; kopjet e
  vjetra aktualizohen para mbylljes. Arkivat e ngrira në 16:00 dhe skedarët e
  dërguar më parë mbeten dokumente historike dhe nuk rishkruhen me të dhëna të reja.

- Hyrja automatike e Mira AI Agent dërgon `request_id=autoai-YYYYMMDDHHMM`
  (tentativat pasuese shtojnë `-2` / `-3`). Skema `VoiceStart` te
  `backend/app/schemas/discord_voice_meeting.py` duhet t'i pranojë bashkë me
  `auto1h-` dhe ID-të numerike të nisjeve manuale; përndryshe API-ja e refuzon
  nisjen para krijimit të sesionit. Kontrollo endpoint-in `/voice-meetings/start`
  në të dy API-të aktive, panelin mira-kontrolli dhe ruajtjen te Mira/PX Notes.
  Testet me skema të izoluara të shënimeve duhet të krijojnë edhe `MeetingNote`,
  sepse leximi i `GaNote` ngarkon flamurin `from_meeting` përmes `meeting_notes`.

- Taskat e krijuara drejtpërdrejt nga Regjistrimet krijojnë PX Note me
  `knowledge_type=RECORDING` dhe lidhjen `ga_note_origin_id`. PX Notes shfaq
  etiketën `REC` pranë etiketave të tjera; printimi klonon të njëjtën tabelë
  dhe e përfshin etiketën. Kjo vlerë nuk është kategori Knowledge PX.
  Shënimet e dërguara nga Takimet identifikohen nga lidhja ekzistuese
  `MeetingNote.ga_note_id` dhe API-ja kthen `from_meeting=true` për
  etiketën `TAK`, edhe për shënimet e vjetra dhe të bashkuara. `RECORDING`
  ka përparësi kur ekziston; etiketat nuk ndryshojnë të dhënat e ruajtura.

- Development, Graphic Design dhe Product Content përdorin
  `CollapsibleTaskTitle` për titujt në listat All (Waiting Confirmation,
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
  ose bashkohen; statusi i tyre lexohet nga taskat e Note-s PX (`ga_note_origin_id`).
  Ngjyrat e statusit duhet të mbeten të njëjta me PX Notes. Regjistrimi i lidhur
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

`.github/workflows/deploy.yml` përdor `frontend/scripts/wait-for-readiness.ps1`
për kandidatin, rikthimin e versionit të mëparshëm dhe kontrollin përfundimtar.
Ndryshimet e këtij kontrolli ndikojnë pranimin ose rollback-un e gjithë build-it,
përfshirë Common View, Department Views, Finance dhe faqet e raporteve; nuk
ndryshojnë renderuesit ose të dhënat e tyre. Kontrollo përgjigjen e vonuar,
gabimet HTTP dhe refuzimin e një faqeje HTTP 200 me commit të vjetër. Vetëm pas
kontrollit të commit-it të ri përditësohet shënuesi `frontend.sha`. Prova lokale
e kontrollit nuk zëvendëson verifikimin e deployment-it real në server.

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
