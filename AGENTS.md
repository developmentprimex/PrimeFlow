# Udhëzime për punën në këtë projekt

## Ndryshimet në faqet e lidhura

Për ndryshime funksionale ose vizuale në aplikacion, lexo pjesën përkatëse të
[hartës së ndikimit dhe kontrolleve](docs/change-impact-checklist.md).

- Identifiko kategorinë e ndryshimit dhe faqet, API-të, raportet dhe eksportet që
  e përdorin të njëjtën të dhënë ose sjellje. Verifiko varësitë në kodin aktual.
- Për çdo ndryshim funksional ose vizual në aplikacion, njofto përdoruesin për
  faqet dhe raportet e tjera të prekura, pasi të verifikosh lidhjet në kod dhe
  para përgjigjes përfundimtare. Kjo vlen edhe për ngjyra, CSS, filtra, etiketa
  dhe printim; mos e anashkalo si “ndryshim lokal” ose “vetëm vizual”.
- Kur ka vende të tjera të prekura dhe shtrirja atje nuk është miratuar tashmë,
  pyet një herë, shkurt, duke i emërtuar konkretisht. Pyetja kërkohet edhe nëse
  përdoruesi ka përmendur vetëm faqen fillestare:
  **“Ky ndryshim prek edhe [faqet]. Dëshiron ta zbatojmë edhe atje, apo t'i lëmë
  vetëm për kontroll?”**
- Përmendja e një faqeje të vetme nuk përjashton vetvetiu faqet e lidhura.
  Nëse përdoruesi thotë shprehimisht “vetëm Common View” ose kufizon ndryshe
  shtrirjen, respektoje pa pyetur përsëri; megjithatë trego shkurt ndikimin te
  vendet e tjera dhe se ato nuk u ndryshuan.
- Nëse përdoruesi ka kërkuar zbatim gjithkund ose e ka miratuar tashmë shtrirjen,
  vazhdo pa kërkuar konfirmim përsëri dhe trego ku zbatohet. Përfundo punën e
  pavarur të autorizuar ndërsa pret përgjigjen për pjesën shtesë; mos e zgjero
  implementimin në vende të pamiratuara. Nëse nuk gjenden vende të tjera të
  prekura, thuaje shkurt dhe mos bëj pyetje pa nevojë.
- Për shembull, për ndryshimin e ngjyrës së BLL në Common View, kontrollo edhe
  paraqitjen dhe printimin përkatës në 1H SHTYPI Today/Tomorrow dhe raportet që
  shfaqin BLL. Mos deklaro përhapje automatike kur stilet janë të veçanta.
- Leximi ose përditësimi i hartës nuk e zëvendëson njoftimin dhe pyetjen ndaj
  përdoruesit. Mos e mbyll punën pa këtë komunikim kur ka ndikim të lidhur.
- “Vetëm për kontroll” do të thotë verifikim pa zgjeruar implementimin. Raporto
  mospërputhjet; mos e paraqit kontrollin e papërfunduar si të kryer.
- `Department Views` përfshin Development, Graphic Design dhe Product Content;
  kontrollo secilin implementim dhe mënyrën My View kur aplikohet. Finance është
  kontroll më vete. `M1 / M2 / M3` kërkon kontroll të të tre raporteve përkatëse.
- Në fund jep shkurt çfarë u ndryshua, ku u kontrollua dhe çfarë mbetet për kontroll.
  Kur zbulohet një varësi e re, përditëso hartën që të mos harrohet herën tjetër.

Këto udhëzime ruajnë marrëveshjen me përdoruesin për kontrollin e ndryshimeve
ndërmjet faqeve. Kërkesa konkrete e përdoruesit përcakton shtrirjen e punës.
