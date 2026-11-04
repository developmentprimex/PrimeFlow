# Mira Host — kontrolli shtesë i ciklit të takimit, 04.11.2026

Kontrolli vazhdoi mbi commit-in `49f23090` dhe rregullimin lokal të kontrollit
paraprak. U analizuan rinisja përpara upload-it të të dhënave të vjetra, shkrimet
e vonuara gjatë pastrimit, anulimi i punës së takimit dhe ndalimi gjatë nisjes.
Faqet e lidhura mbetën **vetëm për kontroll**, sipas zgjedhjes së përdoruesit.

## Gjetje të konfirmuara dhe të rregulluara

1. **P1 — një tentativë mund të mbishkruante të dhënat e paruajtura të tjetrës.**
   Mbrojtja e kontrollit paraprak pengonte fshirjen e snapshot-it të ndryshuar
   pas upload-it, por të dy tentativat ende shkruanin në `<meeting_id>.json`.
   Një rinisje përpara rikuperimit humbiste rreshtat dhe konfirmimet e tentativës
   së vjetër. Në rendin e kundërt, pastrimi i vonuar mund të mbishkruante kopjen
   e re. Dy provat dështuan para rregullimit. Tani skedarët e rinj kanë emrin
   `<meeting_id>.attempt-<join_attempt>.json`; çdo tentativë ruan dhe pastron
   vetëm kopjen e vet. Leximi i formatit të vjetër ruhet. Kontrolli i snapshot-it
   të ndryshuar gjatë upload-it gjithashtu mbetet në fuqi.

2. **P1 — anulimi i procesit mund të raportohej si takim i përfunduar.**
   `asyncio.CancelledError` nuk kapej nga `except Exception`. Blloku `finally`
   vazhdonte te mbyllja me arsyen fillestare `completed`, të cilën serveri e
   trajton si DONE. Prova e riprodhoi këtë sjellje. Tani arsyeja bëhet
   `interrupted:task_cancelled`, ndërsa anulimi përcillet te thirrësi. Një arsye
   ekzistuese, si ndalimi me komandë, ruhet. Kjo e mban të zbatueshëm rikuperimin
   e takimit të ndërprerë, sipas rregullave ekzistuese të serverit.

3. **P2 — ndalimi përpara lidhjes mund të humbiste kontrollin e tentativës.**
   ID-ja e takimit të përgatitur ruhej para kontrollit të anulimit, por
   `join_attempt` merrej vetëm më vonë te `connect`. Tani ruhet menjëherë edhe
   tentativa. Edhe rruga manuale që ndalet gjatë `/session/start` dërgon
   `expected_join_attempt` në kërkesën për pastrim.

U shtuan tetë teste në `backend/tests/test_mira_host_lifecycle.py`, duke mbuluar
edhe formatin e vjetër, pastrimin e një tentative pa prekur tjetrën, ndryshimin e
snapshot-it brenda së njëjtës tentativë dhe ndalimin gjatë përgatitjes manuale.
U përshtat prova e mëparshme e skedarit të rinisjes për emërtimin e ri.

## Verifikimi pas ndryshimeve

| Grupi | Rezultati |
| --- | --- |
| Host backend, përfshirë nisjen manuale, test mode, rikuperimin dhe tetë provat e reja | 244 kaluan |
| 1H Reports, SHTYPI, freeze/strike, Mira Notes dhe kartat Discord 1H | 118 kaluan; 10 u anashkaluan |
| Audio/Discord Node | 100 kaluan |
| Mira Notes/grupimi/kujtesa frontend | 7 kaluan |

Gjithsej **469 teste kaluan; 10 që kërkojnë databazën e dedikuar u anashkaluan**.
`git diff HEAD --check` kaloi.

## Ndikimi dhe kufijtë

Ndryshimet janë brenda kontrolluesit të Host. Përmirësojnë ruajtjen e transkriptit
dhe statusin e burimit që shfaqet te Mira; UI-ja, gjeneruesit e raporteve, PX Notes
dhe Task Details nuk u ndryshuan. Harta e ndikimit u plotësua për skedarët sipas
tentativës dhe anulimin përpara lidhjes.

**Konflikti i përmbledhjeve në sfond mbetet i hapur**, në zonën “vetëm për
kontroll”. Riprodhuesi manual u ekzekutua përsëri dhe dy skenarët e njohur
dështuan: rezultati i vjetër ende mund të ruhet pas rinisjes ose pas mbërritjes së
transkriptit të ri gjatë gjenerimit. Këto dështime dokumentojnë defektin dhe nuk
janë përfshirë te numri i testeve të kaluara.

Nuk u bë test me databazë reale ose takim Discord/OpenAI në prodhim. Nuk u
verifikua deploy-i. Skedarët e rinj sipas tentativës kërkojnë kontrolluesin e
përditësuar për rikuperim; një kthim te kontrolluesi i vjetër nuk i lexon këta
emra skedarësh. Kontrolluesi i ri lexon edhe skedarët e vjetër. Mbrojtja në server
vazhdon të kërkojë `join_attempt`; skedarët historikë pa të nuk kanë atë evidencë.

Rregullimet e këtij kontrolli janë lokale, pa commit/push/deploy nga ky raund.
Nuk nevojitet migrim databaze. Për aktivizim duhet përditësuar/rinisur
kontrolluesi dhe pastaj kryer prova zanore reale.
