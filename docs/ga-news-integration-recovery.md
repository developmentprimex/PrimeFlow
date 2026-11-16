# GA Time Table attachment recovery — 2026-11-16

News runs separately from TaskManager in `F:/website/news-intelligence` on the
application server. Its GA attachment integration reads the Admin Tasks daily
print view and `/api/exports/ga-time.xlsx`. The scheduled News slots are 07:00
and 21:00 in Europe/Budapest.

The configured binding at
`E:/private/news-ga-morning-20261028/ga-timetable-binding.json` was missing.
Restoring that protected binding and its private cache repaired attachment
generation without modifying News source code, recipients, schedules, or the
TaskManager application. The existing configuration reads this binding for each
export, so no application restart was needed.

Verification on 2026-11-16:

- PrimeFlow authentication succeeded for the bound GA account.
- A fresh daily PDF passed the existing date, one-page, comment-column and final
  row checks: 57,589 bytes.
- A fresh daily Excel passed the existing date, four-column and frozen printed
  row checks: 7,009 bytes.
- The scheduled morning attachment function returned both files after activation;
  the evening attachment phase remained enabled.
- News scheduler, digest and GA exporter source hashes remained unchanged.
- Verification sent no email. Automatic SMTP delivery remains a separate check.

The private server-side verification record is
`E:/private/news-ga-morning-20261028/repair-20261116.json`.

When moving News or PrimeFlow, verify the configured binding path, PrimeFlow
Python/backend, browser executable, private cache and runtime account permissions.
Do not assume moving the application folder also moves this external binding.
Morning and evening use separate cache directories. Keep investigation of News
delivery-on-export-failure separate from repairing the attachment export; this
recovery did not change that behavior.
