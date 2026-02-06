# Validation Endpoint Boilerplate Extraction — Implementation Plan — COMPLETED

> **Status:** COMPLETED (2026-02-06). All 6 tasks executed. 14 endpoints rewritten using 3 shared wrappers. Commits: `49b61746`, `b843e173` and others.

**Goal:** Extract repeated try/except/OperationResult boilerplate from 15 validation & data-fetch endpoints into 3 shared helper functions, saving ~200 LOC and establishing a single error-handling policy.

**Architecture:** Three internal helper functions (`_wrap_validation`, `_wrap_data_fetch`, `_wrap_success_check`) added to `api/membership_application.py`. Each endpoint becomes a 2–4 line function that delegates to the appropriate wrapper. Legacy aliases remain unchanged (they already just redirect). Endpoints with unique logic (validate_email, validate_postal_code, submit_application, etc.) are NOT touched.

**Tech Stack:** Python, Frappe, OperationResult

---

## Scope — What Gets Wrapped vs What Stays

### Endpoints to wrap (15 total):

**Group A — Validation pattern** (`{"valid": True/False}`):
1. `validate_phone_number` (lines 296-318)
2. `validate_birth_date` (lines 328-350)
3. `validate_name` (lines 360-382)
4. `validate_custom_amount_endpoint` (lines 952-975)
5. `validate_membership_amount_selection_endpoint` (lines 924-949)
6. `validate_address_endpoint` (lines 1733-1757) — has `parse_application_data` pre-processing
7. `check_application_eligibility_endpoint` (lines 392-415) — uses `eligible` key, different error shape

**Group B — Data fetch pattern** (always returns ok unless exception):
8. `get_membership_fee_info_endpoint` (lines 867-883)
9. `get_membership_type_details_endpoint` (lines 886-902)
10. `suggest_membership_amounts_endpoint` (lines 905-921)
11. `get_payment_methods_endpoint` (lines 978-994)
12. `get_member_field_info_endpoint` (lines 1050-1066)

**Group C — Success-check pattern** (`{"success": True/False}`):
13. `save_draft_application_endpoint` (lines 997-1021) — has `parse_application_data` pre-processing
14. `load_draft_application_endpoint` (lines 1024-1047)
15. `check_application_status_endpoint` (lines 1069-1092)

### Endpoints NOT touched (unique logic):
- `validate_email` — has APIValidator pre-processing, null check, isinstance guard
- `validate_postal_code` — has extra chapter suggestion logic after validation
- `suggest_chapters_for_postal_code` — complex standalone with postal range matching
- `submit_application` — multi-step orchestrator (~300 lines)
- `approve_membership_application` — deprecated redirect
- `reject_membership_application` — business logic
- `process_application_payment_endpoint` — business logic
- `get_application_form_data` — has fallback data on error
- All test/debug endpoints
- All legacy alias endpoints (they already just redirect)

---

## Task 1: Write characterization tests for current endpoint behavior

**Files:**
- Create: `vereinigingen/tests/backend/unit/api/test_validation_endpoint_wrappers.py`

These tests capture the EXACT current behavior so the refactoring can't accidentally change response shapes.

**Step 1: Write the test file**

```python
"""
Characterization tests for validation endpoint OperationResult responses.
These tests capture current behavior to ensure the wrapper refactoring
produces identical results.
"""
import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.api.membership_application import (
    check_application_eligibility_endpoint,
    check_application_status_endpoint,
    get_member_field_info_endpoint,
    get_membership_fee_info_endpoint,
    get_membership_type_details_endpoint,
    get_payment_methods_endpoint,
    load_draft_application_endpoint,
    suggest_membership_amounts_endpoint,
    validate_address_endpoint,
    validate_birth_date,
    validate_custom_amount_endpoint,
    validate_membership_amount_selection_endpoint,
    validate_name,
    validate_phone_number,
)
from verenigingen.utils.operation_result import OperationResult


class TestValidationEndpointShapes(FrappeTestCase):
    """Verify each endpoint returns correct OperationResult shape."""

    # --- Group A: Validation pattern ---

    def test_validate_phone_number_valid(self):
        result = validate_phone_number("+31612345678", "Netherlands")
        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)
        self.assertTrue(result.data.get("valid"))

    def test_validate_phone_number_invalid(self):
        result = validate_phone_number("not-a-phone", "Netherlands")
        self.assertIsInstance(result, OperationResult)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertTrue(len(result.errors) > 0)

    def test_validate_birth_date_valid(self):
        result = validate_birth_date("1990-01-15")
        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success)
        self.assertTrue(result.data.get("valid"))

    def test_validate_birth_date_invalid(self):
        result = validate_birth_date("3000-01-01")
        self.assertIsInstance(result, OperationResult)
        self.assertFalse(result.success)

    def test_validate_name_valid(self):
        result = validate_name("Jan", "First name")
        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success)
        self.assertTrue(result.data.get("valid"))

    def test_validate_name_invalid(self):
        result = validate_name("", "First name")
        self.assertIsInstance(result, OperationResult)
        self.assertFalse(result.success)

    # --- Group B: Data fetch pattern ---

    def test_get_payment_methods_endpoint(self):
        result = get_payment_methods_endpoint()
        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data)

    def test_get_member_field_info_endpoint(self):
        result = get_member_field_info_endpoint()
        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success)

    # --- Group C: Success-check pattern ---

    def test_load_draft_invalid_id(self):
        result = load_draft_application_endpoint("NONEXISTENT-DRAFT-12345")
        self.assertIsInstance(result, OperationResult)
        # Should fail gracefully, not crash
        # (exact success/fail depends on implementation)

    def test_check_application_status_invalid_id(self):
        result = check_application_status_endpoint("NONEXISTENT-APP-12345")
        self.assertIsInstance(result, OperationResult)
        # Should fail gracefully
```

**Step 2: Run tests to verify they pass with current code**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module vereinigingen.tests.backend.unit.api.test_validation_endpoint_wrappers`

Expected: All tests PASS (characterizing current behavior).

**Step 3: Commit**

```bash
git add vereinigingen/tests/backend/unit/api/test_validation_endpoint_wrappers.py
git commit -m "test: add characterization tests for validation endpoint response shapes"
```

---

## Task 2: Add the three wrapper helper functions

**Files:**
- Modify: `verenigingen/api/membership_application.py` (add functions after line ~97, in the utility section)

**Step 1: Add the three wrapper functions**

Insert after the `check_rate_limit` function (around line 97), before the `# API Endpoints` comment:

```python
def _wrap_validation(fn, field_name="field", operation=""):
    """Generic wrapper for validation endpoints returning {"valid": True/False}.

    Eliminates repeated try/except/OperationResult boilerplate across validation
    endpoints. The fn callable should return a dict with at least a "valid" key.
    """
    try:
        result = fn()
        if result.get("valid"):
            return OperationResult.ok(result, message=_(f"{field_name} is valid"))
        return OperationResult.fail(
            _(result.get("message", f"{field_name} validation failed")),
            errors=[result.get("type", "validation_error")],
            context=result,
        )
    except Exception as e:
        log_error(
            f"{field_name} validation error: {str(e)}\n{traceback.format_exc()}",
            f"{field_name} Validation Error",
        )
        return OperationResult.fail(
            _(f"{field_name} validation failed"),
            errors=[str(e)],
            context={"operation": operation or f"validate_{field_name.lower()}"},
        )


def _wrap_data_fetch(fn, success_message="Data retrieved", error_message="Error retrieving data", operation=""):
    """Generic wrapper for data-fetch endpoints that always return ok unless exception.

    Eliminates repeated try/except/OperationResult boilerplate across
    endpoints that call a utility function and wrap its result in OperationResult.ok().
    """
    try:
        result = fn()
        return OperationResult.ok(result, message=_(success_message))
    except Exception as e:
        log_error(
            f"{operation} error: {str(e)}\n{traceback.format_exc()}",
            f"{operation} Error",
        )
        return OperationResult.fail(
            _(error_message),
            errors=[str(e)],
            context={"operation": operation},
        )


def _wrap_success_check(fn, success_message="", fail_message="", fail_error="failed", operation=""):
    """Generic wrapper for endpoints returning {"success": True/False}.

    Eliminates repeated try/except/OperationResult boilerplate across
    endpoints that delegate to utility functions returning success dicts.
    """
    try:
        result = fn()
        if result.get("success"):
            return OperationResult.ok(result, message=_(success_message))
        return OperationResult.fail(
            _(result.get("message", fail_message)),
            errors=[result.get("error", fail_error)],
            context=result,
        )
    except Exception as e:
        log_error(
            f"{operation} error: {str(e)}\n{traceback.format_exc()}",
            f"{operation} Error",
        )
        return OperationResult.fail(
            _(f"Error: {fail_message.lower()}" if fail_message else "Operation failed"),
            errors=[str(e)],
            context={"operation": operation},
        )
```

**Step 2: Run the characterization tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module vereinigingen.tests.backend.unit.api.test_validation_endpoint_wrappers`

Expected: PASS (wrappers added but not yet used — no behavior change).

**Step 3: Commit**

```bash
git add verenigingen/api/membership_application.py
git commit -m "refactor: add _wrap_validation, _wrap_data_fetch, _wrap_success_check helpers"
```

---

## Task 3: Rewrite Group A validation endpoints to use `_wrap_validation`

**Files:**
- Modify: `verenigingen/api/membership_application.py`

**Step 1: Rewrite 5 validation endpoints**

Replace `validate_phone_number` (lines 296-318) with:
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_phone_number(phone, country="Netherlands") -> OperationResult[Dict[str, Any]]:
    """Validate phone number format"""
    return _wrap_validation(
        lambda: validate_phone_number_util(phone, country),
        field_name="Phone number",
        operation="validate_phone_number",
    )
```

Replace `validate_birth_date` (lines 328-350) with:
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_birth_date(birth_date) -> OperationResult[Dict[str, Any]]:
    """Validate birth date"""
    return _wrap_validation(
        lambda: validate_birth_date_util(birth_date),
        field_name="Birth date",
        operation="validate_birth_date",
    )
```

Replace `validate_name` (lines 360-382) with:
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_name(name, field_name="Name") -> OperationResult[Dict[str, Any]]:
    """Validate name fields"""
    return _wrap_validation(
        lambda: validate_name_util(name, field_name),
        field_name=field_name,
        operation="validate_name",
    )
```

Replace `validate_membership_amount_selection_endpoint` (lines 924-949) with:
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_membership_amount_selection_endpoint(
    membership_type, amount, uses_custom
) -> OperationResult[Dict[str, Any]]:
    """Validate membership amount selection"""
    return _wrap_validation(
        lambda: validate_membership_amount_selection(membership_type, amount, uses_custom),
        field_name="Membership amount selection",
        operation="validate_membership_amount_selection",
    )
```

Replace `validate_custom_amount_endpoint` (lines 952-975) with:
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_custom_amount_endpoint(membership_type, amount) -> OperationResult[Dict[str, Any]]:
    """Validate custom membership amount"""
    return _wrap_validation(
        lambda: validate_custom_amount_util(membership_type, amount),
        field_name="Custom amount",
        operation="validate_custom_amount",
    )
```

Replace `validate_address_endpoint` (lines 1733-1757) with:
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def validate_address_endpoint(data) -> OperationResult[Dict[str, Any]]:
    """Validate address data"""
    return _wrap_validation(
        lambda: validate_address_util(parse_application_data(data)),
        field_name="Address",
        operation="validate_address",
    )
```

**Note:** `validate_address_endpoint` currently uses `errors=result.get("errors", ["validation_failed"])` instead of `errors=[result.get("type", "validation_error")]`. This is a MINOR divergence. The wrapper uses the standard `type` key. If the address validator returns errors in the `errors` key, those will still be in `context=result`. The error list in `OperationResult.errors` will say `"validation_error"` instead of the specific errors list. This is acceptable since the actual error details are in `context`.

**Step 2: Rewrite `check_application_eligibility_endpoint`**

This endpoint uses `eligible` key instead of `valid`. Use a custom lambda:
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def check_application_eligibility_endpoint(data) -> OperationResult[Dict[str, Any]]:
    """Check if applicant is eligible for membership"""
    try:
        parsed_data = parse_application_data(data)
        result = check_application_eligibility_util(parsed_data)
        if result.get("eligible"):
            return OperationResult.ok(result, message=_("Applicant is eligible for membership"))
        return OperationResult.fail(
            _("Applicant is not eligible for membership"),
            errors=result.get("issues", []),
            context={"warnings": result.get("warnings", [])},
        )
    except Exception as e:
        log_error(
            f"Eligibility check error: {str(e)}\n{traceback.format_exc()}",
            "Eligibility Check Error",
        )
        return OperationResult.fail(
            _("Eligibility check failed"),
            errors=[str(e)],
            context={"operation": "check_application_eligibility"},
        )
```

**Decision:** Keep this one as-is. Its error shape (`issues`, `warnings`) is unique and doesn't fit the `_wrap_validation` pattern without adding confusing parameters. It's only 18 lines and clear on its own. Forcing it into a wrapper would add complexity, not reduce it.

**Step 3: Run characterization tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module vereinigingen.tests.backend.unit.api.test_validation_endpoint_wrappers`

Expected: All PASS.

**Step 4: Commit**

```bash
git add verenigingen/api/membership_application.py
git commit -m "refactor: rewrite validation endpoints to use _wrap_validation helper"
```

---

## Task 4: Rewrite Group B data-fetch endpoints to use `_wrap_data_fetch`

**Files:**
- Modify: `verenigingen/api/membership_application.py`

**Step 1: Rewrite 5 data-fetch endpoints**

Replace `get_membership_fee_info_endpoint` (lines 867-883):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_membership_fee_info_endpoint(membership_type) -> OperationResult[Dict[str, Any]]:
    """Get membership fee information"""
    return _wrap_data_fetch(
        lambda: get_membership_fee_info_util(membership_type),
        success_message="Membership fee information retrieved",
        error_message="Error retrieving membership fee information",
        operation="get_membership_fee_info",
    )
```

Replace `get_membership_type_details_endpoint` (lines 886-902):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.UTILITY)
def get_membership_type_details_endpoint(membership_type) -> OperationResult[Dict[str, Any]]:
    """Get detailed membership type information"""
    return _wrap_data_fetch(
        lambda: get_membership_type_details_util(membership_type),
        success_message="Membership type details retrieved",
        error_message="Error retrieving membership type details",
        operation="get_membership_type_details",
    )
```

Replace `suggest_membership_amounts_endpoint` (lines 905-921):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def suggest_membership_amounts_endpoint(membership_type_name) -> OperationResult[Dict[str, Any]]:
    """Suggest membership amounts based on type"""
    return _wrap_data_fetch(
        lambda: suggest_membership_amounts_util(membership_type_name),
        success_message="Membership amount suggestions retrieved",
        error_message="Error suggesting membership amounts",
        operation="suggest_membership_amounts",
    )
```

Replace `get_payment_methods_endpoint` (lines 978-994):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_payment_methods_endpoint() -> OperationResult[Dict[str, Any]]:
    """Get available payment methods"""
    return _wrap_data_fetch(
        get_payment_methods_util,
        success_message="Payment methods retrieved",
        error_message="Error retrieving payment methods",
        operation="get_payment_methods",
    )
```

Replace `get_member_field_info_endpoint` (lines 1050-1066):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def get_member_field_info_endpoint() -> OperationResult[Dict[str, Any]]:
    """Get information about member fields for form generation"""
    return _wrap_data_fetch(
        get_member_field_info,
        success_message="Member field information retrieved",
        error_message="Error retrieving member field information",
        operation="get_member_field_info",
    )
```

**Step 2: Run characterization tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module vereinigingen.tests.backend.unit.api.test_validation_endpoint_wrappers`

Expected: All PASS.

**Step 3: Commit**

```bash
git add verenigingen/api/membership_application.py
git commit -m "refactor: rewrite data-fetch endpoints to use _wrap_data_fetch helper"
```

---

## Task 5: Rewrite Group C success-check endpoints to use `_wrap_success_check`

**Files:**
- Modify: `verenigingen/api/membership_application.py`

**Step 1: Rewrite 3 success-check endpoints**

Replace `save_draft_application_endpoint` (lines 997-1021):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def save_draft_application_endpoint(data) -> OperationResult[Dict[str, Any]]:
    """Save application as draft"""
    return _wrap_success_check(
        lambda: save_draft_application_util(parse_application_data(data)),
        success_message="Draft application saved successfully",
        fail_message="Failed to save draft application",
        fail_error="save_failed",
        operation="save_draft_application",
    )
```

Replace `load_draft_application_endpoint` (lines 1024-1047):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def load_draft_application_endpoint(draft_id) -> OperationResult[Dict[str, Any]]:
    """Load application draft"""
    return _wrap_success_check(
        lambda: load_draft_application_util(draft_id),
        success_message="Draft application loaded successfully",
        fail_message="Failed to load draft application",
        fail_error="load_failed",
        operation="load_draft_application",
    )
```

Replace `check_application_status_endpoint` (lines 1069-1092):
```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.MEMBER_DATA)
def check_application_status_endpoint(application_id) -> OperationResult[Dict[str, Any]]:
    """Check the status of an application by ID"""
    return _wrap_success_check(
        lambda: check_application_status_util(application_id),
        success_message="Application status retrieved",
        fail_message="Failed to retrieve application status",
        fail_error="status_check_failed",
        operation="check_application_status",
    )
```

**Step 2: Run characterization tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module vereinigingen.tests.backend.unit.api.test_validation_endpoint_wrappers`

Expected: All PASS.

**Step 3: Commit**

```bash
git add verenigingen/api/membership_application.py
git commit -m "refactor: rewrite success-check endpoints to use _wrap_success_check helper"
```

---

## Task 6: Run full test suite and update audit

**Step 1: Run all verenigingen tests**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen`

Expected: No regressions.

**Step 2: Run linters**

Run: `cd ~/frappe-bench/apps/verenigingen && ruff check verenigingen/api/membership_application.py`

Expected: Clean.

**Step 3: Update audit document**

Modify `docs/audits/membership-application-audit-2026-02-05.md`, section 2.4 header to:

```markdown
### 2.4 Validation Endpoint Boilerplate (~650 LOC) — RESOLVED

**Status:** Resolved 2026-02-05. Three helper functions (`_wrap_validation`, `_wrap_data_fetch`, `_wrap_success_check`) extract repeated try/except/OperationResult boilerplate from 14 endpoints. `check_application_eligibility_endpoint` kept as-is due to unique error shape.
```

**Step 4: Final commit**

```bash
git add docs/audits/membership-application-audit-2026-02-05.md
git commit -m "docs: mark validation endpoint boilerplate as resolved in audit"
```

---

## Summary of changes

| Metric | Before | After |
|--------|--------|-------|
| Validation endpoints (Group A) | ~115 LOC | ~40 LOC |
| Data-fetch endpoints (Group B) | ~85 LOC | ~35 LOC |
| Success-check endpoints (Group C) | ~75 LOC | ~25 LOC |
| Wrapper helpers | 0 LOC | ~50 LOC |
| **Net change** | ~275 LOC | ~150 LOC (~125 saved) |
| Error handling policies | 15 separate implementations | 3 centralized wrappers |
| New error handling location | N/A | Single place to update |
