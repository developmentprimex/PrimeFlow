# Mira Host — auditimi pas push-it, 03.11.2026

Kodi i kontrolluar: `7e3f106df120d0597a9a619efa16a4686740d267` në `main`.

U konfirmuan katër mangësi me skenarë sintetikë që thërrasin kontrolluesin dhe shërbimet aktuale. Në fazën e auditimit nuk u ndryshua kodi i aplikacionit. Pas kërkesës për rregullim u zbatuan ndryshimet lokale të shënuara në fund të raportit. Nuk u bë push dhe nuk u përdor databaza, Discord-i ose OpenAI në prodhim. Gjetjet përshkruajnë sjelljen e kodit para rregullimeve; nuk pretendojnë se këto raste kanë ndodhur në një takim real.

## 1. P1 — Rikthimi pas shkëputjes mund ta humbë stafin e mbetur

**Skenari:** Një person është ACTIVE, tjetri WAITING. Lidhja ndërpritet dhe takimi mbyllet me `interrupted:voice_disconnected`. Planifikuesi ose përdoruesi e nis përsëri të njëjtin slot.

**Shkaku:** `finish_meeting` i kthen radhët ACTIVE/WAITING/DEFERRED në SKIPPED. `start_meeting` e lejon riprovimin për gabimet e ndërprerjes dhe e kthen takimin në GA_PHASE. `begin_staff` sheh ID-të ekzistuese të personave dhe nuk krijon radhë të reja për ta, por as nuk i rikthen radhët SKIPPED në pritje. `next_turn` përzgjedh vetëm WAITING dhe DEFERRED të pranishëm.

**Prova e riprodhuar:** Riprovimi i dytë u lejua; të dy personat mbetën SKIPPED; nuk u krijua asnjë radhë zëvendësuese dhe `current` doli null. Kontrolluesi mund ta interpretojë këtë si përfundim të raportimit, megjithëse personat nuk raportuan.

**Ndikimi:** Humbja e lidhjes mund të shkaktojë humbje të vazhdimit të takimit, edhe kur bot-i lidhet përsëri me sukses.

**Rregullimi i rekomanduar:** Ruaj dallimin mes personave që përfunduan dhe radhëve të ndërprera. Në rikthim, rindërto pritjen vetëm për radhët e papërfunduara dhe ruaj faktet që u raportuan tashmë. Rishikimi PM ka nevojë për të njëjtin kontroll, sepse edhe `finish_pm` i kalon personat e papërfunduar në SKIPPED.

Burimet: `backend/app/services/mira_host.py:581`, `:632`, `:660`, `:782`; `backend/app/services/mira_host_runtime.py:89`.

## 2. P1 — Dështimi i nisjes PM mund ta lërë Mirën pa hap vijues

**Skenari:** Në 11:50 përfundon stafi dhe duhet të nisë rishikimi PM. Kërkesa `/pm/next` dështon; leximi i rikuperimit `/pm/current` konfirmon `initialized=false`.

**Shkaku:** `present_turn` vendos `pm_reviewed=true` përpara se `_advance_pm` ta konfirmojë nisjen. Pas dështimit, `pm_current` dhe `current_turn` janë bosh. `watch_turn` nuk ka person aktiv, kohë fillimi ose persona të shtyrë për të kontrolluar dhe nuk provon sërish inicializimin PM. `end_person_turn` kërkon një turn_id aktiv, që ende nuk ekziston.

**Prova e riprodhuar:** Gjendja mbeti `pm_reviewed=true`, `pm_current=null`; kontrolluesi i radhës nuk bëri asnjë kërkesë të re; përsëritja e `end_person_turn` u refuzua si radhë e ndryshuar.

**Ndikimi:** Mira mund të mbetet pa vazhdim deri te kufiri i takimit. Shënimi i fazës si e nisur përpara konfirmimit rrezikon edhe mbyllje të parakohshme në rrugët e riprovimit të fillimit të stafit.

**Rregullimi i rekomanduar:** Ndaj gjendjen “PM po inicializohet” nga “PM u konfirmua”. Shto rikuperim të kufizuar që mund të nisë PM pa turn_id kur serveri konfirmon se inicializimi nuk u krye. Mos përsërit një kalim nëse serveri ka tashmë person aktiv.

Burimet: `backend/mira_host.py:710`, `:748`, `:541`; `backend/app/services/mira_host_runtime.py:98`.

## 3. P2 — Personat me vetëm BLL nuk hyjnë në radhën e 16:00

**Skenari:** Një person ka detyrë të bllokuar, por asnjë detyrë 1H të vendosur në slotin 16:00.

**Shkaku:** `person_brief` i përfshin detyrat BLL në 16:00, por `participants` e ndërton radhën vetëm nga detyrat 1H të atij sloti. Përgjegjësi që ka vetëm BLL nuk arrin te brief-i i vet.

**Prova e riprodhuar:** Brief-i i personit kishte një detyrë BLL, ndërsa personi mungonte nga `participants('16:00')`.

**Ndikimi:** Mbulesa e BLL në takimin e fundit është e pjesshme: varen nga fakti nëse përgjegjësi ka edhe detyrë 1H në 16:00.

**Rregullimi i rekomanduar:** Nëse BLL duhet të trajtohet për të gjithë përgjegjësit në këtë takim, bashko përgjegjësit e BLL me radhën 16:00, duke ruajtur rendin, përjashtimet dhe shmangien e dublimit. Alternativisht cakto një fazë të veçantë për BLL. Kjo pjesë ka nevojë për vendimin e rrjedhës përpara implementimit.

Burimet: `backend/app/services/mira_host.py:214`, `:272`, `:360`, `:632`.

## 4. P2 — Upload-i gjatë stafit vonon kontrollin e kohës dhe pranisë

**Skenari:** Gjatë raportimit të stafit, kërkesa që ruan transkriptin vonohet.

**Shkaku:** Cikli kryesor kryen `watch_turn`, pret pesë sekonda dhe pastaj pret drejtpërdrejt `flush_lines`. Kontrolli vijues i mungesave, paralajmërimi i kohës dhe timeout-i nuk ekzekutohen derisa upload-i të kthehet. Upload-i në sfond i përdorur gjatë pritjes së orës zyrtare nuk zbatohet në këtë cikël.

**Prova e riprodhuar:** Në një ekzekutim të simuluar të `run`, upload-i u mbajt në pritje ndërsa ora u avancua 120 sekonda. Numri i kontrolleve të radhës mbeti një; kontrolli i dytë u krye vetëm pas lirimit të upload-it.

**Ndikimi:** Mira mund ta japë vonë paralajmërimin e fundit, ta tejkalojë kohën e personit ose ta vërejë me vonesë largimin nga kanali. Audioja dhe mjetet mund të vazhdojnë veçmas; problemi është te kontrolluesi periodik i kohës/pranisë.

**Rregullimi i rekomanduar:** Kryej upload-et në një punë të vetme në sfond edhe gjatë stafit, me kufi kohe dhe ruajtjen ekzistuese të të dhënave për rikuperim. Kontrolli i radhës duhet të ketë ritëm të pavarur nga transkriptet.

Burimet: `backend/mira_host.py:470`, `:541`, `:998`.

## Provat dhe përparësia

Riprodhuesi lokal: `tmp/mira-host-audit-round-3.py`. Ai përdor payload-e sintetike, një DB të simuluar dhe një bridge të simuluar. Katër kontrollet konfirmuan gjendjet problematike të përshkruara më sipër. Asnjë thirrje reale drejt databazës ose shërbimeve zanore nuk u krye.

Rendi i rekomanduar për rregullime: **rikthimi pas shkëputjes → inicializimi PM → kontrolluesi i kohës/pranisë → mbulimi BLL sipas rrjedhës së miratuar**.

Testet e mëparshme të kaluara mbulojnë shumë rrugë të zakonshme dhe rikuperime brenda një kalimi; këto prova shtojnë skenarët përtej mbylljes/rinisjes dhe inicializimin e pasuksesshëm të fazës tjetër.

## Statusi pas zbatimit lokal

Të katër mangësitë u rregulluan pas kërkesës së përdoruesit:

- `begin_staff` rikthen në WAITING radhët SKIPPED të personave që ende duhet të raportojnë kur i njëjti takim riniset. DONE/TIMEOUT, personat e përjashtuar dhe mungesat e plota nuk rikthehen. ID-të e radhëve, shënimet dhe faktet e diskutimit ruhen. Rishikimi PM ruan numrin e tentativës dhe i rikthen radhët e papërfunduara vetëm një herë për rilidhjen e re.
- Kontrolluesi përdor `pm_pending` për inicializimin e pakonfirmuar; `pm_reviewed` vendoset pas përgjigjes së konfirmuar. Kontrolli periodik e riprovon nisjen nën bllokimin e kalimit të radhës. Një person PM që është aktiv tashmë në server adoptohet pa u përfunduar; një gjendje pa person aktiv, por me WAITING, nuk interpretohet si përfundim.
- Radha e 16:00 bashkon personat me detyra 1H dhe përgjegjësit që kanë vetëm BLL të hapura, pa dublime. Përjashtimet për GA/KA, Haxheren dhe mungesat e plota vazhdojnë të zbatohen. Njoftimi paraprak përfshin BLL dhe hyrja zanore nis nga grupi i parë me detyrë të hapur, përfshirë BLLOK.
- Upload-i përdor të njëjtën punë të vetme në sfond edhe gjatë stafit. Kërkesa ka kufi kohe; anulimi i një batch-i i rikthen rreshtat/metrikat e padërguara në pritje dhe ruan konfirmimet për riprovim. Një batch i konfirmuar më parë nuk rikthehet gabimisht në listën e padërguar.

U shtuan **11 teste** në `backend/tests/test_mira_host_recovery.py`, përfshirë rrugën ndalim → rinisje → staf, rikthimin PM, dy tentativa PM të njëkohshme, përgjegjësit me vetëm BLL, upload-in e bllokuar gjatë ciklit real të stafit dhe anulimin pas një batch-i të suksesshëm.

Verifikimi i gjerë dha **394 teste backend të kaluara, 2 dështime dhe 15 të anashkaluara**, me 77 nënraste shtesë të kaluara. Dy dështimet ishin testet e Kujtesës me afate 20–40 milisekonda (`test_hard_deadline_cancels_a_stalled_context_refresh` dhe `test_refresh_denial_and_timeout_close_worker`); të dy kaluan kur u ekzekutuan veçmas, pa ndryshim kodi. Kështu të gjitha **396 testet e përzgjedhura** kaluan gjatë verifikimit, duke shënuar paqëndrueshmërinë e atyre dy testeve në ekzekutimin e përbashkët. **99 teste audio/Discord kaluan**. 15 testet Desktop/PostgreSQL mbetën të anashkaluara sepse nuk është konfiguruar databaza lokale e dedikuar.

U kontrollua edhe përputhshmëria e statuseve ekzistuese me paraqitjen e Mira Meetings në frontend, pa ndryshime UI. Kontrollet e raportit 1H, SHTYPI dhe PX Notes u përfshinë në grupin e testeve; këta gjenerues nuk u ndryshuan në këtë rregullim. `git diff HEAD --check` kaloi dhe nuk ka konflikte merge.

Nuk nevojitet migrim databaze. Mbetet prova në një takim real për sjelljen zanore dhe kushtet reale të rrjetit. Ndryshimet janë lokale, pa commit ose push.
