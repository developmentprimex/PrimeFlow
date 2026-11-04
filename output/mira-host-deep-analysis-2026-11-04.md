# Mira Host — analizë dhe rregullime, 04.11.2026

U kontrolluan kontrolluesi Python, shërbimi/API i Host, radha dhe rikuperimi PM,
promptet sipas fazave, punët e audios/Discord-it, ruajtja e transkriptit dhe
lidhjet me raportet/shënimet. Analiza përdori kodin aktual dhe prova sintetike;
nuk është auditim i një takimi real ose i konfigurimit të ruajtur në prodhim.

Ndryshimet janë lokale, pa commit, push ose deploy. Nuk nevojitet migrim databaze.
Përdoruesi zgjodhi **“Vetëm për kontroll”** për faqet e lidhura: Mira
(historiku/përmbledhjet), PX Notes, Task Details, Common View, 1H Reports dhe
SHTYPI Today. Implementimi mbetet brenda rrjedhës së Host-Mira; gjeneruesit e
raporteve, shënimet reale, detyrat dhe UI-të e lidhura nuk u ndryshuan.

## Probleme të konfirmuara dhe të rregulluara

| Përparësia | Problemi dhe shkaku | Rregullimi |
| --- | --- | --- |
| P1 | Një rikuperim/mbyllje e vonuar për të njëjtën ID takimi mund të mbyllte tentativën e rinisur. API-ja kontrollonte ID-në, pa identitetin e lidhjes. | Nisja kthen `join_attempt`; kontrolluesi dhe skedari i rikuperimit e ruajnë dhe e dërgojnë si `expected_join_attempt`. API-ja e kontrollon nën bllokimin e takimit dhe e pranon mbylljen e vjetër si të tejkaluar, pa mbyllur sesionin e ri. Transkripti i rikuperuar ruhet. |
| P1 | Ndalimi priste drejtpërdrejt upload-in përfundimtar dhe kërkesën `/finish`. Vonesa e rrjetit mund ta mbante kontrolluesin të zënë gjatë pastrimit. | Ruhet menjëherë evidenca e rikuperimit; upload-i periodik anulohet duke ruajtur batch-in e papërfunduar. Upload-i përfundimtar dhe `/finish` kanë secili kufi 12 sekonda. Rreshtat/metrikat dhe konfirmimet e paruajtura mbeten për rikuperim. |
| P2 | Në 11:50 personi me vetëm punë të pambyllur në 10:00/11:00 nuk hynte në radhë. Brief-i e përfshinte punën, por radha kërkonte detyrë në slotin aktual. | Pas personave të slotit aktual shtohen përgjegjësit e punëve të hapura nga slotet e mëparshme. Ruhen përjashtimet, mungesat dhe shmangia e dublimit. E njëjta listë përdoret për ftesën paraprake. |
| P2 | Një snapshot bosh `pm_review=[]` interpretohej si përfundim. Kjo anashkalonte burimin e freskët PM ose radhën PM të ruajtur pas ndërprerjes. | Prania e hapit `pm_review`, edhe me listë bosh, nis kontrollin PM. Shërbimi PM përcakton nga gjendja e vet nëse ka persona apo nëse mund të mbyllet. |
| P2 | `wait_for_user(reason="user_pause")` nuk ruante pauzën ndaj një udhëzimi të mëvonshëm të sistemit. Vetëm disa formulime të njohura nga rregulli tekstual e aktivizonin pauzën e qëndrueshme. | Edhe pauza e njohur nga modeli ruhet për thënien/fazën aktuale. “Vazhdo” ose ndryshimi i radhës e liron. Eventet e vjetra mbeten të mbrojtura nga identiteti i fazës/radhës. |
| P2 | Prompti kishte paqartësi mes kufirit dy fjali dhe leximit të plotë `read_aloud`, si dhe mes raportimit të paqartë dhe kushtit për kalim të radhës. Koha PM nuk jepej shprehimisht. | Leximi i përzgjedhur përjashtohet nga kufiri i bisedës. Sqarohet ruajtja `unclear=true` pas një përpjekjeje sqarimi, duke dalluar heshtjen. PM ndjek kufirin ekzistues deri në dy minuta për person. Versioni i promptit është `2026-11-04.1`. |

Provat e reja për radhën, snapshot-in bosh, pauzën, vonesat përfundimtare dhe
mbylljen e vjetër e riprodhuan sjelljen problematike para rregullimit.

## Gjetje e mbetur në zonën “vetëm për kontroll”

**P1 — një përmbledhje në sfond mund të publikojë rezultat të vjetruar.**
`backend/app/services/mira_host.py::summarize` lexon takimin dhe transkriptin,
pret gjenerimin nga provideri dhe më pas vendos `summary` / `summary_status=READY`
pa kontrolluar përsëri tentativën, gjendjen ose versionin e transkriptit.
Nëse ndërkohë takimi riniset, ose mbërrijnë rreshta të rikuperuar që e vendosin
përmbledhjen në PENDING, rezultati i vjetër mund ta mbishkruajë këtë gjendje.
Kjo prek përmbledhjen në Mira dhe përmbajtjen që mund të ndahet më pas në PX Notes.

Dy skenarët u riprodhuan me provider dhe DB të simuluar: rinisje gjatë gjenerimit
dhe transkript i vonuar gjatë gjenerimit. Në të dy, rezultati i vjetër u ruajt.
Nuk pretendohet se kjo ka ndodhur në prodhim. Për këtë rrjedhë nuk u bë ndryshim,
sipas zgjedhjes së përdoruesit për faqet e lidhura.

Riprodhuesi manual: `output/mira-host-summary-audit-2026-11-04.py`.
Nga rrënja e projektit:

```powershell
backend/.venv/Scripts/python.exe output/mira-host-summary-audit-2026-11-04.py
```

Ky riprodhues del me dy dështime të pritshme sa kohë ekziston mangësia; nuk
përfshihet në suitën standarde të regresionit. Rregullimi i rekomanduar është
kontrolli i versionit/tentativës dhe transkriptit nën bllokim para publikimit,
me të njëjtin kontroll për shënimet për person që gjenerohen pas përmbledhjes.

## Kontrollet e kryera

- **235 teste Host backend kaluan**, përfshirë tetë prova të reja dhe nisjen manuale.
- **118 teste backend të lidhura kaluan; 10 u anashkaluan** sepse kërkojnë databazën e dedikuar. U përfshinë 1H Reports, SHTYPI, freeze/strike, Mira Notes, grupimi i shënimeve dhe kartat Discord 1H.
- **100 teste audio/Discord kaluan**, përfshirë provën e re të pauzës së njohur nga modeli.
- **7 teste frontend kaluan** për Mira Notes, grupimin dhe kujtesën/dukshmërinë.
- `git diff --check` kaloi; nuk u gjetën shenja konflikti merge në skedarët e Host të kontrolluar.

Në total: **460 teste të kaluara dhe 10 të anashkaluara**. Riprodhuesi i mangësisë
së përmbledhjes raportohet veçmas dhe nuk numërohet si test i kaluar.

Lidhjet e raportimit u verifikuan në kod: Host lexon snapshot-in, intervalet dhe
ndërtuesin e dokumentit të 1H Reports; përzgjedhja e personave të Host nuk
rishkruan këta gjenerues. Lidhja me PX Notes dhe Task Details kalon përmes
shënimit/taskut burimor; krijimi automatik i detyrave nga notes mbetet i ndaluar
në mjetet e fazës GA. Kontrollet e Task Details/Common View ishin në kod;
nuk u krye provë e re interaktive në këto faqe.

## Aktivizimi dhe kufijtë

Për aktivizim duhet publikuar backend-i dhe rinisur kontrolluesi/boti që përdor
punëtorin Node të përditësuar. Mbrojtja e tentativës kërkon të dy komponentët e
përditësuar. Klientët dhe skedarët e vjetër pa `join_attempt` mbeten të lexueshëm,
por nuk kanë evidencën e nevojshme për kontrollin e ri të tentativës.

Mbetet një provë dëgjimore në Discord për shqiptimin, ritmin, dy folës, kërkesën
për pritje dhe rikthimin pas shkëputjes. Nuk u përdor OpenAI/Discord në prodhim,
nuk u testua databazë reale dhe nuk u ndryshuan modeli, zëri ose kredencialet.
Përmbledhjet mbeten pika e parë e rekomanduar për një rregullim të mëvonshëm
nëse zgjerohet shtrirja në faqet e lidhura.
