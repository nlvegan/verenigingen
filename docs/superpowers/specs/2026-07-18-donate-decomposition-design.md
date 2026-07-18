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
  (draft=True). They are ~80% identical. **Complete** list of differences that the
  merged function must preserve under the `draft` flag (verified against
  `donate.py:425` and `donate.py:487`):
  - `status`: `map_donation_status(form_data.donation_status)` (final) vs
    `"Promised"` (draft).
  - campaign field handling: the final path does the
    `frappe.db.exists("Donation Campaign", …)` existence-check with the
    notes-fallback; the draft path sets `campaign` directly.
  - ANBI agreement fields (`anbi_agreement_number`/`_date`): final path only.
  - **explicit `donation_doc.validate()`**: draft path calls it (`donate.py:463`)
    before insert; final path does not (it validates once via `insert()`). The
    plan must decide to keep the explicit call for the draft branch (safest —
    behavior-preserving) after confirming `Donation.validate()` is
    side-effect-free/idempotent.
  - **save mechanism**: draft uses a raw `secure_user_context` block with an
    explicit `flags.ignore_mandatory = False` (`donate.py:471`); final uses the
    `_save_donation_as_system_user` helper. Collapse both to the helper (the
    helper is functionally equivalent; `ignore_mandatory=False` is already the
    default). State this collapse explicitly in the plan.
  - **logging**: draft emits an info log after insert (`donate.py:475`); final
    does not. Preserve (guard the log on the `draft` branch).
  - NOT a difference: the campaign `if/elif` chain (draft) vs three separate `if`s
    (final) — `donation_purpose_type` is single-valued, so they are equivalent.
    Do not "simplify" one into the other as if fixing a bug.
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
  `secure_user_context`, and sets `owner` to the system user (the `owner`
  override stays in this public-form wrapper, NOT in the shared builder).

**Shared `_build_new_donor` must be parameterized — the two flows set DIVERGENT
field sets** (verified against `donate.py:386` and `donor_service.py:160`):

| field | public form | `create_donor_from_donation_data` |
|---|---|---|
| `donor_name`/`donor_email`/`phone`/`donor_type` | yes | yes |
| `contact_person` / `address` / `donor_category` | yes | **no** |
| `anbi_consent` | not set | `= 0` |
| `owner` override (post-insert) | yes | no |

The shared helper must reproduce each flow's exact field set (e.g. via explicit
kwargs), so it removes the duplicated *lookup + construction skeleton* without
silently giving either flow fields it never had. Note: `create_donor_from_donation_data`
is currently **test-only** (`tests/services/test_donor_service.py`) — no production
caller — so the risk of the shared builder is contained, but "behavior-preserving"
still requires the divergent field sets be kept exact. The two flows keep their
distinct security wrappers and return types (doc vs name).

**Not fully unified — third copy out of scope:** `web_form/donation_form/donation_form.py`
has its OWN `get_or_create_donor` (line 103, already using `get_donor_by_email`)
and its own `create_donation` (line 84). It is a separate web form and stays out
of scope; "single implementation" here means the *donate.py page* flow, not the
whole app. To avoid cross-module confusion with that file's `create_donation`, the
new service method lives on `PublicDonationService` (namespaced), not as a bare
module function.

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
   the API contract test and JS callers keep working. Keep `@frappe.whitelist()`
   outermost per the decorator-order rule.
3. **Operation-context strings are cosmetic:** `get_system_user_for_operation`
   uses its `operation_context` argument only for log/error text — it always
   returns `settings.creation_user`. So the differing context strings between the
   draft and final save paths do NOT switch system users; the merge cannot change
   which user owns the record via that argument. (Safety finding — reduces merge
   risk.)

### Import discipline

The new `public_donation_service.py` must import `PaymentHook` and the Mollie
`CompletePaymentService` **at function level, not module top**. No import cycle
exists today (the donation services don't import payments, and payments don't
import `services.donation`), but the `Donation` DocType controller imports
`services.donation.*`. A service that imports payments at module scope could
create a load-order cycle if any controller later imports the service at module
scope. `donate.py` currently imports `PaymentHook` at module top (fine for a
*page*); do not carry that top-level import into the *service*.

## Test strategy

- **Update test imports** to the new service locations (decision). Only **four**
  files import symbols that actually MOVE (verified by grep):
  `tests/backend/portal/test_guest_donation_flow.py`,
  `tests/backend/components/test_donate_page.py`,
  `tests/backend/components/test_donate_page_mollie.py`,
  `tests/backend/portal/test_page_donate.py` (the last only for
  `map_donation_status`; its `get_context`/`get_donation_status`/
  `mark_donation_paid`/`retry_payment` imports STAY, those endpoints remain in
  donate.py). Each keeps asserting the same behavior; only the import path changes.
- **Do NOT touch** these (they were on an earlier over-inclusive list):
  `tests/integration/test_sepa_mandate_authentication_security.py` imports nothing
  from donate — its `process_sepa_direct_debit` is a local test closure, not an
  import; `tests/donor/test_campaign_donation_integration.py` and
  `tests/donor/test_donation_agreement.py` import ONLY `submit_donation`, which
  stays in donate.py.
- **Delete** the isolated tests that exercise only the dead processors
  (`test_process_bank_transfer_*`, `test_process_sepa_direct_debit_*`,
  `test_process_cash_payment_*`, and the parametrized rows in
  `test_guest_donation_flow.py` that iterate over those three). The live
  PaymentHook path stays covered by the guest-donation-flow and Mollie tests.
  **Before deleting, confirm coverage of the equivalent response shapes on the
  live path:** `_convert_payment_hook_response` must have (or gain) a test for the
  `MANDATE_FORM` → `mandate_required` and `SHOW_INSTRUCTIONS` → `awaiting_transfer`
  (bank) / `cash_pending` (cash) branches. The surviving `process_payment_method`
  test only covers an always-available method — if these conversion branches are
  otherwise uncovered, ADD a `_convert_payment_hook_response` unit test rather than
  losing the assertion outright.
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
- **Modify:** 4 test files (import updates — see Test strategy)
- **Delete:** dead processors + their isolated tests (add a
  `_convert_payment_hook_response` branch test if coverage gap confirmed)
