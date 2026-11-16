# Lidhja e email-it — hapi 1

Faqja `/admin/email` (Administration → Lidhja e email-it) lejon vetëm ADMIN të
lidhë `info@primexeu.com` me Microsoft 365 dhe të provojë leximin e kategorive
dhe deri në 10 mesazheve më të reja në **Inbox**. Email-et në dosje të tjera
nuk përfshihen në këtë provë. Pamja tregon subjektin, dërguesin, datën, një
fragment dhe kategoritë e mesazhit; nuk shkarkon bashkëngjitje.

Ky hap nuk krijon PX Notes, taska ose klasifikim me AI. Nuk ndryshon kategori,
nuk shënon email-e si të lexuara dhe nuk aktivizon sinkronizim në sfond.
Fragmentet shfaqen vetëm pas klikimit **Provo leximin**, pa u ruajtur në DB.

## Konfigurimi

Përdor të njëjtin tenant/app registration Microsoft që konfigurohet nga
`MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID`, por një OAuth callback dhe
një lidhje DB të veçantë. Nuk ndryshon scopes, tokenat ose callback-un e kalendarit.

1. Apliko migrimin `0187_mailbox_connection` përmes rrjedhës normale të deploy-it.
2. Në server vendos:

   ```dotenv
   MS_MAILBOX_EMAIL=info@primexeu.com
   MS_MAIL_REDIRECT_URI=https://api-flow.primexeu.com/api/mailbox/callback
   MS_MAIL_TOKEN_KEY_FILE=C:/PrimeFlowData/Mailbox/token.key
   ```

   Deploy-i normal i vendos këto tri vlera. Para autorizimit, përgatit çelësin
   në server me udhëzimet te `docs/mailbox-production-readiness.md`.
   `FRONTEND_URL` duhet të jetë adresa publike e frontend-it. Për lokal përdor
   callback-un `http://localhost:8000/api/mailbox/callback` dhe frontend-in lokal;
   host-i ku kërkohet authorize-url duhet të jetë i njëjtë me atë të callback-ut,
   që Microsoft të kthejë cookie-n e autorizimit.
3. Në Entra → App registrations → aplikacioni PrimeFlow → Authentication shto
   adresën e saktë të mësipërme si **Web Redirect URI**, krahas asaj të kalendarit.
4. API permissions → Microsoft Graph → **Delegated permissions**:
   `User.Read`, `Mail.Read`, `MailboxSettings.Read`. OAuth kërkon edhe
   `offline_access`. Nëse tenant-i kërkon miratim nga administratori, plotësoje.
5. Hape faqen si ADMIN, kliko **Lidh Microsoft 365**, hyr me llogarinë
   `info@primexeu.com` dhe mirato lejet e leximit.
6. Pas kthimit, kliko **Provo leximin**. Autorizimi i ruajtur dhe prova reale e
   leximit janë gjendje të veçanta; koha e kontrollit përditësohet vetëm pas
   leximit të suksesshëm të mesazheve dhe të kategorive.

Lloji i mailbox-it duhet konfirmuar nga administratori në Exchange para
autorizimit. Lidhja kërkon hyrje direkte me llogarinë e konfiguruar. Callback-u
kontrollon edhe `/me/mailboxSettings/userPurpose` dhe pranon vetëm `user`.
`shared`, `unknown`, room/equipment dhe llogaritë e tjera refuzohen para ruajtjes.
Shared mailbox kërkon rrjedhë tjetër; mos aktivizo hyrjen direkte të tij.

## Ndarja dhe ruajtja

- `/api/mailbox/*` mbrohen nga roli ADMIN, përveç OAuth callback-ut që kontrollon
  state-in e nënshkruar, afatin, cookie-n e shfletuesit dhe administratorin aktiv.
- Tokenat ruhen me Fernet te `mailbox_connections`, me çelës të veçantë te
  `MS_MAIL_TOKEN_KEY_FILE`, jashtë repository-t dhe DB-së. `JWT_SECRET` nuk
  përdoret për enkriptimin e tyre. Të gjitha instancat lexojnë të njëjtin skedar;
  ruaje në backup privat. Nuk gjenerohet/zëvendësohet automatikisht nga API-ja.
  Pa çelës të vlefshëm bllokohen autorizimi dhe leximi.
- `authorized` nënkupton vetëm autorizim të ruajtur. `connected` bëhet true
  vetëm pas një leximi real të suksesshëm të kategorive dhe Inbox-it, i shënuar
  te `last_checked_at`; ky është historiku i provës së fundit, jo health-check live.
- `microsoft_tokens`, Microsoft Calendar, Meeting Scheduler, Development dhe
  sinkronizimi i takimeve nuk lexojnë këtë tabelë.
- **Shkëput** fshin vetëm lidhjen lokale të email-it. Nuk revokon consent-in
  e aplikacionit në Microsoft dhe nuk shkëput kalendarin.
- Përmbajtja e email-eve nuk dërgohet te Claude ose ndonjë model tjetër në këtë hap.

Identiteti Entra dhe client secret-i janë ende të përbashkët me aplikacionin
**PrimeFlow Calendar**. Ndarja është te scopes e kërkuara, callback-u, cookie,
tabela/tokenat dhe çelësi i enkriptimit; nuk është aplikacion Entra i veçantë.

Verifikim lokal pa lexuar mailbox-in real:

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_mailbox_connection tests.test_microsoft_events_retry
```

Kontrolli i ndërfaqes me API të simuluar (pa email-e reale), duke përfshirë
desktop/mobile, kufizimin e stafit dhe shfaqjen e tekstit të email-it pa HTML aktiv:

```powershell
cd frontend
npx.cmd playwright test --config playwright.mailbox.config.ts
```

Nëse Chromium-i për versionin aktual të Playwright mungon, instalo browser-in
e tij ose cakto `MAILBOX_CHROMIUM_EXECUTABLE` te një Chromium ekzistues.

Referencat API:
[List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0),
[List masterCategories](https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories?view=graph-rest-1.0).
