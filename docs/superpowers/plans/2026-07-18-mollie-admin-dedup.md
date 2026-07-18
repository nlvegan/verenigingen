# Mollie Admin Page Dedup (KISS-3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Extract the forked payment-processing logic shared by `templates/pages/mollie_payments_debug.py` and `mollie_payment_processing.py` into a new service, so a batching/dedup fix lands once. Both pages' whitelisted endpoints stay working as thin wrappers. Behavior-preserving.

**Architecture:** New `verenigingen_payments/mollie/services/bulk_payment_admin_service.py` (module-level functions) holds the shared bodies; each page endpoint becomes a wrapper that delegates, injecting its page-local access-check callable. `sanitize_csv_field` → new `.../mollie/services/shared/csv_utils.py`. Per-page `process_payment_batch_job` back-compat shims retained for in-flight jobs.

**Spec:** `docs/superpowers/specs/2026-07-18-mollie-admin-dedup-design.md` (read it — carries the SME-review findings F1–F14).

## Global Constraints

- **Behavior-preserving for all LIVE paths.** No change to charging/batching/dedup logic.
- **Access-denied behavior (BEHAVIOR-CRITICAL):** the access check stays INSIDE the moved `try` in the service body as `if not access_check(): frappe.throw(_("Access denied"))`. The outer `except Exception` catches it and returns `{"error": "Access denied", ...}` (HTTP 200) + logs — this exact behavior must be preserved. Do NOT lift the check into the wrapper (that would raise instead of return a dict). Each wrapper injects its own callable: `access_check=has_mollie_debug_access` (debug) / `access_check=has_payment_processing_access` (processing). Throw text stays exactly `frappe.throw(_("Access denied"))`.
- **Wrapper shape:** `@frappe.whitelist(...)` OUTERMOST (exact original args: `allow_guest=False, methods=["POST"]` where present) → `@high_security_api(operation_type=OperationType.FINANCIAL)` → `def fn(...): return bulk_payment_admin_service.fn(..., access_check=<page_fn>)`. No `try/except` and no access check in the wrapper itself.
- **Service functions:** module-level, NO `@frappe.whitelist`, NO `@high_security_api`, NO access check of their own beyond calling the injected `access_check()`. Each carries the moved `try/except → frappe.log_error → return {"error": ...}` verbatim (titles/messages/return shape preserved).
- **Endpoint dotted paths UNCHANGED:** `verenigingen.templates.pages.mollie_payments_debug.<fn>` and `...mollie_payment_processing.<fn>` all still resolve (page JS untouched).
- **Batch worker:** one canonical `bulk_payment_admin_service.process_payment_batch_job`; the service's `bulk_process_member_payments` enqueues it by its new dotted path. Each page keeps a one-line `process_payment_batch_job` back-compat shim delegating to the service worker (in-flight jobs). Shims are NOT whitelisted.
- **`bulk_retrieve_all_member_payments`** canonical = processing's SUPERSET (`retrieval_mode` + `_retrieve_global_payments_with_orphans`); debug wrapper delegates with `retrieval_mode="customer"`.
- **Locate code by SYMBOL NAME, not line numbers** (files drift between tasks).
- Run tests on **test_site_1**, NOT veg11. Render check via `bench --site veg11.veganisme.org execute` (inspection-only).
- Follow existing service-layer conventions; keep imports that were function-level function-level.

## File Structure

- **Create:** `verenigingen_payments/mollie/services/bulk_payment_admin_service.py`, `verenigingen_payments/mollie/services/shared/csv_utils.py`
- **Shrink:** `templates/pages/mollie_payments_debug.py`, `templates/pages/mollie_payment_processing.py`
- **Modify:** `templates/pages/mollie_bulk_payment_creation.py`, `templates/pages/mollie_subscription_recreation.py`
- **Tests:** `tests/backend/portal/test_page_mollie_payments_debug.py`, `test_page_mollie_payment_processing.py`, `test_page_mollie_bulk_payment_creation.py`, `test_page_mollie_subscription_recreation.py`, `tests/payment/test_mollie_debug_service_bulk.py`

---

### Task 1: Extract `sanitize_csv_field` into shared `csv_utils.py`

**Files:**
- Create: `verenigingen/verenigingen_payments/mollie/services/shared/csv_utils.py`
- Modify: `verenigingen/templates/pages/mollie_bulk_payment_creation.py`, `verenigingen/templates/pages/mollie_subscription_recreation.py`
- Test: `tests/backend/portal/test_page_mollie_bulk_payment_creation.py`, `tests/backend/portal/test_page_mollie_subscription_recreation.py`

**Interfaces:**
- Produces: `sanitize_csv_field(value: str) -> str` in `...mollie.services.shared.csv_utils`.

- [ ] **Step 1: Create `csv_utils.py`** with the exact current `sanitize_csv_field` body (copy verbatim from `mollie_bulk_payment_creation.py`'s `def sanitize_csv_field`). Include the module docstring and any imports it needs (it uses only stdlib/str ops — verify from the source).

- [ ] **Step 2: Repoint both CSV pages.** In `mollie_bulk_payment_creation.py` and `mollie_subscription_recreation.py`, delete the local `def sanitize_csv_field(...)` and add `from verenigingen.verenigingen_payments.mollie.services.shared.csv_utils import sanitize_csv_field` (bind the name into the module so `page.sanitize_csv_field` attribute access still resolves — F12). Do NOT use `import csv_utils; csv_utils.sanitize_csv_field`.

- [ ] **Step 3: Run tests to verify pass**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_mollie_bulk_payment_creation` and `... --module verenigingen.tests.backend.portal.test_page_mollie_subscription_recreation`
Expected: PASS (the `page.sanitize_csv_field(...)` attribute tests at `test_page_mollie_bulk_payment_creation.py:167` / `test_page_mollie_subscription_recreation.py:152` still resolve via the bound import).

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "refactor(mollie): extract sanitize_csv_field into shared csv_utils"
```

---

### Task 2: Consolidate the bulk-processing core (`bulk_process_member_payments` + `process_payment_batch_job`)

**Files:**
- Create: `verenigingen/verenigingen_payments/mollie/services/bulk_payment_admin_service.py`
- Modify: `verenigingen/templates/pages/mollie_payments_debug.py`, `verenigingen/templates/pages/mollie_payment_processing.py`
- Test: `tests/backend/portal/test_page_mollie_payments_debug.py`, `test_page_mollie_payment_processing.py`, `tests/payment/test_mollie_debug_service_bulk.py`

**Interfaces:**
- Produces: `bulk_payment_admin_service.bulk_process_member_payments(payment_ids, docstatus=0, payment_modes=None, create_bank_transactions=None, *, access_check)` and `bulk_payment_admin_service.process_payment_batch_job(batch_num, payment_ids, docstatus, payment_modes, tracking_id)`.

- [ ] **Step 1: Scaffold the service module** `bulk_payment_admin_service.py` with a module docstring explaining it holds the shared Mollie admin bulk-processing logic extracted from the two page controllers, and that `access_check` is injected by each page wrapper.

- [ ] **Step 2: Move `bulk_process_member_payments` into the service.** Copy the body from `mollie_payments_debug.py`'s `bulk_process_member_payments` VERBATIM (it is logic-identical to processing's — keep the fuller deprecation-warning string "Use payment_modes parameter instead. This parameter will be removed in a future version." per F9). Changes:
  - Add keyword-only `*, access_check` param; replace the in-`try` `if not has_mollie_debug_access():` with `if not access_check():` (keep `frappe.throw(_("Access denied"))` exactly, INSIDE the try).
  - Change the `frappe.enqueue(...)` target string from the page dotted path to `"verenigingen.verenigingen_payments.mollie.services.bulk_payment_admin_service.process_payment_batch_job"`.
  - Keep all imports it uses function-level as in the original (e.g. `MollieDebugService`), and the outer `except → frappe.log_error(title="Bulk process member payments error") → return {"error": ..., "payment_ids": ...}` verbatim.

- [ ] **Step 3: Move `process_payment_batch_job` into the service** — copy verbatim from either page (identical); it calls the Mollie service to process a batch. Keep its docstring.

- [ ] **Step 4: Convert both pages' `bulk_process_member_payments` to wrappers** (keep exact decorators):

```python
@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def bulk_process_member_payments(payment_ids, docstatus=0, payment_modes=None, create_bank_transactions=None):
    return bulk_payment_admin_service.bulk_process_member_payments(
        payment_ids, docstatus, payment_modes, create_bank_transactions,
        access_check=has_mollie_debug_access,   # processing: has_payment_processing_access
    )
```

- [ ] **Step 5: Add per-page `process_payment_batch_job` back-compat shims** (F8) in BOTH pages (not whitelisted):

```python
def process_payment_batch_job(batch_num, payment_ids, docstatus, payment_modes, tracking_id):
    # Back-compat shim: in-flight jobs queued under this page's old dotted path.
    return bulk_payment_admin_service.process_payment_batch_job(
        batch_num, payment_ids, docstatus, payment_modes, tracking_id
    )
```
Add `from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service` to both pages.

- [ ] **Step 6: Repoint the enqueue-path test (F11).** In `test_mollie_payment_processing.py` (~line 539-542) the assertion `mock_enqueue.call_args_list[0].args[0] == f"{PAGE}.process_payment_batch_job"` must become the service path `"verenigingen.verenigingen_payments.mollie.services.bulk_payment_admin_service.process_payment_batch_job"`. Update any equivalent assertion in `test_page_mollie_payments_debug.py`.

- [ ] **Step 7: Run tests to verify pass**

Run: `... --module verenigingen.tests.backend.portal.test_page_mollie_payments_debug`, `... test_page_mollie_payment_processing`, `... --module verenigingen.tests.payment.test_mollie_debug_service_bulk`
Expected: PASS — access-denied still returns the `{"error": "Access denied"}` dict; batching/enqueue behavior preserved (enqueue now targets the service path).

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "refactor(mollie): consolidate bulk_process_member_payments + batch worker into service"
```

---

### Task 3: Consolidate `bulk_retrieve_all_member_payments` (superset) + `_retrieve_global_payments_with_orphans`

**Files:**
- Modify: `verenigingen/verenigingen_payments/mollie/services/bulk_payment_admin_service.py`, both page controllers
- Test: `test_page_mollie_payments_debug.py`, `test_page_mollie_payment_processing.py`

**Interfaces:**
- Produces: `bulk_payment_admin_service.bulk_retrieve_all_member_payments(days_back=30, max_payments=5000, payment_status_filter=None, retrieval_mode="customer", *, access_check)`; and private `_retrieve_global_payments_with_orphans(days_back, max_payments, payment_status_filter)`.

- [ ] **Step 1: Move `_retrieve_global_payments_with_orphans` into the service** — copy verbatim from `mollie_payment_processing.py` (the ~264-LOC helper); keep its function-level imports as-is.

- [ ] **Step 2: Move `bulk_retrieve_all_member_payments` (SUPERSET) into the service** — copy processing's version verbatim (it has the `retrieval_mode` param + the `global_payments` branch calling `_retrieve_global_payments_with_orphans`). Add `*, access_check`; replace the in-`try` access check with `if not access_check():` (keep `frappe.throw(_("Access denied"))`). Preserve the outer `except → log_error → return {"error": ...}` verbatim.

- [ ] **Step 3: Convert both pages' wrappers.** Processing passes `retrieval_mode` through:
```python
def bulk_retrieve_all_member_payments(days_back=30, max_payments=5000, payment_status_filter=None, retrieval_mode="customer"):
    return bulk_payment_admin_service.bulk_retrieve_all_member_payments(
        days_back, max_payments, payment_status_filter, retrieval_mode,
        access_check=has_payment_processing_access,
    )
```
Debug does NOT expose `retrieval_mode` (its JS never sends it) — its wrapper omits the param, delegating with the default `"customer"` (behavior-preserved):
```python
def bulk_retrieve_all_member_payments(days_back=30, max_payments=5000, payment_status_filter=None):
    return bulk_payment_admin_service.bulk_retrieve_all_member_payments(
        days_back, max_payments, payment_status_filter,
        access_check=has_mollie_debug_access,
    )
```
Keep each wrapper's exact original `@frappe.whitelist(allow_guest=False, methods=["POST"])` + `@high_security_api(...)` decorators.

- [ ] **Step 4: Run tests to verify pass**

Run: `... test_page_mollie_payments_debug`, `... test_page_mollie_payment_processing`
Expected: PASS — debug retrieval unchanged (customer mode); processing keeps global_payments/orphan capability.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor(mollie): consolidate bulk_retrieve (superset) + orphan helper into service"
```

---

### Task 4: Consolidate `retrieve_customer_payments_for_processing` + `batch_process_dues_payments`

**Files:**
- Modify: `bulk_payment_admin_service.py`, both page controllers
- Test: `test_page_mollie_payments_debug.py`, `test_page_mollie_payment_processing.py`

**Interfaces:**
- Produces: `bulk_payment_admin_service.retrieve_customer_payments_for_processing(customer_id, limit=250, *, access_check)` and `bulk_payment_admin_service.batch_process_dues_payments(payment_ids, customer_id=None, *, access_check)`.

- [ ] **Step 1: Move both functions into the service** — copy verbatim from either page (logic-identical; `batch_process_dues_payments` does `html.unescape` the input in both — keep it). Add `*, access_check`; replace the in-`try` access check with `if not access_check():` (keep `frappe.throw(_("Access denied"))`). Preserve each outer `except → log_error(title=...) → return {"error": ..., "payment_ids": ...}` verbatim (titles: "Mollie batch process dues payments error", and the retrieve function's title).

- [ ] **Step 2: Convert both pages' wrappers** (4 wrappers total), each keeping its exact original decorators and injecting its page access-check:
```python
def retrieve_customer_payments_for_processing(customer_id, limit=250):
    return bulk_payment_admin_service.retrieve_customer_payments_for_processing(
        customer_id, limit, access_check=has_mollie_debug_access,   # processing: has_payment_processing_access
    )
def batch_process_dues_payments(payment_ids, customer_id=None):
    return bulk_payment_admin_service.batch_process_dues_payments(
        payment_ids, customer_id, access_check=has_mollie_debug_access,   # processing: has_payment_processing_access
    )
```
(F13: debug's copies of these two are not called by debug's JS but stay as conservative wrappers — do not delete.)

- [ ] **Step 3: Run tests to verify pass**

Run: `... test_page_mollie_payments_debug`, `... test_page_mollie_payment_processing`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "refactor(mollie): consolidate retrieve_customer_payments + batch_process_dues into service"
```

---

### Task 5: Final sweep — verify dedup complete, no forked logic, full suite + render green

**Files:** both page controllers (comment/import cleanup only if needed); whole Mollie test set.

- [ ] **Step 1: Verify no duplicated bodies remain.** Confirm each of the 5 consolidated functions exists as a thin wrapper (≤ ~6 lines) in BOTH pages and as ONE implementation in the service. Confirm the two `process_payment_batch_job` shims delegate to the service. Confirm `_retrieve_global_payments_with_orphans` exists only in the service.

```bash
grep -nE "def (bulk_process_member_payments|process_payment_batch_job|bulk_retrieve_all_member_payments|retrieve_customer_payments_for_processing|batch_process_dues_payments|_retrieve_global_payments_with_orphans)" verenigingen/templates/pages/mollie_payments_debug.py verenigingen/templates/pages/mollie_payment_processing.py verenigingen/verenigingen_payments/mollie/services/bulk_payment_admin_service.py
```
Expected: each wrapper appears once per page; each impl once in the service; `_retrieve_global_payments_with_orphans` only in the service; no `sanitize_csv_field` def left in the two CSV pages.

- [ ] **Step 2: Clean up now-unused imports** in the two page controllers (grep before removing each — e.g. helpers only used by the moved bodies). Do NOT remove imports still used by the pages' remaining (non-consolidated) endpoints.

- [ ] **Step 3: Run the full Mollie admin test set + render check**

Run each: `test_page_mollie_payments_debug`, `test_page_mollie_payment_processing`, `test_page_mollie_bulk_payment_creation`, `test_page_mollie_subscription_recreation`, `test_mollie_debug_service_bulk`, and any `test_bulk_payment_checker`.
Then render: `bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.verify_portal_base_css.run` (expect `VERIFY OK`; both mollie pages are in the harness page set).
Expected: ALL PASS.

- [ ] **Step 4: Commit any final cleanup**

```bash
git add -A && git commit -m "refactor(mollie): final cleanup — dedup complete, thin wrappers, suite green"
```

---

## Self-Review notes

- **Spec coverage:** csv_utils dedup (Task 1); bulk-processing core + shims + enqueue-test repoint (Task 2, covers F8/F9/F11); bulk_retrieve superset + orphan helper (Task 3); retrieve/batch dupes (Task 4, covers F13); final sweep (Task 5). Access-check injection preserving the caught-error-dict behavior is a Global Constraint applied in Tasks 2–4 (covers F10 + the access-denied behavior finding).
- **Behavior notes honored:** access-denied returns `{"error": "Access denied"}` dict (not raised); both dotted paths preserved; debug bulk_retrieve stays customer-mode; idempotency untouched (MollieDebugService not modified); enqueue targets the service worker with per-page shims for in-flight jobs.
- **Type/interface consistency:** every service function takes keyword-only `access_check`; wrappers inject `has_mollie_debug_access` / `has_payment_processing_access`; `bulk_retrieve` service signature includes `retrieval_mode="customer"` with debug omitting it.
