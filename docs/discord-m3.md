# M3 dhe plani për ditën e ardhshme në Discord

Përdor lidhjet ekzistuese personale të Discord-it dhe orën e raporteve të platformës.
Pyetjet, përgjigjet, marrësi dhe dërgimi ruhen në databazë. Polling-u është çdo
30 sekonda; rinisja e botit nuk i ridërgon pyetjet e dërguara.

Provat e dërguara para orarit nuk e konsumojnë njoftimin e rregullt: dërgimi
normal llogaritet nga 15:50 për M3 dhe nga 16:10 për planin e nesërm. Pyetjet
pa përgjigje të provës riemetohen sipas gjendjes aktuale, me një lease të veçantë
për tentativën reale; pas dërgimit të ri hiqen butonat nga mesazhi i provës.
Përgjigjet tashmë të ruajtura nuk pastrohen. Konfirmimi përfundimtar pret që
kartat individuale të jenë dërguar në orarin e rregullt, jo thjesht gjatë provës.

## Ora 15:50

- Detyrat TODO brenda Start–Due të ditës, përfshirë detyrat e sistemit: **Komento**,
  **Në progres**, **Mbylle**, **Shtyje**. Komenti është i detyrueshëm për këto veprime.
- Dorëzimet me M3 ose M2/3: **Po, e dorëzova** ruhet menjëherë dhe hap koment
  opsional. **Jo** kërkon koment. Për detyrat e përbashkëta, përgjigjja e secilit
  shfaqet me emër; një JO e mban rezultatin JO dhe PO kërkon përgjigjen e të gjithëve.
- Takimet INT/EXT të përfunduara, pa status mbajtur/anuluar: pyetja u shkon
  pjesëmarrësve të caktuar. Vetëm takimet pa asnjë pjesëmarrës i shkojnë
  `diellza.veliu`. Një pjesëmarrës pa lidhje Discord nuk zëvendësohet me Diellzën.
  Takimet e ardhshme dhe ato të anuluara në kalendar nuk pyeten.

Mbledhja e M3 vazhdon deri në 16:10 për të përfshirë takimet që përfundojnë më vonë.

**Hap detyrën** shfaq kartën e plotë të detyrës në të njëjtin mesazh të kanalit personal, me
statusin, slotin, afatin, të gjitha pikat, komentet dhe butonat normalë të veprimit.
Te detyrat TODO, butoni vjen menjëherë pas **Shtyje**, në të njëjtin rresht.
Teksti i gjatë shfletohet me faqe brenda të njëjtit mesazh pa u shkurtuar.
**Kthehu te M3** rikthen pyetjen e raportimit me përgjigjen dhe komentin aktual.

## Ora 16:10

Secili person i lidhur merr listën e plotë të detyrave për ditën e ardhshme të
punës. Të premten, plani është për të hënën. Përzgjedhja e datave ndjek Common View.
Çdo detyrë ka një kartë kompakte me vetëm rreshtin e parë të titullit, pa markup
teknik, përshkrim ose data. Titulli klikohet për të hapur detyrën. Butonat janë
menjëherë poshtë në një rresht: **Po, kryhet** për Due nesër ose **Po, punohet**
për detyrat e tjera, pastaj **Jo — shtyje · Hap detyrën · Koment**. **Hap detyrën** hap
kartën e plotë me veprimet e detyrës brenda të njëjtit mesazh të raportimit.
Tekstet e gjata shfletohen me faqe që respektojnë kufirin e Discord-it. Preview-t
automatike të linkut janë të çaktivizuara edhe gjatë rifreskimit të kartave.
Discord nuk mbështet tre
butona në të njëjtin rresht me tekstin e titullit. Përgjigjja dhe prania e komentit
shfaqen si shenja të shkurtra pranë titullit; teksti i gjatë i komentit ruhet në platformë.
**Jo — shtyje** hap menjëherë Start, Due dhe arsyen; shtyrja ruhet pasi dërgohet formulari.

Pas dërgimit të kartave të detyrave, vjen **Po për të gjitha**, që plotëson vetëm
detyrat ende pa përgjigje. Përgjigjet individuale, përfshirë JO dhe shtyrjet, ruhen.
**Koment** ruan komentin pa vendosur automatikisht PO/JO; nëse kishte përgjigje,
ajo ruhet. Konfirmimi i përgjithshëm ruan komentet ekzistuese.

Detyrat 1H/R1 pa slot marrin përzgjedhësin e slotit. Kopjet e një detyre me
`fast_task_group_id` të njëjtë, ose instancat e të njëjtit template sistemi për atë
ditë, krahasohen. Nëse slotet ndryshojnë, shfaqen emri dhe ora e secilit, butoni
**Konfirmoj orën time**, butonat **Si kolegu** dhe përzgjedhësi i orarit.
Titujt e ngjashëm pa lidhje të përbashkët nuk bashkohen.

Sloti ruhet për datën konkrete të ditës së ardhshme, përmes së njëjtës rrjedhë si
My View. Ndryshimi i slotit nuk ndryshon slotet e kolegëve.

## Shtyrja

Formulari hap menjëherë **Start**, **Due** dhe **Komenti / arsyeja**. Datat janë
të mbushura me vlerat aktuale. Mund të ndryshohet vetëm njëra; tjetra ruan edhe
orën aktuale. Kontrollet e platformës për afatet, detyrat e përbashkëta, auditimin
dhe shpjegimin e shtyrjes vazhdojnë të zbatohen.

Në M3 dhe në planin e nesërm, ndryshimi zbatohet drejtpërdrejt përmes editimit
normal të detyrës. Në M2 dhe te butoni i përgjithshëm **Kërko shtyrje**, mbetet
konfirmimi ekzistues nga Diellza; pas arsyes shfaqen të dyja datat, pa zgjedhje të llojit të datës.

## Kontrolli i ndryshimeve

Çdo veprim rikontrollon lidhjen Discord, ditën, pronësinë dhe gjendjen aktuale.
Formularët me data, përgjigje ose slote të vjetruara refuzohen. Konfirmimi i planit
lidhet me listën dhe afatet që personi pa. Ndryshimet e sloteve nuk kërkojnë
konfirmimin e gjithë planit përsëri.

Përgjigjet M3 ruhen te raporti dhe te komentet personale. Komentet e detyrave TODO
ruhen edhe te evidenca ditore. Veprimet dhe përgjigjet regjistrohen në audit.
Përgjigjet e vendosura nga menaxheri në raport mbyllin formularët përkatës të Discord-it.

## Aktivizimi dhe verifikimi

U aktivizua më 27.10.2026. Migrimi `0169_discord_m3_questions`, të 11 skedarët e
paketës, endpoint-et M3 në të dyja API-të (8000/8080) dhe rilidhja e botit u
verifikuan në server. Xhiroja përfundimtare e M3 kaloi 20 teste, përfshirë nëntë
prova transaksionale në skema të përkohshme. Verifikimi nuk dërgoi mesazhe.

Kërkohet migrimi `0169_discord_m3_questions`, pastaj rinisja e API-ve dhe procesit
`primeflow-discord`. Nuk kërkohet konfigurim i ri ose lidhje e re e punonjësve.
Kërkohet të jetë aktiv konfigurimi ekzistues i asistentit Discord.

Testet pa databazë:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_discord_m3.py tests/test_discord_m2_approvals.py tests/test_m3_reporting_points.py tests/test_m3_unheld_meetings.py -q
```

Testet transaksionale përdorin `M2_TEST_DATABASE_URL` dhe skema të përkohshme;
nuk kontaktojnë Discord-in dhe nuk prekin rreshtat e punës. Nga `backend` mund të
përdoret `python ../tmp/run-m3-db-tests.py` me konfigurimin lokal të lidhjes.
