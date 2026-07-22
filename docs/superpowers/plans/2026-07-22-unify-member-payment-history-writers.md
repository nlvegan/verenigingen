# Unify Member Payment-History Writers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the incremental writer and the (collapsed) full-rebuild produce the *same* `Member.payment_history` rows by routing every invoice row through one shared builder, and delete the dead PE-based "Unreconciled/Donation Payment" row-types.

**Architecture:** `PaymentHistoryEntryBuilder.build_from_query_row` becomes the single invoice-row constructor; `build_from_invoice_doc` assembles a row dict and delegates to it. The `PaymentHistoryService` rebuild feeds its batch-fetched data through the builder; `background_jobs.load_payment_history_batch_optimized` collapses into a thin wrapper over the service. The phantom payment row-types (0 rows ever on production) and their two readers are removed.

**Tech Stack:** Frappe/ERPNext v15/v16, Python 3.x, `EnhancedTestCase` real-DB integration tests, Jest for JS.

**Spec:** `docs/superpowers/specs/2026-07-22-unify-member-payment-history-writers-design.md`

## Global Constraints

- Site for all tests: **one of `test_site_1`..`test_site_5`, never `veg11.veganisme.org`**. Command form: `bench --site test_site_1 run-tests --app verenigingen --module <dotted.module>`.
- Real integration tests only — **no mocking of business logic** (the `test-quality-enforcer` / `block-inappropriate-mocks` hooks will reject it).
- Translation: wrap user-facing Python strings in `_()`, JS in `__()`.
- `payment_history` legitimately contains **invoice rows only** (transaction_type ∈ {"Membership Invoice", "Regular Invoice"}). No PE-based rows.
- Canonical membership classifier = `is_membership_invoice` (boolean, unconditionally set). The `membership` link supplies the Membership *reference* only, when present.
- The unrelated **`Donation Payment` DocType** (child table on `Donation`) must NOT be touched — it shares a name string with the deleted `transaction_type` but is a different entity.
- Commit after each task. Conventional Commits. End commit messages with `Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `verenigingen/utils/payment_history_builder.py` | The single source of truth for building payment_history rows | Rework `build_from_query_row` into full-field constructor; make `build_from_invoice_doc` delegate |
| `verenigingen/services/member/payment/payment_history_service.py` | Canonical full-rebuild (batch queries → rows) | Route invoice rows through the builder; delete `_add_unreconciled_payments` |
| `verenigingen/utils/background_jobs.py` | Job orchestration (enqueue/cache/save) | Collapse `load_payment_history_batch_optimized` into a thin delegator to the service |
| `verenigingen/verenigingen/doctype/member/mixins/financial_mixin.py` | Financial summary stats | Drop the two phantom counters |
| `verenigingen/public/js/member/js_modules/payment-utils.js` | Member-form payment history rendering/stats | Drop the two phantom `transaction_type` branches |
| `verenigingen/tests/payment/test_regression_payment_history_dynamic_links.py` | Builder Dynamic-Link regression tests | Migrate fixtures to the new row schema |
| `verenigingen/tests/services/test_payment_history_service_realdb.py` | Real-DB rebuild tests | Invert the unreconciled/donation assertions |
| `verenigingen/tests/payment/test_payment_history_writer_parity.py` | NEW — divergence regression | Incremental vs rebuild field-identity |

### Canonical row schema (input to `build_from_query_row`)

Every caller assembles this dict; the builder maps it to a `payment_history` child row:

```
{
  "invoice_name": str,                 # SI name
  "is_membership_invoice": 0 | 1,      # classifier
  "membership": str | None,            # Membership record name (reference only)
  "posting_date": date,
  "due_date": date | None,
  "grand_total": float,
  "outstanding_amount": float,
  "invoice_status": str,               # SI.status
  "docstatus": 0 | 1 | 2,
  "coverage_start_date": date | None,
  "coverage_end_date": date | None,
  "paid_amount": float,
  "reconciled": 0 | 1,
  "payment_entry": str | None,
  "payment_date": date | None,
  "payment_method": str | None,
  "has_mandate": 0 | 1,
  "sepa_mandate": str | None,
  "mandate_status": str | None,
  "mandate_reference": str | None,
}
```

---

## Task 1: Make `build_from_query_row` the single invoice-row constructor

**Files:**
- Modify: `verenigingen/utils/payment_history_builder.py` (`build_from_query_row` ~198-242, `build_from_invoice_doc` ~47-196)
- Test: `verenigingen/tests/payment/test_regression_payment_history_dynamic_links.py`

**Interfaces:**
- Produces: `PaymentHistoryEntryBuilder.build_from_query_row(row: dict) -> dict` consuming the **canonical row schema** above and emitting a full `payment_history` child dict (all Dynamic-Link `*_doctype` fields included). `build_from_invoice_doc(invoice_doc, member_doc=None, mandate_cache=None) -> dict` assembles a canonical row from a Sales Invoice document and returns `build_from_query_row(row)`.

- [ ] **Step 1: Write the failing test** — parity + classifier behavior.

Append to `verenigingen/tests/payment/test_regression_payment_history_dynamic_links.py`:

```python
def test_query_row_classifies_membership_by_boolean_not_link():
    """is_membership_invoice=1 with no membership link -> Membership Invoice, no reference."""
    from verenigingen.utils.payment_history_builder import PaymentHistoryEntryBuilder

    row = {
        "invoice_name": "SI-TEST-1",
        "is_membership_invoice": 1,
        "membership": None,
        "posting_date": "2026-01-01",
        "due_date": "2026-01-31",
        "grand_total": 100.0,
        "outstanding_amount": 100.0,
        "invoice_status": "Unpaid",
        "docstatus": 1,
        "paid_amount": 0,
    }
    entry = PaymentHistoryEntryBuilder.build_from_query_row(row)
    assert entry["transaction_type"] == "Membership Invoice"
    assert entry["reference_doctype"] is None
    assert entry["reference_name"] is None
    assert entry["payment_status"] == "Unpaid"


def test_query_row_membership_reference_when_link_present():
    from verenigingen.utils.payment_history_builder import PaymentHistoryEntryBuilder

    row = {
        "invoice_name": "SI-TEST-2",
        "is_membership_invoice": 1,
        "membership": "MEM-0001",
        "posting_date": "2026-01-01",
        "grand_total": 100.0,
        "outstanding_amount": 0.0,
        "invoice_status": "Paid",
        "docstatus": 1,
        "paid_amount": 100.0,
    }
    entry = PaymentHistoryEntryBuilder.build_from_query_row(row)
    assert entry["transaction_type"] == "Membership Invoice"
    assert entry["reference_doctype"] == "Membership"
    assert entry["reference_name"] == "MEM-0001"
    assert entry["payment_status"] == "Paid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_regression_payment_history_dynamic_links`
Expected: FAIL — old `build_from_query_row` reads `row["membership_id"]` / `row["invoice_name"]` and has no `is_membership_invoice` handling (KeyError or wrong `transaction_type`).

- [ ] **Step 3: Rewrite `build_from_query_row`**

Add a module-level import near the top of `payment_history_builder.py` (function-level to avoid any `utils/__init__` import cycle):

```python
# inside build_from_query_row, first lines:
from verenigingen.utils import determine_payment_status
```

Replace the whole `build_from_query_row` method body with:

```python
    @staticmethod
    def build_from_query_row(row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a payment history entry from a canonical row dict.

        This is THE single invoice-row constructor. Callers (incremental builder
        via build_from_invoice_doc, and the batch rebuild) assemble the canonical
        row schema and pass it here so every writer emits identical rows.
        """
        from verenigingen.utils import determine_payment_status

        # Classifier: the unconditionally-set boolean (NOT the conditional link).
        is_membership = bool(row.get("is_membership_invoice"))
        membership = row.get("membership")
        transaction_type = "Membership Invoice" if is_membership else "Regular Invoice"
        if is_membership and membership:
            reference_doctype = "Membership"
            reference_name = membership
        else:
            reference_doctype = None
            reference_name = None

        # Shared payment-status derivation (same util the service uses).
        status_shim = frappe._dict(
            docstatus=row.get("docstatus"),
            status=row.get("invoice_status"),
            outstanding_amount=flt(row.get("outstanding_amount")),
            grand_total=flt(row.get("grand_total")),
        )
        payment_status = determine_payment_status(status_shim, flt(row.get("paid_amount", 0)))

        payment_entry = row.get("payment_entry")
        sepa_mandate = row.get("sepa_mandate")

        return {
            "invoice": row["invoice_name"],
            "invoice_doctype": "Sales Invoice",  # Required for Dynamic Link
            "posting_date": row.get("posting_date"),
            "due_date": row.get("due_date"),
            "coverage_start_date": row.get("coverage_start_date"),
            "coverage_end_date": row.get("coverage_end_date"),
            "transaction_type": transaction_type,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "amount": flt(row.get("grand_total")),
            "outstanding_amount": flt(row.get("outstanding_amount")),
            "status": row.get("invoice_status"),
            "payment_status": payment_status,
            "payment_date": row.get("payment_date"),
            "payment_entry": payment_entry,
            "payment_entry_doctype": "Payment Entry" if payment_entry else None,
            "payment_method": row.get("payment_method"),
            "paid_amount": flt(row.get("paid_amount", 0)),
            "reconciled": 1 if row.get("reconciled") else 0,
            "has_mandate": 1 if row.get("has_mandate") else 0,
            "sepa_mandate": sepa_mandate,
            "sepa_mandate_doctype": "SEPA Mandate" if sepa_mandate else None,
            "mandate_status": row.get("mandate_status"),
            "mandate_reference": row.get("mandate_reference"),
        }
```

- [ ] **Step 4: Make `build_from_invoice_doc` delegate**

In `build_from_invoice_doc`, keep the existing PE-reference query, coverage-field read, and mandate-resolution blocks that compute `paid_amount`, `payment_entry`, `payment_date`, `payment_method`, `reconciled`, `coverage_start_date`, `coverage_end_date`, `has_mandate`, `sepa_mandate`, `mandate_status`, `mandate_reference`. **Remove** its inline `transaction_type`/`reference_*` block (the `if hasattr(invoice_doc, "membership")...` at ~65-68) and its inline `payment_status` ladder (~105-116). Replace the final `entry = {...}; return entry` (~168-196) with:

```python
        row = {
            "invoice_name": invoice_doc.name,
            "is_membership_invoice": getattr(invoice_doc, "is_membership_invoice", 0),
            "membership": getattr(invoice_doc, "membership", None),  # ast-skip: custom field
            "posting_date": invoice_doc.posting_date,
            "due_date": invoice_doc.due_date,
            "grand_total": invoice_doc.grand_total,
            "outstanding_amount": invoice_doc.outstanding_amount,
            "invoice_status": invoice_doc.status,
            "docstatus": invoice_doc.docstatus,
            "coverage_start_date": coverage_start_date,
            "coverage_end_date": coverage_end_date,
            "paid_amount": paid_amount,
            "reconciled": reconciled,
            "payment_entry": payment_entry,
            "payment_date": payment_date,
            "payment_method": payment_method,
            "has_mandate": has_mandate,
            "sepa_mandate": sepa_mandate,
            "mandate_status": mandate_status,
            "mandate_reference": mandate_reference,
        }
        return PaymentHistoryEntryBuilder.build_from_query_row(row)
```

- [ ] **Step 5: Migrate the existing regression fixtures to the new schema**

In `test_regression_payment_history_dynamic_links.py`, every `query_row` fixture currently uses keys `invoice_name`, `membership_id`, `grand_total`, `outstanding_amount`, `invoice_status`, `payment_status`, `allocated_amount`, `payment_entry`, `sepa_mandate`. Update each to the canonical schema: replace `"membership_id": X` with `"is_membership_invoice": 1, "membership": X`; drop `"payment_status"` (now derived — add `"docstatus"` + `"invoice_status"` instead); rename `"allocated_amount"` → `"paid_amount"`. Keep the `*_doctype` assertions unchanged. In the existing `build_from_invoice_doc` vs `build_from_query_row` consistency test, feed the query_row the same `is_membership_invoice`/`membership` the invoice doc carries.

- [ ] **Step 6: Run tests to verify they pass**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_regression_payment_history_dynamic_links`
Expected: PASS (all, including the migrated fixtures and the two new tests).

- [ ] **Step 7: Commit**

```bash
git add verenigingen/utils/payment_history_builder.py verenigingen/tests/payment/test_regression_payment_history_dynamic_links.py
git commit -m "refactor(payment-history): single invoice-row builder via build_from_query_row

Classify by is_membership_invoice; membership link supplies reference only.
Shared determine_payment_status. build_from_invoice_doc now delegates.

Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu"
```

---

## Task 2: Route the `PaymentHistoryService` rebuild through the builder

**Files:**
- Modify: `verenigingen/services/member/payment/payment_history_service.py` (`load_payment_history_batched` ~138-230, `_build_entry_from_invoice` ~343-448)
- Test: `verenigingen/tests/services/test_payment_history_service_realdb.py`

**Interfaces:**
- Consumes: `PaymentHistoryEntryBuilder.build_from_query_row` (Task 1).
- Produces: `load_payment_history_batched` appends builder-produced dicts for invoice rows; unchanged public signature (`OperationResult`).

- [ ] **Step 1: Write the failing test** — membership-without-link classification via the real service.

Add to `TestPaymentHistoryServiceRealDB`:

```python
def test_membership_invoice_without_link_classified_by_boolean(self):
    inv = self._make_submitted_invoice(is_membership_invoice=1)
    # No membership link set on the invoice.
    self.member.reload()
    self.service.load_payment_history_batched(self.member)
    rows = [r for r in self.member.payment_history if r.invoice == inv.name]
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0].transaction_type, "Membership Invoice")
    self.assertIsNone(rows[0].reference_name)
```

(If `create_test_sales_invoice` doesn't accept `is_membership_invoice`, set it in `_make_submitted_invoice` before submit: `invoice.is_membership_invoice = 1`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: FAIL — current `_build_entry_from_invoice` classifies via `is_membership_invoice` but returns `transaction_type` set and `reference_doctype=None`; the assertion on the *builder-consistent* behavior differs, or the row is "Regular". (Confirms the service isn't yet on the shared builder.)

- [ ] **Step 3: Rewrite `_build_entry_from_invoice` to assemble a row and call the builder**

Replace the method body (keep the payment-cache extraction of `paid_amount`/`payment_entry`/`payment_date`/`payment_method`/`reconciled`, coverage-service call, and mandate resolution) so it ends by returning a dict from the builder rather than a `PaymentHistoryEntry`:

```python
    def _build_entry_from_invoice(
        self, member_doc, invoice, payment_cache, default_mandate
    ) -> Dict[str, Any]:
        payment_refs = payment_cache.payment_refs_by_invoice.get(invoice.name, [])
        payment_date = payment_entry = payment_method = None
        paid_amount = 0.0
        reconciled = 0

        if payment_refs:
            for pe_ref in payment_refs:
                payment_cache.reconciled_payments.append(pe_ref.parent)
                paid_amount += float(pe_ref.allocated_amount or 0)
            relevant = [
                payment_cache.payments_by_name[r.parent]
                for r in payment_refs
                if r.parent in payment_cache.payments_by_name
            ]
            if relevant:
                most_recent = max(relevant, key=lambda p: p.posting_date)
                payment_entry = most_recent.name
                payment_date = most_recent.posting_date
                payment_method = most_recent.mode_of_payment
                reconciled = 1

        coverage = self._coverage_service.get_coverage_for_invoice(
            member_doc.name, invoice.name, invoice
        )
        if not self._coverage_service.validate_coverage_period(coverage, invoice.name):
            coverage.start_date = None
            coverage.end_date = None

        has_mandate = 1 if default_mandate else 0
        row = {
            "invoice_name": invoice.name,
            "is_membership_invoice": invoice.get("is_membership_invoice"),
            "membership": invoice.get("membership"),
            "posting_date": invoice.posting_date,
            "due_date": invoice.due_date,
            "grand_total": invoice.grand_total,
            "outstanding_amount": invoice.outstanding_amount,
            "invoice_status": invoice.status,
            "docstatus": invoice.docstatus,
            "coverage_start_date": coverage.start_date,
            "coverage_end_date": coverage.end_date,
            "paid_amount": paid_amount,
            "reconciled": reconciled,
            "payment_entry": payment_entry,
            "payment_date": payment_date,
            "payment_method": payment_method,
            "has_mandate": has_mandate,
            "sepa_mandate": default_mandate.name if default_mandate else None,
            "mandate_status": default_mandate.status if default_mandate else None,
            "mandate_reference": getattr(default_mandate, "mandate_id", None) if default_mandate else None,
        }
        from verenigingen.utils.payment_history_builder import PaymentHistoryEntryBuilder

        return PaymentHistoryEntryBuilder.build_from_query_row(row)
```

Then in `load_payment_history_batched`, change the invoice loop to append the dict directly (it already does `member_doc.append("payment_history", entry.to_dict())` — change to `member_doc.append("payment_history", entry)` since the builder returns a dict). Add `"is_membership_invoice"` and `"membership"` to the `_fetch_invoices` field list (base_fields ~243-252).

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: the new test PASSes; pre-existing invoice-row tests still pass. (The unreconciled/donation tests will still fail here — they are fixed in Task 3.)

- [ ] **Step 5: Commit**

```bash
git add verenigingen/services/member/payment/payment_history_service.py verenigingen/tests/services/test_payment_history_service_realdb.py
git commit -m "refactor(payment-history): service rebuild builds invoice rows via shared builder

Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu"
```

---

## Task 2B: Add the Sales Invoice `membership` field and fetch it in the rebuild

**Added mid-execution** (see spec "Correction discovered during implementation"): `Sales Invoice` has no `membership` field, so the Membership reference could never persist. Approved resolution: add the field (forward-only, no backfill).

**Files:**
- Modify: `verenigingen/fixtures/custom_field.json` (add one Sales Invoice field)
- Modify: `verenigingen/services/member/payment/payment_history_service.py` (`_fetch_invoices` — add `membership` to the queried fields, guarded by `has_column`)
- Test: `verenigingen/tests/services/test_payment_history_service_realdb.py`

**Interfaces:**
- Produces: a persisted `membership` Link(Membership) field on Sales Invoice; the rebuild's invoice query returns `membership`; `build_from_query_row` (Task 1) already turns it into `reference_doctype="Membership"`/`reference_name=<membership>`.

- [ ] **Step 1: Add the custom field fixture**

Add to `verenigingen/fixtures/custom_field.json` a full entry modelled on the existing `"Sales Invoice-is_membership_invoice"` entry (copy ALL its keys/defaults, changing only the fields below):

```json
{
  "name": "Sales Invoice-membership",
  "dt": "Sales Invoice",
  "fieldname": "membership",
  "fieldtype": "Link",
  "label": "Membership",
  "options": "Membership",
  "insert_after": "is_membership_invoice",
  "module": "Verenigingen",
  "read_only": 1
}
```
Keep every other key at the same default the sibling `is_membership_invoice` entry uses (docstatus, translatable, etc.). `read_only: 1` because the generator populates it, not the user.

- [ ] **Step 2: Migrate the test site so the column exists**

Run: `bench --site test_site_1 migrate`
Then verify: `bench --site test_site_1 console` → `frappe.db.has_column("Sales Invoice", "membership")` returns `True`. Repeat migrate on any other test_site_N a test run will use.

- [ ] **Step 3: Write the failing test** — the reference now flows end-to-end.

```python
def test_membership_reference_persists_and_flows_to_history(self):
    """With the membership field present, a linked membership becomes the row reference."""
    membership = self.create_test_membership(member=self.member.name)  # or the factory's equivalent
    inv = self._make_submitted_invoice(is_membership_invoice=1)
    frappe.db.set_value("Sales Invoice", inv.name, "membership", membership.name)
    self.member.reload()
    self.service.load_payment_history_batched(self.member)
    row = next(r for r in self.member.payment_history if r.invoice == inv.name)
    self.assertEqual(row.transaction_type, "Membership Invoice")
    self.assertEqual(row.reference_doctype, "Membership")
    self.assertEqual(row.reference_name, membership.name)
```
If the factory has no `create_test_membership`, create a minimal Membership doc inline in the test helper (real doc, no mock) and `track_doc` it. If setting `membership` via the field is blocked because it is read_only, use `frappe.db.set_value` as shown (bypasses the read-only UI guard for test setup).

- [ ] **Step 4: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: FAIL — `_fetch_invoices` does not yet select `membership`, so the builder receives `membership=None` and `reference_doctype` stays `None`.

- [ ] **Step 5: Fetch `membership` in `_fetch_invoices`**

In `payment_history_service.py._fetch_invoices`, following the existing `has_column` guard pattern used for the coverage fields, conditionally append `membership` to the queried fields:

```python
        if frappe.db.has_column("Sales Invoice", "membership"):
            query_fields.append("membership")
```
(Place it alongside the coverage-field guard block so the query stays a single `frappe.get_all`.) The builder already maps `row.get("membership")` → the reference.

- [ ] **Step 6: Run test to verify it passes**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: PASS (new test + all pre-existing).

- [ ] **Step 7: Commit**

```bash
git add verenigingen/fixtures/custom_field.json verenigingen/services/member/payment/payment_history_service.py verenigingen/tests/services/test_payment_history_service_realdb.py
git commit -m "feat(payment-history): add persisted Sales Invoice membership link

Sales Invoice had no membership field, so the dues generator's assignment
never persisted. Add the Link(Membership) custom field (forward-only) and
fetch it in the rebuild so the Membership reference is real and consistent
across both writers.

Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu"
```

---

## Task 3: Delete the phantom PE row-types from the service

**Files:**
- Modify: `verenigingen/services/member/payment/payment_history_service.py` (delete `_add_unreconciled_payments` ~450-528; delete its call ~206-209)
- Test: `verenigingen/tests/services/test_payment_history_service_realdb.py`

**Interfaces:**
- Produces: `load_payment_history_batched` emits invoice rows only; no `_add_unreconciled_payments`.

- [ ] **Step 1: Invert the phantom-row tests**

In `test_payment_history_service_realdb.py`, find the tests asserting an "Unreconciled Payment" standalone row and a "Donation Payment" classification. Replace their assertions with the guarantee that no such rows are produced. Example replacement test:

```python
def test_no_pe_based_rows_are_emitted(self):
    """payment_history is invoice-only; standalone Payment Entries never add rows."""
    inv = self._make_submitted_invoice(is_membership_invoice=1)
    self._pay_invoice(inv)  # creates a PE referencing the SI
    self.member.reload()
    self.service.load_payment_history_batched(self.member)
    types = {r.transaction_type for r in self.member.payment_history}
    self.assertNotIn("Unreconciled Payment", types)
    self.assertNotIn("Donation Payment", types)
    # The reconciling PE marks the invoice row Paid, it does not add its own row.
    self.assertTrue(all(r.invoice for r in self.member.payment_history))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: FAIL — `_add_unreconciled_payments` still adds standalone rows (or the old inverted tests still reference deleted behavior).

- [ ] **Step 3: Delete the phantom logic**

In `load_payment_history_batched`, delete the block (~206-209):

```python
            # Add unreconciled payments
            unreconciled_count = self._add_unreconciled_payments(
                member_doc, payment_cache.reconciled_payments
            )
```

Update the return `data` dict to drop `unreconciled_payments` and set `entries_loaded` to `success_count`. Delete the entire `_add_unreconciled_payments` method (~450-528). Remove the now-unused `reconciled_payments` tracking only if nothing else reads it (leave `payment_cache.reconciled_payments` appends — harmless, still used to identify reconciled PEs for the invoice row).

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/services/member/payment/payment_history_service.py verenigingen/tests/services/test_payment_history_service_realdb.py
git commit -m "refactor(payment-history): drop dead PE-based unreconciled/donation rows from service

Zero such rows ever produced on production; payment_history is invoice-only.

Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu"
```

---

## Task 4: Collapse the `background_jobs` rebuild into the service

**Files:**
- Modify: `verenigingen/utils/background_jobs.py` (`load_payment_history_batch_optimized` ~511-791; `refresh_member_financial_history_optimized` ~463-509 reads `result["entries_processed"]`)
- Test: `verenigingen/tests/services/test_payment_history_service_realdb.py` (add a refresh-path test)

**Interfaces:**
- Consumes: `get_payment_history_service().load_payment_history_batched(member_doc) -> OperationResult` (populates `member_doc.payment_history` in memory).
- Produces: `load_payment_history_batch_optimized(member_doc) -> {"entries_processed": int}` (unchanged shape, so `refresh_member_financial_history_optimized` keeps working).

- [ ] **Step 1: Write the failing test** — the persisting refresh path emits invoice-only rows via the service.

```python
def test_refresh_optimized_uses_service_invoice_only(self):
    from verenigingen.utils.background_jobs import refresh_member_financial_history_optimized

    inv = self._make_submitted_invoice(is_membership_invoice=1)
    self.member.reload()
    result = refresh_member_financial_history_optimized(self.member)
    self.assertEqual(result["status"], "completed")
    self.member.reload()
    types = {r.transaction_type for r in self.member.payment_history}
    self.assertNotIn("Unreconciled Payment", types)
    self.assertTrue(any(r.invoice == inv.name for r in self.member.payment_history))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: FAIL — the current `load_payment_history_batch_optimized` still emits "Unreconciled Payment" rows (inline block ~746-789).

- [ ] **Step 3: Replace `load_payment_history_batch_optimized` with a delegator**

Delete the entire inline body (~511-791: the invoice batch queries, the invoice loop, and the unreconciled-payments loop) and replace the function with:

```python
def load_payment_history_batch_optimized(member_doc) -> Dict[str, Any]:
    """Populate member_doc.payment_history via the canonical service rebuild.

    Row construction now lives in PaymentHistoryService (single source of truth).
    This function is retained only as the in-memory populate step for
    refresh_member_financial_history_optimized (which owns cache + save).
    """
    from verenigingen.services.member.payment import get_payment_history_service

    result = get_payment_history_service().load_payment_history_batched(member_doc)
    count = result.data.get("entries_loaded", 0) if result.success else 0
    return {"entries_processed": count}
```

Note: `refresh_member_financial_history_optimized` already clears `member_doc.payment_history = []` before calling and `save()`s after — leave that wrapper intact. The service also clears the table internally; the double-clear is harmless.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: PASS.

- [ ] **Step 5: Verify the on-load path is unaffected + no other caller broke**

Run: `grep -rn "load_payment_history_batch_optimized" verenigingen/ --include=*.py`
Expected: only the definition + `refresh_member_financial_history_optimized` call remain. Confirm `execute_member_payment_history_update_sync` still resolves.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/utils/background_jobs.py verenigingen/tests/services/test_payment_history_service_realdb.py
git commit -m "refactor(payment-history): collapse background_jobs rebuild into the service

background_jobs now owns only orchestration (cache+save); row construction is
the service's job. Removes the second (drifted) full-rebuild implementation.

Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu"
```

---

## Task 5: Remove the two phantom-row readers

**Files:**
- Modify: `verenigingen/verenigingen/doctype/member/mixins/financial_mixin.py:149-152`
- Modify: `verenigingen/public/js/member/js_modules/payment-utils.js:160-164`
- Test: `verenigingen/tests/member/` (financial summary), Jest for JS

**Interfaces:**
- Produces: `get_financial_summary()` no longer returns `donations` / `unreconciled_payments` keys.

- [ ] **Step 1: Write the failing test** — summary no longer advertises phantom counters.

Add a real-DB test (e.g. in `test_payment_history_service_realdb.py` or a member mixin test):

```python
def test_financial_summary_has_no_phantom_counters(self):
    self._make_submitted_invoice(is_membership_invoice=1)
    self.member.reload()
    self.service.load_payment_history_batched(self.member)
    summary = self.member.get_financial_summary()
    self.assertNotIn("donations", summary)
    self.assertNotIn("unreconciled_payments", summary)
    self.assertIn("membership_invoices", summary)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: FAIL — `get_financial_summary` still returns both keys (financial_mixin.py:149-152).

- [ ] **Step 3: Remove the Python counters**

In `financial_mixin.py`, delete these two dict entries (lines 149-152):

```python
                "donations": len([p for p in payment_history if p.transaction_type == "Donation Payment"]),
                "unreconciled_payments": len(
                    [p for p in payment_history if p.transaction_type == "Unreconciled Payment"]
                ),
```

- [ ] **Step 4: Remove the JS branches**

In `payment-utils.js`, delete the two trailing `else if` branches (lines 160-164):

```javascript
		} else if (record.transaction_type === 'Donation Payment') {
			stats.donations++;
		} else if (record.transaction_type === 'Unreconciled Payment') {
			stats.unreconciled++;
		}
```

Leave the preceding `Membership Invoice` / `Regular Invoice` branches intact (close the `else if` chain cleanly). If `stats.donations` / `stats.unreconciled` are initialized earlier in the file and read by no template, remove those initializers too (grep first: `grep -n "stats.donations\|stats.unreconciled" payment-utils.js`).

- [ ] **Step 5: Run tests + JS lint**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb`
Expected: PASS.
Run: `npx eslint verenigingen/public/js/member/js_modules/payment-utils.js`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/verenigingen/doctype/member/mixins/financial_mixin.py verenigingen/public/js/member/js_modules/payment-utils.js verenigingen/tests/services/test_payment_history_service_realdb.py
git commit -m "refactor(payment-history): drop phantom-row readers (summary counters + JS branches)

Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu"
```

---

## Task 6: Divergence regression test (incremental vs rebuild)

**Files:**
- Create: `verenigingen/tests/payment/test_payment_history_writer_parity.py`

**Interfaces:**
- Consumes: `member._build_payment_history_entry(invoice)` (incremental builder path) and `get_payment_history_service().load_payment_history_batched(member)` (rebuild path).

- [ ] **Step 1: Write the parity test**

```python
# Copyright (c) 2026, Veganisme.org and contributors
"""Guard against the incremental writer and the full rebuild diverging."""

import frappe
from verenigingen.services.member.payment.payment_history_service import get_payment_history_service
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Fields compared for parity (exclude volatile/reference-metadata-only fields).
PARITY_FIELDS = [
    "invoice", "transaction_type", "reference_doctype", "reference_name",
    "amount", "outstanding_amount", "status", "payment_status",
    "payment_entry", "payment_method", "paid_amount", "reconciled",
    "coverage_start_date", "coverage_end_date",
]


class TestPaymentHistoryWriterParity(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Par", last_name="Ity")
        self.link_member_to_customer(self.member)
        self.member.reload()
        self.service = get_payment_history_service()

    def _make_submitted_invoice(self, **kwargs):
        unique = f"PAR-{frappe.generate_hash(length=8).upper()}-.#####"
        inv = self.create_test_sales_invoice(self.member.name, naming_series=unique, **kwargs)
        inv.is_membership_invoice = kwargs.get("is_membership_invoice", 0)
        inv.save()
        inv.submit()
        self.track_doc("Sales Invoice", inv.name)
        return inv

    def test_incremental_row_matches_rebuild_row(self):
        inv = self._make_submitted_invoice(is_membership_invoice=1)
        self.member.reload()

        # Rebuild path
        self.service.load_payment_history_batched(self.member)
        rebuild_row = next(r for r in self.member.payment_history if r.invoice == inv.name)

        # Incremental path
        incremental_entry = self.member._build_payment_history_entry(frappe.get_doc("Sales Invoice", inv.name))

        for field in PARITY_FIELDS:
            self.assertEqual(
                incremental_entry.get(field),
                rebuild_row.get(field),
                f"Divergence on '{field}': incremental={incremental_entry.get(field)!r} "
                f"rebuild={rebuild_row.get(field)!r}",
            )

    def test_reconciling_pe_flips_invoice_row_to_paid(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        inv = self._make_submitted_invoice(is_membership_invoice=1)
        pe = get_payment_entry("Sales Invoice", inv.name)
        pe.reference_no = "PARITY-PE"
        pe.reference_date = frappe.utils.today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)

        self.member.reload()
        entry = self.member._build_payment_history_entry(frappe.get_doc("Sales Invoice", inv.name))
        self.assertEqual(entry["payment_status"], "Paid")
        self.assertEqual(entry["reconciled"], 1)
        self.assertEqual(entry["transaction_type"], "Membership Invoice")
```

- [ ] **Step 2: Run the parity test**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_history_writer_parity`
Expected: PASS. If `test_incremental_row_matches_rebuild_row` fails, the failure message names the diverging field — reconcile the builder so both paths agree (do not weaken the test).

- [ ] **Step 3: Commit**

```bash
git add verenigingen/tests/payment/test_payment_history_writer_parity.py
git commit -m "test(payment-history): guard incremental vs rebuild row parity

Claude-Session: https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu"
```

---

## Task 7: Full-suite verification + reader sweep

- [ ] **Step 1: Re-grep for any surviving phantom-row producers/readers**

Run:
```bash
grep -rn "Unreconciled Payment\|_add_unreconciled_payments" verenigingen/ --include=*.py --include=*.js | grep -v "/tests/\|test_"
grep -rn "transaction_type == 'Donation Payment'\|transaction_type === 'Donation Payment'" verenigingen/ --include=*.py --include=*.js
```
Expected: no non-test hits for the deleted producer logic (the `Donation Payment` **DocType** references in mollie/donation code are unrelated and must remain).

- [ ] **Step 2: Run the full payment + services test modules**

Run:
```bash
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.services.test_payment_history_service_realdb
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_payment_history_writer_parity
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.payment.test_regression_payment_history_dynamic_links
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.member.test_member_service_coverage
```
Expected: all PASS (the last confirms the `PaymentHistoryEntry` dataclass test still passes — the dataclass is retained even though the rebuild no longer uses it for invoice rows).

- [ ] **Step 3: Pre-commit on touched files**

Run: `pre-commit run --files verenigingen/utils/payment_history_builder.py verenigingen/services/member/payment/payment_history_service.py verenigingen/utils/background_jobs.py verenigingen/verenigingen/doctype/member/mixins/financial_mixin.py verenigingen/public/js/member/js_modules/payment-utils.js`
Expected: Passed/Skipped only.

- [ ] **Step 4: Push branch and open PR**

```bash
git push -u origin unify-payment-history-writers
gh pr create --base develop --title "refactor(payment-history): unify member payment-history writers onto one invoice-row builder" --body "$(cat <<'EOF'
Collapses the incremental writer + two full rebuilds onto a single invoice-row
builder and deletes the dead PE-based unreconciled/donation row-types (0 rows
ever produced on production — verified against veg11).

Spec: docs/superpowers/specs/2026-07-22-unify-member-payment-history-writers-design.md
Plan: docs/superpowers/plans/2026-07-22-unify-member-payment-history-writers.md

https://claude.ai/code/session_014NZnxsmjTaNPUMQroLSFLu
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** WS1 (delete phantom) → Tasks 3+5+7; WS2 (collapse rebuilds) → Task 4; WS3 (shared builder + classifier) → Tasks 1+2; WS4 (incremental needs no new type) → verified by Task 6 parity + reconciliation test. Out-of-scope items (bank txns, expenses, veg11 Unpaid) are untouched.
- **Behavior change (intended):** membership invoice without a `membership` link now classifies as "Membership Invoice" — covered by Task 2 Step 1.
- **Type consistency:** canonical row schema is defined once (File Structure) and consumed identically in Tasks 1, 2, 4. `build_from_query_row` returns a dict everywhere; the service appends that dict (not `.to_dict()`).
- **Retained on purpose:** the `PaymentHistoryEntry` dataclass (still referenced by `test_member_service_coverage.py`); `payment_cache.reconciled_payments` (used to mark invoice rows reconciled).
