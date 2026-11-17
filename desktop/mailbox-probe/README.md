# Local Outlook mailbox read probe

Portable WinForms utility for the manager's Windows laptop. This is separate
from the Graph mailbox integration and never calls a PrimeFlow API. It requires
the manager's already open **classic Outlook** profile; no password, Python,
admin-center access, installation or backend deployment is needed by the user.
Company endpoint controls or Outlook policy may still block the probe; do not
disable those controls. Distribution executable is unsigned.

Package v1.1 (up to 50 emails): `output/PrimeFlow-Outlook-Test-50.zip`. User instructions are in
`LEXO-PARA.txt` in Albanian. Copy the ZIP to the manager's laptop, extract it,
open classic Outlook's target Inbox, run the EXE normally and click **Provo leximin**.
Return only the **Kopjo diagnostikën pa përmbajtje** text. It omits subjects,
senders, body text, entry IDs and category names. It writes to the clipboard
only when that button is clicked; there is no automatic export or persistence.

## Read boundaries

- `Marshal.GetActiveObject("Outlook.Application")` attaches to an existing
  Outlook instance on a dedicated STA thread. There is no instance creation,
  `Logon`, token/cookie/credential reading, `Quit` or profile modification.
- Select the target by exact case-insensitive account SMTP (`info@primexeu.com`)
  and Exchange account type. If not found, examine store-owner identity using
  `PR_MAILBOX_OWNER_ENTRYID` and `GetExchangeUser().PrimarySmtpAddress`.
  This fallback may be unsupported on some profiles; failure stops safely.
  No display-name matching or default personal Inbox fallback is allowed.
- Reject ambiguous or non-Exchange stores. ExchangeStoreType is a local
  Outlook store classification, **not** proof of UserMailbox/SharedMailbox.
- Read `Store.Categories`, not the session's default category list, then the
  store's `GetDefaultFolder(6)` Inbox. Sort its Items collection by received
  time descending, skip items whose Class is not MailItem (43), return at most
  fifty MailItems. Stop with an incomplete-result warning if more than 1,000
  non-email items must be scanned. No store/message save operation is used.
- Read subject, sender display name, received time, category string and UnRead
  without assigning those properties. Optional body text is off by default;
  explicit opt-in reads plain text and displays up to 400 characters per email.
  HTML, links, attachments and active email content are not rendered/executed.
- Display Outlook's offline/connection status with a local-cache qualification.
  This does not force server sync or prove freshness. Empty collections are
  valid reads; partial failures never claim overall success.
- `LOCAL_READ_OK` means both local categories and Inbox were read. It does not
  mean Graph authorization, cloud integration, mailbox type verification or
  successful unattended execution on a server. No network uploader, timer,
  autostart, Claude, category writes, PX Notes or task creation exists here.
- COM calls can wait for Outlook's own dialogs. The UI remains responsive but
  does not let users close the form until its worker completes; dismiss the
  Outlook request if present. No automated response to security/auth dialogs.

## Build and verify

On Windows with .NET Framework v4 and its bundled C# compiler:

```powershell
& ./desktop/mailbox-probe/verify.ps1
& ./desktop/mailbox-probe/build.ps1
```

No package downloads or execution-policy changes are required. If enterprise
policy blocks scripts/executables, have IT review them through its normal process.
Build outputs an AnyCPU EXE, instructions, SHA256 file and ZIP. It uses Windows'
.NET Framework and late-bound COM, without shipping an Office interop dependency.

Eleven tests use fake read objects: exact identity, ambiguous/missing/wrong
mailbox, Exchange-owner fallback, latest-fifty sorting, non-email skipping, read
state preservation, empty results, category access denial, optional plain text,
offline status and content-free diagnostics. The test renderer captures only
this program's controls with synthetic messages; it does not access Outlook.
Real acceptance remains pending on the manager's laptop, including account/owner
matching compatibility, programmatic-access policy and cache freshness.

The probe has no dependencies on the PrimeFlow web admin page, Calendar,
PX Notes, tasks or reports. They do not consume the local result.

Microsoft references:
[Store categories](https://learn.microsoft.com/en-us/office/vba/api/outlook.store.categories),
[Items.Sort](https://learn.microsoft.com/en-us/office/vba/api/outlook.items.sort),
[Outlook object-model security](https://learn.microsoft.com/en-us/office/vba/outlook/how-to/security/security-behavior-of-the-outlook-object-model),
[API selection and desktop context](https://learn.microsoft.com/en-us/office/client-developer/outlook/selecting-an-api-or-technology-for-developing-solutions-for-outlook).
