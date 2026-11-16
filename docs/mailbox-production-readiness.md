# Microsoft 365 mailbox connection — production readiness

## Local follow-up — 2026-11-16

The production observations below are a historical snapshot from November 9;
they have not been rechecked against the live server in this follow-up.
The current checkout also contains migrations `0188_meeting_note_manual_status`
and `0189_two_task_markers`. Before release, inspect the actual deployed Alembic
revision and the release head; do not assume that the older `0186` → `0187`
transition below describes the next deployment.

Local validation on November 16: the production frontend build, separate
TypeScript check, focused shared-marker lint and both mocked mailbox browser
tests passed. All 21 browser tests for direct/per-assignee task markers, both
marker synchronization unit tests and the 17 backend mailbox tests also passed.
These checks do not establish Microsoft authorization or live mailbox access.
The Outlook probe verification script was blocked by this workstation's
PowerShell execution policy; no policy was changed. Real Outlook acceptance
on the manager's laptop and production Microsoft 365 acceptance remain pending.

## Production snapshot — 2026-11-09

Audited on 2026-11-09, approximately 07:51 UTC. This is a preparation report;
**info@primexeu.com is not connected or verified for email reading.** Production
checks used read-only SQL and Microsoft Graph GETs. No deployment, migration,
permission grant, mailbox change, classification, Note or task creation occurred.

## Verified production state

| Item | Observation |
|---|---|
| Production UI | `https://primeflow.primexeu.com/admin/email` returns 404 |
| Production API | `/api/mailbox/status` and `/api/mailbox/callback` on `https://api-flow.primexeu.com` return 404 |
| Database revision | `0186_meeting_clients` |
| Mailbox table | `mailbox_connections` does not exist |
| Server implementation | Mailbox router, integration, model and migration not deployed |
| Latest deployment workflow inspected | Run 1097, commit `59496a675d0a43568fedfa77a0965fa50337fb37`, completed successfully; no active job among the three latest runs inspected |
| Runtime dependency | Server Python 3.13 has the `cryptography` package directory |
| Mailbox environment | `MS_MAILBOX_EMAIL`, `MS_MAIL_REDIRECT_URI`, `MS_MAIL_TOKEN_KEY_FILE` not configured in the production `.env` |
| Existing client secret | Present; app credential metadata expires 2028-09-03 (not proof of future validity) |
| Existing Calendar token scopes | `Calendars.ReadWrite`, `User.Read`, plus identity scopes; no mailbox read scope shown |
| Mailbox type | **Unverified**: Graph `GET /users/info@primexeu.com/mailboxSettings/userPurpose` returned 403 `ErrorAccessDenied` |
| Delegated consent grants | **Unverified**: directory grant listing returned 403 `Authorization_RequestDenied` |
| Application permission assignments | App's `appRoleAssignments` returned an empty list |

Microsoft app authentication succeeded to inspect its own app registration.
That success is **not** mailbox authorization or an email read. Browser inspection
stopped because the computer-use safeguard could not verify the current URL.
The user indicated that an administrator must check the mailbox type.

## Exact Entra application and callback

| Setting | Verified/current value or required addition |
|---|---|
| Tenant/directory ID | `6f589b44-4ed4-43ac-8cfa-8a7f5ff8fe95` |
| Display name | **PrimeFlow Calendar** |
| Application/client ID | `c65ef790-0911-492c-b6ac-b1124269cca6` |
| Application object ID | `d75de240-8cdc-4999-b2f7-b1a04b2dc7a5` |
| Enterprise-app/service-principal object ID | `82a1b5b8-484d-4eaf-a51d-51aa24dcfebc` |
| Supported account types | `AzureADMyOrg` — this tenant only |
| Existing Web redirect, retain | `https://api-flow.primexeu.com/api/microsoft/callback` |
| **Additional Web redirect, exact** | **`https://api-flow.primexeu.com/api/mailbox/callback`** |
| Frontend after callback | `https://primeflow.primexeu.com/admin/email` |
| Implicit access/ID token issuance | Both currently disabled; leave disabled |

The new callback is a **Web** redirect, not an SPA/native callback. Do not replace
the Calendar callback. The admin-page URL is not the OAuth callback. Scheme, host,
path and case must match the authorize/token requests; no trailing slash.

For a confirmed **UserMailbox**, configure Microsoft Graph **Delegated** permissions:

| Permission | Scope ID | Current app manifest | Action |
|---|---|---|---|
| `User.Read` | `e1fe6dd8-ba31-4d61-89e7-88639da4683d` | Present | Retain |
| `offline_access` | `7427e0e9-2fba-42fe-b0c0-848c9e6a8182` | Present | Retain; OAuth requests it for refresh tokens |
| `Mail.Read` | `570282fd-fa5c-430d-a7fd-fc8dc98a9dca` | **Absent** | Add as Delegated |
| `MailboxSettings.Read` | `87f447af-9fa4-4c32-9dfa-4a57a73d18ce` | **Absent** | Add as Delegated |
| `Calendars.ReadWrite` | `1ec239c2-d7c9-4623-a91a-a9775856bb36` | Present | Retain for Calendar; mailbox flow does not request it |

Graph resource application ID is `00000003-0000-0000-c000-000000000000`.
The app manifest lists requested permissions; it does not prove that consent has
been granted. Do not add Application permissions, Mail.ReadWrite, Mail.Send or
MailboxSettings.ReadWrite for this user-mailbox step.

## Administrator sequence

1. In **Exchange admin center → Recipients → Mailboxes**, locate
   `info@primexeu.com` and record **Recipient type**. Alternatively, in an
   already authorized Exchange Online PowerShell session:

   ```powershell
   Get-EXOMailbox -Identity info@primexeu.com |
     Select-Object PrimarySmtpAddress,RecipientTypeDetails
   ```

   Continue with the current implementation only for `UserMailbox`. Do not
   convert a shared mailbox or enable its direct sign-in to make this flow work.
2. In Entra, select the exact tenant/app ID above. Under **Authentication → Web**
   add the mailbox callback alongside the existing Calendar callback. Under
   **API permissions → Add a permission → Microsoft Graph → Delegated**, add the
   two missing read permissions. Preserve existing Calendar configuration/consent.
3. Review consent policy and existing grants in the enterprise app. Prefer the
   sign-in user's consent for the read scopes if permitted. If the tenant requires
   an administrator, use its approved admin-consent workflow. Review the scope
   and account coverage before granting: the app also contains the existing
   Calendar permission. Do not blindly grant new tenant-wide Calendar access or
   replace/remove an existing Calendar grant. The mailbox OAuth request is only
   `offline_access User.Read Mail.Read MailboxSettings.Read`.
4. Release **only mailbox-related changes** after normal checks. Do not include
   the unrelated dirty Department View files. Production backend working directory
   is `C:\actions-runner\_work\PrimeFlow\PrimeFlow\backend`. Expected transition
   is exactly `0186_meeting_clients` → `0187_mailbox_connection`; its upgrade only
   creates `mailbox_connections` and advances the Alembic revision. The deployment
   schema verifier now checks its nine columns. Apply the migration through the
   normal deployment path; do not stamp or reset unrelated schema.
5. Provision the dedicated encryption key on the server, using the production
   Python interpreter and an elevated Administrator/SYSTEM session:

   ```powershell
   & 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe' `
     scripts/init_mailbox_token_key.py --path C:/PrimeFlowData/Mailbox/token.key
   ```

   Run from the backend working directory after the script is deployed. This
   creates a persistent Fernet key without printing it, protects the dedicated
   directory for Administrators and SYSTEM, and validates rather than replaces
   an existing key. Verify the actual backend service identities can read it.
   Use a new dedicated directory; review any existing explicit ACLs separately.
   Back up the key privately, outside Git/DB/logs. Do not regenerate it on deploy.

   The release workflow now writes:

   ```dotenv
   MS_MAILBOX_EMAIL=info@primexeu.com
   MS_MAIL_REDIRECT_URI=https://api-flow.primexeu.com/api/mailbox/callback
   MS_MAIL_TOKEN_KEY_FILE=C:/PrimeFlowData/Mailbox/token.key
   FRONTEND_URL=https://primeflow.primexeu.com
   ```

   Existing MS_CLIENT_ID/MS_TENANT_ID/MS_CLIENT_SECRET stay in place. No new
   client secret is required. The API refuses authorization/reads if the key is
   unavailable. The prior JWT-derived encryption was removed because the current
   deployment embeds its JWT secret in tracked source; this change does not rotate
   that shared secret or alter Calendar authentication.
6. After deployment, confirm the admin page loads, mailbox status is restricted
   to ADMIN, `encryption_ready=true`, and `authorized=false`, `connected=false`.
   An unauthenticated status request should be rejected rather than return 404.
   Click **Lidh Microsoft 365** in the same browser and sign in to the confirmed
   user mailbox `info@primexeu.com`. The administrator/user performs sign-in,
   MFA and permission approval. Never send a password/client secret to chat.

If Exchange reports **SharedMailbox**, stop before step 2's delegated-mail
authorization. The current `/me` implementation is not a shared-mailbox flow.
Delegated `Mail.Read.Shared` can read shared messages, but that alone does not
establish access to the shared mailbox's master category settings. A separate,
explicitly scoped design is required for both resources, for example a dedicated
app with Exchange Application RBAC roles `Application Mail.Read` and
`Application MailboxSettings.Read`, limited to this one mailbox. Do not add
unrestricted tenant-wide Application permissions or change Calendar to work around
this. No shared-mailbox app, roles or grants have been created here.

## Acceptance after real authorization

The callback verifies `/me` matches `info@primexeu.com`, then reads
`/me/mailboxSettings/userPurpose`. It stores the connection only if that is `user`.
It stores `mailbox_type=user` with encrypted tokens. This still yields only
`authorized=true`, **`connected=false`**, `last_checked_at=null`.

On the real production admin page, click **Provo leximin** and require successful
Graph responses for both of these resources:

```http
GET https://graph.microsoft.com/v1.0/me/outlook/masterCategories
GET https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$top=10&$orderby=receivedDateTime desc&$select=id,subject,from,receivedDateTime,bodyPreview,categories,hasAttachments,isRead
```

Follow category pagination. Verify that the displayed category names are the
mailbox's existing categories and that the page shows the ten newest received
Inbox messages, or all messages if fewer than ten exist. Record the mailbox,
verification time, category count and message count, without copying email bodies
or credentials into logs. Only after both reads succeed is `last_checked_at`
recorded and `connected=true`. Failure leaves first-time verification unset.

These Graph calls are GET-only; there is no PATCH/POST/DELETE to mail, category
or message endpoints. Token exchanges POST only to Microsoft's OAuth token
endpoint. No mark-read call occurs. Outlook `isRead` and categories are displayed
as returned; other Outlook clients may independently change mailbox state.
No message content is persisted in PrimeFlow's database or sent to an AI model.

## Separation and checks

| Layer | Mailbox | Calendar |
|---|---|---|
| Routes | `/mailbox/*` | `/microsoft/*` |
| OAuth callback | `/api/mailbox/callback` | `/api/microsoft/callback` |
| State type / cookie | `mailbox_oauth` / `primeflow_mailbox_oauth` | Existing Calendar flow unchanged |
| Tokens | Encrypted in `mailbox_connections` | Existing `microsoft_tokens`, unchanged |
| Encryption key | Dedicated persistent key file | Unchanged |
| Requested resource scopes | Mail.Read, MailboxSettings.Read, User.Read | Calendars.ReadWrite, User.Read |
| Entra app/client secret | **Shared existing app identity** | **Same existing app identity** |
| Background work | None | Existing Calendar scheduler, unchanged |

The related Development Calendar, Meeting Scheduler and Calendar sync were
checked for code dependencies; they do not consume `mailbox_connections`.
Mailbox disconnect deletes only its own row and does not revoke app-wide consent.
PX Notes, task tables, reports and classification workers are outside this flow.

Preparation validation: 34 backend mailbox/auth/encryption, Calendar retry and
migration-graph tests passed; offline SQL generation and focused frontend lint
passed. Two simulated browser tests passed, including desktop/mobile, staff access,
escaped email text, the authorization/verification distinction and disconnect.
These do not replace the pending production build/deployment and real acceptance test.

Latest deployment workflow inspected:
[Run 1097](https://github.com/developmentprimex/PrimeFlow/actions/runs/42234333009).

Microsoft references:
[Mailbox purpose](https://learn.microsoft.com/en-us/graph/api/user-get-mailboxsettings?view=graph-rest-1.0),
[Permission definitions](https://learn.microsoft.com/en-us/graph/permissions-reference),
[Categories](https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories?view=graph-rest-1.0),
[Messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0),
[Shared mailboxes](https://learn.microsoft.com/en-us/Exchange/collaboration/shared-mailboxes/shared-mailboxes),
[Scoped application access](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac),
[Redirect URI matching](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url).
