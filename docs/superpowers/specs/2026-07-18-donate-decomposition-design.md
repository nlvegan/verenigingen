# donate.py Decomposition — Design

**Date:** 2026-07-18
**Audit item:** KISS-2 (`docs/audits/2026-07-17-portal-pages-code-quality-audit.md`)
**Status:** Approved scope — pending spec review

## Goal

Shrink the 1,019-LOC `verenigingen/templates/pages/donate.py` page controller to a
thin HTTP/context layer by relocating the public-donation business logic into
`verenigingen/services/donation/`, and unify donor get-or-create into a single
implementation. Behavior-preserving for all **live** paths, guarded by the
existing donation test suite.

## Context / findings

The audit framed this as "donate.py reimplements `services/donation/`". That is
only partly true — the existing services were built for different flows and are
**not drop-in compatible**:

- `DonationFinancialService.create_donation_from_bank_transfer()` submits with
  `paid=1` and writes minimal fields (for reconciling *already-received* bank
  money). donate.py's `create_donation_record()` keeps `paid=0`, does not submit,
  and does full web-form field mapping (status, purpose type, campaign
  existence-check with notes fallback, chapter, specific-goal, ANBI agreement).
  Genuinely different behaviors, not duplicates.
- The services take a `donation_doc` in their constructor; donate.py works from
  raw guest `form_data` and wraps writes in the public-donation
  `secure_user_context` framework.
- The real overlap is narrower than the audit's "~250 LOC" — mainly donor
  get-or-create.

So the chosen approach is **extraction** (move business logic out of the page
controller into the service layer) **plus unifying the donor get-or-create**, not
forcing deduplication against interface-mismatched services.

### Dead code discovered

`process_bank_transfer`, `process_sepa_direct_debit`, and `process_cash_payment`
are **dead in production**. The live path (`submit_donation` →
`process_payment_method`) routes every method through `PaymentHook.initiate_payment`
+ `_convert_payment_hook_response`, which already produces the bank-details /
mandate / cash responses. The three standalone functions are only reached by tests
that call them in isolation. **Decision: delete them and drop the isolated tests.**

## Architecture

### New module: `services/donation/public_donation_service.py`

`PublicDonationService(StatelessService)` with a `get_public_donation_service()`
singleton accessor, matching the sibling services. Responsibilities:

- `submit(form_data) -> dict` — orchestration currently in `submit_donation`:
  validate required fields + email + amount → donor → donation → payment dispatch
  → structured result dict. Preserves both branches: the Mollie payment-first
  branch (draft donation, then `process_mollie_payment`) and the traditional
  branch (create donation, then `process_payment_method`), including the exact
  partial-success / error response shapes.
- `create_donation(donor, form_data, *, draft=False) -> Document` — merges
  `create_donation_record` (draft=False) and `create_draft_donation_for_payment`
  (draft=True). They are ~80% identical; the differences are:
  - `status`: `map_donation_status(form_data.donation_status)` vs `"Promised"`.
  - the campaign field handling: the final path does the
    `frappe.db.exists("Donation Campaign", …)` existence-check with the
    notes-fallback; the draft path sets `campaign` directly. Both behaviors are
    preserved under the `draft` flag.
  - ANBI agreement fields (final path only).
- Payment dispatch (live): `process_payment_method`, `_convert_payment_hook_response`,
  `process_mollie_payment` move here unchanged in behavior.
- `map_donation_status` (pure helper) moves here (its only non-test caller is
  `create_donation`).
- `_save_donation_as_system_user` (the `secure_user_context` insert/save helper)
  moves here — it is shared by donor-creation, donation-creation, and
  payment-method updates.

### Donor unification — into `DonationDonorService`

Add `get_or_create_from_public_form(form_data) -> Document` (returns the donor
**doc**, matching donate.py's current return contract). It:

- Reuses the canonical `get_donor_by_email` lookup (see behavioral note below).
- On existing donor: updates `phone` if missing, saves via `secure_user_context`.
- On new donor: sets the web-form fields (`donor_name`, `donor_email`, `phone`,
  `address`, `contact_person`, `donor_category="Regular Donor"`, `donor_type` via
  the form→settings→"Individual" fallback chain), inserts via
  `secure_user_context`, and sets `owner` to the system user.

Extract the shared new-donor field construction into a private
`_build_new_donor(...)` helper reused by both `get_or_create_from_public_form`
and the existing `create_donor_from_donation_data`, so donor construction lives in
one place. The two flows keep their distinct security wrappers and return types
(doc vs name) but stop duplicating lookup + construction.

### Thin controller: `donate.py`

Keeps only:
- `get_context(context)` — page render. Its 162-LOC, depth-8 body has the
  Mollie-return-status block (lines ~58–110) extracted into a helper
  (`_resolve_return_payment_status(donation)` in the service or a private module
  fn), flattening the nesting.
- The whitelisted endpoints — `submit_donation`, `get_donation_status`,
  `mark_donation_paid`, `retry_payment` — each a thin wrapper delegating to the
  service. **Endpoint names, paths, decorators, and response shapes are
  unchanged**, so the API contract and JS callers are untouched.

## Behavioral notes (on record)

1. **Donor lookup change:** unifying on `get_donor_by_email` (latest-by-creation,
   the documented canonical lookup) differs from donate.py's current
   `frappe.db.get_value("Donor", {"donor_email": …})` (first-match) **only when
   duplicate donor emails exist**. Arguably a latent-bug fix; recorded as an
   intentional behavior change.
2. **API surface unchanged:** whitelisted endpoint paths
   (`verenigingen.templates.pages.donate.submit_donation`, etc.) stay identical —
   the API contract test and JS callers keep working.

## Test strategy

- **Update test imports** to the new service locations (decision). Affected files
  import donate.py functions directly:
  `tests/backend/portal/test_guest_donation_flow.py`,
  `tests/backend/components/test_donate_page.py`,
  `tests/backend/components/test_donate_page_mollie.py`,
  `tests/backend/portal/test_page_donate.py`,
  `tests/integration/test_sepa_mandate_authentication_security.py`,
  `tests/donor/test_campaign_donation_integration.py`,
  `tests/donor/test_donation_agreement.py`.
  Each keeps asserting the same behavior; only the import path changes.
- **Delete** the isolated tests that exercise only the dead processors
  (`test_process_bank_transfer_*`, `test_process_sepa_direct_debit_*`,
  `test_process_cash_payment_*`, and the parametrized rows in
  `test_guest_donation_flow.py` that iterate over those three). The live
  PaymentHook path stays covered by the guest-donation-flow and Mollie tests.
- The API-contract JS tests (`tests/setup/*`, `tests/unit/*`) reference the
  endpoint *path* string and need **no** change.
- Each moved unit of logic is verified behavior-identical; the portal render
  harness (`verify_portal_base_css.run`) confirms `/donate` still renders.

## Out of scope

- KISS-3 (Mollie page family dedup) and KISS-4 (other stranded business logic) —
  separate audit items.
- Changing the PaymentHook integration or the Mollie `CompletePaymentService`.
- Any change to the `Donation` DocType schema or the donation web form template.

## Module / file summary

- **Create:** `services/donation/public_donation_service.py`
- **Modify:** `services/donation/donor_service.py` (add public-form method +
  `_build_new_donor`)
- **Shrink:** `templates/pages/donate.py` (→ thin controller)
- **Modify:** 7 test files (import updates)
- **Delete:** dead processors + their isolated tests
