# Procurios SEPA Mandate Import — Handoff

**Date:** 2026-06-03
**Branch:** `develop` (already merged + pushed; no open feature branch)
**Status:** Shipped. Tests passing at last verified commit. No blocking issues.

This document hands off the **Procurios SEPA Mandate Import** feature so any developer (including future-you) can pick up the work, extend it, or operate it in production without re-reading every commit message.

---

## 1. What this feature is

A new submittable DocType **`Procurios Mandate Import`** (module: *Verenigingen Payments*) that imports SEPA mandates from a Procurios CSV export, matching each row's **Debiteur ID** to an existing **Member.procurios_id**.

Hard requirement enforced by design: **a mandate is only imported when a Member with the matching `procurios_id` already exists**. Rows for non-existent members are logged and skipped — never created.

### Business rules baked in

| Rule | Source |
|---|---|
| Active mandates (no `Opzegdatum`) → status `Active` | User decision during brainstorming |
| Cancelled within 12 months (`Opzegdatum` within cutoff) → status `Cancelled` | User: "Active + recently cancelled" |
| Cancelled longer ago than 12 months → skip with reason `filtered_old_cancelled` | Same |
| Duplicate `Mandaatnummer` exists + CSV row is cancelled → update existing | User: "update if cancelled, otherwise skip" |
| Duplicate `Mandaatnummer` exists + CSV row is active → skip | Same |
| Member already has an Active mandate + new active row → skip with reason `conflict` | User: "Skip, log conflict" |
| Procurios ID matches multiple Members → skip with `ambiguous_member` (added in round 2) | Code review finding |

The 12-month cutoff is a module constant `CANCELLED_CUTOFF_MONTHS = 12` (not user-configurable).

---

## 2. Where the code lives

```
verenigingen/
├── verenigingen_payments/doctype/procurios_mandate_import/
│   ├── procurios_mandate_import.json     (DocType schema; module = Verenigingen Payments)
│   ├── procurios_mandate_import.py       (controller, 596 LOC)
│   ├── procurios_mandate_import.js       (client form script, 59 LOC)
│   └── __init__.py
├── utils/csv/procurios_mandate_validator.py   (pure-Python row validator, 161 LOC)
├── utils/csv_import_processor.py              (shared infra; coerce_test_mode lives here)
└── tests/payment/
    ├── test_procurios_mandate_validator.py   (12 unit tests)
    └── test_procurios_mandate_import.py      (integration + scale + permission + cache tests)
```

The sibling **member** importer was hardened in the same session:

```
verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py   (sibling, name-mangling + only_for fixes backported)
verenigingen/tests/member/test_procurios_csv_import.py                            (new controller-level integration tests added at bottom)
```

### Design + plan docs

- `docs/plans/2026-05-27-procurios-mandate-import-design.md` — the spec (commit `0cc7d265`)
- `docs/plans/2026-05-31-procurios-mandate-import.md` — the 8-task implementation plan (commit `ed06c008`)

---

## 3. How the import flow works

User journey:
1. `/app/procurios-mandate-import/new` → attach CSV → save
2. Click **Validate CSV** → controller reads the file, checks required columns, builds a 5-row JSON preview, sets `import_status = "Ready for Import"` (or `"Failed"` with `error_log`)
3. **Submit** → `on_submit` enqueues `process_import_background` on the `long` queue (3600s timeout)
4. The background job processes rows in batches of 50 with batched commits; client form polls every 5s and shows live `mandates_created` / `mandates_updated` / `mandates_skipped` counters
5. On completion: status flips to `Completed` (or `Failed` on whole-job failure); `error_log` holds up to the first 50 row-level errors with a `… and N more` tail; `skipped_summary` shows per-reason counts

### Per-row decision tree (`_process_single_row`)

Order matters — first matching outcome wins:

1. **Ambiguous member match?** (duplicate `procurios_id` in the DB) → skip `ambiguous_member`
2. **No member match?** → skip `no_member`
3. **Existing mandate with same `mandate_id`?**
   - CSV row is cancelled → call `_update_cancellation` → return `updated`
   - CSV row is active → skip `duplicate`
4. **Active row, member already has another active mandate?** → skip `conflict`
5. **Create new mandate** → return `created`

### The three pre-built caches (`_build_caches`)

Called once before the row loop, after a single Member query plus one or two SEPA Mandate queries (filtered to active OR id-in-csv when csv_mandate_ids is supplied):

```python
@dataclass
class _Caches:
    procurios_id_to_member: Dict[str, str]          # Debiteur ID → Member.name
    existing_mandate_by_id: Dict[str, Dict]         # Mandaatnummer → row dict
    members_with_active_mandate: Set[str]
    ambiguous_procurios_ids: Set[str]               # duplicate procurios_ids dropped from the lookup
    member_to_active_count: Dict[str, int]          # for cache-only conflict decrement
```

The cache is **updated in-loop** so subsequent rows in the same CSV see consistent state. Two active rows for the same member: the first creates and bumps `member_to_active_count`; the second hits the `conflict` branch. A cancellation update decrements the count; when it hits zero, the member is dropped from `members_with_active_mandate`.

### Why the SEPA Mandate status is set explicitly

The design originally assumed `sepa_mandate_lifecycle_service.set_status_based_on_dates(...)` would derive `Cancelled` from `cancelled_date`. It does NOT — it only inspects `sign_date` and `expiry_date`. So `_create_mandate` and `_update_cancellation` set `mandate.status = "Cancelled"` explicitly. The lifecycle service's terminal-status preservation logic keeps it that way through validate.

This was a real spec-vs-code drift; the design doc was corrected in commit `71e88598`.

---

## 4. Field mapping (CSV column → SEPA Mandate field)

| CSV column | SEPA Mandate field | Notes |
|---|---|---|
| `Mandaatnummer` | `mandate_id` | |
| `IBAN` | `iban` | Trimmed + uppercased; SEPA Mandate validator re-formats with spaces on save |
| `Rekeninghouder` | `account_holder_name` | |
| `Debiteur ID` | — | Match key → `Member.procurios_id` |
| `Datum van ondertekening` | `sign_date` | ISO `YYYY-MM-DD` |
| `Opzegdatum` | `cancelled_date` | Present → status `Cancelled` |
| `Type machtiging` | `mandate_type` | `Doorlopend → RCUR`, `Eenmalig → OOFF`, else `RCUR` |
| `Incasso-afspraak ID`, `Administratie`, `Pre-notificatie datum` | `notes` | Composed traceability text |

Constants on every created mandate: `scheme = "SEPA"`, `used_for_memberships = 1`, `bic` left blank (SEPA validator derives or warns).

---

## 5. Operating the tool

### As an admin (System Manager or Verenigingen Administrator)

1. Generate the SEPA-mandate export from Procurios (separate export from the general-member CSV — different endpoint in their UI).
2. Save the CSV unmodified. Delimiter is `;`. Encoding is usually UTF-8.
3. New Procurios Mandate Import → attach the CSV → save.
4. Click **Validate CSV**. Inspect the preview. If `import_status` shows `Failed`, read `error_log` (most likely a missing required column).
5. Optional: tick **Test Mode** to process only the first 25 rows for a dry-run.
6. **Submit**. The form auto-refreshes every 5 seconds.
7. After completion, read `skipped_summary` and `error_log`. The summary breakdown looks like:
   ```
   filtered_old_cancelled: 142
   no_member: 87
   ambiguous_member: 0
   duplicate: 3
   conflict: 0
   error: 1
   ```
   Sum of these + `mandates_created` + `mandates_updated` should equal `total_rows`.

### What to expect on a few-thousand-row import

- Caches built once at start (≤1s on the current site)
- Per-row work is pure dict lookups + one `mandate.insert()` (create path) or one `mandate.save()` (update path)
- Batched commits every 50 rows
- 500-row test takes ~125s of which ~100s is fixture setup. A realistic 3,000-row production import should comfortably finish inside the 3,600s background-job timeout.
- The live progress fields (`mandates_created/updated/skipped`) update at every batch boundary, so the user sees movement.

### What to do if the job fails

`import_status = "Failed"` only happens on whole-job catastrophe (CSV unreadable, fatal exception). Per-row failures are caught and counted under `error` — they never abort the batch. The full traceback lands in `error_log` (sanitised via `sanitize_error_for_audit`).

To re-run: create a new import doc with the same CSV. The duplicate-detection logic will skip already-imported mandates and only act on rows that have changed since (e.g., newly cancelled ones).

---

## 6. Test inventory

### Unit tests — `tests/payment/test_procurios_mandate_validator.py` (12 tests, ~0.4s)

Pure-Python; no DB. Pins `today = date(2026, 5, 31)` so cutoff math is deterministic.

Covers: required columns, field mapping, IBAN normalization, mandate-type derivation, date parsing, error collection, the 12-month cutoff.

### Integration tests — `tests/payment/test_procurios_mandate_import.py` (24 tests + 1 scale, ~125s total)

| Class | What it covers |
|---|---|
| `TestProcuriosMandateImportValidate` | validate/preview flow + missing-column rejection |
| `TestProcuriosMandateImportProcessRow` | 8 per-row decision branches (create, no_member, duplicate, update, conflict, cancelled-doesn't-conflict, in-loop conflict, invalid IBAN) |
| `TestProcuriosMandateImportEndToEnd` | Full pipeline with 4 mixed outcomes via `process_import_background` driven in-process |
| `TestProcuriosMandateImportAmbiguousMember` | Two Members sharing one `procurios_id` → ambiguous skip |
| `TestProcuriosMandateImportAllFilteredCompletes` | CSV where every row is filtered → `Completed`, not `Failed` |
| `TestProcuriosMandateImportPermissions` | Non-admin (Guest) cannot call `validate_import_file` or `process_import_background`; uses `assertRaisesRegex("only allowed")` to isolate the `only_for` gate; positive admin-success test for symmetry |
| `TestCoerceTestMode` | Shared `coerce_test_mode` helper unit tests (booleans, truthy/falsy strings, integers, None) |
| `TestPropertyCacheHits` | `doc._validator is doc._validator` regression guard against the name-mangling fix being reverted |
| `TestProcuriosMandateImportScale` | 500-row mix (250 create + 30 update + 100 no_member + 70 filtered + 50 conflict); 180s ceiling |

### Sibling controller tests — `tests/member/test_procurios_csv_import.py`

Original 23 validator-only tests **+** 4 new controller integration tests added in `74594f37`:
- `TestProcuriosCSVImportPermissions` (2 tests) — same `assertRaisesRegex` pattern
- `TestProcuriosCSVImportPropertyCache` (2 tests) — cache-hit regression guard

### How to run

```bash
# Validator unit tests (fast)
~/frappe-bench/env/bin/python -m pytest \
  apps/verenigingen/verenigingen/tests/payment/test_procurios_mandate_validator.py -q

# Mandate import integration (slow; full suite ~125s)
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_import

# Sibling controller (includes the new permission + cache tests)
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.member.test_procurios_csv_import
```

Last verified green: commit `74594f37` on 2026-05-31. There has been substantial churn on `develop` since (v16 baseline triage, factory rework — see commits `c229f3b4`..`c86b4e8a`). **Recommend re-running before any production deployment** to confirm no test has regressed due to underlying model changes.

---

## 7. Review history

The feature went through three rounds of review:

| Round | Commits | Findings |
|---|---|---|
| 1 (initial Opus cross-cutting) | `71e88598` | property-cache name-mangling, uncounted validator errors, design-doc inaccuracy on status derivation, `frappe.only_for` hardening, `test_mode` REST coercion, `title_field`, validate-stage error-log tail |
| 2 (code-quality + skeptical, parallel) | `0a4c13a7`, `1df9de64` | live progress fields stuck at 0 (shared processor hardcoded `members_*`); duplicate `procurios_id` silent misassignment; in-loop `frappe.db.exists` in `_update_cancellation`; time-bomb wall-clock dates in tests; `hasattr` defensive fallback hiding renames; `frappe.only_for` had no test coverage; scale test missed the update path; sibling had same name-mangling + `test_mode` bugs (TD-1/TD-2 backport) |
| 3 (code-quality + skeptical, on the round-2 fixes) | `74594f37` | sibling backport silently SKIPPED `frappe.only_for` (the most important hardening); permission tests didn't isolate the gate (would still pass if `only_for` deleted); all-filtered branch duplicated `skipped_summary` literal inline (drift risk); no test for `coerce_test_mode`; `_build_caches` did unbounded SEPA Mandate scan |

All review findings classified Important / High were addressed before the feature was considered done. Minor / cosmetic findings were explicitly deferred (see §8).

---

## 8. Intentionally deferred — open items

Listed for the next person who touches this code. None block production use.

### Architecture
- **`BaseCSVImport` extraction** (Skeptical TD-3): There is ~120 LOC of structural duplication between `procurios_mandate_import.py` and `procurios_csv_import.py` — the `_parser`/`_validator` properties, `on_submit` enqueue, `_read_csv_file`, the whitelisted `validate_import_file` wrapper, the `process_import_background` outer structure, the finalize skeleton. Worth extracting if a third importer ever lands.
- **`_Caches` as a state class**: The dataclass now has 5 fields with co-maintained invariants (e.g., "if member is in `members_with_active_mandate` then `member_to_active_count[member] ≥ 1`"). The invariants are enforced by per-call discipline scattered across `_build_caches` / `_create_mandate` / `_update_cancellation`. Methods like `record_create(member)` / `record_cancel(member)` would co-locate them. Becoming a smell, not yet painful.

### Correctness / robustness
- **30-day months in the cutoff** (Skeptical TD-8): `cutoff_days = CANCELLED_CUTOFF_MONTHS * 30 = 360 days`, not calendar months. Inline comment in the validator already discloses the approximation. Real fix: `dateutil.relativedelta(months=cutoff_months)`. Low impact.
- **`coerce_test_mode` accepts a narrow truthy set**: `"on"`, `"y"`, `"enabled"` all coerce to False. Most REST clients send `true`/`false` so it's fine, but the docstring should list the accepted strings. Tests now cover the current behaviour.
- **`mijnrood_csv_import.py` uses the explicit-mangled-name idiom**: Different pattern from the two now-fixed Procurios importers. Inconsistency someone might "clean up" the wrong way. A short comment in `mijnrood_csv_import.py` referencing the gotcha would prevent a confused future revert.

### UX
- **`error_log` mixes skip reasons with errors**: `no_member` and `conflict` skips append to `error_log` for admin visibility, but `duplicate` doesn't. Either log every skip reason (consistent) or none (clean separation from `skipped_summary`). Cosmetic.
- **Client poll has no max-attempts cap**: `setInterval(reload, 5000)` runs forever if the worker hangs at status `In Progress`. Matches the sibling member-importer pattern; a 30-min hard cap would be friendlier. Minor.
- **Scale-test ceiling of 180s is generous**: Local-dev hardware finishes in ~125s; CI might be slower. Could tighten to 120s, or convert to a per-row time check (`elapsed / 500 < 0.4`) to catch regressions earlier.

### Test gaps
- **No test that the sibling member-importer's own `process_import_background` works end-to-end.** Round 3 added permission + cache tests for the sibling controller; the actual create-Member flow still has zero integration coverage in this repo. If you ever touch the sibling, add an end-to-end test like the mandate-importer's `TestProcuriosMandateImportEndToEnd`.
- **No test for invalid `Opzegdatum`**: The validator parses `Opzegdatum` via `_parse_date`; `test_map_row_invalid_date_raises` covers `Datum van ondertekening` only. A future "skip row, treat as active" change would go silent. Trivial to add.

---

## 9. Known interaction points to keep in mind when modifying

### Things that will break if you change them
- **`Member.procurios_id`** — the match key. If renamed: `_build_caches` query, the `Member` JSON field, the existing `procurios_csv_import.py` controller, and several tests. Lots of grep hits.
- **`SEPA Mandate.mandate_id`** uniqueness — assumed unique in the existing-mandate cache. The DocType doesn't enforce `unique:1` (it's a plain Data field). If two existing mandates ever share an id, the cache holds the last and the import treats only that one as "existing".
- **`Member SEPA Mandate Link.mandate_reference`** — the e2e test asserts directly against this child-table field name (no `hasattr` fallback). Renaming would break the test loudly, which is the intent.
- **`sepa_mandate_lifecycle_service.set_status_based_on_dates`** — currently it preserves terminal statuses (`Cancelled`, `Rejected`, `Expired`). If that preservation is removed, the import's explicit `mandate.status = "Cancelled"` will be overwritten on save. Test would catch this immediately.

### Things you can safely change
- The 12-month cutoff (`CANCELLED_CUTOFF_MONTHS` in `procurios_mandate_validator.py`). Tests use a pinned date so they still work; integration tests use `_recent_cancellation_date()` which is relative-to-today.
- The `progress_field_map` mechanism in `csv_import_processor.py` — backward compatible default for existing member importers; adding more field-name keys is harmless.
- The `coerce_test_mode` accepted-string set — tests cover the current contract, change them together.

---

## 10. Open follow-up actions for next session (if anyone picks this up)

Ordered by value:

1. **Re-run the suites** against current `develop` (`c86b4e8a`) since there's been significant model churn. If anything broke, the failures will point at exactly which assumption changed.
2. **Drive a real Procurios CSV through it** in a non-production site. The 500-row scale test confirms the architecture, but a real export will catch any encoding / column-naming surprises that the synthetic test fixtures don't.
3. **Decide on the open `error_log` semantics question** (item in §8 UX): admin imports are infrequent and surfacing skip reasons in `error_log` is genuinely useful for "why didn't this row import?" debugging. Either commit to that and add the missing `duplicate` reason, or remove the existing `no_member` / `conflict` logging.
4. **Open a tracked issue for `BaseCSVImport` extraction.** The third importer triggers it; this is a paper-trail item, not work to do now.
5. **Push `member_to_active_count` invariant into a method on `_Caches`** if you find yourself touching the cancellation path for any other reason.

---

## 11. Quick reference: commit map of the feature

```
0cc7d265  docs(plans): design doc                                   (round 0)
ed06c008  docs(plans): implementation plan                          (round 0)

11811d91  feat: scaffold DocType                                    (Task 1)
6280d5e4  feat: ProcuriosMandateValidator + 12 unit tests           (Task 2)
6d7a3c8b  feat: validate + preview flow                             (Task 3)
b573603d  feat: per-row processor with caches                       (Task 4)
67b133cb  feat: background job + finalize                           (Task 5)
e96e74a5  feat: client form script                                  (Task 6)
52069f7f  test: 500-row scale smoke test                            (Task 7)

71e88598  refactor: post-review hardening                           (round 1 review)
0a4c13a7  fix: cross-cutting review findings                        (round 2 review — mandate)
1df9de64  fix: backport hardening to procurios_csv_import sibling   (round 2 review — sibling)
74594f37  fix: close round-2 review findings                        (round 3 review — final)
```

All pushed to `origin/develop`. No open branches. No outstanding work.

---

## Contact / context

User: foppe (foppe@veganisme.org)
Site: veg11.veganisme.org
Active sessions: this feature was built/reviewed across roughly 2026-05-22 → 2026-05-31, with the design phase the week before.
