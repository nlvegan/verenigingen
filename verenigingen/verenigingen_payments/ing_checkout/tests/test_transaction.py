# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ING Checkout Transaction DocType

Tests status mapping, transaction creation, and helper functions.
"""

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
    """Test transaction creation and retrieval using real database operations."""

    def _unique_txn_id(self, suffix=""):
        """Generate a unique transaction ID for test isolation."""
        return f"EX-TEST-{frappe.generate_hash(length=8)}{suffix}"

    def test_create_new_transaction(self):
        """Test creating a new transaction."""
        txn_id = self._unique_txn_id()

        result = get_or_create_transaction(
            transaction_id=txn_id,
            reference_doctype="Sales Invoice",
            reference_name="INV-001",
            amount=25.00,
            payment_method="iDEAL",
        )

        self.assertEqual(result.transaction_id, txn_id)
        self.assertEqual(result.reference_doctype, "Sales Invoice")
        self.assertEqual(result.reference_name, "INV-001")
        self.assertEqual(flt(result.amount), 25.00)
        self.assertEqual(result.payment_method, "iDEAL")
        self.assertEqual(result.status, "Pending")
        # Verify it was actually persisted
        self.assertTrue(frappe.db.exists("ING Checkout Transaction", result.name))

    def test_get_existing_transaction(self):
        """Test retrieving existing transaction instead of creating a duplicate."""
        txn_id = self._unique_txn_id()

        # Create the transaction first
        original = get_or_create_transaction(
            transaction_id=txn_id,
            amount=50.00,
        )

        # Call again with same transaction_id — should return existing
        result = get_or_create_transaction(transaction_id=txn_id)

        self.assertEqual(result.name, original.name)
        self.assertEqual(flt(result.amount), 50.00)

    def test_transaction_amount_is_float(self):
        """Test that amount is properly converted to float."""
        txn_id = self._unique_txn_id()

        result = get_or_create_transaction(
            transaction_id=txn_id,
            amount="100.50",  # String amount
        )

        self.assertEqual(flt(result.amount), flt("100.50"))

    def test_default_payment_method(self):
        """Test default payment method is iDEAL."""
        txn_id = self._unique_txn_id()

        result = get_or_create_transaction(transaction_id=txn_id)

        self.assertEqual(result.payment_method, "iDEAL")


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
