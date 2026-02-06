# -*- coding: utf-8 -*-
# Copyright (c) 2026, Your Organization and Contributors
# See license.txt

"""
Characterization tests for membership application validation endpoint wrappers.

These tests capture the EXACT current behavior of 15 validation/data-fetch/success-check
endpoints in verenigingen.api.membership_application. They serve as a safety net
during refactoring: if any test breaks after a code change, the behavior has shifted.

IMPORTANT: The @public_api decorator converts OperationResult objects to dicts
(via OperationResult.to_dict(nested=True)) before returning. So when calling
these endpoint functions directly in Python, the return type is a dict with the
nested schema:
  Success: {"success": True, "timestamp": ..., "data": {...}, "meta": {...}}
  Failure: {"success": False, "timestamp": ..., "error": {"message": ..., "errors": [...]}, "meta": {...}}

The tests verify:
- result["success"] (bool)
- result["data"] (dict) on success, result["error"] (dict) on failure
- Key fields within data/error

Endpoints are grouped by pattern:
  Group A (Validation): returns {"valid": True/False} inside result["data"]
  Group B (Data fetch): always returns success unless exception
  Group C (Success-check): returns {"success": True/False} inside result["data"]
"""

import json

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
    save_draft_application_endpoint,
    suggest_membership_amounts_endpoint,
    validate_address_endpoint,
    validate_birth_date,
    validate_custom_amount_endpoint,
    validate_membership_amount_selection_endpoint,
    validate_name,
    validate_phone_number,
)


def _get_any_membership_type():
    """Return the name of a real Membership Type, or None if none exist."""
    types = frappe.get_all("Membership Type", limit=1)
    return types[0]["name"] if types else None


def _assert_success_shape(test_case, result):
    """Assert the common shape of a successful response dict."""
    test_case.assertIsInstance(result, dict)
    test_case.assertTrue(result["success"])
    test_case.assertIn("timestamp", result)
    test_case.assertIn("data", result)
    test_case.assertIsInstance(result["data"], dict)


def _assert_failure_shape(test_case, result):
    """Assert the common shape of a failed response dict."""
    test_case.assertIsInstance(result, dict)
    test_case.assertFalse(result["success"])
    test_case.assertIn("timestamp", result)
    test_case.assertIn("error", result)
    test_case.assertIsInstance(result["error"], dict)
    test_case.assertIn("message", result["error"])


# ---------------------------------------------------------------------------
# Group A -- Validation pattern
# ---------------------------------------------------------------------------


class TestValidatePhoneNumber(FrappeTestCase):
    """Characterize validate_phone_number endpoint wrapper."""

    def test_valid_phone_returns_success_with_valid_data(self):
        result = validate_phone_number("+31612345678", "Netherlands")
        _assert_success_shape(self, result)
        self.assertTrue(result["data"]["valid"])
        self.assertIn("message", result["data"])

    def test_invalid_phone_returns_failure(self):
        result = validate_phone_number("not-a-phone", "Netherlands")
        _assert_failure_shape(self, result)
        self.assertIn("errors", result["error"])
        self.assertIsInstance(result["error"]["errors"], list)
        self.assertTrue(len(result["error"]["errors"]) > 0)

    def test_empty_phone_is_optional_so_valid(self):
        """Phone is optional; empty string still passes the underlying validator."""
        result = validate_phone_number("", "Netherlands")
        _assert_success_shape(self, result)
        self.assertTrue(result["data"]["valid"])


class TestValidateBirthDate(FrappeTestCase):
    """Characterize validate_birth_date endpoint wrapper."""

    def test_valid_birth_date_returns_success(self):
        result = validate_birth_date("1990-01-15")
        _assert_success_shape(self, result)
        self.assertTrue(result["data"]["valid"])
        self.assertIn("age", result["data"])

    def test_future_birth_date_returns_failure(self):
        result = validate_birth_date("3000-01-01")
        _assert_failure_shape(self, result)
        self.assertIn("errors", result["error"])

    def test_empty_birth_date_returns_failure(self):
        result = validate_birth_date("")
        _assert_failure_shape(self, result)


class TestValidateName(FrappeTestCase):
    """Characterize validate_name endpoint wrapper."""

    def test_valid_name_returns_success(self):
        result = validate_name("Jan", "First name")
        _assert_success_shape(self, result)
        self.assertTrue(result["data"]["valid"])
        self.assertIn("sanitized", result["data"])

    def test_empty_name_returns_failure(self):
        result = validate_name("", "First name")
        _assert_failure_shape(self, result)
        self.assertIn("errors", result["error"])

    def test_name_with_html_tags_returns_failure(self):
        result = validate_name("<script>alert(1)</script>", "First name")
        _assert_failure_shape(self, result)


class TestValidateMembershipAmountSelection(FrappeTestCase):
    """Characterize validate_membership_amount_selection_endpoint wrapper."""

    def test_with_nonexistent_membership_type_returns_failure(self):
        result = validate_membership_amount_selection_endpoint(
            "NONEXISTENT-TYPE-12345", 10, False
        )
        _assert_failure_shape(self, result)
        self.assertIn("errors", result["error"])

    def test_with_real_membership_type_zero_custom_returns_failure(self):
        mt = _get_any_membership_type()
        if not mt:
            self.skipTest("No Membership Type exists in database")

        result = validate_membership_amount_selection_endpoint(mt, 0, True)
        # Custom amount of 0 is invalid ("must be greater than 0")
        _assert_failure_shape(self, result)


class TestValidateCustomAmount(FrappeTestCase):
    """Characterize validate_custom_amount_endpoint wrapper."""

    def test_with_nonexistent_membership_type_returns_failure(self):
        result = validate_custom_amount_endpoint("NONEXISTENT-TYPE-12345", 50)
        _assert_failure_shape(self, result)

    def test_with_real_membership_type_and_null_amount(self):
        mt = _get_any_membership_type()
        if not mt:
            self.skipTest("No Membership Type exists in database")

        result = validate_custom_amount_endpoint(mt, None)
        _assert_failure_shape(self, result)
        self.assertIn("valid amount", result["error"]["message"].lower())

    def test_with_real_membership_type_and_positive_amount(self):
        mt = _get_any_membership_type()
        if not mt:
            self.skipTest("No Membership Type exists in database")

        result = validate_custom_amount_endpoint(mt, 9999)
        _assert_success_shape(self, result)
        self.assertTrue(result["data"]["valid"])


class TestValidateAddressEndpoint(FrappeTestCase):
    """Characterize validate_address_endpoint wrapper."""

    def test_valid_address_returns_success(self):
        address_data = json.dumps(
            {
                "address_line1": "Keizersgracht 123",
                "city": "Amsterdam",
                "postal_code": "1015CJ",
                "country": "Netherlands",
            }
        )
        result = validate_address_endpoint(address_data)
        _assert_success_shape(self, result)
        self.assertTrue(result["data"]["valid"])

    def test_missing_fields_returns_failure_with_errors_list(self):
        """Address validation uses errors=result.get('errors', ['validation_failed'])
        so the error object has a list of specific missing-field messages."""
        address_data = json.dumps(
            {
                "address_line1": "",
                "city": "",
                "postal_code": "",
                "country": "",
            }
        )
        result = validate_address_endpoint(address_data)
        _assert_failure_shape(self, result)
        errors = result["error"]["errors"]
        self.assertIsInstance(errors, list)
        self.assertTrue(len(errors) > 0)
        # The fixed error message is "Address validation failed"
        self.assertIn("Address validation failed", result["error"]["message"])


class TestCheckApplicationEligibility(FrappeTestCase):
    """Characterize check_application_eligibility_endpoint wrapper."""

    def test_eligible_applicant_returns_success_with_eligible_key(self):
        """On success, data contains 'eligible' key, not 'valid' or 'success'."""
        data = json.dumps(
            {
                "first_name": "Test",
                "last_name": "User",
                "email": f"chartest-{frappe.utils.random_string(8)}@example.com",
                "birth_date": "1990-01-01",
                "address_line1": "Test Street 123",
                "city": "Amsterdam",
                "postal_code": "1000AA",
                "country": "Netherlands",
            }
        )
        result = check_application_eligibility_endpoint(data)
        self.assertIsInstance(result, dict)
        # Should be eligible if membership types exist
        if result["success"]:
            _assert_success_shape(self, result)
            self.assertTrue(result["data"]["eligible"])
        else:
            # If not eligible (e.g., no membership types), verify the fail shape
            _assert_failure_shape(self, result)

    def test_ineligible_applicant_returns_failure_with_issues(self):
        """Fail path uses errors from result.get('issues'),
        and context/meta contains 'warnings'."""
        data = json.dumps(
            {
                "first_name": "",
                "last_name": "",
                "email": "invalid-email",
                "birth_date": "",
                "address_line1": "",
                "city": "",
                "postal_code": "",
                "country": "",
            }
        )
        result = check_application_eligibility_endpoint(data)
        _assert_failure_shape(self, result)
        self.assertIn("not eligible", result["error"]["message"])
        errors = result["error"]["errors"]
        self.assertIsInstance(errors, list)
        self.assertTrue(len(errors) > 0)
        # meta contains "context" with "warnings" key
        self.assertIn("meta", result)
        context = result["meta"].get("context", {})
        self.assertIn("warnings", context)


# ---------------------------------------------------------------------------
# Group B -- Data fetch pattern
# ---------------------------------------------------------------------------


class TestGetMembershipFeeInfo(FrappeTestCase):
    """Characterize get_membership_fee_info_endpoint wrapper."""

    def test_with_real_membership_type_returns_success(self):
        mt = _get_any_membership_type()
        if not mt:
            self.skipTest("No Membership Type exists in database")

        result = get_membership_fee_info_endpoint(mt)
        _assert_success_shape(self, result)
        # Key fields from the fee info util
        self.assertIn("standard_amount", result["data"])
        self.assertIn("currency", result["data"])

    def test_with_nonexistent_type_returns_success_wrapping_error_dict(self):
        """Data-fetch pattern: the util returns an error dict (not an exception),
        so the endpoint wraps it in OperationResult.ok -- the outer success is True
        but data contains success=False."""
        result = get_membership_fee_info_endpoint("NONEXISTENT-TYPE-12345")
        self.assertIsInstance(result, dict)
        # The endpoint wraps the util result in OperationResult.ok unconditionally
        self.assertTrue(result["success"])
        # The inner data dict signals the real error
        self.assertFalse(result["data"]["success"])
        self.assertIn("error", result["data"])


class TestGetMembershipTypeDetails(FrappeTestCase):
    """Characterize get_membership_type_details_endpoint wrapper."""

    def test_with_real_membership_type_returns_success(self):
        mt = _get_any_membership_type()
        if not mt:
            self.skipTest("No Membership Type exists in database")

        result = get_membership_type_details_endpoint(mt)
        _assert_success_shape(self, result)
        self.assertIn("amount", result["data"])
        self.assertIn("suggested_amounts", result["data"])

    def test_with_nonexistent_type_returns_success_wrapping_error_dict(self):
        """Same pattern as fee info: outer success, inner error."""
        result = get_membership_type_details_endpoint("NONEXISTENT-TYPE-12345")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["success"])


class TestSuggestMembershipAmounts(FrappeTestCase):
    """Characterize suggest_membership_amounts_endpoint wrapper."""

    def test_with_real_membership_type_returns_success_or_fail(self):
        mt = _get_any_membership_type()
        if not mt:
            self.skipTest("No Membership Type exists in database")

        result = suggest_membership_amounts_endpoint(mt)
        self.assertIsInstance(result, dict)
        # Could succeed or fail depending on template config; verify shape
        if result["success"]:
            self.assertIn("data", result)
            self.assertIn("suggestions", result["data"])
        else:
            _assert_failure_shape(self, result)

    def test_with_nonexistent_type_returns_success_wrapping_error_dict(self):
        """Same wrapped pattern as other data-fetch endpoints."""
        result = suggest_membership_amounts_endpoint("NONEXISTENT-TYPE-12345")
        self.assertIsInstance(result, dict)
        # The util catches exceptions and returns {success: False, ...}
        # The endpoint wraps that in OperationResult.ok
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["success"])


class TestGetPaymentMethods(FrappeTestCase):
    """Characterize get_payment_methods_endpoint wrapper."""

    def test_returns_success_with_payment_methods(self):
        result = get_payment_methods_endpoint()
        _assert_success_shape(self, result)
        self.assertIn("payment_methods", result["data"])
        self.assertIsInstance(result["data"]["payment_methods"], list)


class TestGetMemberFieldInfo(FrappeTestCase):
    """Characterize get_member_field_info_endpoint wrapper."""

    def test_returns_success_with_fields(self):
        result = get_member_field_info_endpoint()
        _assert_success_shape(self, result)
        self.assertIn("fields", result["data"])
        self.assertIsInstance(result["data"]["fields"], dict)


# ---------------------------------------------------------------------------
# Group C -- Success-check pattern
# ---------------------------------------------------------------------------


class TestSaveDraftApplication(FrappeTestCase):
    """Characterize save_draft_application_endpoint wrapper."""

    def test_valid_data_returns_success_with_draft_id(self):
        data = json.dumps({"first_name": "Test", "last_name": "User"})
        result = save_draft_application_endpoint(data)
        _assert_success_shape(self, result)
        self.assertTrue(result["data"]["success"])
        self.assertIn("draft_id", result["data"])
        # Clean up the draft from cache
        draft_id = result["data"]["draft_id"]
        frappe.cache().delete_value(f"application_draft:{draft_id}")

    def test_null_data_returns_failure(self):
        """parse_application_data raises ValueError for None, caught by endpoint."""
        result = save_draft_application_endpoint(None)
        _assert_failure_shape(self, result)
        self.assertIn("errors", result["error"])


class TestLoadDraftApplication(FrappeTestCase):
    """Characterize load_draft_application_endpoint wrapper."""

    def test_nonexistent_draft_returns_failure(self):
        result = load_draft_application_endpoint("DRAFT-nonexistent-12345")
        _assert_failure_shape(self, result)

    def test_saved_then_loaded_draft_round_trip(self):
        """Save a draft, then load it to verify full round-trip."""
        data = json.dumps({"first_name": "Round", "last_name": "Trip"})
        save_result = save_draft_application_endpoint(data)
        self.assertTrue(save_result["success"])
        draft_id = save_result["data"]["draft_id"]

        load_result = load_draft_application_endpoint(draft_id)
        self.assertIsInstance(load_result, dict)
        self.assertTrue(load_result["success"])
        self.assertIn("data", load_result)
        inner_data = load_result["data"]
        self.assertTrue(inner_data["success"])
        self.assertIn("data", inner_data)
        self.assertEqual(inner_data["data"]["first_name"], "Round")

        # Cleanup
        frappe.cache().delete_value(f"application_draft:{draft_id}")


class TestCheckApplicationStatus(FrappeTestCase):
    """Characterize check_application_status_endpoint wrapper."""

    def test_nonexistent_application_returns_failure(self):
        result = check_application_status_endpoint("APP-nonexistent-12345")
        _assert_failure_shape(self, result)

    def test_empty_application_id_returns_failure(self):
        """Even with empty input, the endpoint returns a dict (not an exception)."""
        result = check_application_status_endpoint("")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
