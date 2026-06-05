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

    def _create_reference_invoice(self):
        """Create a real draft Sales Invoice so the transaction's reference
        Dynamic Link passes link validation (v16 validates Dynamic Links).

        Creates its own dedicated Customer so it doesn't pick a polluted one
        whose linked Member was rolled back by another test (which would trip a
        Sales Invoice validation hook on the missing Member link).
        """
        company = frappe.get_all("Company", limit=1, pluck="name")[0]
        company_currency = frappe.db.get_value("Company", company, "default_currency")
        customer_name = "ING-Recon-Test-Customer"
        if not frappe.db.exists("Customer", customer_name):
            frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": customer_name,
                    "customer_type": "Individual",
                    "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
                }
            ).insert(ignore_permissions=True)
        item = frappe.get_all("Item", limit=1, pluck="name")[0]
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "company": company,
                "customer": customer_name,
                "currency": company_currency,
                "items": [{"item_code": item, "qty": 1, "rate": 25.00}],
            }
        )
        si.insert(ignore_permissions=True)
        return si.name

    def test_create_new_transaction(self):
        """Test creating a new transaction."""
        txn_id = self._unique_txn_id()
        invoice_name = self._create_reference_invoice()

        result = get_or_create_transaction(
            transaction_id=txn_id,
            reference_doctype="Sales Invoice",
            reference_name=invoice_name,
            amount=25.00,
            payment_method="iDEAL",
        )

        self.assertEqual(result.transaction_id, txn_id)
        self.assertEqual(result.reference_doctype, "Sales Invoice")
        self.assertEqual(result.reference_name, invoice_name)
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
