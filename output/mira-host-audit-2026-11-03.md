# Analizë e Host-Mira — 03.11.2026

Analizuar commit-i `fa255a222a16abf253f34002035ce432da505686`. Analiza përfshin prompt-in, shërbimin Python, kontrolluesin e Discord, worker-in Realtime, audion, API-n, cilësimet në faqe dhe testet përkatëse. Nuk u ndryshua kodi i aplikacionit, nuk u nis takim real dhe nuk u thirr modeli me pagesë. Nuk u lexuan transkripte private ose të dhëna nga databaza e prodhimit.

Përfundimi: Host-Mira ka një bazë funksionale dhe mbrojtje të dobishme, por vazhdimi i bisedës, ndërprerjet dhe disa kalime ende kanë boshllëqe. Përmirësimi me ndikimin më të madh është kontrolli më i qartë i rrjedhës nga aplikacioni, i shoqëruar me prompt më të përqendruar për fazën aktuale.

## Çfarë u verifikua

- 148 teste backend për Mira Host: kaluan.
- 80 teste të paketës së audios/Discord: kaluan. Kjo paketë përfshin edhe regjistruesin e heshtur; rezultatet e tij nuk provojnë automatikisht të njëjtën sjellje te host-worker.
- Prova shtesë sintetike riprodhuan problemet e audios dhe rrjedhës të përshkruara më poshtë.
- Provat gjenden te `tmp/mira-host-audit-2026-11-03.mjs` dhe `tmp/mira_host_audit_2026_11_03.py`.
- Kalimi i testeve ekzistuese nuk provon cilësinë e shqiptimit, transkriptimit ose ritmit në një takim real.

## Gjetjet me përparësi të lartë

### 1. Butoni “Ndalo” në faqe nuk e ndal takimin aktiv

**E konfirmuar në kod dhe në provë sintetike.** Faqja dërgon `enabled=false`; API ndryshon vetëm `enabled_until`. Kontrolluesi merr një tick me `enabled=false`, por nuk e mbyll sesionin aktiv. Komanda `/mira ndalo` kryen edhe një veprim shtesë `bot.mira_host.stop(...)`, prandaj dy rrugët nuk janë të barabarta.

Prova: pas një tick-u të çaktivizuar, sesioni mbeti aktiv dhe `closed=false`.

Ndikimi: përdoruesi sheh “Mira u ndal”, por Mira mund të vazhdojë takimin. Ndryshimi i orarit dhe ndalimi i takimit aktiv duhet të kenë sjellje të përcaktuar qartë.

Zgjidhja: kërkesë e ruajtur për ndalimin e sesionit aktiv, e konsumuar nga kontrolluesi, me konfirmim kur procesi zanor është mbyllur. Nëse synimi i një veprimi është vetëm çaktivizimi i takimeve të ardhshme, etiketa duhet ta thotë këtë.

Burime: `frontend/src/components/mira/settings-tab.tsx:69`, `backend/app/api/routers/mira.py:121`, `backend/mira_host.py:306`, `backend/mira_host.py:990`.

### 2. Një ndryshim i vogël në lexim mund ta lërë Mirën në heshtje

**E riprodhuar.** Vazhdimi pas notes kërkon që transkripti i përgjigjes të përmbajë tekstin e pritur pothuajse fjalë për fjalë, pas normalizimit. “Shënimi 1” dhe “Shënimi i parë” nuk përputhen. Në këtë rast delivery fshihet, por nuk mbetet detyrim për vazhdim dhe nuk aktivizohet rikuperimi.

Prova: pas leximit me “Shënimi i parë”, numri i kërkesave të përgjigjes mbeti 1 edhe pas 20 sekondash. Nuk u krijua vazhdimi pas leximit.

Ndikimi: edhe pas heqjes së pyetjeve për aprovim, mund të mbetet një pauzë e pashpjeguar. I njëjti mekanizëm përdoret për konfirmimin e leximit të progresit; atje mungesa e konfirmimit ruan të dhënat si të palexuara, por nuk siguron vetë një rrugë rikuperimi të plotë.

Zgjidhja: të ndahen përfundimi i audios, mbulimi i përmbajtjes dhe vendimi për vazhdim. Për notes lejohet vazhdim i kontrolluar pas përmendjes; për Done/Strike të përdoren pjesë të vogla me identifikues dhe konfirmime të veçanta. Leximi i pasaktë duhet të ketë rikuperim me kufi ose shtyrje të shënuar, jo heshtje pa afat. Nuk duhet të shënohet si i dëgjuar progres që nuk u komunikua.

Burime: `backend/discord-voice/host-worker.mjs:73`, `backend/discord-voice/host-worker.mjs:80`, `backend/discord-voice/host-worker.mjs:234`.

### 3. Ndërprerja nuk mbulon dy raste të zakonshme

**Të dyja u riprodhuan.**

- Nëse stafi fillon të flasë gjatë mendimit të Mirës, përpara audios së parë, nuk armatoset kontrolli i ndërprerjes. Kur audio mbërrin, Mira mund të flasë mbi personin që tashmë po flet.
- Një “Mira, prit” i shkurtër mund të përfundojë përpara pragut prej 450 ms. Transkripti njihet si kërkesë për pritje, por audio që po luhet nuk ndalet nga ky kontroll.

Provat: në të dy rastet numri i anulimeve ishte 0 dhe audio mbeti në radhë.

Zgjidhja: të kontrollohet fjala aktive edhe kur mbërrin audio e parë; kërkesat e qarta “prit/ndalu” të trajtohen posaçërisht, duke ruajtur tolerancën ndaj “aha/po”. Pragu kohor i vetëm nuk dallon qëllimin e fjalës.

Burime: `backend/discord-voice/host-worker.mjs:183`, `backend/discord-voice/host-worker.mjs:191`, `backend/discord-voice/host-worker.mjs:203`, `backend/discord-voice/host-worker.mjs:234`.

### 4. Dështimi i vazhdueshëm i dekodimit të zërit mund të kalojë pa sinjal

**E riprodhuar.** Host-worker i kap gabimet e dekodimit dhe i anashkalon pa numërues, alarm ose rikrijim të dekoderit. Prova me 500 paketa të dështuara nuk prodhoi asnjë ngjarje gabimi ose ndërprerjeje.

Ndikimi: Mira mund të duket e lidhur, ndërsa nuk merr zërin e një pjesëmarrësi. Afati i personit mund të përfundojë pa u dalluar problemi teknik nga mungesa e raportimit.

Zgjidhja: matje për çdo folës të paketave të marra/dekoduara, tolerancë ndaj dështimeve kalimtare, rikrijim i kufizuar i dekoderit dhe njoftim i kontrolluesit kur problemi vazhdon. Afati i raportimit nuk duhet ta trajtojë automatikisht dështimin teknik si mungesë përgjigjeje.

Burim: `backend/discord-voice/host-worker.mjs:351`.

## Gjetjet e tjera funksionale

### 5. “Notes të reja” aktualisht janë 40 notes më të vjetra ende të hapura

**E konfirmuar në query.** `open_notes` nuk përdor datën e leximit, gjendje “e përmendur” ose një kufi kohor të risisë. Rendit sipas krijimit, nga më e vjetra, dhe merr 40.

Pasojat: notes mund të përsëriten në çdo takim; nëse 40 të vjetrat mbeten të hapura, note-i i 41-të nuk hyn në rezultat. Edhe notes që njerëzit i kanë shënuar si të diskutuara nuk filtrohen nga kjo query.

Shkurtimi i secilit note nuk vendos buxhet për të gjithë hyrjen. Prova me 40 notes dha 1 000 fjalë. Me një supozim ilustrues prej 150 fjalësh/minutë, kjo është rreth 6.7 minuta; kjo shifër nuk është matje e zërit real të Mirës.

Zgjidhja: të regjistrohen përmendjet e notes veçmas nga gjendja e vetë note-it; të zgjidhen ato të reja ose ende të pakomunikuara, me ndarje në pjesë dhe buxhet të përgjithshëm, p.sh. 20–30 sekonda si objektiv fillestar për testim. Të tregohet kur ka të tjera. Test mode nuk duhet t’i konsumojë përmendjet reale. Kthimi në detyra mbetet punë e stafit.

Burime: `backend/app/services/mira_host.py:974`, `backend/app/services/mira_host.py:1264`.

### 6. Playback mund t’ia atribuojë audion e luajtur item-it të gabuar

**E riprodhuar në komponent.** Radha mban frame audio pa identitetin e item-it, ndërsa ruhet vetëm item-i më i fundit. Nëse shtohet audio B përpara zbrazjes së audios A, koha e luajtur për frame-t e A numërohet ndaj B.

Prova: u luajt një frame i A, por `clear()` ktheu B me `playedMs=20`. Në një ndërprerje, kjo mund të çojë te truncation me item dhe kohë të pasaktë. Shpeshtësia reale varet nga mbivendosja e përgjigjeve dhe rrjedha e ngjarjeve; nuk u mat në prodhim.

Zgjidhja: frame-t të kenë `item_id` dhe pozicionin brenda atij item-i; ndërprerja të përdorë item-in që po luhet. Të kontrollohet edhe gjenerimi i përgjigjes tjetër gjatë audios ende të paluajtur.

Burim: `backend/discord-voice/host-audio.mjs:134`.

### 7. Detyra të ndryshme mund të bashkohen nga titulli gjatë njoftimit të progresit

**E riprodhuar.** Bashkimi i Done/Strike përdor tekstin e titullit të folur. Dy detyra me ID të ndryshme dhe titull “OFERTA”, për klientë të ndryshëm, dhanë një njoftim, ndërsa të dy ID-të u përfshinë për shënim si të komunikuara.

Zgjidhja: identiteti i detyrës ose një lidhje e shprehur e grupit të përbashkët të drejtojë bashkimin. Titulli i njëjtë nuk mjafton. Për tituj të përsëritur, të shtohet një dallues i shkurtër si projekti/klienti.

Burime: `backend/app/services/mira_host.py:930`, `backend/app/services/mira_host.py:934`.

### 8. Mira nuk merr disa detaje të detyrës në kontekstin normal të radhës

**E riprodhuar.** `task_line` përmban përshkrimin dhe komentin e simbolit, por `turn_brief` dhe `task_lines` nuk i përfshijnë në dorëzimin normal të radhës. Në provë, as udhëzimi në përshkrim dhe as komenti i simbolit nuk arritën te konteksti zanor.

Ndikimi: Mira mund të pyesë në mënyrë të përgjithshme për “OFERTA”, pa ditur që komenti thotë “prit përgjigjen e furnitorit”. `get_person_brief` mund t’i kthejë detajet, por prompt-i dekurajon kërkimet kur mendon se të dhënat tashmë janë dhënë.

Zgjidhja: të përfshihen detajet e rëndësishme me kufi gjatësie në `plan_discutimi`; të jepet gjendja “detajet mungojnë” kur nevojitet kërkim. Detyrat me tituj të ngjashëm të dallohen qartë.

Burime: `backend/app/services/mira_host.py:290`, `backend/mira_host.py:49`, `backend/mira_host.py:65`.

### 9. Fazat nuk kanë të njëjtin nivel kontrolli

**E konfirmuar në kod dhe provë.** `end_ga_phase` mund të nisë stafin pa kontrolluar nëse notes u morën ose progresi u lexua. Prova e thirri pa këto hapa dhe mori kalimin te stafi. Kjo provon mungesën e kontrollit, jo se modeli e anashkalon fazën në çdo takim.

Rishikimi PM dërgon një listë globale dhe përfundon me një `end_person_turn` për gjithë rishikimin; nuk ka radhë të ruajtur PM për çdo person ose afat të veçantë si në pjesën kryesore. Kur të gjithë të mbeturit mungojnë, kontrolluesi pret vetëm 5 sekonda përpara se të fillojë mbylljen, edhe pse sapo mund të ketë dërguar ftesa.

Zgjidhja: nënfaza të shprehura GA → notes → progres → staf; secila përfundon si e kryer, bosh ose e shtyrë për arsye teknike. Të mos bllokohet takimi përgjithmonë për një lookup të dështuar. PM të ketë radhë/person/gjendje. Pritja për të ftuarit e munguar të jetë e përcaktuar dhe e konfigurueshme, pa vonuar personat që janë të pranishëm.

Burime: `backend/mira_host.py:734`, `backend/mira_host.py:472`, `backend/mira_host.py:616`.

### 10. Koha e transkriptit është koha e mbërritjes, jo koha e të folurit

**Rrezik i konfirmuar nga rrjedha e të dhënave; ndikimi në përmbledhje kërkon replay.** Ngjarja e transkriptit nga worker-i nuk dërgon kufijtë kohorë të fjalës. Kontrolluesi vendos orën e marrjes së saj. Më pas `lines_during` ndan bisedën sipas orës së fillimit/fundit të radhës.

Nëse transkriptimi i fjalës së fundit të një personi mbërrin pas kalimit te tjetri, ai mund të futet në segmentin e radhës tjetër. Emri i folësit mund të mbetet i saktë, por materiali i përzgjedhur për shënimet e personit është i gabuar.

Gjithashtu përmbledhja mbështetet kryesisht te transkripti; faktet e strukturuara `DISCUSSION` dhe vendimet `NOTE` nuk futen shprehimisht si fakte të veçanta në input-in e saj. Kjo ul përdorimin e të dhënave që aplikacioni tashmë i ka ruajtur.

Zgjidhja: ruajtje e `speech_id`, `started_at`, `ended_at` dhe lidhjes me radhën; përdorim i këtyre për përmbledhjen. Faktet e ruajtura dhe transkripti të jepen me burime të dallueshme. Radhët me timeout të ruajnë edhe raportimin e pjesshëm.

Burime: `backend/discord-voice/host-worker.mjs:203`, `backend/mira_host.py:661`, `backend/app/services/mira_host.py:730`, `backend/app/services/mira_host.py:773`.

### 11. Ftesat nuk kanë mekanizëm të plotë për ridërgim pas dështimit

**E konfirmuar në kod.** Tick-u shënon event-in si të marrë përpara se kontrolluesi ta dërgojë në Discord. Nëse dërgimi dështon, kontrolluesi e regjistron gabimin, por eventi unik nuk rimarret nga tick-u i ardhshëm.

Zgjidhja: radhë njoftimesh me status në pritje/dërguar/dështuar, numër tentimesh dhe afat skadimi sipas slotit. Ridërgim me kufi dhe pa dublikim pas suksesit.

Burime: `backend/app/services/mira_host.py:442`, `backend/app/services/mira_host.py:450`, `backend/mira_host.py:306`.

## Vlerësimi i prompt-it

Prompt-i ka udhëzime të mira për shqipen, shmangien e lavdërimeve, mosshpikjen e progresit, një pyetje për herë, dallimin e të dhënave nga udhëzimet dhe mosndryshimin e statusit/datës së detyrës. Heqja e krijimit të detyrave nga notes është e shprehur qartë dhe mjetet për këtë nuk ekspozohen në fazën GA.

Pikat që do të përmirësoja:

1. **Prompt sipas fazës.** Sot dërgohen rregullat e të gjitha fazave që në fillim; në kalim ndryshojnë mjetet, por jo udhëzimet për fazën. Duhet një bërthamë e përhershme për gjuhën dhe sjelljen, plus rregullat e fazës aktuale. OpenAI Docs këshillon përputhjen e prompt-it me mjetet e disponueshme dhe nisjen nga udhëzime minimale të testuara.
2. **Përparësi e qartë për protokollin.** Protokolli parazgjedhje ka pikën “BZ Det nga Stafi për GA”, ndërsa rregullat e stafit thonë të mos pyesë për detyra GA/BZ. Kjo është paqartësi për t’u pastruar, jo provë që modeli gjithmonë pyet gabim. Protokolli i personalizuar duhet të ketë kufij të qartë kundrejt rrjedhës së kontrolluar.
3. **Pritje me dalje të përcaktuar.** “Prit” duhet të përfundojë me “vazhdo”, me kthimin e personit ose me afat të qartë. Heshtja për zhurmë, kërkesa njerëzore për pritje dhe pritja e një shërbimi duhen trajtuar si gjendje të ndryshme.
4. **Ndërprerje sipas materialit.** Rregulli i përgjithshëm thotë të vazhdojë nga pika e mbetur, ndërsa progresi kërkon rilexim. Duhet një cursor për pjesët e komunikuara: vazhdo pjesën e pambuluar; mos rifillo listën pa nevojë.
5. **Pyetja e radhës të mbështetet në gjendje.** Ruaj në kod detyrën aktuale, faktet e sqaruara, çfarë mungon dhe nëse u kërkua tashmë një sqarim. Modeli formulon pyetjen natyrshëm; nuk mban i vetëm shënim të gjithë mbulimit të bisedës. Kjo duhet të ruajë fleksibilitetin që një përgjigje të sqarojë disa pika njëherësh.
6. **Shembuj të shkurtër për rastet e vështira.** Të shtohen raste për korrigjim të raportimit, “jo ajo detyrë”, afat të paqartë, ndërhyrje të GA gjatë radhës së stafit, dy persona njëkohësisht dhe kërkesë për pritje. Një rast i suksesshëm i raportimit nuk mbulon këto sjellje.

Një skelet më i përqendruar i politikës do të ishte:

> Fol shqip, shkurt dhe me një pyetje për herë. Gjendja dhe veprimi i radhës vijnë nga sistemi. Përdor vetëm mjetet e fazës aktuale. Përmend notes e zgjedhura pa pyetje ose kthim në detyra. Për personin aktual pyet vetëm çështjen e hapur që ka dhënë sistemi; përdor të gjitha faktet e përgjigjes së tij pa e bërë të përsërisë. Ruaj vetëm atë që tha folësi i identifikuar. Pas ruajtjes ndiq veprimin e radhës. Në paqartësi kërko një sqarim; nëse ende mungon raportimi, shënoje për pas takimit dhe vazhdo. Për “prit” ndalo audion dhe prit rifillimin e përcaktuar. Në gabim ndiq rikuperimin e mjetit; mos pretendo sukses dhe mos dubliko shkrimin.

Ky është drejtim për prompt-in, jo zëvendësim i gatshëm për deploy. Rregullat specifike të shqiptimit, pranisë dhe test mode duhet të ruhen dhe të verifikohen.

## Çfarë do të ruaja dhe çfarë do të matja

Do të ruaja radhët me ID dhe kontrollin ndaj përfundimit të personit të gabuar, dallimin test/real, kontrollin e folësit për raportime, ruajtjen e transkriptit për rikuperim, mosndryshimin e detyrave dhe mjetin e heshtjes për bisedat anësore.

Nuk ka prova nga kjo analizë që kërkohet ndërrimi i modelit. Fillimisht do të riparoja sjelljet e riprodhuara dhe pastaj do të krahasoja prompt-et me të njëjtat skenarë.

Matjet duhet të përfshijnë kohën deri te audio e dëgjuar, pauzat pa arsye, pyetjet e përsëritura, rastet e paqarta, shëndetin e audios, suksesin e mjeteve dhe mbulimin e agjendës. Aktualisht ka matje për audion e gjeneruar dhe kohën e mjeteve, gjë që është bazë e dobishme.

Të ruhet versioni/hash-i i prompt-it dhe modeli për çdo takim. `PROMPT_VERSION` aktual mbetet `2026-11-02.3` edhe pas ndryshimit të notes të 03.11; statusi aktual nuk jep vetë gjurmën historike të prompt-it të çdo takimi.

Buxheti i Knowledge në prompt kufizohet në 8 000 shenja; faqja e shpjegon këtë. Prandaj nuk e klasifikoj si defekt të fshehur. Megjithatë vlera e konfigurueshme deri në 120 000 mund të thjeshtohet që kuptimi të jetë më i qartë. Kërkimi i Knowledge është leksikor; përmirësimi i tij duhet vlerësuar me pyetje reale ku ai dështon, jo me shtim infrastrukture pa prova.

## Rendi i rekomanduar i punës

1. Riparo ndalimin nga faqja, ngecjen pas leximit dhe dy rastet e ndërprerjes. Shto testet që mungojnë.
2. Riparo detektimin e notes të reja dhe buxhetin e hyrjes, konfirmimet e leximit dhe identitetin e audios.
3. Riparo bashkimin e detyrave, kalimin e detajeve dhe kohët e transkriptit.
4. Vendos nënfazat GA/PM, trajtimin e problemeve të audios dhe ridërgimin e ftesave.
5. Testo prompt-in e përqendruar dhe ruaj versionin/rezultatet për krahasim.

Skenarët e vlerësimit duhet të mbulojnë: zero notes; 1 dhe 40+ notes; notes të përmendura më parë; lexim me numra të shqiptuar ndryshe; lexim të ndërprerë; “aha”; “Mira prit”; fjalë që nis gjatë mendimit; dy folës; folës pa lidhje Discord; raportim që sqaron disa pika; korrigjim raportimi; dy detyra me titull të njëjtë; detyrë që ndryshon gjatë radhës; API timeout; dekodim të dështuar; ardhje me vonesë; PM; ndalim nga faqja dhe Discord; dhe crash me rikuperim të transkriptit.

## Dokumentacioni i përdorur

- [OpenAI Docs — Prompting Realtime models](https://developers.openai.com/api/docs/guides/voice-prompting): udhëzime të përqendruara, përputhje me mjetet dhe trajtim i heshtjes/gabimeve.
- [OpenAI Docs — Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations): te WebSocket aplikacioni menaxhon audion e luajtur dhe truncation gjatë ndërprerjes.

Rekomandimet për këtë aplikacion janë nxjerrë nga kodi dhe provat sintetike. Dokumentacioni mbështet mekanizmat e përgjithshëm; nuk provon shpeshtësinë e problemeve në takimet tuaja reale.

## Zbatimi lokal pas analizës

Rregullimet u implementuan lokalisht pas kërkesës së përdoruesit, pa push ose deploy. Gjetjet më sipër përshkruajnë versionin e audituar; sjellja e re është:

| Pika | Ndryshimi i implementuar |
| --- | --- |
| Ndalimi | Faqja ruan një kërkesë për ndalimin e takimeve aktive. Kontrolluesi e merr në tick-un e ardhshëm dhe mbyll procesin zanor. Faqja tregon “Mira po ndalet…” deri te përfundimi. Një kërkesë e vjetër nuk e ndal një rinisje të mëvonshme. Butoni është i disponueshëm edhe për takim manual aktiv pa orar automatik. |
| Leximi dhe vazhdimi | Leximi ka një tentim rikuperimi; pas dështimit të përsëritur pjesa shtyhet për takim tjetër, pa u shënuar si e komunikuar. Numrat e notes pranohen edhe kur shqiptohen si numra rendorë. Done/Strike kanë pjesë dhe konfirmime të veçanta, ndaj nuk përsëriten pjesët e konfirmuara. |
| Ndërprerjet | Fjala që nis gjatë gjenerimit ndal përgjigjen edhe para audios së parë. “Mira, prit” ndal audion; vazhdimi pret “vazhdo/jam gati” ose ndryshimin e radhës/fazës. “Aha/po” i shkurtër ruan tolerancën ekzistuese. |
| Audio | Frame-t ruajnë item-in e saktë për truncation. Dështimet e vazhdueshme të dekodimit shkaktojnë një tentim rikrijimi dhe sinjal teknik. Buxheti i personit mbahet gjatë këtij problemi; pas 30 sekondash të pazgjidhura ruhet timeout me arsye teknike. |
| Notes | Përzgjidhen notes të hapura, të padiskutuara dhe të pakomunikuara që nga ndryshimi i fundit, nga më të rejat. Hyrja kufizohet në maksimum 5 notes dhe rreth 60 fjalë të titujve/përmendjeve; njoftohet kur ka të tjera. Përmendjet ruhen vetëm pas leximit të konfirmuar dhe nuk ndryshojnë vetë PX Notes. Test mode nuk konsumon përmendjet reale. |
| Identiteti i detyrave | Detyrat e ndryshme nuk bashkohen vetëm nga titulli. Detyra e përbashkët me të njëjtën ID përmendet një herë me pronarët e saj. Kur titujt përsëriten, përdoret edhe përshkrimi i shkurtër kur ekziston. |
| Konteksti i radhës | Përshkrimi, komenti i simbolit, simboli dhe afati kalojnë në planin e diskutimit. Një raportim i qartë i mëvonshëm mund ta korrigjojë gjendjen e mëparshme “unclear”. |
| Fazat | GA kontrollon nëse kërkimet/leximet përfunduan ose u shtynë për arsye teknike. Rezultatet e vonuara GA nuk lexohen pasi ka nisur stafi. PM ka radhë të ruajtur për çdo person, raportim të autorizuar, kontroll të pranisë dhe timeout. Rishikimi PM bëhet edhe kur sloti nuk ka radhë kryesore. |
| Transkripti dhe përmbledhja | Ruhen ID-ja e fjalës, koha e të folurit dhe radha sipas audios së ngarkuar, edhe kur VAD/transkriptimi vonohet. Përmbledhja merr edhe faktet dhe vendimet e strukturuara; radhët me timeout mund të kenë shënime të raportimit të pjesshëm. Konfirmimet e leximit ruhen edhe në skedarin e rikuperimit. |
| Ftesat | Ftesat kanë lease, maksimum 3 tentime dhe konfirmim dërgimi. Një konfirmim i humbur riprovohet pa ridërguar mesazhin brenda të njëjtit proces. Si çdo dërgim te Discord pa çelës të jashtëm idempotence, një crash mes dërgimit dhe konfirmimit ende mund të prodhojë një dublikatë. |
| Prompt-i | U nda sipas fazës dhe ndryshon bashkë me mjetet. U hoq udhëzimi parazgjedhje konfliktues për GA/BZ dhe u shtuan shembuj për korrigjim, afat të paqartë dhe dy folës. Versioni `2026-11-03.1`, modeli dhe hash-et e prompt-eve ruhen për takimin. |

Pritja kur të gjithë personat e mbetur mungojnë është e konfigurueshme me `MIRA_HOST_MISSING_STAFF_GRACE_SECONDS` (parazgjedhje 20, kufij 5–120). Personat e pranishëm vazhdojnë pa këtë pritje. Rregullimet përdorin tabelën ekzistuese të ngjarjeve; nuk kërkohet migrim i databazës.

Verifikimi përfundimtar: **243 teste backend**, **90 teste audio/Discord** dhe **7 teste frontend** kaluan. Kaluan edhe kontrolli TypeScript i frontend-it (`tsc --noEmit --incremental false`), ESLint për skedarët e prekur dhe `git diff --check`. Këto janë testet e përzgjedhura për Host-Mira dhe funksionet e lidhura, jo gjithë suite-a e projektit.

Nuk u nis takim real ose sesion modeli me pagesë. Shqiptimi, cilësia e transkriptimit dhe natyrshmëria e bisedës duhen dëgjuar në një provë zanore pas aktivizimit. Një cursor më i hollësishëm brenda diskutimit të secilës detyrë dhe krahasime të prompt-eve me model real mbeten përmirësime të ardhshme; rrjedha kryesore, mbulimi i detyrave dhe radhët PM tashmë kontrollohen nga aplikacioni.
