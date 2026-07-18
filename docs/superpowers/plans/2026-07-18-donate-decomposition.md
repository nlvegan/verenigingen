# donate.py Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink the 1,019-LOC `verenigingen/templates/pages/donate.py` page controller to a thin HTTP/context layer by relocating public-donation business logic into a new `PublicDonationService`, unify donor get-or-create into `DonationDonorService`, and delete three PaymentHook-superseded dead processors — behavior-preserving for all live paths.

**Architecture:** New `services/donation/public_donation_service.py` (`PublicDonationService(StatelessService)` + `get_public_donation_service()` singleton) owns donation orchestration, creation, payment dispatch, and the pure/secure helpers. `DonationDonorService` gains a public-form donor method sharing a parameterized `_build_new_donor`. `donate.py` keeps `get_context` and the four whitelisted endpoints as thin delegators.

**Tech Stack:** Frappe v16, Python 3.14, `StatelessService` base, existing donation test suite.

**Design doc:** `docs/superpowers/specs/2026-07-18-donate-decomposition-design.md` (read it for the full findings; this plan is the executable form).

## Global Constraints

- **Behavior-preserving for all LIVE paths.** The only accepted behavior change: donor lookup unifies on `get_donor_by_email` (latest-by-creation) vs the old `frappe.db.get_value` (first-match) — differs only with duplicate donor emails.
- **`@frappe.whitelist()` MUST be the outermost decorator** on the four endpoints (Frappe checks whitelist by object identity). Order: `@frappe.whitelist(...)` → security decorator → `def`.
- **Whitelisted endpoint dotted paths are UNCHANGED:** `verenigingen.templates.pages.donate.submit_donation`, `.get_donation_status`, `.mark_donation_paid`, `.retry_payment` all stay in `donate.py`. The API-contract JS tests (`tests/setup/*`, `tests/unit/*`) reference the path string and must NOT need edits.
- **Import discipline:** in `public_donation_service.py`, import `PaymentHook` and Mollie `CompletePaymentService` at FUNCTION level, never module-top (load-order cycle safety — the `Donation` controller imports `services.donation.*`).
- **`_build_new_donor` must preserve each flow's exact field set** (public: `contact_person`/`address`/`donor_category`/owner-override; `create_donor_from_donation_data`: `anbi_consent=0` only). Owner override stays in the public-form wrapper, not the builder.
- **Run tests on a test site, NOT veg11** (veg11's before_tests bootstrap crashes). Use e.g. `bench --site test_site_1 run-tests --app verenigingen --module <dotted.module>`. Portal render check via `bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.verify_portal_base_css.run` is inspection-only and OK on veg11.
- **Follow the sibling service pattern** (`dashboard_service.py`): module-level `_service_instance = None`, `StatelessService.__init__(service_name=...)`, `get_public_donation_service()` accessor.
- Wrap user-facing strings in `_()`. Preserve every `frappe.log_error` title/message and every `secure_user_context` description string verbatim when moving (they are the audit trail; operation-context strings are cosmetic but keep them stable).

---

## File Structure

- **Create:** `verenigingen/services/donation/public_donation_service.py` — `PublicDonationService` + singleton. Owns: `submit`, `create_donation`, `process_payment_method`, `_convert_payment_hook_response`, `process_mollie_payment`, `resolve_return_payment_status`, `get_donation_status_data`, `mark_donation_paid_impl`, `retry_payment_impl`, `map_donation_status`, `_save_donation_as_system_user`.
- **Modify:** `verenigingen/services/donation/donor_service.py` — add `get_or_create_from_public_form` + parameterized `_build_new_donor`; refactor `create_donor_from_donation_data` to use it.
- **Shrink:** `verenigingen/templates/pages/donate.py` — keep `get_context` (Mollie-return block extracted) + four thin whitelisted endpoints; delete relocated functions and the three dead processors.
- **Modify (tests):** `tests/backend/portal/test_guest_donation_flow.py`, `tests/backend/components/test_donate_page.py`, `tests/backend/components/test_donate_page_mollie.py`, `tests/backend/portal/test_page_donate.py`, `tests/services/test_donor_service.py` (only if it asserts `create_donor_from_donation_data` internals).
- **Delete (tests):** the isolated dead-processor tests (see Task 5).

---

### Task 1: Scaffold `PublicDonationService`; move `map_donation_status` + `_save_donation_as_system_user`

**Files:**
- Create: `verenigingen/services/donation/public_donation_service.py`
- Modify: `verenigingen/templates/pages/donate.py` (remove the two defs, import from service)
- Test: `verenigingen/tests/backend/components/test_donate_page.py`, `verenigingen/tests/backend/portal/test_page_donate.py`

**Interfaces:**
- Produces: `PublicDonationService.map_donation_status(status_value: str) -> str` (staticmethod); `PublicDonationService._save_donation_as_system_user(doc, operation, operation_context, description)`; `get_public_donation_service() -> PublicDonationService`.

- [ ] **Step 1: Write the failing test** — repoint the `map_donation_status` assertions in `test_page_donate.py` (line 51) to the service.

```python
# test_page_donate.py — replace the import at line 51
from verenigingen.services.donation.public_donation_service import (
    get_public_donation_service,
)
# in the test body, replace `map_donation_status(...)` calls with:
svc = get_public_donation_service()
self.assertEqual(svc.map_donation_status("One-time donation"), "One-time")
self.assertEqual(svc.map_donation_status("Monthly recurring"), "Recurring")
self.assertEqual(svc.map_donation_status("Promised donation"), "Promised")
self.assertEqual(svc.map_donation_status("Recurring"), "Recurring")
self.assertEqual(svc.map_donation_status("garbage value"), "One-time")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_donate`
Expected: FAIL — `ModuleNotFoundError: verenigingen.services.donation.public_donation_service`.

- [ ] **Step 3: Create the service module with the two helpers**

```python
# verenigingen/services/donation/public_donation_service.py
"""
Public Donation Service

Business logic for the public donation portal (`templates/pages/donate.py`),
extracted from the page controller. Handles donation orchestration, creation,
payment dispatch, and the secure guest-donation write helpers.

PaymentHook / Mollie imports are function-level (not module-top) to avoid a
load-order cycle: the Donation DocType controller imports services.donation.*.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.secure_operations import (
    get_system_user_for_operation,
    secure_document_operation,
    secure_user_context,
)


class PublicDonationService(StatelessService):
    """Business logic for the public donation portal page."""

    def __init__(self):
        super().__init__(service_name="PublicDonationService")

    @staticmethod
    def map_donation_status(status_value):
        """Map form donation status to DocType status values"""
        status_mapping = {
            "One-time donation": "One-time",
            "Monthly recurring": "Recurring",
            "Promised donation": "Promised",
            "One-time": "One-time",
            "Recurring": "Recurring",
            "Promised": "Promised",
        }
        return status_mapping.get(status_value, "One-time")

    def _save_donation_as_system_user(self, doc, operation, operation_context, description):
        """Save or insert a donation/donor document using system user context.

        PUBLIC DONATION FLOW: Guests lack roles in ESCALATION_ALLOWED_ROLES so
        secure_document_operation(allow_system_user=True) fails for them.  This
        helper switches to the configured system user via secure_user_context()
        instead — the same pattern used for donor creation elsewhere.
        """
        system_user = get_system_user_for_operation(operation_context)
        with secure_user_context(system_user, description):
            getattr(doc, operation)()
            frappe.db.commit()


_service_instance = None


def get_public_donation_service() -> PublicDonationService:
    """Get or create the PublicDonationService singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = PublicDonationService()
    return _service_instance
```

- [ ] **Step 4: Point `donate.py` at the service; remove its two defs**

In `donate.py`: delete `def map_donation_status(...)` (lines ~1009-1019) and `def _save_donation_as_system_user(...)` (lines ~319-340). Add near the top-of-module imports:

```python
from verenigingen.services.donation.public_donation_service import (
    get_public_donation_service,
)
```

Replace the two internal call sites in `donate.py` that remain at this stage:
- `create_donation_record` (line ~509): `"status": map_donation_status(...)` → `"status": get_public_donation_service().map_donation_status(...)`
- every `_save_donation_as_system_user(...)` call (lines ~549, 593, 719, 768, 803, 876) → `get_public_donation_service()._save_donation_as_system_user(...)`.

- [ ] **Step 5: Repoint the `test_donate_page.py` map_donation_status test** (lines 120-126) to `get_public_donation_service().map_donation_status(...)` (add the service import at top).

- [ ] **Step 6: Run tests to verify pass**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_donate` and `... --module verenigingen.tests.backend.components.test_donate_page`
Expected: PASS (the map_donation_status and any still-present donate tests). `_save_donation_as_system_user` is exercised indirectly by the donor/donation tests.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/services/donation/public_donation_service.py verenigingen/templates/pages/donate.py verenigingen/tests/backend/portal/test_page_donate.py verenigingen/tests/backend/components/test_donate_page.py
git commit -m "refactor(donate): scaffold PublicDonationService; move map_donation_status + secure save helper"
```

---

### Task 2: Unify donor get-or-create into `DonationDonorService`

**Files:**
- Modify: `verenigingen/services/donation/donor_service.py`
- Modify: `verenigingen/templates/pages/donate.py` (delegate `get_or_create_donor`)
- Test: `verenigingen/tests/backend/portal/test_guest_donation_flow.py`, `verenigingen/tests/backend/components/test_donate_page.py`

**Interfaces:**
- Produces: `DonationDonorService.get_or_create_from_public_form(form_data) -> Document` (returns donor DOC); `DonationDonorService._build_new_donor(...) -> Document` (private, parameterized).
- Consumes: `get_donor_by_email` (module fn, donor_service.py:20), `get_system_user_for_operation`/`secure_user_context` (secure_operations), `get_verenigingen_settings` (settings_utils).

- [ ] **Step 1: Write the failing test** — in `test_guest_donation_flow.py`, repoint the two `get_or_create_donor` uses (lines 201, 214) and their imports (line block ~47 and the local imports at 112/137/169 that name it) to the service:

```python
# replace `from verenigingen.templates.pages.donate import get_or_create_donor`
from verenigingen.services.donation.donor_service import get_donation_donor_service
# and each call `get_or_create_donor(form_data)` becomes:
donor = get_donation_donor_service(None).get_or_create_from_public_form(form_data)
```

(The existing `DonationDonorService.__init__` takes `donation_doc`; the public-form method does not use it, so pass `None`. Confirm the accessor `get_donation_donor_service(donation_doc)` at donor_service.py:394 accepts it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_guest_donation_flow`
Expected: FAIL — `AttributeError: 'DonationDonorService' object has no attribute 'get_or_create_from_public_form'`.

- [ ] **Step 3: Add `_build_new_donor` + `get_or_create_from_public_form`; refactor `create_donor_from_donation_data`**

Add to `DonationDonorService` (in `donor_service.py`). `_build_new_donor` reproduces each flow's exact field set via explicit kwargs:

```python
def _build_new_donor(
    self,
    *,
    donor_name: str,
    email: str,
    donor_type: str,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    contact_person: Optional[str] = None,
    donor_category: Optional[str] = None,
    anbi_consent: Optional[int] = None,
):
    """Construct (not insert) a new Donor doc. Each caller passes exactly the
    fields its flow set historically — do not default-fill divergent fields."""
    donor = frappe.new_doc("Donor")
    donor.donor_name = donor_name
    donor.donor_email = email
    donor.donor_type = donor_type
    if phone:
        donor.phone = phone
    if address is not None:
        donor.address = address
    if contact_person is not None:
        donor.contact_person = contact_person
    if donor_category is not None:
        donor.donor_category = donor_category
    if anbi_consent is not None:
        donor.anbi_consent = anbi_consent
    return donor

def get_or_create_from_public_form(self, form_data):
    """Get existing donor or create one from the public donation web form.

    Returns the donor DOCUMENT (not the name), matching the donate.py contract.
    Uses the public-donation secure_user_context framework for guest writes.
    """
    existing_donor = get_donor_by_email(form_data.donor_email)
    if existing_donor:
        if form_data.get("donor_phone") and not existing_donor.phone:
            existing_donor.phone = form_data.donor_phone
            try:
                system_user = get_system_user_for_operation("public_donation_donor_update")
                with secure_user_context(
                    system_user, f"Updating donor phone for public donation: {existing_donor.name}"
                ):
                    existing_donor.save()
                    frappe.db.commit()
                frappe.logger().info(
                    f"Updated donor {existing_donor.name} with phone information from public donation form"
                )
            except Exception as e:
                frappe.log_error(
                    f"Failed to update donor information: {str(e)}", "Public Donation - Donor Update Error"
                )
        return existing_donor

    from verenigingen.utils.settings_utils import get_verenigingen_settings

    settings = get_verenigingen_settings()
    if not settings:
        frappe.throw(_("Unable to load system settings"), frappe.ValidationError)
    donor_type = form_data.get("donor_type") or getattr(settings, "default_donor_type", None) or "Individual"

    donor_doc = self._build_new_donor(
        donor_name=form_data.donor_name,
        email=form_data.donor_email,
        donor_type=donor_type,
        phone=form_data.get("donor_phone", ""),
        address=form_data.get("donor_address", ""),
        contact_person=form_data.donor_name,
        donor_category="Regular Donor",
    )
    try:
        system_user = get_system_user_for_operation("public_donation_donor_creation")
        with secure_user_context(
            system_user, f"Creating donor for public donation: {form_data.donor_email}"
        ):
            donor_doc.insert()
            frappe.db.commit()
            frappe.db.set_value("Donor", donor_doc.name, "owner", system_user)
            frappe.db.commit()
        frappe.logger().info(
            f"Created donor record for public donation: {form_data.donor_name} ({form_data.donor_email})"
        )
        return donor_doc
    except Exception as e:
        frappe.log_error(
            f"Failed to create donor record for public donation: {str(e)}",
            "Public Donation - Donor Creation Error",
        )
        frappe.throw(_("Unable to process donation: Failed to create donor record"))
```

Then refactor the new-donor branch of `create_donor_from_donation_data` (donor_service.py:159-173) to call `_build_new_donor(donor_name=donor_name, email=email, donor_type=donor_type or self._get_default_donor_type(), phone=phone, anbi_consent=0)` then `donor.insert()`. Its behavior (fields set: name/email/type/phone + `anbi_consent=0`, returns name) must be unchanged.

- [ ] **Step 4: Delegate `donate.py`'s `get_or_create_donor`** — replace its body (lines 342-422) with:

```python
def get_or_create_donor(form_data):
    from verenigingen.services.donation.donor_service import get_donation_donor_service
    return get_donation_donor_service(None).get_or_create_from_public_form(form_data)
```

(This delegate is removed in Task 6 when `submit` moves; keeping it now keeps the tree green and lets any remaining internal caller work.)

- [ ] **Step 5: Repoint `test_donate_page.py`** get_or_create_donor uses (lines 306, 316) to the service accessor.

- [ ] **Step 6: Run tests to verify pass**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_guest_donation_flow` and `... --module verenigingen.tests.backend.components.test_donate_page` and `... --module verenigingen.tests.services.test_donor_service`
Expected: PASS (donor creation/lookup preserved; `create_donor_from_donation_data` still returns name with `anbi_consent=0`).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(donate): unify public-form donor get-or-create into DonationDonorService"
```

---

### Task 3: Merge donation creation into `PublicDonationService.create_donation`

**Files:**
- Modify: `verenigingen/services/donation/public_donation_service.py`
- Modify: `verenigingen/templates/pages/donate.py` (delegate both creators)
- Test: `verenigingen/tests/backend/components/test_donate_page.py`, `verenigingen/tests/backend/components/test_donate_page_mollie.py`

**Interfaces:**
- Produces: `PublicDonationService.create_donation(donor, form_data, *, draft=False) -> Document`.

- [ ] **Step 1: Write the failing tests** — repoint `test_donate_page.py:331` (`create_donation_record`) and `test_donate_page_mollie.py:308` (`create_draft_donation_for_payment`):

```python
# test_donate_page.py
svc = get_public_donation_service()
donation = svc.create_donation(donor, form_data)            # draft=False
# test_donate_page_mollie.py
donation = svc.create_donation(donor, form_data, draft=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.components.test_donate_page_mollie`
Expected: FAIL — `AttributeError: ... has no attribute 'create_donation'`.

- [ ] **Step 3: Implement `create_donation` on `PublicDonationService`** — one function covering BOTH paths under `draft`. Preserve every difference from the design's complete list (status; campaign existence-check + notes-fallback on final vs direct-set on draft; ANBI on final only; explicit `validate()` on draft; info log on draft; save via the shared helper).

```python
def create_donation(self, donor, form_data, *, draft=False):
    """Create a Donation from public-form data.

    draft=True  -> Mollie payment-first flow: status 'Promised', campaign set
                   directly, explicit validate(), info log (mirrors the old
                   create_draft_donation_for_payment).
    draft=False -> traditional flow: status from map_donation_status, campaign
                   existence-checked with notes-fallback, ANBI fields (mirrors
                   the old create_donation_record).
    """
    from verenigingen.utils.settings_utils import get_verenigingen_settings

    settings = get_verenigingen_settings()
    if not settings:
        frappe.throw(
            _("Verenigingen Settings not configured. Please run app installation setup."),
            frappe.ValidationError,
        )

    purpose_type = form_data.get("donation_purpose_type", "General")
    donation_doc = frappe.new_doc("Donation")
    donation_data = {
        "company": settings.company,
        "donor": donor.name,
        "donation_date": getdate(),
        "amount": flt(form_data.amount),
        "mode_of_payment": form_data.get("payment_method"),
        "status": "Promised" if draft else self.map_donation_status(form_data.get("donation_status", "One-time")),
        "donation_purpose_type": purpose_type,
        "donation_notes": form_data.get("donation_notes", ""),
        "paid": 0,
    }

    if draft:
        if purpose_type == "Campaign" and form_data.get("campaign_reference"):
            donation_data["campaign"] = form_data["campaign_reference"]
        elif purpose_type == "Chapter" and form_data.get("chapter_reference"):
            donation_data["chapter_reference"] = form_data["chapter_reference"]
        elif purpose_type == "Specific Goal" and form_data.get("specific_goal_description"):
            donation_data["specific_goal_description"] = form_data["specific_goal_description"]
    else:
        if purpose_type == "Campaign" and form_data.get("campaign_reference"):
            campaign_ref = form_data.get("campaign_reference")
            if frappe.db.exists("Donation Campaign", campaign_ref):
                donation_data["campaign"] = campaign_ref
            else:
                user_notes = donation_data.get("donation_notes", "")
                donation_data["donation_notes"] = (
                    f"Campaign: {campaign_ref}\n\n{user_notes}" if user_notes else f"Campaign: {campaign_ref}"
                )
        if purpose_type == "Chapter" and form_data.get("chapter_reference"):
            donation_data["chapter_reference"] = form_data.get("chapter_reference")
        if purpose_type == "Specific Goal" and form_data.get("specific_goal_description"):
            donation_data["specific_goal_description"] = form_data.get("specific_goal_description")

    donation_doc.update(donation_data)

    if not draft and form_data.get("anbi_agreement_number"):
        donation_doc.anbi_agreement_number = form_data.anbi_agreement_number
        donation_doc.anbi_agreement_date = getdate(form_data.get("anbi_agreement_date", getdate()))

    if draft:
        donation_doc.validate()  # preserve the explicit pre-insert validate() of the old draft path

    try:
        self._save_donation_as_system_user(
            donation_doc,
            "insert",
            "public_donation_draft_creation" if draft else "public_donation_creation",
            (
                f"Creating draft donation for public donation: {donor.donor_email}"
                if draft
                else f"Creating donation for public donation: {donor.donor_email} amount €{form_data.amount}"
            ),
        )
    except Exception as e:
        frappe.log_error(
            message=f"Failed to create donation record: {str(e)}",
            title="Donation Creation Security",
        )
        frappe.throw(_("Unable to process donation: Failed to create donation record"))

    if draft:
        frappe.logger().info(
            f"Created draft donation for public donation: {donor.donor_name} amount €{form_data.amount}"
        )

    return donation_doc
```

- [ ] **Step 4: Delegate both `donate.py` creators** — replace bodies of `create_donation_record` (line 487) and `create_draft_donation_for_payment` (line 425):

```python
def create_donation_record(donor, form_data):
    return get_public_donation_service().create_donation(donor, form_data, draft=False)

def create_draft_donation_for_payment(donor, form_data):
    return get_public_donation_service().create_donation(donor, form_data, draft=True)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `... --module verenigingen.tests.backend.components.test_donate_page` and `... test_donate_page_mollie` and `... test_guest_donation_flow` and `... test_campaign_donation_integration` and `... test_donation_agreement`
Expected: PASS. Pay attention to `test_campaign_donation_integration` (campaign existence-check + notes-fallback) and any ANBI assertions.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(donate): merge donation creation into PublicDonationService.create_donation(draft=)"
```

---

### Task 4: Move payment dispatch; delete dead processors

**Files:**
- Modify: `verenigingen/services/donation/public_donation_service.py`
- Modify: `verenigingen/templates/pages/donate.py` (delegate live dispatch; delete 3 dead processors)
- Test: `verenigingen/tests/backend/components/test_donate_page.py`, `verenigingen/tests/backend/components/test_donate_page_mollie.py`, `verenigingen/tests/backend/portal/test_guest_donation_flow.py`

**Interfaces:**
- Produces: `PublicDonationService.process_payment_method(donation, form_data) -> dict`, `._convert_payment_hook_response(result) -> dict`, `.process_mollie_payment(donation, form_data) -> dict`.

- [ ] **Step 1: Repoint the live-dispatch tests (fail first)** — in `test_donate_page.py`: `process_payment_method` (379, 388), `_convert_payment_hook_response` (396, 410, 415, 427, 438) → `get_public_donation_service().<name>(...)`. In `test_donate_page_mollie.py`: `process_mollie_payment` (320, 341, 351) → service.

- [ ] **Step 2: Run to verify fail**

Run: `... --module verenigingen.tests.backend.components.test_donate_page`
Expected: FAIL — service lacks `process_payment_method`/`_convert_payment_hook_response`.

- [ ] **Step 3: Move the three live functions into the service** — copy `process_payment_method` (donate.py:568-641), `_convert_payment_hook_response` (644-712), `process_mollie_payment` (794-866) verbatim into `PublicDonationService` as methods (add `self`; internal calls to `_save_donation_as_system_user` become `self._save_donation_as_system_user`; internal `_convert_payment_hook_response(...)` becomes `self._convert_payment_hook_response(...)`). Keep the `from ...hooks import PaymentHook` and `from ...complete_payment_service import CompletePaymentService` imports FUNCTION-LEVEL inside the methods (do not move to module top).

- [ ] **Step 4: Delegate in `donate.py` and DELETE dead processors** — replace `process_payment_method`, `_convert_payment_hook_response`, `process_mollie_payment` bodies with `return get_public_donation_service().<name>(...)` one-liners (these delegates are removed in Task 5/6 as callers move; keep for green). **Delete** `process_bank_transfer` (715-761), `process_sepa_direct_debit` (764-791), `process_cash_payment` (872-898) entirely — they are dead (PaymentHook path supersedes them).

- [ ] **Step 5: Delete the dead-processor tests** — remove `test_process_bank_transfer_returns_instructions` (test_donate_page.py:340), `test_process_cash_payment_returns_pending` (348), `test_process_sepa_direct_debit_returns_mandate_required` (354); and in `test_guest_donation_flow.py` remove the parametrized rows/imports iterating over `process_bank_transfer`/`process_sepa_direct_debit`/`process_cash_payment` (lines ~137-146). Confirm the `_convert_payment_hook_response` tests (repointed in Step 1) still cover the `mandate_required`/`awaiting_transfer`/`cash_pending` shapes — they do (test_donate_page.py:415-438); no new test needed.

- [ ] **Step 6: Run tests to verify pass**

Run: `... test_donate_page` and `... test_donate_page_mollie` and `... test_guest_donation_flow`
Expected: PASS; the deleted tests are gone; the response-shape assertions live on via `_convert_payment_hook_response`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(donate): move payment dispatch to service; delete PaymentHook-superseded dead processors"
```

---

### Task 5: Move `submit` orchestration; thin `submit_donation` endpoint; drop internal delegates

**Files:**
- Modify: `verenigingen/services/donation/public_donation_service.py`
- Modify: `verenigingen/templates/pages/donate.py`
- Test: `verenigingen/tests/backend/portal/test_guest_donation_flow.py`

**Interfaces:**
- Produces: `PublicDonationService.submit(form_data) -> dict`.
- Consumes: `get_donation_donor_service`, own `create_donation`/`process_payment_method`/`process_mollie_payment`.

- [ ] **Step 1: Confirm the endpoint contract test is green baseline** — `test_guest_donation_flow.py` imports `submit_donation` from `donate` (stays valid). Run it to record the current pass set.

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_guest_donation_flow`
Expected: PASS (baseline).

- [ ] **Step 2: Implement `PublicDonationService.submit(form_data)`** — move the orchestration from `donate.py:submit_donation` (216-316, the body inside the try). It calls `get_donation_donor_service(None).get_or_create_from_public_form(form_data)`, then the Mollie branch (`self.create_donation(donor, form_data, draft=True)` → `self.process_mollie_payment`) vs traditional branch (`self.create_donation(donor, form_data, draft=False)` → `self.process_payment_method`). Preserve EVERY response dict shape (validation errors, partial-success `donation_created`, Mollie redirect wrapping, the outer exception handler with `debug_error`). Keep the required-field/email-regex/amount validation verbatim.

- [ ] **Step 3: Thin the endpoint** — replace `donate.py:submit_donation` body with:

```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.FINANCIAL)
def submit_donation(**kwargs):
    """Process donation form submission (delegates to PublicDonationService)."""
    return get_public_donation_service().submit(frappe._dict(kwargs))
```

- [ ] **Step 4: Remove now-unused internal delegates** — with `submit` moved, delete from `donate.py`: `get_or_create_donor`, `create_donation_record`, `create_draft_donation_for_payment`, `process_payment_method`, `_convert_payment_hook_response`, `process_mollie_payment` (all now live in services and have no remaining `donate.py` caller). Grep `donate.py` to confirm no internal references remain before deleting each.

- [ ] **Step 5: Run tests to verify pass**

Run: `... test_guest_donation_flow` and `... test_donate_page` and `... test_donate_page_mollie`
Expected: PASS — same response shapes, endpoint path unchanged.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(donate): move submit orchestration to service; thin submit_donation endpoint"
```

---

### Task 6: Extract `get_context` Mollie-return block; thin status/paid/retry endpoints

**Files:**
- Modify: `verenigingen/services/donation/public_donation_service.py`
- Modify: `verenigingen/templates/pages/donate.py`
- Test: `verenigingen/tests/backend/portal/test_page_donate.py`

**Interfaces:**
- Produces: `PublicDonationService.resolve_return_payment_status(donation) -> dict` (returns `{"payment_status":..., "title":..., "payment_pending_webhook":bool?}`); `.get_donation_status_data(donation_id) -> dict`; `.mark_donation_paid_impl(donation_id, payment_reference) -> dict`; `.retry_payment_impl(donation_id) -> str|None` (returns payment_url or None; raises on error).

- [ ] **Step 1: Repoint/confirm `test_page_donate.py`** — `get_context` (63,79,106,118,129), `get_donation_status` (141,150,157), `mark_donation_paid` (164), `retry_payment` (179,185,193) imports all STAY (endpoints remain in donate.py). Add any new assertions if `resolve_return_payment_status` warrants a direct unit test; otherwise the existing `get_context` tests cover it. Run to confirm baseline.

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.portal.test_page_donate`
Expected: PASS (baseline).

- [ ] **Step 2: Extract the return-status resolver** — move the `donation_id`-return block in `get_context` (donate.py:57-110, the paid/Mollie-status logic) into `PublicDonationService.resolve_return_payment_status(donation)`, returning a dict the controller applies to `context`. In `get_context`, replace the nested block with:

```python
    donation_id = frappe.form_dict.get("donation_id")
    if donation_id:
        try:
            donation = frappe.get_doc("Donation", donation_id)
            context.donation_result = donation
            status = get_public_donation_service().resolve_return_payment_status(donation)
            context.payment_status = status["payment_status"]
            context.title = status["title"]
            if status.get("payment_pending_webhook"):
                context.payment_pending_webhook = True
        except frappe.DoesNotExistError:
            frappe.log_error(f"Donation {donation_id} not found on return from payment")
            context.payment_status = "error"
```

`resolve_return_payment_status` contains the paid/`payment_id`/Mollie-client branch (donate.py:64-106) verbatim, returning the corresponding `payment_status`/`title` (and `payment_pending_webhook` when Mollie reports paid). Keep the Mollie import function-level and the `frappe.log_error` on client failure.

- [ ] **Step 3: Move status/paid/retry bodies to the service; thin the endpoints** — move `get_donation_status` body (908-923) → `get_donation_status_data`; `mark_donation_paid` body (930-951) → `mark_donation_paid_impl`; `retry_payment` body (958-1006) → `retry_payment_impl` (return the payment_url on success, `None` if no redirect; keep the `frappe.throw`s). Endpoints become:

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_donation_status(donation_id):
    return get_public_donation_service().get_donation_status_data(donation_id)

@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def mark_donation_paid(donation_id, payment_reference: str | None = None):
    return get_public_donation_service().mark_donation_paid_impl(donation_id, payment_reference)

@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.FINANCIAL)
def retry_payment(donation_id):
    payment_url = get_public_donation_service().retry_payment_impl(donation_id)
    if payment_url:
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = payment_url
        return
    frappe.throw(_("Failed to create retry payment. Please try again or contact support."))
```

Keep `mark_donation_paid`'s `frappe.has_permission("Donation", "write")` guard and `secure_document_operation` inside `mark_donation_paid_impl` verbatim. `retry_payment_impl` keeps the paid/mode_of_payment checks and the outer try/except → `frappe.throw`. (The HTTP redirect assignment stays in the endpoint, not the service.)

- [ ] **Step 4: Clean up `donate.py` imports** — remove now-unused imports (`flt`/`getdate`/`secure_document_operation`/`secure_user_context`/`get_system_user_for_operation`/`PaymentHook` if no longer referenced by the remaining `get_context` + endpoints). Grep to confirm before removing each; `QueryBuilder` and `_` are still used by `get_context`.

- [ ] **Step 5: Run tests + render check**

Run: `... test_page_donate` and the full donation set: `... test_donate_page`, `... test_donate_page_mollie`, `... test_guest_donation_flow`, `... test_campaign_donation_integration`, `... test_donation_agreement`, `... test_donor_service`.
Then render: `bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.verify_portal_base_css.run` (expect `VERIFY OK` — `/donate` still renders).
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(donate): extract get_context return-status resolver; thin status/paid/retry endpoints"
```

---

### Task 7: Final sweep — confirm donate.py is thin, no dead references, full suite green

**Files:**
- Modify: `verenigingen/templates/pages/donate.py` (docstring/comment cleanup only if needed)
- Test: whole donation suite

- [ ] **Step 1: Verify controller shrink** — `wc -l verenigingen/templates/pages/donate.py` should be dramatically smaller (≈250-350 LOC: docstring + imports + `get_context` + 4 endpoints). Grep donate.py for any leftover business logic or references to deleted names.

- [ ] **Step 2: Grep the app** for stale references to moved/deleted symbols outside the service and the 4 test files:

```bash
grep -rn "donate import \(get_or_create_donor\|create_donation_record\|create_draft_donation_for_payment\|process_payment_method\|process_mollie_payment\|process_bank_transfer\|process_sepa_direct_debit\|process_cash_payment\|_convert_payment_hook_response\|map_donation_status\|_save_donation_as_system_user\)" verenigingen/ --include="*.py" | grep -v coverage_html_report
```
Expected: no non-test hits; no hits for the three deleted processors anywhere (incl. tests).

- [ ] **Step 3: Run the full donation-related suite**

Run each module: `test_page_donate`, `test_donate_page`, `test_donate_page_mollie`, `test_guest_donation_flow`, `test_campaign_donation_integration`, `test_donation_agreement`, `test_donor_service`, and the donation dashboard/reporting tests if present.
Expected: ALL PASS.

- [ ] **Step 4: Commit any final cleanup**

```bash
git add -A
git commit -m "refactor(donate): final cleanup — thin controller, no dead references"
```

---

## Self-Review notes

- **Spec coverage:** new `PublicDonationService` (Tasks 1,3,4,5,6), donor unification with parameterized `_build_new_donor` (Task 2), dead-processor deletion + test deletion (Task 4), thin controller + endpoint paths unchanged (Tasks 5,6), 4-file test migration (spread across tasks), function-level payment imports (Task 4), coverage of response shapes retained via `_convert_payment_hook_response` tests (Task 4). All covered.
- **Behavior notes honored:** donor lookup change is the only accepted delta; every response dict shape and log/secure-context string moves verbatim; explicit draft `validate()` preserved.
- **Type consistency:** `get_or_create_from_public_form` returns a doc; `create_donor_from_donation_data` still returns a name; `create_donation` returns a doc; `retry_payment_impl` returns url|None with the redirect assignment kept in the endpoint.
