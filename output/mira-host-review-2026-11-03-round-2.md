# Mira Host — analiza e dytë, 03.11.2026

Ky raund kontrolloi ndryshimin e personave, audion gjatë kalimit të radhës, transkriptet që mbërrijnë me vonesë, kërkesat e papërfunduara dhe rikuperimin e mikrofonit/API-së. U gjetën dhe u rregulluan gjashtë probleme të tjera. Ndryshimet janë lokale, pa commit, push ose deploy.

## Gjetjet dhe rregullimet

1. **Audioja e personit të mëparshëm mund të vazhdonte gjatë radhës së re.** Ndalimi i audios zbatohej vetëm në daljen nga hyrja GA. Tani ndryshimi i personit ose fazës anulon përgjigjen e vjetër, heq audion e mbetur dhe udhëzimet zanore të vjetra. Paketat e vonuara të përgjigjes së anuluar nuk luhen. Konfigurimi i përsëritur i së njëjtës radhë nuk e ndërpret atë.

2. **“Prit/vazhdo” i një transkripti të vonuar mund të ndryshonte pritjen e personit të ri.** Kontrolli zanor tani pranon pauzën/rifillimin vetëm nga një thënie që i përket fazës dhe kalimit aktual të radhës. Çdo kalim ka identitet të veçantë, edhe kur hyrja dhe mbyllja nuk kanë turn_id ose kur një person kthehet në të njëjtën radhë më vonë. PËRGJIGJA automatike, rikuperimi i një përgjigjeje të injoruar dhe atribuimi i folësit te mjetet kontrollojnë gjithashtu origjinën e thënies. Transkripti i vonuar ruhet me radhën e vet origjinale; nuk përdoret si përgjigje e personit të ri.

3. **Një kërkesë për të dhënat e stafit të vjetër mund të bllokonte pyetjen për personin e ri.** Kërkesat e leximit mbajnë radhën ku janë nisur. Kur radha ndryshon, leximi i vjetër hiqet nga pritja; PËRGJIGJA e tij e vonuar nuk krijon përgjigje tjetër zanore. Shkrimet dhe kalimi i radhës ruajnë rezultatin e tyre real, sepse mund të jenë zbatuar në server.

4. **Defekti i mikrofonit të një kolegu mund të ndërpriste raportimin aktual.** Gabimet ruhen për folësin përkatës, por paralajmërimi zanor lidhet vetëm me personin aktiv dhe nuk përsëritet për çdo event. Eventet e përsëritura nuk e rifillojnë timerin e defektit. Nëse personi hyn në radhë me një defekt të mëhershëm, merr deri në 30 sekonda për rilidhje nga fillimi i radhës së tij; nuk kalon menjëherë në timeout për shkak të kohës së kaluar përpara radhës.

5. **Rikuperimi i dekoderit në segmentin pasues mund të mbetej i paregjistruar.** Kur krijimi i dekoderit dështonte dhe segmenti tjetër hapej me sukses, dekoderi i ri nuk njihte gjendjen e gabimit të atij folësi. Gjendja e defektit tani ruhet për folësin përtej segmentit. Sapo merret audio e vlefshme, dërgohet eventi i rikuperimit dhe kontrolluesi nuk e trajton më mikrofonin si të prishur.

6. **Një vonesë API gjatë kontrollit të kohës mund ta abortonte gjithë takimin.** Kontrolluesi tani lejon rikuperimin e gabimeve të përkohshme të kalimit, duke mbajtur mbrojtjen e turn_id dhe leximin e gjendjes së serverit. Pas tre gabimeve të tilla pa një kontroll të suksesshëm, ndalet me gabim; nuk rrotullohet pafund dhe nuk e raporton takimin si të përfunduar me sukses. Gabimet e tjera të papritura vazhdojnë të dalin si gabime.

## Verifikimi

- **129 teste backend kaluan**, me **30 nënraste shtesë**, për rrjedhën, ritmin, rikuperimin, botin dhe gjendjen e takimit.
- **99 teste audio/Discord kaluan**, përfshirë tetë prova të reja për kalimin e personave, pauzën/rifillimin e vonuar, pauzën e hyrjes, mbylljen pa turn_id, kërkesat e vjetra, ruajtjen e rezultateve të shkrimit dhe rikuperimin e dekoderit.
- `git diff HEAD --check` kaloi; nuk u gjetën konflikte Git në skedarët e kontrolluar.

Rregullat ekzistuese mbeten: notes → strike → Done përpara orës, staf/prani në fillimin zyrtar, pa lexim të orëve, përjashtim i detyrave të Haxheres dhe pyetja “Me çka ke vazhduar?” kur detyrat aktuale/paraprake janë të gjitha TODO. Nuk u ndryshua modeli ose zëri dhe nuk nevojitet migrim databaze.

Testet përdorin të dhëna sintetike dhe transport të simuluar; nuk u zhvillua takim real Discord/OpenAI. Ky raund nuk përfshiu integrimin me databazë reale ose testim dëgjimor në prodhim.
