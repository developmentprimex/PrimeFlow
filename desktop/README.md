# Mira për Windows

Merr shënime nga Discord Group DM, Teams, Zoom ose një program tjetër që
dëgjohet në pajisjen e zgjedhur të kompjuterit. Mira nuk flet dhe nuk ka nevojë
të hyjë si bot në thirrje. Nuk identifikon folësit. Botin ekzistues Discord nuk
e ndryshon dhe nuk e përdor për kapjen e audios.

## Përdorimi

1. Shpaketo **gjithë** dosjen `Mira` dhe hap `Mira.exe`. Mbaje `_internal`
   pranë skedarit EXE. Ky është program portativ për Windows x64, jo instalues.
2. Hyr me emailin dhe fjalëkalimin e PrimeFlow. Adresa e API-së është
   `https://api-flow.primexeu.com`; PX Notes hapet te `https://primeflow.primexeu.com`.
   Për një instalim tjetër vendos adresën e tij të API-së. Kërkohet server HTTPS me
   migration `0165_mira_desktop` dhe API-n e re të aktivizuar.
3. Zgjidh kufjet/altoparlantin që përdor thirrja dhe mikrofonin tënd. Pajisja
   mund të ndryshojë kur kufjet Bluetooth kalojnë në modalitet thirrjeje:
   hape thirrjen fillimisht, pastaj **Rilexo pajisjet** dhe zgjidh pajisjen e saktë.
4. Njoftoji pjesëmarrësit, konfirmo kutinë dhe shtyp **Fillo shënimet**.
5. Kontrollo që indikatorët **Thirrja** dhe **Mikrofoni** lëvizin kur dëgjohen
   zërat përkatës. Nëse ndryshon pajisjen gjatë takimit, përfundo dhe nis një
   takim tjetër me pajisjen e re.
6. Shtyp **Përfundo**. Transkripti përpunohet dhe shënimet ruhen një herë në PX Notes.
   Mund t'i kopjosh ose të hapësh listën PX Notes. Heshtja nuk krijon shënime.

Kapet **gjithë audioja e pajisjes së zgjedhur**, përfshirë njoftime ose muzikë
nga programe të tjera. Përdor kufje për të shmangur futjen e zërit të thirrjes
përsëri nga mikrofoni. Asnjë regjistrim nuk fillon automatikisht.

## Ndërprerjet dhe të dhënat

Audioja ndahet në segmente deri 10 sekonda. Pjesët që presin dërgimin dhe
transkripti lokal enkriptohen me Windows DPAPI, të lidhura me përdoruesin e
Windows-it, te `%LOCALAPPDATA%\PrimeFlow\Mira`. Fjalëkalimi dhe tokenët nuk
ruhen në disk. Audioja lokale fshihet pas konfirmimit të transkriptimit;
serveri ruan tekstin dhe shënimet, jo skedarët audio.

Në mungesë interneti, radha lokale vazhdon deri 512 MiB. Dëgjimi ndalet me
mesazh nëse radha mbushet, pajisja shkëputet ose kapja dështon. Kufiri i një
takimi është 4 orë. Pas mbylljes/rinisjes, hyr në të njëjtën llogari dhe zgjidh
takimin nga lista **Hap / vazhdo ruajtjen**. Kjo dërgon pjesët e ruajtura;
nuk rinis mikrofonin. Audio e humbur gjatë ndërprerjes nuk rikrijohet.

Ndryshimi i kompjuterit ose përdoruesit Windows nuk transferon çelësat DPAPI.
Përpara se të fshish dosjen lokale, përfundo ruajtjen e takimeve në pritje.
Serveri lejon 3 takime të papërfunduara dhe 24 nisje në 24 orë për përdorues.
Një nisje me pajisje të dështuara mund të përfundohet nga lista e rikuperimit,
edhe pa segmente, për të liruar kuotën.

## Ndërtimi

Kërkohet Windows x64 dhe Python 3.12 me Tkinter:

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

Rezultati: `output/mira-windows/Mira/Mira.exe`. Varësitë instalohen në
`desktop/.venv`. Për ta nisur nga kodi pas instalimit përdor `desktop/start.cmd`.
Programi nuk është i nënshkruar me certifikatë publikimi.

## Backend: aktivizim i veçuar

Publiko vetëm skedarët e rinj `mira_desktop` (model/schema/service/router),
regjistrimin e router-it/modelit dhe migration `0165_mira_desktop`. Kërkohet
`OPENAI_API_KEY`; përdoren modelet ekzistuese të transkriptimit dhe shënimeve.
Ky shërbim nuk varet nga `DISCORD_MEETING_NOTES_ENABLED`.

```powershell
cd backend
python -m alembic upgrade 0165_mira_desktop
```

Pastaj rinis proceset API që shërbejnë PrimeFlow. Nuk kërkohet rinisje e botit
Discord ose ndryshim te oraret/kanalet e tij. Ndryshimet e mëparshme të
papublikuara për hyrjen automatike 1H janë punë më vete dhe nuk përfshihen
automatikisht në këtë aktivizim.

Verifiko `GET /api/mira-desktop/capabilities` me një përdorues të autentikuar,
pastaj një takim të shkurtër prove me njoftim pjesëmarrësish. Kontrollo tekstin,
një PX Note, dhe rikuperimin pas ndërprerjes së internetit. Ende nevojitet ky
verifikim real me pajisjet/thirrjet e përdoruesit; testet sintetike nuk e zëvendësojnë.

## Testet

```powershell
$env:PYTHONPATH='desktop'
python -m unittest discover -s desktop/tests -v
```

Backend: `backend/tests/test_mira_desktop*.py`. Integrimi pranon vetëm një
databazë lokale, të veçuar, me emrin `mira_desktop_test`; nuk përdor databazën
e prodhimit. Testet mbulojnë kufijtë e audios, autentikimin/pronësinë, migrimin,
përsëritjet, konkurrencën, rikuperimin dhe ruajtjen vetëm një herë të shënimeve.

Burimet e kapjes: [Windows WASAPI loopback](https://learn.microsoft.com/windows/win32/coreaudio/loopback-recording)
dhe [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch).
