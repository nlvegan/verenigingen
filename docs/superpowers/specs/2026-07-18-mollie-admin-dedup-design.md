# Mollie Admin Page Dedup (KISS-3) — Design

**Date:** 2026-07-18
**Audit item:** KISS-3 (`docs/audits/2026-07-17-portal-pages-code-quality-audit.md`)
**Status:** Approved scope — pending spec review

## Goal

Eliminate the forked payment-processing code shared between the two Mollie admin
page controllers (`templates/pages/mollie_payments_debug.py` 1,210 LOC and
`mollie_payment_processing.py` 888 LOC) by extracting the shared logic into a
service, so a batching/dedup fix lands in one place instead of two. Both pages'
whitelisted endpoints keep working (each page's JS calls its own dotted path).
Behavior-preserving.

## Context / findings

Both pages are **live** — each page's HTML/JS calls its OWN page's dotted-path
endpoints, so neither page can be deleted; both endpoint paths must keep working.

The duplicated functions are currently in sync but forked. Verified diffs:

| function | debug vs processing |
|---|---|
| `bulk_process_member_payments` (~140 LOC) | identical logic; differs only in type hints, comments, the access-check call, and the enqueued batch-job dotted path |
| `process_payment_batch_job` (~25 LOC) | identical except a comment |
| `retrieve_customer_payments_for_processing` | identical except type hints + the access-check call |
| `batch_process_dues_payments` | identical except type hints + the access-check call + one comment (both `html.unescape` the input identically) |
| `bulk_retrieve_all_member_payments` | **NOT identical** — processing's is a functional SUPERSET: extra `retrieval_mode` param + a `"global_payments"` branch calling `_retrieve_global_payments_with_orphans` (264-LOC helper unique to processing). Debug's == processing's default `"customer"` path |
| `sanitize_csv_field` | identical (2 copies, in `mollie_bulk_payment_creation.py:60` and `mollie_subscription_recreation.py:154` — NOT in the two admin pages) |

The two access-check functions (`has_mollie_debug_access` / `has_payment_processing_access`)
have **identical role lists** (`[SYSTEM_MANAGER, "Administrator", VERENIGINGEN_ADMIN,
VERENIGINGEN_STAFF, "Treasurer"]`); they differ only in name. They stay page-local
(out of scope to unify — they are page-semantic and tiny).

## Architecture

### New service: `verenigingen_payments/mollie/services/bulk_payment_admin_service.py`

Module-level functions (procedural admin operations; `process_payment_batch_job`
is enqueued by dotted path via `frappe.enqueue`, so a plain module function is the
right shape — not a class method). These functions contain the shared logic and do
**NOT** perform the page access check (authz stays at the endpoint wrapper). No
`@frappe.whitelist`/`@high_security_api` on the service functions — those stay on
the page endpoints.

- `bulk_process_member_payments(payment_ids, docstatus=0, payment_modes=None, create_bank_transactions=None)` — the shared ~140-LOC body. Enqueues **this module's** `process_payment_batch_job` (single canonical batch worker). Keep the fuller deprecation-warning wording ("Use payment_modes parameter instead. This parameter will be removed in a future version.") as the canonical string (F9).
- `process_payment_batch_job(batch_num, payment_ids, docstatus, payment_modes, tracking_id)` — the shared batch worker (one canonical copy).
- `retrieve_customer_payments_for_processing(customer_id, limit=250)`
- `batch_process_dues_payments(payment_ids, customer_id=None)`
- `bulk_retrieve_all_member_payments(days_back=30, max_payments=5000, payment_status_filter=None, retrieval_mode="customer")` — the **SUPERSET** (processing's) version.
- `_retrieve_global_payments_with_orphans(days_back, max_payments, payment_status_filter)` — moved from `mollie_payment_processing.py` (used by the `"global_payments"` retrieval_mode).

### New shared util: `verenigingen_payments/mollie/services/shared/csv_utils.py`

- `sanitize_csv_field(value: str) -> str` — the CSV-injection-prevention helper (one copy). `mollie_bulk_payment_creation.py` and `mollie_subscription_recreation.py` drop their local copies and import it as `from verenigingen.verenigingen_payments.mollie.services.shared.csv_utils import sanitize_csv_field` (F12 — bind the name into each page module so existing tests that call `page.sanitize_csv_field(...)` / `msr.sanitize_csv_field(...)` by module attribute still resolve; do NOT use `import csv_utils; csv_utils.sanitize_csv_field`).

### Thin page endpoints (both admin pages)

Each of the 5 whitelisted endpoints on each page becomes a thin wrapper:

```python
@frappe.whitelist(allow_guest=False, methods=["POST"])   # exact original decorator kept
@high_security_api(operation_type=OperationType.FINANCIAL)
def bulk_process_member_payments(payment_ids, docstatus=0, payment_modes=None, create_bank_transactions=None):
    if not has_mollie_debug_access():                     # page-local access check kept
        frappe.throw(_("Access denied"), frappe.PermissionError)   # match the original throw exactly
    return bulk_payment_admin_service.bulk_process_member_payments(
        payment_ids, docstatus, payment_modes, create_bank_transactions
    )
```

- `@frappe.whitelist()` MUST stay OUTERMOST; keep the EXACT original decorator args (`allow_guest=False`, `methods=["POST"]` where present) and the exact original access-denied throw for each function.
- Dotted paths unchanged: `verenigingen.templates.pages.mollie_payments_debug.<fn>` and `...mollie_payment_processing.<fn>` both still resolve — page JS untouched.
- The `mollie_payment_processing.bulk_retrieve_all_member_payments` wrapper passes `retrieval_mode` through; the `mollie_payments_debug` wrapper does NOT expose `retrieval_mode` (its JS never sends it), so it delegates with the default `"customer"` — **exactly preserving debug's current behavior**.

### Error-contract boundary (F10 — required)

Each function's `try/except … frappe.log_error(...) → return {"error": …}` block moves
**with the body, as one unit, into the service function**. The page wrapper is ONLY
`access-check → delegate` — it must NOT add its own `try/except` around the delegate
(a second layer would double-wrap and change the error shape/message the JS depends
on). The exception boundary lives in exactly one place: the moved service body, with
every `frappe.log_error` title/message preserved verbatim.

### Batch-job compatibility shims (F8 — required, deploy-safety)

`process_payment_batch_job` is enqueued by dotted path and runs in a worker. Moving
it into the service means the OLD paths (`...mollie_payments_debug.process_payment_batch_job`,
`...mollie_payment_processing.process_payment_batch_job`) stop resolving — a job
enqueued just before deploy but executed by a worker after deploy would fail to
import. **Keep a one-line `process_payment_batch_job(...)` shim in EACH page** that
delegates to the service worker:

```python
def process_payment_batch_job(batch_num, payment_ids, docstatus, payment_modes, tracking_id):
    # Back-compat shim: old queued jobs reference this page's dotted path.
    return bulk_payment_admin_service.process_payment_batch_job(
        batch_num, payment_ids, docstatus, payment_modes, tracking_id
    )
```

New enqueues target the service's canonical worker; the shims exist only to catch
in-flight jobs and can be removed in a later release. (No whitelist on the shims —
they were never whitelisted.)

## Behavioral notes (on record)

1. **No behavior change to the debug page**: its `bulk_retrieve_all_member_payments` delegates with `retrieval_mode="customer"` (its only current mode). Processing keeps its full `"customer"`/`"global_payments"` capability.
2. **API surface unchanged**: all 10 endpoint dotted paths (5 per page) stay identical; each page's access gate stays identical.
3. **Batch-job enqueue path changes** (internal): new enqueues target the single `...bulk_payment_admin_service.process_payment_batch_job`. In-flight jobs queued under the old per-page paths stay safe via the per-page compatibility shims (see "Batch-job compatibility shims" above) — no queue-drain required.
4. **Access checks NOT unified** — kept page-local (identical role lists today; page-semantic).

## Test strategy

- Locate existing tests exercising these functions (e.g. `test_bulk_payment_checker`, any `test_*mollie*` covering the admin endpoints) via grep for the function names + the two page dotted paths. Prefer keeping endpoint-level tests as integration coverage (endpoints still exist as wrappers) and add service-level unit tests for the consolidated functions.
- **Specific tests that MUST be repointed/updated (F11):** `test_mollie_payment_processing.py:539-542` hard-asserts the enqueue target equals `{PAGE}.process_payment_batch_job` — after consolidation the enqueue target is `...bulk_payment_admin_service.process_payment_batch_job`, so this assertion must be updated to the service path. Also review the delegation tests around `test_mollie_payments_debug.py:295-330` and the `page.sanitize_csv_field` attribute calls at `test_page_mollie_bulk_payment_creation.py:167` / `test_page_mollie_subscription_recreation.py:152` (kept working by the F12 import form).
- **F13 note:** debug's `batch_process_dues_payments` and `retrieve_customer_payments_for_processing` are not called by debug's own JS (possibly dead there). Still convert them to thin wrappers (conservative — preserves the dotted path in case of external callers); do not delete them in this pass.
- Add a focused test asserting: (a) both pages' `bulk_process_member_payments` wrappers still enforce their access check and delegate; (b) `bulk_retrieve_all_member_payments` debug-wrapper defaults to customer mode while processing-wrapper honors `retrieval_mode="global_payments"`.
- Run on **test_site_1** (NOT veg11). Render check both pages via `bench --site veg11.veganisme.org execute` render harness (inspection-only).
- Preserve the payment-safety invariants: batching, dedup, idempotency behavior must be byte-equivalent in the consolidated `bulk_process_member_payments`/`process_payment_batch_job`.

## Global constraints (bind every task)

- Behavior-preserving for all LIVE paths; no change to charging/batching/dedup logic.
- `@frappe.whitelist()` OUTERMOST; exact original decorator args; endpoint dotted paths unchanged.
- Service functions carry NO access check and NO whitelist decorator; authz stays on the page wrappers with each page's own access-check function and its exact original throw.
- The consolidated `bulk_retrieve_all_member_payments` is the SUPERSET; debug delegates with `retrieval_mode="customer"`.
- Preserve every `frappe.log_error` title/message and user-facing string verbatim when moving.
- Run tests on test_site_1, not veg11.

## Out of scope

- Unifying the two access-check functions (page-local, identical today).
- The `_retrieve_global_payments_with_orphans` internal logic (moves verbatim).
- KISS-4 (other stranded page logic); the non-duplicated debug/processing endpoints (customer/subscription/mandate/balance debug helpers) stay in their pages.
- Any change to the Mollie client, webhook, or payment-entry creation logic.

## File summary

- **Create:** `verenigingen_payments/mollie/services/bulk_payment_admin_service.py`; `verenigingen_payments/mollie/services/shared/csv_utils.py`
- **Shrink:** `templates/pages/mollie_payments_debug.py`, `templates/pages/mollie_payment_processing.py` (5 endpoints each → thin wrappers; each retains a one-line `process_payment_batch_job` back-compat shim; move `_retrieve_global_payments_with_orphans` out of processing into the service)
- **Modify:** `templates/pages/mollie_bulk_payment_creation.py`, `templates/pages/mollie_subscription_recreation.py` (import shared `sanitize_csv_field`, drop local copies)
- **Modify/add tests:** repoint/keep endpoint tests; add service unit tests
