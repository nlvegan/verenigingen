# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Unit tests for chapter cost center resolution in InvoiceGenerator and DuesPaymentProcessor.

Tests branching logic using mocks — no database required.
Covers:
- _get_cost_center priority chain (chapter > company > Main > Main-abbr)
- _get_chapter_cost_center lookup
- _resolve_chapter_cost_center (Mollie path) with company fallback
"""

import unittest
from unittest.mock import MagicMock, patch

from verenigingen.services.billing.invoice_generator import InvoiceGenerator


def _make_schedule(**overrides):
    """Create a minimal mock schedule for InvoiceGenerator."""
    sched = MagicMock()
    sched.name = "TEST-SCHED-001"
    sched.member = "TEST-MEM-001"
    sched.dues_rate = 25.0
    sched.billing_frequency = "Monthly"
    sched.membership_type = "Regular Member"
    sched.member_name = "Test User"
    for k, v in overrides.items():
        setattr(sched, k, v)
    return sched


def _make_member(name="TEST-MEM-001"):
    """Create a minimal mock member doc."""
    member = MagicMock()
    member.name = name
    member.customer = "TEST-CUST-001"
    member.full_name = "Test User"
    return member


class TestGetChapterCostCenter(unittest.TestCase):
    """Test InvoiceGenerator._get_chapter_cost_center() lookup logic."""

    def setUp(self):
        self.schedule = _make_schedule()
        self.generator = InvoiceGenerator(self.schedule)

    @patch("verenigingen.services.billing.invoice_generator.frappe")
    def test_returns_chapter_cost_center_when_exists(self, mock_frappe):
        """Chapter with a valid cost center should be returned."""
        # Import the actual module to patch correctly
        with patch(
            "verenigingen.utils.chapter_utils.get_member_primary_chapter",
            return_value="Chapter-Amsterdam",
        ):
            mock_frappe.db.get_value.return_value = "Amsterdam - NVV"
            mock_frappe.db.exists.return_value = True

            result = self.generator._get_chapter_cost_center("TEST-MEM-001")

            self.assertEqual(result, "Amsterdam - NVV")

    @patch("verenigingen.services.billing.invoice_generator.frappe")
    def test_returns_none_when_no_chapter(self, mock_frappe):
        """Member with no active chapter should return None."""
        with patch(
            "verenigingen.utils.chapter_utils.get_member_primary_chapter",
            return_value=None,
        ):
            result = self.generator._get_chapter_cost_center("TEST-MEM-001")

            self.assertIsNone(result)

    @patch("verenigingen.services.billing.invoice_generator.frappe")
    def test_returns_none_when_chapter_has_no_cost_center(self, mock_frappe):
        """Chapter without cost_center field set should return None."""
        with patch(
            "verenigingen.utils.chapter_utils.get_member_primary_chapter",
            return_value="Chapter-Empty",
        ):
            mock_frappe.db.get_value.return_value = None

            result = self.generator._get_chapter_cost_center("TEST-MEM-001")

            self.assertIsNone(result)

    @patch("verenigingen.services.billing.invoice_generator.frappe")
    def test_returns_none_when_cost_center_doesnt_exist(self, mock_frappe):
        """Chapter referencing a deleted/nonexistent cost center should return None."""
        with patch(
            "verenigingen.utils.chapter_utils.get_member_primary_chapter",
            return_value="Chapter-Stale",
        ):
            mock_frappe.db.get_value.return_value = "Deleted-CC"
            mock_frappe.db.exists.return_value = False

            result = self.generator._get_chapter_cost_center("TEST-MEM-001")

            self.assertIsNone(result)


class TestGetCostCenterPriorityChain(unittest.TestCase):
    """Test InvoiceGenerator._get_cost_center() priority chain with member_doc."""

    def setUp(self):
        self.schedule = _make_schedule()
        self.generator = InvoiceGenerator(self.schedule)
        self.member = _make_member()

    def test_chapter_cost_center_takes_priority(self):
        """When chapter has a cost center, it should be returned over company default."""
        with patch.object(
            self.generator, "_get_chapter_cost_center", return_value="Amsterdam - NVV"
        ):
            result = self.generator._get_cost_center("Test Company", self.member)

        self.assertEqual(result, "Amsterdam - NVV")

    @patch("verenigingen.services.billing.invoice_generator.frappe")
    def test_fallback_to_company_default_when_no_chapter_cc(self, mock_frappe):
        """When chapter has no cost center, should fall back to company default."""
        with patch.object(self.generator, "_get_chapter_cost_center", return_value=None):
            mock_frappe.db.get_value.return_value = "Main - TC"
            mock_frappe.db.exists.return_value = True

            result = self.generator._get_cost_center("Test Company", self.member)

        self.assertEqual(result, "Main - TC")

    @patch("verenigingen.services.billing.invoice_generator.frappe")
    def test_no_member_doc_skips_chapter_lookup(self, mock_frappe):
        """When member_doc is None, chapter lookup should be skipped entirely."""
        mock_frappe.db.get_value.return_value = "Company Default - TC"
        mock_frappe.db.exists.return_value = True

        with patch.object(self.generator, "_get_chapter_cost_center") as mock_chapter_cc:
            result = self.generator._get_cost_center("Test Company", None)

            mock_chapter_cc.assert_not_called()

        self.assertEqual(result, "Company Default - TC")

    @patch("verenigingen.services.billing.invoice_generator.frappe")
    def test_no_member_doc_backward_compatible(self, mock_frappe):
        """Calling without member_doc (old call pattern) should still work."""
        mock_frappe.db.get_value.return_value = "Fallback - TC"
        mock_frappe.db.exists.return_value = True

        result = self.generator._get_cost_center("Test Company")

        self.assertEqual(result, "Fallback - TC")


class TestResolveChapterCostCenterMollie(unittest.TestCase):
    """Test DuesPaymentProcessor._resolve_chapter_cost_center() for Mollie path."""

    def setUp(self):
        # Import here to avoid import-time frappe issues in unit tests
        pass

    @patch("verenigingen.verenigingen_payments.mollie.services.dues_payment_processor.frappe")
    def test_returns_chapter_cost_center(self, mock_frappe):
        """When member's chapter has a cost center, return it."""
        with patch(
            "verenigingen.utils.chapter_utils.get_member_primary_chapter",
            return_value="Chapter-Utrecht",
        ):
            mock_frappe.db.get_value.return_value = "Utrecht - NVV"
            mock_frappe.db.exists.return_value = True

            from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
                DuesPaymentProcessor,
            )

            processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)
            member = _make_member()

            result = processor._resolve_chapter_cost_center(member, "Test Company")

        self.assertEqual(result, "Utrecht - NVV")

    @patch("verenigingen.verenigingen_payments.mollie.services.dues_payment_processor.frappe")
    def test_falls_back_to_company_default(self, mock_frappe):
        """When chapter has no cost center, fall back to company default."""
        with patch(
            "verenigingen.utils.chapter_utils.get_member_primary_chapter",
            return_value="Chapter-NoCostCenter",
        ):
            # First call: chapter cost_center (None)
            # Second call: company cost_center
            # Third call: exists check for company CC
            def get_value_side_effect(doctype, name, field=None, **kwargs):
                if doctype == "Chapter":
                    return None  # No chapter cost center
                if doctype == "Company":
                    return "Main - TC"
                return None

            mock_frappe.db.get_value.side_effect = get_value_side_effect
            mock_frappe.db.exists.return_value = True

            from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
                DuesPaymentProcessor,
            )

            processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)
            member = _make_member()

            result = processor._resolve_chapter_cost_center(member, "Test Company")

        self.assertEqual(result, "Main - TC")

    @patch("verenigingen.verenigingen_payments.mollie.services.dues_payment_processor.frappe")
    def test_returns_none_when_nothing_configured(self, mock_frappe):
        """When neither chapter nor company has a cost center, return None."""
        with patch(
            "verenigingen.utils.chapter_utils.get_member_primary_chapter",
            return_value=None,
        ):
            mock_frappe.db.get_value.return_value = None

            from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
                DuesPaymentProcessor,
            )

            processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)
            member = _make_member()

            result = processor._resolve_chapter_cost_center(member, "Test Company")

        self.assertIsNone(result)
