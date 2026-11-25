# GA Time Table — iPhone Calendar dhe Reminders

Calendar dhe Reminders importohen nga iPhone. Për kryerjen e një reminder-i,
PrimeFlow ruan kërkesën derisa Shortcut-i ta kryejë në iPhone dhe ta konfirmojë.

## Burimet e lejuara

- Calendar: `ganimete.ar@gmail.com`
- Reminders list: `REMINDER`
- Timezone: `Europe/Berlin`

Serveri refuzon emra të tjerë edhe nëse Shortcut-i dërgon të dhëna nga një listë
ose kalendar tjetër. Të dhënat e së shtunës dhe së dielës anashkalohen, sepse GA
Time Table paraqet javën e punës nga e hëna në të premte.

## 1. Aktivizimi në PrimeFlow

1. Kryej migrimin e databazës: `alembic upgrade head`.
2. Hape **Admin Tasks → GA Time Table → iPhone Sync**.
3. Kontrollo emrin e Calendar-it dhe listës së Reminders.
4. Shtyp **Create pairing**.
5. Kopjo `Import URL` dhe `Pairing token`. Token-i shfaqet vetëm një herë.

Krijimi i një token-i të ri revokon token-in e vjetër. **Disconnect** revokon
token-in dhe heq nga Time Table të gjitha hyrjet që janë importuar nga telefoni.

## 2. Shortcut-i në iPhone

Krijo një Shortcut të ri me emrin `PrimeFlow GA Sync`.

### A. Intervali i sinkronizimit

1. Merr `Current Date`.
2. Krijo `Window Start` duke zbritur 7 ditë.
3. Krijo `Window End` duke shtuar 60 ditë.
4. Formato të dyja si `yyyy-MM-dd`.

Intervali i dërguar nuk mund të jetë më i gjatë se 93 ditë.

### B. Calendar events

1. Përdor **Find Calendar Events**.
2. Vendos filtrat:
   - Calendar is `ganimete.ar@gmail.com`
   - Start Date është ndërmjet `Window Start` dhe `Window End`
3. Për çdo event, krijo një Dictionary me:
   - `title`: Title
   - `starts_at`: Start Date i formatuar ISO 8601
   - `ends_at`: End Date i formatuar ISO 8601
   - `is_all_day`: Is All Day
   - `calendar_name`: `ganimete.ar@gmail.com`
   - `location`: Location (opsionale)
   - `id`: Identifier, nëse ky detail shfaqet në versionin e iOS-it
4. Shto çdo Dictionary në variablën-listë `Events`.

### C. Reminders

1. Përdor **Find Reminders**.
2. Vendos filtrat:
   - List is `REMINDER`
3. Për çdo reminder, krijo një Dictionary me:
   - `title`: Title
   - `due_at`: Due Date i formatuar ISO 8601, vetëm kur ka datë dhe orë
   - `due_date`: Due Date i formatuar `yyyy-MM-dd`, kur ka vetëm datë
   - `is_completed`: Is Completed
   - `reminder_list_name`: `REMINDER`
   - `notes`: Notes (opsionale)
   - `id`: Identifier, nëse ky detail shfaqet në versionin e iOS-it
4. Shto çdo Dictionary në variablën-listë `Reminders`.

Reminder-at pa datë lejohen; ata shfaqen në rreshtin pa orë të ditës kur fillon
intervali i sinkronizimit.

### D. Kërkesa në PrimeFlow

1. Krijo Dictionary-n kryesor:

```json
{
  "sync_window_start": "Window Start (yyyy-MM-dd)",
  "sync_window_end": "Window End (yyyy-MM-dd)",
  "timezone": "Europe/Berlin",
  "calendar_name": "ganimete.ar@gmail.com",
  "reminder_list_name": "REMINDER",
  "events": "Events variable",
  "reminders": "Reminders variable"
}
```

2. Shto **Get Contents of URL**:
   - URL: `Import URL` nga PrimeFlow
   - Method: `POST`
   - Request Body: `JSON`
   - JSON: Dictionary kryesor
   - Header: `X-PrimeFlow-Sync-Token` = `Pairing token`
3. Shto **Show Result** vetëm gjatë testit të parë.

Një përgjigje e suksesshme ka këtë formë:

```json
{
  "imported": 12,
  "calendar_imported": 7,
  "reminders_imported": 5,
  "skipped": 0,
  "synced_at": "2026-09-03T10:00:00Z"
}
```

### E. Kryerja e kërkesave nga PrimeFlow

1. Para importit, bëj **GET** te `/api/ga-time-slots/icloud-sync/completed`
   me të njëjtin host dhe header `X-PrimeFlow-Sync-Token` si importi.
2. Për çdo element, kërko në listën e çiftuar reminder-in me titullin `title`
   dhe datën `due_at`. Krahaso orët si data, përfshirë zonën kohore.
   Një vlerë `YYYY-MM-DD` vlen për reminder me vetëm datë. `null` vlen
   për reminder pa datë. Vazhdo kur përputhet saktësisht një reminder,
   edhe kur ai tashmë rezulton i kryer në telefon.
3. Përdor **Edit Reminder** për ta shënuar si të kryer dhe mblidh `id`
   e kërkesës pasi Reminder-i të rezultojë i kryer. Lëri të pakonfirmuara
   kërkesat që dështuan ose patën më shumë se një përputhje.
4. Bëj **POST** te `/api/ga-time-slots/icloud-sync/completed/ack`
   me të njëjtin header dhe JSON `{"ids": [...]}`. Dërgo më pas importin
   si zakonisht. Kërkesat e konfirmuara largohen nga radha, edhe pas një importi
   që ende i raporton si të hapura.

Për reminder-at e importuar para këtij përditësimi, ekzekuto importin një herë
që PrimeFlow të ketë titullin dhe datën e origjinës.

## 3. Lejet dhe testi

1. Ekzekuto Shortcut-in manualisht.
2. Kur iPhone pyet, jep leje për Calendar, Reminders dhe lidhjen me PrimeFlow.
3. Në PrimeFlow, hap javën përkatëse te GA Time Table.
4. Calendar shfaqet me sfond të kaltër. Reminders e hapur kanë sfond të verdhë;
   ata të kryer kanë sfond të gjelbër dhe shenjën `✓ Done` në tabelë dhe në printim.
5. Eventet/reminders me orë vendosen në rreshtin përkatës. Ata pa orë vendosen
   në rreshtin e posaçëm pa orë të asaj date.

## 4. Automatizimi

Pasi testi manual kalon:

1. Hape **Shortcuts → Automation → New Automation**.
2. Zgjidh **App**, pastaj Calendar dhe Reminders, me trigger **Is Closed**.
3. Zgjidh **Run Immediately** dhe ekzekuto `PrimeFlow GA Sync`.
4. Shto edhe një automation **Time of Day** në mëngjes si kontroll rezervë.

Personal automation është specifik për atë iPhone; nuk duhet konfiguruar në
pajisjet e tjera.

## Siguria

- Mos e dërgo token-in me email ose chat.
- Mos vendos Apple Account password, Gmail password ose kod MFA në Shortcut.
- Nëse telefoni humbet ose token-i ekspozohet, përdor menjëherë **Disconnect**
  dhe krijo një pairing të ri.
