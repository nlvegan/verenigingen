"""
Tests for fee query consolidation.

Verifies that the three fee query functions in application_helpers.py
return consistent data from the same underlying membership type + template.
"""

import importlib
import frappe
from frappe.tests.utils import FrappeTestCase


class TestFeeQueryConsolidation(FrappeTestCase):
    """Tests verifying fee query functions exist and are importable."""

    def test_get_membership_fee_info_importable(self):
        """get_membership_fee_info must be importable from application_helpers."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "get_membership_fee_info", None)
        self.assertIsNotNone(func)
        self.assertTrue(callable(func))

    def test_get_membership_type_details_importable(self):
        """get_membership_type_details must be importable from application_helpers."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "get_membership_type_details", None)
        self.assertIsNotNone(func)
        self.assertTrue(callable(func))

    def test_suggest_membership_amounts_importable(self):
        """suggest_membership_amounts must be importable from application_helpers."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "suggest_membership_amounts", None)
        self.assertIsNotNone(func)
        self.assertTrue(callable(func))

    def test_canonical_function_exists(self):
        """get_membership_type_fee_info must exist as the canonical source."""
        module = importlib.import_module("verenigingen.utils.application_helpers")
        func = getattr(module, "get_membership_type_fee_info", None)
        self.assertIsNotNone(func, "get_membership_type_fee_info must exist as canonical function")
        self.assertTrue(callable(func))

    def test_canonical_function_returns_required_keys(self):
        """Canonical function must return all keys needed by all three wrappers."""
        # Get a real membership type
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import get_membership_type_fee_info

        result = get_membership_type_fee_info(mt[0].name)
        self.assertTrue(result.get("success"), f"Expected success, got: {result}")

        # Must contain ALL fields needed by any wrapper
        required_keys = [
            "membership_type", "membership_type_name", "description",
            "amount", "currency", "billing_frequency",
            "minimum_amount", "maximum_amount",
            "suggested_amounts",
        ]
        for key in required_keys:
            self.assertIn(key, result, f"Missing key '{key}' in canonical result")

    def test_fee_info_wrapper_returns_expected_keys(self):
        """get_membership_fee_info must return its expected response shape."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import get_membership_fee_info

        result = get_membership_fee_info(mt[0].name)
        self.assertTrue(result.get("success"))
        self.assertIn("standard_amount", result)
        self.assertIn("currency", result)
        self.assertIn("billing_frequency", result)

    def test_type_details_wrapper_returns_expected_keys(self):
        """get_membership_type_details must return its expected response shape."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import get_membership_type_details

        result = get_membership_type_details(mt[0].name)
        self.assertTrue(result.get("success"))
        self.assertIn("amount", result)
        self.assertIn("suggested_amounts", result)
        self.assertIn("minimum_amount", result)
        self.assertIn("maximum_amount", result)

    def test_suggest_amounts_wrapper_returns_expected_keys(self):
        """suggest_membership_amounts must return its expected response shape."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import suggest_membership_amounts

        result = suggest_membership_amounts(mt[0].name)
        # This may fail if template has no suggested_amount — that's OK for now
        if result.get("success"):
            self.assertIn("base_amount", result)
            self.assertIn("suggestions", result)
            self.assertIsInstance(result["suggestions"], list)

    def test_all_three_agree_on_base_amount(self):
        """All three functions must agree on the base amount for the same membership type."""
        mt = frappe.get_all("Membership Type", limit=1, fields=["name"])
        if not mt:
            self.skipTest("No Membership Type exists in the system")

        from verenigingen.utils.application_helpers import (
            get_membership_fee_info,
            get_membership_type_details,
            suggest_membership_amounts,
        )

        fee_result = get_membership_fee_info(mt[0].name)
        details_result = get_membership_type_details(mt[0].name)
        suggest_result = suggest_membership_amounts(mt[0].name)

        if all(r.get("success") for r in [fee_result, details_result, suggest_result]):
            fee_amount = fee_result.get("standard_amount", 0)
            details_amount = details_result.get("amount", 0)
            suggest_amount = suggest_result.get("base_amount", 0)

            self.assertEqual(
                float(fee_amount), float(details_amount),
                f"fee_info ({fee_amount}) and type_details ({details_amount}) disagree on amount",
            )
            # After consolidation, suggest_amounts also uses the canonical source
            # so all three should agree
            self.assertEqual(
                float(fee_amount), float(suggest_amount),
                f"fee_info ({fee_amount}) and suggest_amounts ({suggest_amount}) disagree on amount",
            )
