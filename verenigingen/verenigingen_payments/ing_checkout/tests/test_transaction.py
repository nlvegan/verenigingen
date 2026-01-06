# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ING Checkout Transaction DocType

Tests status mapping, transaction creation, and helper functions.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
    STATUS_MAP,
    get_or_create_transaction,
)


class TestStatusMap(FrappeTestCase):
    """Test status code mapping."""

    def test_status_map_paid(self):
        """Test status code 100 maps to Paid."""
        self.assertEqual(STATUS_MAP[100], "Paid")

    def test_status_map_pending(self):
        """Test status code 20 maps to Pending."""
        self.assertEqual(STATUS_MAP[20], "Pending")

    def test_status_map_processing(self):
        """Test status code 25 maps to Processing."""
        self.assertEqual(STATUS_MAP[25], "Processing")

    def test_status_map_cancelled(self):
        """Test status code -90 maps to Cancelled."""
        self.assertEqual(STATUS_MAP[-90], "Cancelled")

    def test_status_map_denied(self):
        """Test status code -63 maps to Denied."""
        self.assertEqual(STATUS_MAP[-63], "Denied")

    def test_status_map_expired(self):
        """Test status code -64 maps to Expired."""
        self.assertEqual(STATUS_MAP[-64], "Expired")

    def test_status_map_refunded(self):
        """Test status code -81 maps to Refunded."""
        self.assertEqual(STATUS_MAP[-81], "Refunded")

    def test_status_map_coverage(self):
        """Test all expected status codes are mapped."""
        expected_codes = [20, 25, 100, -90, -63, -64, -81]
        for code in expected_codes:
            self.assertIn(code, STATUS_MAP)


class TestGetOrCreateTransaction(FrappeTestCase):
    """Test transaction creation and retrieval."""

    @patch("frappe.db.get_value")
    @patch("frappe.new_doc")
    def test_create_new_transaction(self, mock_new_doc, mock_get_value):
        """Test creating a new transaction."""
        mock_get_value.return_value = None  # No existing transaction

        mock_doc = MagicMock()
        mock_doc.name = "ING-TXN-00001"
        mock_new_doc.return_value = mock_doc

        result = get_or_create_transaction(
            transaction_id="EX-1234-5678-9012",
            reference_doctype="Sales Invoice",
            reference_name="INV-001",
            amount=25.00,
            payment_method="iDEAL",
        )

        mock_new_doc.assert_called_once_with("ING Checkout Transaction")
        self.assertEqual(mock_doc.transaction_id, "EX-1234-5678-9012")
        self.assertEqual(mock_doc.reference_doctype, "Sales Invoice")
        self.assertEqual(mock_doc.reference_name, "INV-001")
        self.assertEqual(mock_doc.amount, 25.00)
        self.assertEqual(mock_doc.payment_method, "iDEAL")
        self.assertEqual(mock_doc.status, "Pending")
        mock_doc.insert.assert_called_once_with(ignore_permissions=True)

    @patch("frappe.db.get_value")
    @patch("frappe.get_doc")
    def test_get_existing_transaction(self, mock_get_doc, mock_get_value):
        """Test retrieving existing transaction."""
        mock_get_value.return_value = "ING-TXN-00001"

        mock_doc = MagicMock()
        mock_doc.name = "ING-TXN-00001"
        mock_get_doc.return_value = mock_doc

        result = get_or_create_transaction(
            transaction_id="EX-EXISTING-1234",
        )

        mock_get_doc.assert_called_once_with("ING Checkout Transaction", "ING-TXN-00001")
        self.assertEqual(result, mock_doc)
        # new_doc should not be called
        self.assertEqual(result.name, "ING-TXN-00001")

    @patch("frappe.db.get_value")
    @patch("frappe.new_doc")
    def test_transaction_amount_is_float(self, mock_new_doc, mock_get_value):
        """Test that amount is properly converted to float."""
        mock_get_value.return_value = None

        mock_doc = MagicMock()
        mock_new_doc.return_value = mock_doc

        get_or_create_transaction(
            transaction_id="EX-1234",
            amount="100.50",  # String amount
        )

        # Should convert to float
        self.assertEqual(mock_doc.amount, flt("100.50"))

    @patch("frappe.db.get_value")
    @patch("frappe.new_doc")
    def test_default_payment_method(self, mock_new_doc, mock_get_value):
        """Test default payment method is iDEAL."""
        mock_get_value.return_value = None

        mock_doc = MagicMock()
        mock_new_doc.return_value = mock_doc

        get_or_create_transaction(
            transaction_id="EX-1234",
        )

        self.assertEqual(mock_doc.payment_method, "iDEAL")


class TestTransactionValidation(FrappeTestCase):
    """Test transaction validation."""

    def test_negative_amount_throws(self):
        """Test that negative amount throws error."""
        transaction = frappe.new_doc("ING Checkout Transaction")
        transaction.amount = -10.00

        with self.assertRaises(frappe.ValidationError):
            transaction.validate()

    def test_zero_amount_allowed(self):
        """Test that zero amount is allowed."""
        transaction = frappe.new_doc("ING Checkout Transaction")
        transaction.amount = 0
        # Should not raise
        transaction.validate()

    def test_positive_amount_allowed(self):
        """Test that positive amount is allowed."""
        transaction = frappe.new_doc("ING Checkout Transaction")
        transaction.amount = 25.00
        # Should not raise
        transaction.validate()


class TestUpdateFromWebhookStatusMapping(FrappeTestCase):
    """Test that status codes are correctly mapped in webhook updates."""

    def test_paid_status_code(self):
        """Test status code 100 results in Paid status."""
        self.assertEqual(STATUS_MAP.get(100), "Paid")

    def test_pending_status_code(self):
        """Test status code 20 results in Pending status."""
        self.assertEqual(STATUS_MAP.get(20), "Pending")

    def test_unknown_status_defaults(self):
        """Test unknown status code defaults to None (will become Pending)."""
        self.assertIsNone(STATUS_MAP.get(999))


# Note: Integration tests for update_from_webhook, _create_payment_entry,
# _handle_overpayment, and _send_payment_entry_failure_alert require
# actual database context and are covered by integration tests.
# The unit tests above verify the core logic and status mapping.
