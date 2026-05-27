# Procurios SEPA Mandate Import — Design

**Date:** 2026-05-27
**Author:** foppe
**Status:** Draft

## Background

Procurios offers a SEPA-mandate export separate from its general member export.
The existing `Procurios CSV Import` DocType handles the latter (creating Members
matched on `procurios_id`); this design adds a sibling tool that imports SEPA
Mandates and links them to existing Members.

**Hard constraint:** a mandate is imported only when a Member with the matching
`procurios_id` already exists in the system.

## CSV Layout

Delimiter: `;`. Columns (header + example row):

```
Incasso-afspraak ID;Type machtiging;Type machtiging ID;Mandaatnummer;IBAN;
Incassant;Incassant ID;Rekeninghouder;Debiteur naam;Debiteur ID;
Datum van ondertekening;Opzegdatum;Pre-notificatie datum;Administratie ID;Administratie
973;Doorlopend;2;40123603-V005064-00002;NL12TRIO0197963145;
Nederlandse Vereniging voor Veganisme;2;F.J. de Haan;Foppe de Haan;1484;
2015-06-18;2019-02-25;;1;Nederlandse Vereniging voor Veganisme
```

Expected volume: a few thousand rows per import.

## Approach

Add a new submittable DocType **`Procurios Mandate Import`** that mirrors the
existing `Procurios CSV Import` pattern: attach CSV → validate/preview →
submit → background job. It reuses `SecureCSVParser` and
`CSVImportBackgroundProcessor`.

A new validator class `ProcuriosMandateValidator` (sibling of
`ProcuriosDataValidator`) handles row-level parsing, CSV-shape validation, and
mapping.

**Rejected alternatives**
- *Extend the existing `Procurios CSV Import`* — couples two unrelated exports
  behind a type toggle and increases conditional branching across validator,
  processor, and tests.
- *Bench command / one-off script* — no preview, no audit trail, no progress
  tracking, no safe re-run.

## DocType Definition

Module: **Verenigingen Payments** (cohesive with `SEPA Mandate`).

| Section | Field | Type | Notes |
|---|---|---|---|
| — | `naming_series` | Select (hidden) | `PROC-MND-IMP-.YYYY.-.####.` |
| Import Configuration | `csv_file` | Attach (reqd) | |
| | `encoding` | Select | `auto-detect / utf-8 / utf-8-sig / iso-8859-1 / windows-1252` |
| | `csv_delimiter` | Select | `Comma / Semicolon / Tab` (default Semicolon) |
| | `test_mode` | Check | Process first 25 rows only |
| Data Preview | `preview_data` | Code (JSON, read-only) | First 5 mapped rows |
| Import Progress | `import_status` | Select (read-only) | `Pending / Validating / Ready for Import / Queued / In Progress / Completed / Failed` |
| | `progress_percentage` | Percent (read-only) | |
| | `rows_processed`, `total_rows` | Int (read-only) | |
| | `mandates_created`, `mandates_updated`, `mandates_skipped` | Int (read-only) | |
| | `last_processed_at` | Datetime (read-only) | |
| Error Log | `error_log` | Long Text (read-only) | First 50 row-level errors, truncated with summary |
| | `skipped_summary` | Small Text (read-only) | Per-reason breakdown (filtered / no member / duplicate / conflict / error) |
| Import Information | `import_date`, `descriptive_name` | Date, Data | |

- `is_submittable: 1`
- Permissions: `System Manager`, `Verenigingen Administrator` (same as
  `Procurios CSV Import`)
- `on_submit` enqueues the background processor on the `long` queue with
  timeout 3600s
- All progress fields use `allow_on_submit: 1` so the background job can
  update them via `db_set`

The cancelled-mandate cutoff is a **fixed 12 months**, expressed as a module
constant `CANCELLED_CUTOFF_MONTHS = 12` — not a user-editable field.

## CSV → SEPA Mandate Field Mapping

| CSV column | SEPA Mandate field | Mapping |
|---|---|---|
| `Mandaatnummer` | `mandate_id` | direct |
| `IBAN` | `iban` | direct; trimmed, uppercased |
| `Rekeninghouder` | `account_holder_name` | direct |
| `Debiteur ID` | — | match key → `Member.procurios_id` |
| `Debiteur naam` | — | display-only (error messages) |
| `Datum van ondertekening` | `sign_date` | ISO date |
| `Opzegdatum` | `cancelled_date` | ISO date when present; drives status |
| `Type machtiging` | `mandate_type` | `Doorlopend → RCUR`, `Eenmalig → OOFF`, default `RCUR` |
| `Incasso-afspraak ID`, `Administratie`, `Pre-notificatie datum` | `notes` | composed traceability note |
| `Incassant`, `Incassant ID`, `Administratie ID`, `Type machtiging ID` | — | ignored |

Constants on every created mandate:
- `scheme = "SEPA"`
- `used_for_memberships = 1`
- `bic` left blank (SEPA validation service derives or warns; not required)

The mandate's **status is not set explicitly** — the existing
`sepa_mandate_lifecycle_service.set_status_based_on_dates(...)` (invoked from
`SEPAMandate.validate`) derives it from the dates we provide:
- `cancelled_date` set → status becomes `Cancelled`
- `cancelled_date` blank → status becomes `Active`

This avoids fighting the lifecycle service and keeps the import consistent
with mandates created through the normal flow.

## Per-Row Decision Logic

Applied in order; first matching outcome wins:

1. **Classify by `Opzegdatum`:**
   - blank → *active*
   - within `CANCELLED_CUTOFF_MONTHS` of today → *recently-cancelled*
   - older than cutoff → **skip (reason: `filtered_old_cancelled`)**
2. **Match member:** `Debiteur ID → Member.procurios_id`. No match →
   **skip (`no_member`)**.
3. **Duplicate check** against existing `SEPA Mandate` with the same
   `mandate_id`:
   - exists + CSV row *recently-cancelled* → **update** existing mandate's
     `cancelled_date` (lifecycle service will flip status to `Cancelled` on
     save) → counter `mandates_updated`
   - exists + CSV row *active* → **skip (`duplicate`)**
   - none → continue
4. **Member-conflict check** (active rows only): if the matched Member
   already has any other `SEPA Mandate` with `status = Active`, **skip
   (`conflict`)**. Cancelled imports never conflict.
5. **Create** the `SEPA Mandate` document. `after_insert` on the mandate
   auto-creates the link row in `Member.sepa_mandates` via the existing
   `sepa_mandate_member_integration_service`.

Per-row failures (IBAN invalid, date parse error, framework exception) are
caught, sanitised via `sanitize_error_for_audit`, logged with row number and
Debiteur naam, and counted under `error`. They never abort the batch.

## Scaling to Thousands of Rows

The per-row logic must not issue per-row queries for matching, duplicate, or
conflict checks. Before the row loop the processor pre-builds three
in-memory caches with **one query each**:

| Cache | Source query | Used for |
|---|---|---|
| `procurios_id_to_member` | `frappe.get_all("Member", fields=["name","procurios_id"], filters={"procurios_id":["!=",""]})` | step 2 (member match) |
| `existing_mandate_by_id` | `frappe.get_all("SEPA Mandate", fields=["name","mandate_id","status","cancelled_date","member"])` keyed by `mandate_id` | step 3 (duplicate / update) |
| `members_with_active_mandate` | `frappe.get_all("SEPA Mandate", filters={"status":"Active"}, fields=["member"])` collapsed to a `set` | step 4 (conflict) |

For a few thousand mandates / a few thousand members, each cache fits
comfortably in memory (well under a megabyte) and each load query is well
under a second on the active site's indexes. Per-row work becomes pure dict
lookups; database writes happen only on actual create/update.

Other scale measures:
- **Batched commits** via `CSVImportBackgroundProcessor(batch_size=50,
  batch_commit=True)` — same pattern the member import uses.
- **Long-queue background job**, 3600s timeout.
- **Flags on the job:** `frappe.flags.in_background_job = True`,
  `frappe.flags.ignore_version_changes = True` (mirrors the member import).
- **Bounded `error_log`:** first 50 row-level errors verbatim, then
  `"... and N more errors"`. Full per-reason counts always live in
  `skipped_summary`.
- The `members_with_active_mandate` cache **is updated** as new active
  mandates are created. Otherwise two active rows in the same CSV for the
  same member could both pass the step-4 conflict check (different
  `Mandaatnummer`s, same member). After a successful active-mandate
  insert, add the member to the set.
- The `existing_mandate_by_id` cache assumes `mandate_id` is unique in the
  DB. If two existing mandates happen to share an id (a pre-existing data
  issue), the cache holds one and the import operates on that one only.

## Error Handling & Reporting

- Encoding / delimiter / required-column validation runs once at the
  validate stage and fails fast with a clear message in `error_log`.
- Per-row failures append to an in-memory list; final write truncates to 50
  with a `"... and N more"` tail.
- `skipped_summary` reports counts per reason:
  ```
  filtered_old_cancelled: 142
  no_member: 87
  duplicate: 3
  conflict: 0
  error: 1
  ```
- Final status is `Completed` when the job finishes, regardless of how many
  rows were skipped; `Failed` only on whole-job failure (CSV unreadable,
  fatal exception in the processor).

## Testing

Real integration tests using `EnhancedTestCase`, no business-logic mocks
(per project conventions in CLAUDE.md and the test-quality enforcer). Each
test writes a small CSV to a temp file, runs validate + process
synchronously (calling `process_import_background` in-process, not via the
queue), then asserts the resulting SEPA Mandate state.

Coverage:
1. **Active row, new member, no existing mandate** → mandate created,
   status `Active`, linked into `Member.sepa_mandates`.
2. **Recently-cancelled row (within 12 months)** → mandate created, status
   `Cancelled`, `cancelled_date` set.
3. **Old-cancelled row (> 12 months)** → row counted as
   `filtered_old_cancelled`; no mandate created.
4. **Debiteur ID with no matching Member** → counted as `no_member`.
5. **Mandate with same `Mandaatnummer` already exists + CSV row active** →
   counted as `duplicate`.
6. **Mandate with same `Mandaatnummer` already exists + CSV row
   recently-cancelled** → existing mandate updated to `Cancelled` with the
   CSV's `cancelled_date`; counted as `mandates_updated`.
7. **Member already has an unrelated Active mandate + CSV row active** →
   counted as `conflict`; no new mandate created.
8. **Member already has an unrelated Active mandate + CSV row
   recently-cancelled** → cancelled mandate still imported (no conflict on
   cancelled rows).
9. **Malformed row (invalid IBAN)** → counted as `error`; batch continues.
10. **Scale smoke test** — generate a 500-row CSV with mixed outcomes,
    process in test mode, assert all counters match and total runtime is
    bounded.

## File Layout

New files:

```
verenigingen/verenigingen_payments/doctype/procurios_mandate_import/
├── __init__.py
├── procurios_mandate_import.json
├── procurios_mandate_import.py
├── procurios_mandate_import.js
└── test_procurios_mandate_import.py

verenigingen/utils/csv/procurios_mandate_validator.py
```

No changes to existing files except `hooks.py` / fixtures if a new doctype
registration is needed (Frappe auto-discovers doctypes by directory layout;
no manual registration expected).

## Out of Scope

- Updating `Member.iban` or payment-method fields from the mandate CSV
  (mandate is an independent record).
- Cross-creditor filtering (`Incassant ID`). All rows are imported
  regardless of creditor; assumes the export was scoped correctly.
- A second pass to "promote" a recently-cancelled-imported mandate back to
  Active. Re-running an import where the same `Mandaatnummer` reappears
  without an `Opzegdatum` will hit the `duplicate` skip path and leave the
  existing Cancelled mandate untouched. If this becomes a real need, it can
  be added under the same `update if cancelled, otherwise skip` rule.
- Importing pre-notification dates as collection dates. They are kept as
  traceability text in `notes`.
