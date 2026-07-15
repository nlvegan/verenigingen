# Procurios Membership & Mandate Import + Member Import Rename

**Date:** 2026-07-15
**Status:** Approved (design)
**Author:** foppe + Claude

## Context

Procurios is being migrated to this Verenigingen/ERPNext application. Two new
Procurios CSV exports were uploaded (as `Procurios CSV Import` records
`PROC-IMP-2026-0017` and `-0018`) but both failed validation because they are
**not** the person/relation export the current importer was built for:

- **0017 — "Lidmaatschappen"** (memberships/subscriptions): one row per
  membership contract. ~59 rows in the test export.
- **0018 — "Alle mandaten"** (SEPA mandates): one row per mandate. ~7,699 rows.

Neither file creates members — both attach records to **existing** members.
Both link on the Procurios relation ID → `Member.procurios_id`. Verified: the
`Debiteur Id`/`Debiteur ID` column is the **same ID space** across both files
(55/55 people appearing in both matched exactly).

Import ordering is a hard requirement: **member/relation data first** (which
populates `Member.procurios_id`), then mandates and memberships.

### Existing building blocks (reused)

- `Procurios Mandate Import` DocType (`verenigingen_payments`) — **already
  built** and expects file 0018's exact format. Matches `Debiteur ID` →
  `Member.procurios_id`; handles duplicates, cancellations, old-cancelled
  filtering, member conflicts, ambiguous IDs.
- `verenigingen/utils/csv/base_csv_import.py::BaseCSVImport` — CSV plumbing,
  validation/preview, background job, error-log truncation.
- `services/csv_import/membership_import_service.py::MembershipImportService`
  — `create_membership_from_csv(member_doc, row_data)` creates an **active**
  Membership + dues schedule with advisory locking + dedup.
- `services/member/member_lookup_service.py::MemberLookupService` — cascade
  member matching (member_id / procurios_id / email).

## Scope

Three workstreams. All part of the Procurios→Verenigingen cutover.

### Workstream 1 — Rename `Procurios CSV Import` → `Member Import`

The existing person/relation importer is being generalized in name to
`Member Import`. Its validator (`ProcuriosDataValidator`) and behaviour are
**unchanged** — only naming.

- Migrate **patch**: `frappe.rename_doc("DocType", "Procurios CSV Import",
  "Member Import")` (renames `tabProcurios CSV Import` → `tabMember Import`,
  rewires links). Idempotent (guard on existence).
- Naming series → `MEM-IMP-.YYYY.-.####.`. The 2 existing `PROC-IMP-2026-00xx`
  records **keep their names** (Frappe does not rewrite existing names on a
  series change) — acceptable.
- Rename on disk: folder `verenigingen/verenigingen/doctype/procurios_csv_import/`
  → `member_import/`, files, class `ProcuriosCSVImport` → `MemberImport`,
  `_BACKGROUND_METHOD` string, the 2 whitelisted method dotted-paths, JS,
  `whitelist_files.txt`, and references in `base_csv_import.py` /
  `csv_import_processor.py`. Existing test file renamed and updated.

**Blast radius (verified):** 6 real files reference the old name.

### Workstream 2 — New `Procurios Membership Import`

Mirrors the `Procurios Mandate Import` structure.

**DocTypes**
- `Procurios Membership Import` (series `PROC-MEMB-IMP-.YYYY.-.####.`,
  submittable to match sibling): `csv_file` (Attach, reqd), `encoding`,
  `csv_delimiter`, `membership_type_mapping` (child table), `import_status`,
  preview, progress counters (`memberships_created`, `memberships_skipped`,
  `total_rows`, `rows_processed`), `error_log`, `top_errors_summary`,
  `descriptive_name`.
- `Procurios Membership Type Mapping` (child): `procurios_type` (Data,
  read-only) + `membership_type` (Link → Membership Type). **Link-to-existing
  only** — no auto-create.

**Custom field on `Membership`** — `procurios_membership_id` (Data, indexed).
Stores the Procurios membership `Id` (e.g. `7112`) for idempotency. Added via
the app's custom-field fixture/patch mechanism.

**Validator** — `utils/csv/procurios_membership_validator.py`:
`ProcuriosMembershipRow` dataclass + `ProcuriosMembershipValidator`.
- `check_required_columns(headers)` — required: `Debiteur Id`, `Type`,
  `Ingangsdatum`, `Id`.
- `extract_membership_types(csv_data)` — distinct `Type` values, for the
  mapping table.
- `validate_and_map(csv_data)` → `(rows, errors)`. Per-row mapping:
  - `Debiteur Id` → `debiteur_id` (match key), `Debiteur Naam` → `debiteur_naam`
  - `Type` → `procurios_type` (raw; resolved to Membership Type via mapping in
    the controller). **The export header contains `Type` twice** — the naive
    `csv.DictReader` keeps the last; the reader must dedupe/pick the membership
    `Type` deliberately (both columns hold the same value in the sample, but
    this must be handled explicitly, not by luck).
  - `Ingangsdatum` → `start_date`; `Aanmaakdatum` → `creation_ref`
  - `Opgezegd` / `Einddatum` / `Vervaldatum` → status determination
  - `Normale prijs (type)` (fallback `Normale prijs (abonnement)`) → `dues_rate`
  - `Looptijd` (`1 Maand` / `1 Jaar` / …) → `payment_period` (monthly/annual/…)
  - `Id` → `procurios_membership_id`

  **Status rule:** `Opgezegd` non-empty → **Cancelled** (cancellation_date =
  parseable `Opgezegd` else `Einddatum`); elif `Einddatum` set and in the past
  → **Expired**; else **Active**. (Exact `Opgezegd` semantics — date vs flag —
  confirmed against real data during implementation.)

**Controller** — `ProcuriosMembershipImport(BaseCSVImport)`:
- *Validate/preview:* read CSV → `check_required_columns` → **upsert distinct
  `Type` values into `membership_type_mapping`**, preserving any already-chosen
  `membership_type` and appending blank rows for new types → build preview →
  set `Ready for Import`. Also verify the `csv_*_dues_schedule` templates exist
  in Verenigingen Settings and surface a clear error if missing.
- *Import guard:* refuse to run if any `membership_type_mapping` row has an
  empty `membership_type`.
- *Caches:* `procurios_id → member` (same ambiguity handling as the mandate
  importer — a `procurios_id` on >1 Member is dropped and its rows skipped as
  `ambiguous_member`); set of already-imported `procurios_membership_id`;
  members with an existing active Membership.
- *Per-row (`_process_single_member`):*
  1. Match `debiteur_id` → member via cache. No member → **skip + log**
     (`no member with procurios_id=…`). Ambiguous → skip + log.
  2. Idempotency: `procurios_membership_id` already imported → **skip**.
  3. Resolve `membership_type` from the mapping table.
  4. **Active row:** if member already has an active Membership → **skip +
     log**. Else build `row_data = {member_id, membership_type, payment_period,
     member_since=start_date, dues_rate}` and call
     `MembershipImportService.create_membership_from_csv(member_doc, row_data)`
     → active Membership **+ dues schedule** (`create_invoice=False`). Set
     `procurios_membership_id` on the created Membership.
  5. **Cancelled/Expired row:** create a submitted `Membership` directly with
     the mapped type, `start_date`, `status`, `cancellation_date`/reason, and
     `procurios_membership_id`. **No dues schedule.** Historical rows import
     regardless of any existing active Membership (additive).
- *Finalize:* write counters + truncated error log; status `Completed`.
- Background entrypoint + `validate_import_file` whitelisted methods guarded
  `@critical_api(OperationType.ADMIN)`, `@frappe.whitelist()` outermost.

**Membership status automation:** `Membership` is submittable and may compute
`status` in its own hooks. The importer must produce the correct **final**
status for historical rows (Cancelled/Expired) — using the existing
`member._system_update` / appropriate flags to avoid status being overwritten.
Verified during implementation against the Membership controller.

### Workstream 3 — Run the Procurios mandate import (full, on veg11)

Create a `Procurios Mandate Import` record, attach file 0018's CSV, validate →
import (full run). Expected on veg11: **2 SEPA Mandates created** (members
`procurios_id` 1072 René Beemer, 1073 Sonja Rijs; both active mandates, neither
member has an existing SEPA Mandate), everything else `skip: no member`. Report
the exact created/updated/skipped/error breakdown. This doubles as the mandate
importer's first real end-to-end exercise.

## Data flow

```
Member Import (relation export)  →  populates Member.procurios_id   [prerequisite]
                                          │
                 ┌────────────────────────┴───────────────────────┐
   Procurios Mandate Import                       Procurios Membership Import
   Debiteur ID → Member.procurios_id              Debiteur Id → Member.procurios_id
        → SEPA Mandate                                 → Membership (+ dues schedule if active)
```

## Testing (run by Claude, iterate to green)

Real integration tests only (no business-logic mocks, per repo rules). Run on
`test_site_1..5`; create/delete records freely; iterate until passing.

- **Membership validator:** required-column detection; duplicate `Type` column
  handled; status determination (active / cancelled / expired); `Looptijd` →
  payment_period; `Normale prijs` → dues_rate; distinct-type extraction.
- **Membership import flow:** match by procurios_id; skip-no-member (+log);
  skip-ambiguous; active → Membership + dues schedule created; already-active →
  skip + log; cancelled/expired → historical record with correct status + no
  dues schedule; idempotent re-run (procurios_membership_id) creates nothing new;
  import blocked when a type mapping is incomplete.
- **Mandate import:** exercised via the real veg11 run (Workstream 3) plus any
  existing `Procurios Mandate Import` tests.
- **Rename:** update/rename the existing `Procurios CSV Import` tests; confirm
  the rename patch is idempotent and links are rewired.

## Non-goals / YAGNI

- No auto-creation of Membership Types (link-to-existing only).
- No name/email/IBAN fallback matching for memberships — `procurios_id` only
  (confirmed sufficient; members exist first).
- No backfill invoices for imported memberships (`create_invoice=False`);
  ongoing billing flows from the dues schedule.
- No changes to the person/relation `ProcuriosDataValidator` beyond the rename.

## Preconditions

1. Member/relation data imported first (populates `Member.procurios_id`).
2. Target Membership Types exist and are chosen in the mapping table.
3. `csv_monthly/quarterly/annual_dues_schedule` configured in Verenigingen
   Settings (checked on validate).
