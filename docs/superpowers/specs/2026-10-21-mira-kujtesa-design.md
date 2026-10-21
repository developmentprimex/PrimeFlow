# Mira: kujtesa e takimeve (regjistri i gjallë)

Status: dizajn në shqyrtim. Asgjë nuk është ndërtuar ende.

## Qëllimi dhe arsyeja

Sot Mira i nis të gjitha takimet pa ditur asgjë për ato të mëparshmet. Transkriptet
dhe shënimet ruhen në databazë, por Mira nuk i përdor më. Përdoruesi kërkon që Mira
të mbajë mend çka është folur në takimet e kaluara dhe ta përdorë këtë kur shkruan
shënimet e takimit të ri. Shembull: në 1H të orës 14:18 Mira e di çka u tha në 09:58
dhe dje, dhe shkruan p.sh. "Për ofertën e klientit X ishte vendosur dje që ta
përgatisë Arta; sot u tha që ende s'ka përfunduar" ose "Kjo temë u përmend edhe në
3 takimet e fundit pa u zgjidhur."

Shënimet për PX Notes janë për njerëzit dhe mbeten të shkurtra. Kujtesa është gjë
tjetër, e ndarë prej tyre: mund të jetë më e gjatë dhe të mbajë informacione që në
Notes nuk hyjnë, si premtime të vogla, emra klientësh, numra apo tema të prekura
kalimthi. Përdoruesi e zgjodhi qëllimisht këtë ndarje.

## Çka u vendos me përdoruesin

1. **Regjistër i gjallë, jo kujtesë për secilin takim.** Pas çdo takimi Mira
   përditëson një regjistër: shton pikat e reja, shënon si të mbyllura ato që u
   kryen ose u zgjidhën dhe i lë të hapura ato që presin. Çdo pikë mban historikun
   e vet, p.sh. "u përmend më 15.10, 18.10, 21.10". Mira nis çdo takim me gjendjen
   aktuale, jo duke lexuar qindra takime.
2. **Kujtesa nxirret nga transkripti i plotë**, jo nga përmbledhja për Notes.
3. **Një regjistër i vetëm për gjithë stafin.** Përfshin takimet 1H, takimet e
   departamenteve dhe ato të nisura me `/takimi fillo`. Mira e lexon të gjithin në
   çdo takim.
4. **Kujtesa përdoret te shënimet e takimit të ri.** Mira mbetet e heshtur në
   takim. Lidhjet me takimet e kaluara dalin në shënimet që shkojnë në PX Notes dhe
   në kanalin personal të Discord-it.
5. **Faqe në PrimeFlow, "Kujtesa e Mira-s"**, me pamje shumë minimale, të thjeshtë
   dhe të bukur. Ndërtohet me skill-in frontend-design. Përdoruesi zgjodhi pamjen
   B: lista majtas, hollësitë e pikës së zgjedhur djathtas.
6. **Të gjithë e shohin dhe të gjithë e korrigjojnë.** Çdo përdorues aktiv i
   PrimeFlow ka qasje, pavarësisht departamentit. Përdoruesi e vendosi këtë duke
   ditur që regjistri ka përmbajtje nga takimet e të gjitha departamenteve.
7. **Hyjnë të gjitha takimet**, edhe ato të nisura me `/takimi fillo` që
   organizatori nuk i ruajti në PX Notes. Përdoruesi e vendosi këtë duke ditur
   që përmbajtja e tyre bëhet e dukshme për të gjithë stafin përmes regjistrit.
   Përditësimi i regjistrit nuk pret ruajtjen e shënimeve. Statuset që hyjnë:
   READY, SAVED, dhe FAILED kur ka transkript (dështoi vetëm përmbledhja).
8. **Pa takimet e vjetra.** Regjistri nis bosh dhe mbushet vetëm nga takimet pas
   aktivizimit. Migrimi i shënon takimet ekzistuese si "nuk zbatohet", që të mos
   përpunohen. Takimet që përfundojnë kur flag-u është i fikur shënohen njësoj.

## Qëllimet, jashtë fushës, anti-qëllimet

**Qëllimet**
- Shënimet e takimit të ri lidhen saktë me takimet e mëparshme: detyrat e mbetura,
  temat që përsëriten pa u zgjidhur dhe vendimet që ndryshojnë.
- Regjistri është i dukshëm dhe mund të korrigjohet nga njerëzit. Korrigjimi i
  njeriut ka përparësi.
- Çdo pikë tregon nga cili takim vjen dhe çka u tha aty.

**Jashtë fushës në këtë version**
- Përdorimi i regjistrit te asistenti me zë në PrimeFlow ose te `/pyet` në
  Discord. Mund të shtohet më vonë mbi të njëjtin regjistër.
- Regjistrimet e ekranit dhe audios ("Regjistrimet", recording analysis). Ato
  kanë lejet e veta (RBAC) dhe nuk duhet të dalin te një faqe që e sheh i gjithë
  stafi. *Vendimi im.*
- Krijimi ose ndryshimi automatik i detyrave në PrimeFlow nga regjistri.
- Regjistra të ndarë sipas departamentit ose kanalit.

**Anti-qëllimet**, d.m.th. dështim edhe nëse teknikisht punon:
- Mira shpik lidhje. Lidh dy tema vetëm kur është e qartë që flitet për të njëjtën
  gjë. Përndryshe nuk i lidh.
- Shënimet për Notes zgjaten ose mbushen me historik. Lidhja me të kaluarën
  shkruhet shkurt, vetëm aty ku ka vlerë.
- Një gabim i Mira-s në regjistër kalon nga takimi në takim pa u parë. Faqja dhe
  korrigjimet ekzistojnë për ta parandaluar këtë.
- Dështimi i kujtesës e bllokon ose e vonon dorëzimin e shënimeve të takimit.
- Teksti i takimit trajtohet si udhëzim për Mira-n. Transkripti dhe regjistri janë
  të dhëna, jo komanda, njësoj si sot te `RULES`.

## Rrjedha pas çdo takimi

Puna e përfundimit ekzistuese (`backend/app/jobs/discord_voice_meetings.py`)
vazhdon me këtë radhë:

1. **Shënimet.** `summarize_meeting` merr si kontekst shtesë një pamje të
   regjistrit *para* këtij takimi: pikat e hapura dhe pikat e mbyllura së fundmi.
   `FINAL_SYSTEM` merr udhëzime për mënyrën si i lidh shënimet me të kaluarën:
   brenda pjesëve ekzistuese, shkurt, me referencë si "(1H, 21.10 09:58)", dhe
   vetëm kur lidhja është e qartë. Regjistri është i dukshëm vetëm në hapin final;
   përmbledhjet ndërmjetëse të pjesëve nuk e marrin.
2. **Dorëzimi i shënimeve** bëhet si sot, në Discord ose direkt në PX Notes për 1H
   e planifikuara. Nuk pret hapin 3.
3. **Përditësimi i regjistrit.** Një thirrje e veçantë te modeli merr
   transkriptin e plotë të takimit (në pjesë, nëse është i gjatë) dhe regjistrin
   aktual, dhe kthen veprime të strukturuara (Structured Outputs):
   - **shto pikë** me titull, përshkrim, njerëzit e përmendur dhe llojin
     (detyrë/ndjekje, temë e hapur, vendim, informacion);
   - **përmendje e re** e një pike ekzistuese, me përmbledhjen e asaj që u tha
     dhe referencat e segmenteve;
   - **ndryshim i gjendjes aktuale** të pikës, p.sh. afati i ri ose vendimi i ri;
   - **mbyll** me arsyen, p.sh. "u konfirmua që u dërgua".

   Aplikacioni i validon veprimet: ID ekzistuese, gjatësitë, lloji. Pastaj i
   zbaton në një transaksion. Model: `DISCORD_AI_MODEL`, `store=false`, njësoj si
   përmbledhja.

Përditësimet e regjistrit zbatohen me radhë sipas kohës së nisjes së takimit dhe
të serializuara (një takim njëkohësisht, p.sh. me advisory lock), që dy takime
të mos e mbishkruajnë njëri-tjetrin. Çdo takim zbatohet në regjistër vetëm një
herë; një riprovim nuk shton përmendje të dyfishta. Dështimi i hapit 3 riprovohet
në tick-et pasuese dhe nuk e prek kurrë gjendjen e shënimeve. Nëse takimi i
radhës vjen para se të përditësohet regjistri nga takimi i kaluar, shënimet e
tij përdorin regjistrin ashtu siç është. Kjo pranohet.

**Dështimet e përsëritura.** *Vendimi im:* një përditësim riprovohet deri në 5
herë. Pas kësaj takimi shënohet "kujtesa dështoi", dhe takimet pasuese vazhdojnë
pa e pritur. Dështimi nuk fshihet: shfaqet në diagnostikë dhe në fund të faqes
("1 takim nuk u përfshi në kujtesë"), dhe një admin mund ta riprovojë nga faqja.
Një takim që ende po përgatit shënimet i mban në pritje takimet e mëvonshme
për më së shumti 15 minuta. Pas kësaj ata vazhdojnë, dhe ai zbatohet kur të
jetë gati.

Takimet pa të folur të kuptueshëm (`FAILED` pa segmente) nuk e prekin regjistrin.
Takimet e pjesshme e prekin, por përmendjet e tyre shënohen si nga takim i
pjesshëm.

## Rregullat e regjistrit

- **Korrigjimi i njeriut fiton.** Kur dikush e ndryshon tekstin ose e mbyll një
  pikë, Mira nuk e kthen vetë mbrapsht. Mund ta rihapë ose ta ndryshojë vetëm kur
  në një takim të ri thuhet qartë diçka tjetër. Edhe atëherë kjo shfaqet në
  historik si përmendje e re, e dukshme. *Vendimi im për zbatimin:* modeli e sheh
  që pika është korrigjuar nga një person dhe i merr udhëzimet në prompt.
  Aplikacioni e zbaton ndryshimin e tij pa hap miratimi, sepse historiku e bën
  të dukshëm dhe çdokush mund ta kthejë. Nëse një person e ndryshon pikën ndërsa
  Mira po punon mbi pamjen e vjetër (versioni nuk përputhet), përmendja e Mira-s
  ruhet, por ndryshimi i saj i gjendjes për atë pikë hidhet poshtë.
- **Pikat "e gabuara"** i jepen modelit gjithmonë, vetëm me titull, pavarësisht
  moshës së tyre, që Mira të mos i rikrijojë. *Vendimi im.*
- **Historiku nuk fshihet.** Çdo përmendje, korrigjim, mbyllje dhe rihapje
  shënohet me datën dhe me burimin: takimi ose emri i personit.
- **Pikat e heshtura.** Një pikë e hapur që nuk përmendet për 30 ditë shënohet
  "e heshtur". Nuk fshihet dhe rizgjohet nëse përmendet sërish. *Vendimi im;
  pragu është konfigurim.*
- **Madhësia e kontekstit.** Modeli merr pikat e hapura dhe ato të mbyllura në 14
  ditët e fundit, jo të gjithë historikun. Për secilën merr gjendjen aktuale dhe
  disa përmendjet e fundit. Nëse regjistri rritet përtej kufirit të kontekstit,
  përparësi kanë pikat e përmendura së fundmi dhe ato që përsëriten. Kjo nuk
  pritet në heshtje: mungesa regjistrohet në diagnostikë. *Vendimi im; numrat
  janë konfigurim.*
- **Fshirja.** Nuk ka fshirje të plotë nga faqja. Një pikë e gabuar mbyllet si
  "e gabuar", që Mira të mos e rikrijojë, dhe mbetet në skedën e të mbyllurave.
  *Vendimi im.*

## Faqja "Kujtesa e Mira-s"

Rruga e re në frontend, p.sh. `/mira-kujtesa`, me një hyrje në sidebar. Pamja B
nga skicat:

- Titulli "Kujtesa e Mira-s" dhe një rresht: "Çka mban mend Mira nga takimet.
  Përditësohet pas çdo takimi."
- Skedat **Të hapura** (me numër), **Të mbyllura** (me numër), **Të gjitha**.
  Pikat e heshtura dallohen qetë brenda skedës së të hapurave.
- Majtas: lista e shkurtër. Çdo rresht ka titullin e pikës dhe numrin e takimeve
  ku u përmend. Renditja: e përmendura së fundmi në krye.
- Djathtas: pika e zgjedhur, me titullin, gjendjen aktuale, njerëzit dhe
  historikun si vijë kohore (takimi, data dhe ora, çka u tha). Korrigjimet e
  njerëzve shfaqen në të njëjtën vijë kohore.
- Veprimet: **Korrigjo** (titulli dhe përshkrimi), **Shëno të mbyllur** ose
  **Rihap**, dhe **Shëno si të gabuar**.
- Në celular: vetëm lista. Hollësitë hapen mbi listë dhe kanë kthim mbrapa.
- Gjendja bosh: "Mira nuk ka mbajtur mend asgjë ende. Pikat shfaqen pas takimit
  të parë me shënime."

Stili ndjek PrimeFlow (shadcn, Segoe UI, sfond i bardhë, ngjyra neutrale) me një
ngjyrë të vetme theksi për pikat e hapura. Elementi kryesor është vija kohore e
historikut; pjesa tjetër mbetet e qetë. Skica e pranuar:
`.superpowers/brainstorm/1141-1792566447/content/register-layout.html` (opsioni B).

Konkurrenca: dy persona mund të korrigjojnë njëkohësisht, dhe Mira mund të
përditësojë njëkohësisht. Çdo pikë ka version. Një ruajtje me version të vjetër
refuzohet me mesazh të qartë dhe faqja rifreskon pikën.

## Të dhënat

Migrim i ri, numri i radhës pas `0155`:

- **Pikat e kujtesës:** id, titulli, përshkrimi (gjendja aktuale), lloji, gjendja
  (hapur/mbyllur/e gabuar), njerëzit e përmendur (emra si tekst), versioni,
  koha e përmendjes së fundit, e krijuar/përditësuar, dhe kush e ka korrigjuar
  së fundi (Mira ose përdoruesi).
- **Ngjarjet e historikut:** pika, lloji (përmendje, ndryshim, mbyllje,
  rihapje, korrigjim nga njeriu), teksti, takimi burim (`discord_voice_meetings.id`)
  ose përdoruesi, referencat e segmenteve, koha.
- **Te `discord_voice_meetings`:** gjendja e përditësimit të kujtesës (në pritje,
  e zbatuar, dështoi) dhe numri i riprovimeve, që zbatimi të jetë një herë dhe
  i rikuperueshëm.

API: lista me filtër sipas gjendjes, leximi i një pike me historik, korrigjimi,
mbyllja, rihapja dhe shënimi si e gabuar. Kërkon përdorues të autentikuar; nuk
ka kufizim departamenti.

## Siguria dhe diagnostika

- Transkripti dhe regjistri u jepen modelit si të dhëna. Udhëzimet përsërisin
  rregullat e `RULES`: pa komanda, pa shpikje, pa tools.
- Teksti që shkruajnë njerëzit në faqe trajtohet edhe ai si të dhëna kur i jepet
  Mira-s.
- Log-et nuk përmbajnë përmbajtje të takimeve. Diagnostika `MIRA_DIAGNOSTIC`
  raporton vetëm numra: veprimet e zbatuara, të refuzuara, dështimet dhe pikat
  e lëna jashtë kontekstit.
- Aktivizim me flag të veçantë, p.sh. `MIRA_MEMORY_ENABLED`, në fillim `false`.
  Me flag të fikur, shënimet punojnë saktësisht si sot.

## Verifikimi

- Teste me OpenAI të zëvendësuar për: shtimin e pikës, përmendjen e re, mbylljen,
  ndryshimin e vendimit, veprimet me ID të panjohur (refuzohen), riprovimin pa
  dyfishim, renditjen e dy takimeve, dështimin e kujtesës pa prekur shënimet,
  dhe korrigjimin e njeriut që nuk mbishkruhet nga Mira.
- Teste për API-n dhe konfliktin e versionit.
- Test që `summarize_meeting` pa regjistër jep të njëjtin rezultat si sot.
- Provë reale: dy takime 1H me radhë ku i dyti i rikthehet një teme të të parit.
  Shënimet e të dytit duhet ta përmendin lidhjen, dhe faqja duhet ta tregojë
  pikën me dy përmendje.

## Çka i mbetet ndërtuesit

Emrat e saktë të tabelave dhe rrugëve, skema e Structured Outputs, ndarja e
transkriptit të gjatë për përditësimin e regjistrit, kufijtë e saktë të
kontekstit dhe pamja përfundimtare e faqes brenda drejtimit të mësipërm.
