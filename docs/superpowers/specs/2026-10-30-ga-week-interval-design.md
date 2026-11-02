# Household recurrence by week interval

The existing selected-weekday schedule must support an optional start date and interval in calendar weeks. Rotation ownership still comes from the existing configured day owner. Timing remains optional and an untimed recurrence must never create an alarm.

Use `recurrence_interval_weeks` (default 1, integer 1–52) and `recurrence_anchor_date` (optional date) in the existing private JSON definition. An interval greater than one requires an anchor and a weekly or selected-weekday frequency. Compare Monday-based calendar weeks in Europe/Belgrade, reject dates before the anchor, and generate only selected weekdays in matching weeks. Existing definitions behave exactly as before.

The alternative of precreating one-off tasks indefinitely does not represent a lasting recurrence. No new scheduler or database migration is needed: the existing generation worker applies the stored rule. Tablets must receive dated occurrences for interval schedules to avoid locally assuming a weekly recurrence. The existing template editor must retain and expose the two values.

Validate anchor/interval pairing, the date boundary, skip weeks, year and daylight-saving boundaries, ownership, idempotence, untimed tablet cards, and legacy definitions. Household identities and source instructions stay outside Git.
