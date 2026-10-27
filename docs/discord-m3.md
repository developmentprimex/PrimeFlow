# M3 dhe plani për ditën e ardhshme në Discord

Përdor lidhjet ekzistuese personale të Discord-it dhe orën e raporteve të platformës.
Pyetjet, përgjigjet, marrësi dhe dërgimi ruhen në databazë. Polling-u është çdo
30 sekonda; rinisja e botit nuk i ridërgon pyetjet e dërguara.

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

## Ora 16:10

Secili person i lidhur merr listën e plotë të detyrave për ditën e ardhshme të
punës. Të premten, plani është për të hënën. Përzgjedhja e datave ndjek Common View.
Lista ka faqe me nga 10 detyra; çdo detyrë mund të hapet nga përzgjedhësi.

**Po, të gjitha** konfirmon se punohet në të gjitha dhe se kryhen detyrat me Due
atë ditë. Konfirmon edhe pyetjet individuale për këto afate. **Jo** kërkon koment.
Detyrat me Due nesër kanë edhe kartë individuale; Deadline Important shënohet veçmas.
Nga çdo detyrë e listës mund të hapet shtyrja drejtpërdrejt.

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
