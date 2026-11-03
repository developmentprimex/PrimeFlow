# Host-Mira dhe raporti 1H — përputhja e progresit

Rregullimet janë lokale, pa push/deploy. Objektivi është që hyrja e takimit të ndjekë: **notes të reja → Done → Strike të intervalit → detyrat e stafit**.

## Burimi dhe intervalet

Mira përdor të njëjtin ndërtues dokumenti që përdor “Preview fresh report”. Zgjedhja e detyrave, dita, slotet/seksionet, përfundimet dhe teksti aktual i detyrës/shënimit kontrollohen me të njëjtat rregulla. Leximi i audios nuk gjeneron Word/PNG dhe nuk dërgon email.

| Takimi | Intervali i raportit |
| --- | --- |
| 10:00 | 08:00–10:00 |
| 11:00 | 10:00–11:00 |
| 11:50 | 11:00–11:50 |
| 14:20 | 11:50–14:20 |
| 16:00 | 14:20–16:00 |

Fillimi i intervalit përjashtohet dhe fundi përfshihet, njësoj si raporti. Historia ose ora e leximit të një takimi të mëparshëm nuk e zgjeron intervalin e slotit aktual. Raporti i freskët dhe Mira mund të pasqyrojnë ndryshime të mëvonshme të detyrave; kjo nuk është një lexim nga kopja historike e emailit të dërguar më parë.

## Done dhe Strike

- Done përfshin vetëm detyrat që raporti përfshin për atë dritare. Përfundimi mund të jetë nga një detyrë e planifikuar për një slot tjetër, kur raporti e përfshin si të kryer në këtë interval.
- Koha e përfundimit ruhet brenda të dhënave për filtrimin e saktë. Mira nuk lexon orën dhe nuk komenton mungesën e saj.
- Strike nxirret nga i njëjti funksion që prodhon/ngjyros pikat blu në raport dhe drejton filtrin `strikes > 0`.
- Numërohen fushat TITLE dhe DESCRIPTION, përfshirë rastet e vjetra me orë të shkruar në tekst dhe pa event të veçantë.
- Një pikë e fshirë ose aktualisht e rihapur nuk shpallet si progres, edhe kur historia ka një event të vjetër STRUCK. Pikat e gjelbra/gritë nuk trajtohen si strike të reja të intervalit.
- Detyra e përbashkët numërohet vetëm një herë, duke ruajtur emrat e pjesëmarrësve. Titulli i njëjtë nuk i bashkon dy ID të ndryshme.
- Personi përgjegjës për detyrën dhe aktori që bëri strike janë fakte të ndara. Kur aktori gjendet në të dhëna, ruhet në rezultat; kur mungon, nuk hamendësohet.

Në shembullin e figurës, `Strikes: 0 · 08:00–10:00` numëron punën e atij intervali. Prania e pikave të vijëzuara në tekst, në vetvete, nuk provon se janë punë e re për t'u njoftuar në këtë takim.

## Rrjedha dhe ritmi

Detyrat e Haxheres (Financat) përjashtohen nga të dhënat e Mira Host: nuk lexohen në Done/Strike, nuk krijojnë radhë stafi dhe nuk futen në ndjekjen e detyrave paraprake, detyrave të bllokuara, detyrave për GA ose rishikimin PM. Ky përjashtim zbatohet vetëm te Mira Host; raportet dhe detyrat e ruajtura mbeten të pandryshuara. Nuk përjashtohet i gjithë departamenti i Financave.

Mira nis drejtpërdrejt me notes e reja, pa pyetur për aprovim ose kthim në detyra. Notes përdorin të njëjtat përjashtime si raporti për shënimet e diskutuara, shënimet e krijuara nga Mira dhe shënimet që tashmë kanë detyrë aktive. Konfirmimi që një shënim u përmend nuk e ndryshon origjinën e tij në “krijuar nga Mira”.

Pas notes, përmenden strike-t me personin, detyrën dhe numrin e tyre, pastaj detyrat Done me personin dhe detyrën. Orët dhe intervali nuk lexohen, pasi intervali i takimit dihet; ato mbeten vetëm për kontrollin e të dhënave. Nuk lexohen të gjitha pikat e një checklist-e kur mjafton emri i detyrës dhe numri i pikave. Leximi bashkon deri në tri njoftime të shkurtra dhe rreth 65 fjalë në një përgjigje, duke konfirmuar secilën pjesë veçmas. Pjesa e pasaktë riprovohet veçmas; pjesët e konfirmuara nuk rilexohen.

Nëse lista është bosh, Mira kalon pa lexuar zero dhe pa pyetur “a të vazhdoj?”. Nëse ende nuk është ora zyrtare, pret në heshtje. `list_ga_tasks` mbetet i disponueshëm për kërkesë të shprehur; nuk e ndërpret hyrjen automatike notes/progres/staf.

Kur Mira futet 2–3 minuta përpara slotit, lexon notes, strike dhe Done menjëherë nga raporti i freskët me të dhënat e disponueshme në çastin e leximit. Intervali i filtrit mbetet ai i slotit; ky lexim përpara orës nuk pretendon të përfshijë ndryshime që regjistrohen më vonë.

Fillimi i stafit mbetet ora zyrtare e slotit edhe kur hyrja bëhet me komandë manuale. Në atë orë kontrolluesi hap radhën e stafit dhe lexon praninë aktuale në Discord. Nuk pret përfundimin e hyrjes dhe nuk zgjat pjesën GA me tetë minuta; audioja e hyrjes që ende po luhet ndalet dhe pjesët e papërfunduara shtyhen pa u shënuar si të dëgjuara. API-ja bllokon hapjen e stafit dhe kalimin e radhës përpara orës zyrtare. Sesionet e testimit mund të nisin menjëherë.

Kur të gjitha detyrat e slotit aktual dhe atij menjëherë paraprak janë TODO, RADHA jep pyetjen “Me çka ke vazhduar?”. Ky kusht bazohet vetëm te statusi, pa u ndryshuar nga përqindja ose strike-t. Nëse ndonjë detyrë është në proces, e kryer ose me status tjetër, pyetja nuk hapet automatikisht. Mira e pyet një herë për personin, përpara pyetjeve të detyrave, nëse ai nuk e ka sqaruar tashmë punën që ka vazhduar. Në 11:50 kontrolli TODO përdor vetëm slotin 11:00 dhe 11:50, ndërsa plani i diskutimit vazhdon të përfshijë detyrat e hapura të të gjitha sloteve të mëparshme. Pa asnjë detyrë në këto dy slote pyetja nuk bëhet; nëse vetëm njëri slot ka detyra, kontrollohen ato. Puna tjetër nuk regjistrohet si progres i një detyre të planifikuar.

Prompt-i është versioni `2026-11-03.6`. Nuk kërkohet migrim databaze dhe nuk është ndryshuar modeli zanor.

## Provat

Testet e reja krahasojnë drejtpërdrejt rezultatin e Mirës me `generate_fresh` dhe `ReportDocument.strike_total`, për të pesë slotet. Përfshihen kufijtë e orës, Done jashtë intervalit, dy fushat e strike-ve, pika të rihapura/fshira, timestamps pa event, ndarja përgjegjës/aktor, detyra të përbashkëta, seksione të tjera dhe renditja notes para progresit.

Verifikimi i ndryshimit të orarit: **234 teste backend kaluan**, me 41 nënraste shtesë; **91 teste audio/Discord kaluan**. Përfshihen hyrja manuale para slotit, leximi i hershëm i progresit, bllokimi i kontrollit të mungesave përpara orës zyrtare, prania e freskët në fillim, kalimi i detyrueshëm te stafi kur hyrja ende vazhdon dhe ndalimi i audios së hyrjes. Kaloi edhe `git diff --check`.

Në verifikimin e mëparshëm të plotë kaluan 358 teste backend/raportesh; 15 teste integrimi Desktop/PostgreSQL u anashkaluan sepse nuk është konfiguruar databaza lokale e dedikuar për to. Ato teste integrimi nuk u ekzekutuan në këtë ndryshim të orarit.

Nuk u përdor një sesion real Discord/OpenAI dhe nuk u ndryshuan të dhënat e prodhimit. Natyrshmëria e zërit mbetet për dëgjim pas aktivizimit.
